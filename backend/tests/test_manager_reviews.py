from dataclasses import replace
from datetime import UTC, datetime

import httpx
import pytest
from sqlalchemy import func, select
from sqlalchemy.exc import OperationalError

from backend.core.config import Settings
from backend.main import create_app
from backend.models import (
    AgentContext,
    FeedbackFlag,
    Finding,
    FindingResult,
    ManagerReview,
    ManagerReviewOutcome,
)
from backend.providers import create_fixture_providers
from backend.providers.base import ConflictError
from backend.providers.database import create_database_providers
from backend.providers.reviews import DatabaseReviewProvider
from backend.schemas.reviews import DecisionInput
from tests.database_seed import ALEX, HARBOR, MAYA, NORTHWIND, SAM, seed, sessions_for

NOW = datetime(2026, 11, 2, 11, 0, tzinfo=UTC)
DECISION = {
    "outcome": "corrected",
    "reviewedResult": "meets-criteria",
    "reason": "The order was checked on another screen first.",
    "feedback": "The procedure was followed; no change needed.",
}


def decision_body(outcome):
    """DECISION with another outcome; only corrected carries a reviewedResult."""
    body = {**DECISION, "outcome": outcome}
    if outcome != "corrected":
        del body["reviewedResult"]
    return body


@pytest.fixture
async def data(session):
    result = await seed(session)
    # Alex asks for a review of the procedure finding on the assessed call.
    session.add(
        FeedbackFlag(
            organization_id=result.northwind.id,
            finding_id=result.procedure_finding.id,
            agent_id=result.alex_agent.id,
            reason="I checked the order before offering.",
            agent_context="The order screen was open the whole time.",
            flagged_at=datetime(2026, 10, 9, 9, 30, tzinfo=UTC),
        )
    )
    session.add(
        AgentContext(
            organization_id=result.northwind.id,
            conversation_id=result.assessed.id,
            agent_id=result.alex_agent.id,
            text="The order screen was open the whole time.",
        )
    )
    await session.commit()
    session.expunge_all()
    return result


def client_for(session, providers=None):
    if providers is None:
        providers = replace(
            create_database_providers(sessions_for(session)),
            reviews=DatabaseReviewProvider(sessions_for(session), now=lambda: NOW),
        )
    app = create_app(providers=providers, settings=Settings(app_env="test"))
    return httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    )


MANAGER = {"X-Dev-User": MAYA}


async def queue(client, **params):
    response = await client.get(
        "/api/manager/conversations", params=params, headers=MANAGER
    )
    assert response.status_code == 200
    return response.json()


def decision_path(data, conversation, finding):
    return (
        f"/api/manager/conversations/{data.id(conversation)}"
        f"/findings/{data.id(finding)}/decision"
    )


# --- queue --------------------------------------------------------------------------


async def test_queue_covers_the_organization_only(session, data):
    async with client_for(session) as client:
        items = await queue(client)
    assert {item["id"] for item in items} == {
        data.id(record)
        for record in (
            data.assessed,
            data.processing,
            data.undated,
            data.reviewed,
            data.sam_call,
        )
    }
    names = {item["agentId"]: item["agentName"] for item in items}
    assert names == {ALEX: "Alex Morgan", SAM: "Sam Rivera"}


async def test_queue_shows_the_flag_with_its_finding(session, data):
    async with client_for(session) as client:
        items = await queue(client, status="review-requested")
    [item] = items
    assert item["id"] == data.id(data.assessed)
    assert item["flag"] == {
        "findingId": data.id(data.procedure_finding),
        "findingTitle": "The refund was offered before the order was checked.",
        "reason": "I checked the order before offering.",
        "requestedAt": "2026-10-09T09:30:00Z",
        "status": "requested",
    }


