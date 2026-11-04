from dataclasses import replace
from datetime import UTC, datetime

import httpx
import pytest
from sqlalchemy import func, select
from sqlalchemy.exc import OperationalError

from backend.core.config import Settings
from backend.main import create_app
from backend.models import AgentContext, FeedbackFlag, Finding, FindingResult
from backend.providers import create_fixture_providers
from backend.providers.database import create_database_providers
from backend.providers.feedback import DatabaseFeedbackProvider
from tests.database_seed import ALEX, MAYA, SAM, seed, sessions_for

NOW = datetime(2026, 11, 2, 10, 30, tzinfo=UTC)


@pytest.fixture
async def data(session):
    return await seed(session)


def client_for(session, providers=None):
    if providers is None:
        providers = replace(
            create_database_providers(sessions_for(session)),
            feedback=DatabaseFeedbackProvider(sessions_for(session), now=lambda: NOW),
        )
    app = create_app(providers=providers, settings=Settings(app_env="test"))
    return httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    )


def as_user(user_id):
    return {"X-Dev-User": user_id}


async def count(session, model):
    return await session.scalar(select(func.count()).select_from(model))


async def call_view(client, data, conversation, user=ALEX):
    response = await client.get(
        f"/api/agent/conversations/{data.id(conversation)}", headers=as_user(user)
    )
    return response.json()


# --- context -----------------------------------------------------------------------


async def test_saving_context_never_requests_a_review(session, data):
    flags_before = await count(session, FeedbackFlag)
    async with client_for(session) as client:
        path = f"/api/agent/conversations/{data.id(data.assessed)}/context"
        saved = await client.put(
            path, json={"text": "  The order system was slow.  "}, headers=as_user(ALEX)
        )
        assert saved.status_code == 200
        assert saved.json() == {
            "text": "The order system was slow.",
            "savedAt": "2026-11-02T10:30:00Z",
        }
        session.expunge_all()
        call = await call_view(client, data, data.assessed)
    assert call["agentContext"] == saved.json()
    assert call["reviewRequest"] is None
    assert await count(session, FeedbackFlag) == flags_before


async def test_saving_context_again_replaces_the_note(session, data):
    async with client_for(session) as client:
        path = f"/api/agent/conversations/{data.id(data.assessed)}/context"
        await client.put(path, json={"text": "first"}, headers=as_user(ALEX))
        second = await client.put(path, json={"text": "second"}, headers=as_user(ALEX))
    assert second.json()["text"] == "second"
    assert await count(session, AgentContext) == 1


async def test_context_on_a_processing_call_is_allowed(session, data):
    async with client_for(session) as client:
        response = await client.put(
            f"/api/agent/conversations/{data.id(data.processing)}/context",
            json={"text": "Customer called back later."},
            headers=as_user(ALEX),
        )
    assert response.status_code == 200


@pytest.mark.parametrize("text", ["", "   ", "x" * 4001])
async def test_empty_or_oversized_context_is_rejected(session, data, text):
    async with client_for(session) as client:
        response = await client.put(
            f"/api/agent/conversations/{data.id(data.assessed)}/context",
            json={"text": text},
            headers=as_user(ALEX),
        )
    assert response.status_code == 422
    assert await count(session, AgentContext) == 0


# --- review requests ------------------------------------------------------------------


async def test_flagging_a_finding_creates_one_review_request(session, data):
    finding_id = data.id(data.procedure_finding)
    async with client_for(session) as client:
        path = f"/api/agent/conversations/{data.id(data.assessed)}/review-requests"
        await client.put(
            f"/api/agent/conversations/{data.id(data.assessed)}/context",
            json={"text": "Checked on a second screen."},
            headers=as_user(ALEX),
        )
        first = await client.post(
            path,
            json={"findingId": finding_id, "reason": "I checked the order first."},
            headers=as_user(ALEX),
        )
        assert first.status_code == 201
        assert first.json() == {
            "findingId": finding_id,
            "reason": "I checked the order first.",
            "requestedAt": "2026-11-02T10:30:00Z",
            "status": "requested",
        }
        again = await client.post(
            path,
            json={"findingId": finding_id, "reason": "A different reason."},
            headers=as_user(ALEX),
        )
        assert again.status_code == 200
        assert again.json() == first.json()

        session.expunge_all()
        call = await call_view(client, data, data.assessed)
        assert call["reviewRequest"] == first.json()

        listed = await client.get("/api/agent/conversations", headers=as_user(ALEX))
        status = {c["id"]: c["reviewStatus"] for c in listed.json()}
        assert status[data.id(data.assessed)] == "review-requested"

    flags = (
        await session.scalars(
            select(FeedbackFlag).where(FeedbackFlag.finding_id == int(finding_id))
        )
    ).all()
    assert len(flags) == 1
    # The flag keeps the context as it was when the review was requested.
    assert flags[0].agent_context == "Checked on a second screen."
    assert flags[0].agent_id == data.alex_agent.id


async def test_flagging_leaves_the_automated_finding_unchanged(session, data):
    before = await session.get(Finding, data.procedure_finding.id)
    snapshot = (before.result, before.feedback, before.suggestion)
    session.expunge_all()
    async with client_for(session) as client:
        await client.post(
            f"/api/agent/conversations/{data.id(data.assessed)}/review-requests",
            json={"findingId": data.id(data.procedure_finding), "reason": "Wrong."},
            headers=as_user(ALEX),
        )
    session.expunge_all()
    after = await session.get(Finding, data.procedure_finding.id)
    assert (after.result, after.feedback, after.suggestion) == snapshot
    assert after.result is FindingResult.NEEDS_WORK


