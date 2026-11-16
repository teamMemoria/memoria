"""Only a scoped, current, reference-verified human decision publishes knowledge."""

import httpx
import pytest

from backend.core.config import Settings
from backend.main import create_app
from backend.models import DraftStatus, KnowledgeDraft
from backend.providers.database import create_database_providers
from tests.database_seed import ALEX, MAYA, NORTHWIND, RILEY, seed, sessions_for
from tests.test_knowledge_import import draft_by_key, import_fixture


@pytest.fixture
async def setup(session):
    data = await seed(session)
    await import_fixture(session, data)
    draft = await draft_by_key(session, "draft_refund_assessed")
    # Independent authored fixture: no real guideline is approved by this test.
    draft.verification_reference = {
        "title": "Authored test policy",
        "url": "https://example.test/policy",
    }
    session.add(draft)
    await session.commit()
    providers = create_database_providers(sessions_for(session))
    app = create_app(
        providers=providers, settings=Settings(app_env="test", data_source="database")
    )
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        yield data, draft, providers, client


async def test_decisions_reject_wrong_role_stale_version_and_missing_reference(
    setup, session
):
    _, draft, providers, client = setup
    path = f"/api/manager/knowledge/drafts/{draft.id}"
    detail = await providers.knowledge_review.get_for_approver(
        NORTHWIND, MAYA, str(draft.id)
    )
    body = {
        "version": detail.entry.version,
        "verifiedReferenceUrl": "https://example.test/wrong",
    }
    assert (
        await client.post(path + "/approve", headers={"X-Dev-User": ALEX}, json=body)
    ).status_code == 403
    assert (await client.get(path, headers={"X-Dev-User": RILEY})).status_code in (
        403,
        404,
    )
    assert (
        await client.post(path + "/approve", headers={"X-Dev-User": MAYA}, json=body)
    ).status_code == 409
    body.update(version="stale", verifiedReferenceUrl="https://example.test/policy")
    assert (
        await client.post(path + "/approve", headers={"X-Dev-User": MAYA}, json=body)
    ).status_code == 409
    await session.refresh(draft)
    assert draft.status is DraftStatus.PENDING


async def test_reject_persists_without_publishing_and_cannot_be_redecided(
    setup, session
):
    _, draft, providers, client = setup
    detail = await providers.knowledge_review.get_for_approver(
        NORTHWIND, MAYA, str(draft.id)
    )
    path = f"/api/manager/knowledge/drafts/{draft.id}"
    body = {"version": detail.entry.version, "reason": "Needs an authoritative answer."}
    response = await client.post(
        path + "/reject", headers={"X-Dev-User": MAYA}, json=body
    )
    assert response.status_code == 200, response.text
    assert response.json()["decision"]["reason"] == body["reason"]
    again = await client.get(path, headers={"X-Dev-User": MAYA})
    assert again.json()["entry"]["status"] == "rejected"
    assert (
        await client.post(path + "/reject", headers={"X-Dev-User": MAYA}, json=body)
    ).status_code == 409


async def test_approval_persists_and_is_visible_to_agent_only_after_verification(
    setup, session
):
    data, _, providers, client = setup
    # Separate pending draft with no conflicting or duplicate relationship.
    draft = KnowledgeDraft(
        organization_id=data.northwind.id,
        topic_id=data.approved_entry.topic_id,
        answer_text="Authored independent test policy.",
        verification_reference={
            "title": "Authored test policy",
            "url": "https://example.test/policy",
        },
    )
    session.add(draft)
    await session.commit()
    path = f"/api/manager/knowledge/drafts/{draft.id}"
    detail = await providers.knowledge_review.get_for_approver(
        NORTHWIND, MAYA, str(draft.id)
    )
    body = {
        "version": detail.entry.version,
        "verifiedReferenceUrl": "https://example.test/policy",
    }
    response = await client.post(
        path + "/approve", headers={"X-Dev-User": MAYA}, json=body
    )
    assert response.status_code == 200, response.text
    rows = await client.get("/api/agent/knowledge", headers={"X-Dev-User": ALEX})
    assert any(
        "Authored independent test policy." in row["paragraphs"] for row in rows.json()
    )
    assert (
        await client.post(path + "/approve", headers={"X-Dev-User": MAYA}, json=body)
    ).status_code == 409