@pytest.mark.parametrize(
    ("status", "expected"),
    [
        ("review-complete", ["reviewed"]),
        ("processing", []),
        ("unavailable", ["processing"]),
        ("feedback-ready", ["sam_call", "undated"]),
    ],
)
async def test_queue_status_filters(session, data, status, expected):
    async with client_for(session) as client:
        items = await queue(client, status=status)
    assert sorted(item["id"] for item in items) == sorted(
        data.id(getattr(data, name)) for name in expected
    )


@pytest.mark.parametrize(
    ("query", "expected"),
    [
        ("sam", ["sam_call"]),
        ("before offering", ["assessed"]),
        ("ORDER WAS CHECKED", ["assessed"]),
        ("nothing matches this", []),
    ],
)
async def test_queue_search(session, data, query, expected):
    async with client_for(session) as client:
        items = await queue(client, q=query)
    assert sorted(item["id"] for item in items) == sorted(
        data.id(getattr(data, name)) for name in expected
    )


async def test_unknown_status_is_rejected(session, data):
    async with client_for(session) as client:
        response = await client.get(
            "/api/manager/conversations", params={"status": "bad"}, headers=MANAGER
        )
    assert response.status_code == 422


# --- detail ----------------------------------------------------------------------------


async def test_detail_has_finding_evidence_context_and_permission(session, data):
    async with client_for(session) as client:
        response = await client.get(
            f"/api/manager/conversations/{data.id(data.assessed)}", headers=MANAGER
        )
    detail = response.json()
    assert detail["canDecide"] is True
    call = detail["call"]
    assert call["findings"][0]["evidenceTurnNumbers"] == [2, 5, 7]
    assert call["agentContext"]["text"] == "The order screen was open the whole time."
    assert call["reviewRequest"]["status"] == "requested"
    assert call["decision"] is None


async def test_other_organizations_calls_are_not_found(session, data):
    async with client_for(session) as client:
        detail = await client.get(
            f"/api/manager/conversations/{data.id(data.harbor_call)}", headers=MANAGER
        )
        decision = await client.post(
            decision_path(data, data.harbor_call, data.procedure_finding),
            json=DECISION,
            headers=MANAGER,
        )
    assert (detail.status_code, decision.status_code) == (404, 404)


# --- decisions -------------------------------------------------------------------------


@pytest.mark.parametrize(
    "outcome", ["confirmed", "corrected", "dismissed", "cannot-assess"]
)
async def test_each_outcome_is_recorded_beside_the_finding(session, data, outcome):
    before = await session.get(Finding, data.procedure_finding.id)
    snapshot = (before.result, before.feedback, before.suggestion)
    session.expunge_all()
    async with client_for(session) as client:
        response = await client.post(
            decision_path(data, data.assessed, data.procedure_finding),
            json=decision_body(outcome),
            headers=MANAGER,
        )
        assert response.status_code == 201
        assert response.json() == {
            "outcome": outcome,
            "reason": DECISION["reason"],
            "feedback": DECISION["feedback"],
            "managerName": "Maya Chen",
            "decidedAt": "2026-11-02T11:00:00Z",
        }
        session.expunge_all()
        # The agent sees the decision; the automated result is unchanged.
        agent_view = (
            await client.get(
                f"/api/agent/conversations/{data.id(data.assessed)}",
                headers={"X-Dev-User": ALEX},
            )
        ).json()
        manager_view = (
            await client.get(
                f"/api/manager/conversations/{data.id(data.assessed)}",
                headers=MANAGER,
            )
        ).json()["call"]
    for view in (agent_view, manager_view):
        assert view["decision"] == response.json()
        assert view["reviewRequest"]["status"] == "complete"
        procedure = next(c for c in view["criteria"] if c["id"] == "procedure")
        assert procedure["result"] == "needs-review"

    session.expunge_all()
    after = await session.get(Finding, data.procedure_finding.id)
    assert (after.result, after.feedback, after.suggestion) == snapshot
    review = await session.scalar(
        select(ManagerReview).order_by(ManagerReview.id.desc())
    )
    assert review.outcome is ManagerReviewOutcome(outcome.replace("-", "_"))
    assert review.reviewer_membership_id == data.maya.id
    expected = FindingResult.PASS if outcome == "corrected" else None
    assert review.reviewed_result is expected