async def test_a_reviewed_request_shows_as_complete(session, data):
    async with client_for(session) as client:
        call = await call_view(client, data, data.reviewed)
    assert call["reviewRequest"]["status"] == "complete"
    assert call["reviewRequest"]["findingId"] == data.id(data.reviewed_finding)


@pytest.mark.parametrize(
    "finding",
    ["999999", "not-an-id", "passing"],
)
async def test_only_visible_findings_can_be_flagged(session, data, finding):
    if finding == "passing":
        passing = await session.scalar(
            select(Finding).where(
                Finding.audit_id == data.procedure_finding.audit_id,
                Finding.result == FindingResult.PASS,
            )
        )
        finding = str(passing.id)
    async with client_for(session) as client:
        response = await client.post(
            f"/api/agent/conversations/{data.id(data.assessed)}/review-requests",
            json={"findingId": finding, "reason": "Please check."},
            headers=as_user(ALEX),
        )
    assert response.status_code == 404
    assert response.json() == {"detail": "Finding not found"}


async def test_a_finding_from_another_call_cannot_be_flagged_here(session, data):
    async with client_for(session) as client:
        response = await client.post(
            f"/api/agent/conversations/{data.id(data.assessed)}/review-requests",
            json={"findingId": data.id(data.reviewed_finding), "reason": "x"},
            headers=as_user(ALEX),
        )
    assert response.status_code == 404


async def test_processing_calls_have_nothing_to_flag(session, data):
    async with client_for(session) as client:
        response = await client.post(
            f"/api/agent/conversations/{data.id(data.processing)}/review-requests",
            json={"findingId": "1", "reason": "x"},
            headers=as_user(ALEX),
        )
    assert response.status_code == 404


# --- ownership and failures -------------------------------------------------------------


async def test_agents_cannot_write_on_someone_elses_call(session, data):
    async with client_for(session) as client:
        for conversation in (data.sam_call, data.harbor_call):
            base = f"/api/agent/conversations/{data.id(conversation)}"
            context = await client.put(
                f"{base}/context", json={"text": "mine"}, headers=as_user(ALEX)
            )
            flag = await client.post(
                f"{base}/review-requests",
                json={"findingId": "1", "reason": "x"},
                headers=as_user(ALEX),
            )
            assert (context.status_code, flag.status_code) == (404, 404)
        manager = await client.put(
            f"/api/agent/conversations/{data.id(data.assessed)}/context",
            json={"text": "x"},
            headers=as_user(MAYA),
        )
        assert manager.status_code == 403
        anonymous = await client.put(
            f"/api/agent/conversations/{data.id(data.assessed)}/context",
            json={"text": "x"},
        )
        assert anonymous.status_code == 401
    assert await count(session, AgentContext) == 0


async def test_sam_flagging_his_own_call_works(session, data):
    sam_finding = await session.scalar(
        select(Finding).where(
            Finding.audit_id != data.procedure_finding.audit_id,
            Finding.feedback == "Sam skipped a step.",
        )
    )
    async with client_for(session) as client:
        response = await client.post(
            f"/api/agent/conversations/{data.id(data.sam_call)}/review-requests",
            json={"findingId": str(sam_finding.id), "reason": "Step was done."},
            headers=as_user(SAM),
        )
    assert response.status_code == 201


async def test_a_failed_save_does_not_report_success(session, data):
    class Broken:
        async def __aenter__(self):
            raise OperationalError("INSERT", {}, ConnectionError("refused"))

        async def __aexit__(self, *exc):
            return False

    providers = replace(
        create_database_providers(sessions_for(session)),
        feedback=DatabaseFeedbackProvider(Broken),
    )
    async with client_for(session, providers) as client:
        response = await client.put(
            f"/api/agent/conversations/{data.id(data.assessed)}/context",
            json={"text": "note"},
            headers=as_user(ALEX),
        )
    assert response.status_code == 503


async def test_writes_need_the_database_when_running_on_fixtures():
    app = create_app(
        providers=create_fixture_providers(), settings=Settings(app_env="test")
    )
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.put(
            "/api/agent/conversations/C1042/context",
            json={"text": "note"},
            headers=as_user(ALEX),
        )
    assert response.status_code == 503


async def test_a_nul_character_is_rejected_not_a_database_error(session, data):
    async with client_for(session) as client:
        response = await client.put(
            f"/api/agent/conversations/{data.id(data.assessed)}/context",
            json={"text": "a\u0000b"},
            headers=as_user(ALEX),
        )
    assert response.status_code == 422


async def test_concurrent_flags_create_one_request(committed_sessions):
    import asyncio

    async with committed_sessions() as session:
        data = await seed(session)
    provider = DatabaseFeedbackProvider(committed_sessions, now=lambda: NOW)
    results = await asyncio.gather(
        *[
            provider.request_review(
                "org-northwind",
                ALEX,
                data.id(data.assessed),
                data.id(data.procedure_finding),
                f"Reason {number}",
            )
            for number in range(8)
        ]
    )
    assert sum(created for _, created in results) == 1
    assert len({request.reason for request, _ in results}) == 1
    async with committed_sessions() as session:
        assert await session.scalar(select(func.count()).select_from(FeedbackFlag)) == 2
