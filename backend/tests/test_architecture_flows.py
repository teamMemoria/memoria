"""Complete persistent flows using only disposable, independently authored records."""

from contextlib import asynccontextmanager

import httpx
from sqlalchemy import select

from backend.core.config import Settings
from backend.main import create_app
from backend.models import DraftStatus, KnowledgeDraft, User
from tests.conftest import TEST_DATABASE_URL
from tests.database_seed import ALEX, MAYA, SAM, seed


@asynccontextmanager
async def running_app():
    app = create_app(
        settings=Settings(
            app_env="test", data_source="database", database_url=TEST_DATABASE_URL
        )
    )
    async with (
        app.router.lifespan_context(app),
        httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client,
    ):
        yield client


async def test_profiles_review_and_knowledge_survive_restart(committed_sessions):
    async with committed_sessions() as session:
        data = await seed(session)
        aliases = {
            ALEX: "demo-architecture-agent",
            MAYA: "demo-architecture-manager",
            SAM: "demo-architecture-other",
        }
        for user in await session.scalars(
            select(User).where(User.external_id.in_(aliases))
        ):
            user.external_id = aliases[user.external_id]
        drafts = [
            KnowledgeDraft(
                organization_id=data.northwind.id,
                topic_id=data.assessed.topic_id,
                question=f"Authored verification {i}",
                answer_text=f"Authored test guidance {i}.",
                status=DraftStatus.PENDING,
                verification_reference={
                    "title": "Test policy",
                    "url": "https://example.test/reference",
                },
            )
            for i in range(3)
        ]
        session.add_all(drafts)
        await session.commit()
        call_id, finding_id = str(data.assessed.id), str(data.procedure_finding.id)
        draft_ids = [str(d.id) for d in drafts]
    agent = {"X-Dev-User": aliases[ALEX]}
    manager = {"X-Dev-User": aliases[MAYA]}
    other = {"X-Dev-User": aliases[SAM]}
    call_path = f"/api/agent/conversations/{call_id}"
    async with running_app() as client:
        profiles = (await client.get("/api/demo/profiles")).json()
        assert {p["id"] for p in profiles} == set(aliases.values())
        assert (await client.get("/api/viewer", headers=agent)).json()["id"] == aliases[
            ALEX
        ]
        assert (await client.get(call_path, headers=other)).status_code == 404
        initial = (await client.get(call_path, headers=agent)).json()
        assert initial["decision"] is None
        assert (
            await client.put(
                call_path + "/context",
                headers=agent,
                json={"text": "Authored review context"},
            )
        ).status_code == 200
        request = await client.post(
            call_path + "/review-requests",
            headers=agent,
            json={"findingId": finding_id, "reason": "Please check the cited order"},
        )
        assert request.status_code == 201, request.text
        assert (
            await client.get(f"/api/manager/conversations/{call_id}", headers=manager)
        ).json()["call"]["reviewRequest"]["reason"] == "Please check the cited order"
        decision = {
            "outcome": "confirmed",
            "reason": "The supplied evidence supports the finding",
            "feedback": "Check the order first",
        }
        decided = await client.post(
            f"/api/manager/conversations/{call_id}/findings/{finding_id}/decision",
            headers=manager,
            json=decision,
        )
        assert decided.status_code == 201, decided.text
        for draft_id, outcome in zip(draft_ids[:2], ["approve", "reject"], strict=True):
            path = f"/api/manager/knowledge/drafts/{draft_id}"
            detail = (await client.get(path, headers=manager)).json()["entry"]
            body = (
                {
                    "version": detail["version"],
                    "verifiedReferenceUrl": "https://example.test/reference",
                }
                if outcome == "approve"
                else {
                    "version": detail["version"],
                    "reason": "Not sufficient for publication",
                }
            )
            assert (
                await client.post(path + "/" + outcome, headers=agent, json=body)
            ).status_code == 403
            response = await client.post(
                path + "/" + outcome, headers=manager, json=body
            )
            assert response.status_code == 200, response.text
    # New application, new engine and fresh connections: no in-memory decisions survive.
    async with running_app() as client:
        refreshed = (await client.get(call_path, headers=agent)).json()
        assert refreshed["decision"]["reason"] == decision["reason"]
        assert refreshed["criteria"] == initial["criteria"]
        assert refreshed["findings"] == initial["findings"]
        assert refreshed["transcript"] == initial["transcript"]
        assert refreshed["agentContext"]["text"] == "Authored review context"
        states = []
        for draft_id in draft_ids:
            states.append(
                (
                    await client.get(
                        f"/api/manager/knowledge/drafts/{draft_id}", headers=manager
                    )
                ).json()["entry"]["status"]
            )
        assert states == ["approved", "rejected", "draft"]
        entries = (await client.get("/api/agent/knowledge", headers=agent)).json()
        assert any("Authored test guidance 0." in str(e) for e in entries)
        assert not any(
            "Authored test guidance 1." in str(e)
            or "Authored test guidance 2." in str(e)
            for e in entries
        )