@pytest.mark.parametrize(
    "body",
    [
        {k: v for k, v in DECISION.items() if k != "reviewedResult"},
        {**decision_body("dismissed"), "reviewedResult": "meets-criteria"},
        {**DECISION, "reviewedResult": "fixed"},
    ],
    ids=["corrected-without-result", "result-without-corrected", "unknown-result"],
)
async def test_a_corrected_result_is_required_exactly_for_corrected(
    session, data, body
):
    async with client_for(session) as client:
        response = await client.post(
            decision_path(data, data.assessed, data.procedure_finding),
            json=body,
            headers=MANAGER,
        )
    assert response.status_code == 422
    assert (
        await session.scalar(
            select(func.count())
            .select_from(ManagerReview)
            .join(FeedbackFlag)
            .where(FeedbackFlag.finding_id == data.procedure_finding.id)
        )
        == 0
    )


async def test_a_different_corrected_result_conflicts(session, data):
    path = decision_path(data, data.assessed, data.procedure_finding)
    async with client_for(session) as client:
        await client.post(path, json=DECISION, headers=MANAGER)
        conflict = await client.post(
            path, json={**DECISION, "reviewedResult": "cannot-assess"}, headers=MANAGER
        )
    assert conflict.status_code == 409


async def test_the_same_decision_twice_is_one_decision(session, data):
    path = decision_path(data, data.assessed, data.procedure_finding)
    async with client_for(session) as client:
        first = await client.post(path, json=DECISION, headers=MANAGER)
        second = await client.post(path, json=DECISION, headers=MANAGER)
    assert (first.status_code, second.status_code) == (201, 200)
    assert second.json() == first.json()
    count = await session.scalar(
        select(func.count())
        .select_from(ManagerReview)
        .join(FeedbackFlag)
        .where(FeedbackFlag.finding_id == data.procedure_finding.id)
    )
    assert count == 1


async def test_a_conflicting_decision_is_refused(session, data):
    path = decision_path(data, data.assessed, data.procedure_finding)
    async with client_for(session) as client:
        await client.post(path, json=DECISION, headers=MANAGER)
        conflict = await client.post(
            path, json=decision_body("dismissed"), headers=MANAGER
        )
    assert conflict.status_code == 409
    session.expunge_all()
    stored = await session.scalar(
        select(ManagerReview)
        .join(FeedbackFlag)
        .where(FeedbackFlag.finding_id == data.procedure_finding.id)
    )
    assert stored.outcome is ManagerReviewOutcome.CORRECTED


async def test_an_already_decided_request_from_the_seed_conflicts(session, data):
    async with client_for(session) as client:
        response = await client.post(
            decision_path(data, data.reviewed, data.reviewed_finding),
            json=DECISION,
            headers=MANAGER,
        )
    assert response.status_code == 409


async def test_only_review_requests_can_be_decided(session, data):
    sam_finding = await session.scalar(
        select(Finding).where(Finding.feedback == "Sam skipped a step.")
    )
    async with client_for(session) as client:
        unflagged = await client.post(
            f"/api/manager/conversations/{data.id(data.sam_call)}"
            f"/findings/{sam_finding.id}/decision",
            json=DECISION,
            headers=MANAGER,
        )
        wrong_call = await client.post(
            decision_path(data, data.reviewed, data.procedure_finding),
            json=DECISION,
            headers=MANAGER,
        )
    assert unflagged.status_code == 404
    assert unflagged.json() == {"detail": "Review request not found"}
    assert wrong_call.status_code == 404


@pytest.mark.parametrize(
    "body",
    [
        {**DECISION, "reason": "  "},
        {**DECISION, "feedback": ""},
        {**DECISION, "outcome": "approved"},
        {"outcome": "confirmed", "reason": "x"},
    ],
)
async def test_decisions_need_an_outcome_reason_and_feedback(session, data, body):
    async with client_for(session) as client:
        response = await client.post(
            decision_path(data, data.assessed, data.procedure_finding),
            json=body,
            headers=MANAGER,
        )
    assert response.status_code == 422


# --- permissions and failures ----------------------------------------------------------


async def test_agents_cannot_use_the_review_routes(session, data):
    agent = {"X-Dev-User": ALEX}
    async with client_for(session) as client:
        responses = [
            await client.get("/api/manager/conversations", headers=agent),
            await client.get(
                f"/api/manager/conversations/{data.id(data.assessed)}", headers=agent
            ),
            await client.post(
                decision_path(data, data.assessed, data.procedure_finding),
                json=DECISION,
                headers=agent,
            ),
        ]
    assert [response.status_code for response in responses] == [403, 403, 403]


async def test_a_failed_save_does_not_report_success(session, data):
    class Broken:
        async def __aenter__(self):
            raise OperationalError("INSERT", {}, ConnectionError("refused"))

        async def __aexit__(self, *exc):
            return False

    providers = replace(
        create_database_providers(sessions_for(session)),
        reviews=DatabaseReviewProvider(Broken),
    )
    async with client_for(session, providers) as client:
        response = await client.post(
            decision_path(data, data.assessed, data.procedure_finding),
            json=DECISION,
            headers=MANAGER,
        )
    assert response.status_code == 503


async def test_the_queue_needs_the_database_when_running_on_fixtures():
    app = create_app(
        providers=create_fixture_providers(), settings=Settings(app_env="test")
    )
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.get("/api/manager/conversations", headers=MANAGER)
    assert response.status_code == 503


async def test_queue_is_scoped_by_organization_in_the_provider(session, data):
    provider = DatabaseReviewProvider(sessions_for(session))
    harbor_view = await provider.list_for_manager(HARBOR, "manager-harbor")
    assert {item.id for item in harbor_view} == {data.id(data.harbor_call)}


async def test_managers_see_the_context_as_it_was_when_review_was_requested(
    session, data
):
    async with client_for(session) as client:
        await client.put(
            f"/api/agent/conversations/{data.id(data.assessed)}/context",
            json={"text": "A note written after the request."},
            headers={"X-Dev-User": ALEX},
        )
        session.expunge_all()
        detail = await client.get(
            f"/api/manager/conversations/{data.id(data.assessed)}", headers=MANAGER
        )
    assert detail.json()["call"]["agentContext"] == {
        "text": "The order screen was open the whole time.",
        "savedAt": "2026-10-09T09:30:00Z",
    }


async def test_a_nul_character_in_a_decision_is_rejected(session, data):
    async with client_for(session) as client:
        response = await client.post(
            decision_path(data, data.assessed, data.procedure_finding),
            json={**DECISION, "feedback": "bad\u0000text"},
            headers=MANAGER,
        )
    assert response.status_code == 422


async def test_concurrent_decisions_record_one_and_answer_the_rest(committed_sessions):
    import asyncio

    async with committed_sessions() as session:
        data = await seed(session)
        session.add(
            FeedbackFlag(
                organization_id=data.northwind.id,
                finding_id=data.procedure_finding.id,
                agent_id=data.alex_agent.id,
                reason="Please check.",
            )
        )
        await session.commit()
    provider = DatabaseReviewProvider(committed_sessions, now=lambda: NOW)
    outcomes = ["corrected", "dismissed"] * 4

    async def attempt(outcome):
        try:
            _, created = await provider.decide(
                NORTHWIND,
                MAYA,
                data.id(data.assessed),
                data.id(data.procedure_finding),
                DecisionInput.model_validate(decision_body(outcome)),
            )
            return "created" if created else "same"
        except ConflictError:
            return "conflict"

    results = await asyncio.gather(*[attempt(outcome) for outcome in outcomes])
    assert results.count("created") == 1
    assert set(results) <= {"created", "same", "conflict"}
