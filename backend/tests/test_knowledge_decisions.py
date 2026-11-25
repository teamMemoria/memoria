"""Only a scoped, current, reference-verified human decision publishes knowledge."""

import json

import httpx
import pytest
from sqlalchemy import select

from backend.core.config import Settings
from backend.data.seed_policies import seed_demo_policies
from backend.entities.guidelines import GUIDELINE_URL, GUIDELINES, PROMO_AGE
from backend.entities.policies import (
    EXTENSION_URL,
    GOLD_EXTENSION_ANSWER,
    GOLD_EXTENSION_KEY,
    GOLD_EXTENSION_QUOTES,
)
from backend.main import create_app
from backend.models import DraftStatus, KnowledgeDraft, KnowledgeReview, ReviewAction
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
    app = create_app(providers=providers, settings=Settings(app_env="test"))
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        yield data, draft, providers, client


async def test_edit_persists_without_publishing_or_losing_source_evidence(
    setup, session
):
    data, draft, _, client = setup
    path = f"/api/manager/knowledge/drafts/{draft.id}"
    headers = {"X-Dev-User": MAYA}
    before = (await client.get(path, headers=headers)).json()
    draft_id, source_key = draft.id, draft.source_key
    assert before["canEdit"] is True
    before = before["entry"]
    change = {
        "version": before["version"],
        "title": "Refund follow-up",
        "question": "What should the customer do next?",
        "guidance": "Check the refund status first.\n\nThen explain the next step.",
    }
    foreign_draft = KnowledgeDraft(
        organization_id=data.harbor.id,
        topic_id=data.harbor_entry.topic_id,
        answer_text="A different organization's guidance.",
    )
    session.add(foreign_draft)
    await session.flush()
    foreign = await client.put(
        f"/api/manager/knowledge/drafts/{foreign_draft.id}/content",
        headers=headers,
        json=change,
    )
    assert foreign.status_code == 404
    assert (
        await client.put(path + "/content", headers={"X-Dev-User": ALEX}, json=change)
    ).status_code == 403
    assert (
        await client.put(
            path + "/content", headers=headers, json={**change, "guidance": "  "}
        )
    ).status_code == 422
    assert (
        await client.put(path + "-missing/content", headers=headers, json=change)
    ).status_code == 404
    response = await client.put(path + "/content", headers=headers, json=change)
    assert response.status_code == 200, response.text
    after = response.json()
    assert after["title"] == change["title"]
    assert after["question"] == change["question"]
    assert after["paragraphs"] == change["guidance"].split("\n\n")
    assert after["version"] != before["version"]
    assert after["status"] == "draft" and after["decision"] is None
    assert after["passages"] == before["passages"]
    assert after["sourceConversationIds"] == before["sourceConversationIds"]
    assert after["verificationReference"] is None
    assert (
        await client.put(path + "/content", headers=headers, json=change)
    ).status_code == 409
    noop = await client.put(
        path + "/content", headers=headers, json={**change, "version": after["version"]}
    )
    assert noop.json() == after
    events = list(
        await session.scalars(
            select(KnowledgeReview).where(KnowledgeReview.draft_id == draft_id)
        )
    )
    assert [event.action for event in events] == [ReviewAction.EDITED]
    assert json.loads(events[0].note)["version"] == before["version"]

    await import_fixture(session, data)
    stored = await draft_by_key(session, source_key)
    assert stored.answer_text == change["guidance"]
    assert stored.edited_question == change["question"]
    assert (await client.get(path, headers=headers)).json()["entry"][
        "version"
    ] == after["version"]
    for version in (before["version"], after["version"]):
        approve = await client.post(
            path + "/approve",
            headers=headers,
            json={
                "version": version,
                "verifiedReferenceUrl": before["verificationReference"]["url"],
            },
        )
        assert approve.status_code == 409
    agent = await client.get("/api/agent/knowledge", headers={"X-Dev-User": ALEX})
    assert all(
        after["paragraphs"][0] not in entry["paragraphs"] for entry in agent.json()
    )


async def test_edit_cannot_reuse_the_catalogue_version_for_different_layer_1_guidance(
    setup, session
):
    _, _, _, client = setup
    await seed_demo_policies(session, NORTHWIND)
    await session.commit()
    headers = {"X-Dev-User": MAYA}
    entries = (
        await client.get("/api/manager/knowledge/drafts", headers=headers)
    ).json()
    before = next(entry for entry in entries if entry["layer"] == "layer1")
    assert before["authoredPolicyVersion"]
    path = f"/api/manager/knowledge/drafts/{before['id']}"
    change = {
        "version": before["version"],
        "title": "Updated policy draft",
        "question": before["question"],
        "guidance": "New guidance awaiting an authoritative review.",
    }
    response = await client.put(path + "/content", headers=headers, json=change)
    assert response.status_code == 200, response.text
    after = response.json()
    assert after["layer"] == "layer1"
    assert after["authoredPolicyVersion"] is None
    approval = await client.post(
        path + "/approve",
        headers=headers,
        json={
            "version": after["version"],
            "authoredPolicyVersion": before["authoredPolicyVersion"],
        },
    )
    assert approval.status_code == 409
    rejection = await client.post(
        path + "/reject",
        headers=headers,
        json={
            "version": after["version"],
            "reason": "Requires authority.",
        },
    )
    assert rejection.status_code == 200
    assert (await client.get(path, headers=headers)).json()["canEdit"] is False
    updated = await client.put(
        path + "/content",
        headers=headers,
        json={
            **change,
            "version": rejection.json()["version"],
        },
    )
    assert updated.status_code == 409


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


async def test_unapprove_withdraws_publication_and_allows_fresh_approval(
    setup, session
):
    data, _, _, client = setup
    reference_url = "https://example.test/policy"
    guide = "Check the customer's membership before extending a subscription."
    draft = KnowledgeDraft(
        organization_id=data.northwind.id,
        topic_id=data.approved_entry.topic_id,
        answer_text=guide,
        verification_reference={"title": "Membership policy", "url": reference_url},
    )
    session.add(draft)
    await session.commit()
    draft_id = draft.id
    path = f"/api/manager/knowledge/drafts/{draft_id}"
    manager = {"X-Dev-User": MAYA}
    agent = {"X-Dev-User": ALEX}
    pending = (await client.get(path, headers=manager)).json()["entry"]
    approve_body = {
        "version": pending["version"],
        "verifiedReferenceUrl": reference_url,
    }
    approved = await client.post(path + "/approve", headers=manager, json=approve_body)
    assert approved.status_code == 200, approved.text
    approved_version = approved.json()["version"]
    published = (await client.get("/api/agent/knowledge", headers=agent)).json()
    published_id = next(row["id"] for row in published if guide in row["paragraphs"])

    revoke = path + "/unapprove"
    assert (
        await client.post(revoke, headers=agent, json={"version": approved_version})
    ).status_code == 403
    assert (
        await client.post(revoke, headers=manager, json={"version": "old"})
    ).status_code == 409
    response = await client.post(
        revoke, headers=manager, json={"version": approved_version}
    )
    assert response.status_code == 200, response.text
    updated = response.json()
    assert updated["status"] == "draft" and updated["decision"] is None
    assert updated["version"] != approved_version
    assert updated["paragraphs"] == [guide]
    assert updated["verificationReference"] == pending["verificationReference"]
    assert (await client.get(path, headers=manager)).json()["canEdit"] is True
    assert (
        await client.get(f"/api/agent/knowledge/{published_id}", headers=agent)
    ).status_code == 404
    assert (
        len((await client.get("/api/agent/knowledge", headers=agent)).json())
        == len(published) - 1
    )
    assert (
        await client.post(revoke, headers=manager, json={"version": approved_version})
    ).status_code == 409
    assert (
        await client.post(path + "/approve", headers=manager, json=approve_body)
    ).status_code == 409
    approve_body["version"] = updated["version"]
    assert (
        await client.post(path + "/approve", headers=manager, json=approve_body)
    ).status_code == 200
    republished = (await client.get("/api/agent/knowledge", headers=agent)).json()
    [latest] = [row for row in republished if guide in row["paragraphs"]]
    assert latest["id"] != published_id
    events = await session.scalars(
        select(KnowledgeReview.action)
        .where(KnowledgeReview.draft_id == draft_id)
        .order_by(KnowledgeReview.id)
    )
    assert events.all() == [
        ReviewAction.APPROVED,
        ReviewAction.UNAPPROVED,
        ReviewAction.APPROVED,
    ]


async def test_authoritative_source_can_be_attached_and_approved(setup, session):
    data, _, _, client = setup
    guideline = GUIDELINES[PROMO_AGE]
    draft = KnowledgeDraft(
        organization_id=data.northwind.id,
        topic_id=data.approved_entry.topic_id,
        source_key=PROMO_AGE,
        answer_text=guideline.answer,
    )
    session.add(draft)
    await session.commit()
    path = f"/api/manager/knowledge/drafts/{draft.id}"
    headers = {"X-Dev-User": MAYA}
    detail = (await client.get(path, headers=headers)).json()["entry"]
    assert detail["canAttachVerification"] is True
    body = {
        "title": "ABCD publisher guideline",
        "url": GUIDELINE_URL,
        "quote": guideline.quote,
        "version": detail["version"],
    }
    for invalid in (
        {"url": "https://example.test/unrelated"},
        {"quote": "This is not the publisher's quotation."},
    ):
        response = await client.put(
            path + "/verification", headers=headers, json={**body, **invalid}
        )
        assert response.status_code == 409
    await session.refresh(draft)
    assert draft.verification_reference is None

    response = await client.put(path + "/verification", headers=headers, json=body)
    assert response.status_code == 200, response.text
    attached = response.json()
    assert attached["status"] == "draft"
    assert attached["version"] != detail["version"]
    assert attached["verificationReference"]["url"] == GUIDELINE_URL
    response = await client.post(
        path + "/approve",
        headers=headers,
        json={"version": attached["version"], "verifiedReferenceUrl": GUIDELINE_URL},
    )
    assert response.status_code == 200, response.text
    assert response.json()["canAttachVerification"] is False


async def test_single_click_approval_records_the_exact_publisher_source(setup, session):
    data, _, _, client = setup
    draft = KnowledgeDraft(
        organization_id=data.northwind.id,
        topic_id=data.approved_entry.topic_id,
        source_key=GOLD_EXTENSION_KEY,
        question="How should an Agent handle an eligible Gold subscription extension?",
        answer_text=GOLD_EXTENSION_ANSWER,
    )
    session.add(draft)
    await session.commit()
    path = f"/api/manager/knowledge/drafts/{draft.id}"
    headers = {"X-Dev-User": MAYA}
    before = (await client.get(path, headers=headers)).json()["entry"]
    assert before["approvalReference"]["url"] == EXTENSION_URL
    assert before["verificationReference"] is None
    body = {"version": before["version"], "verifiedReferenceUrl": EXTENSION_URL}
    for invalid in (
        {"verifiedReferenceUrl": None},
        {"verifiedReferenceUrl": "https://example.test/unrelated"},
        {"version": "stale"},
    ):
        response = await client.post(
            path + "/approve", headers=headers, json={**body, **invalid}
        )
        assert response.status_code == 409
    assert draft.verification_reference is None
    response = await client.post(path + "/approve", headers=headers, json=body)
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "approved"
    assert response.json()["approvalReference"] is None
    await session.refresh(draft)
    assert draft.verification_reference["url"] == EXTENSION_URL
    assert draft.verification_reference["quote"].splitlines() == list(
        GOLD_EXTENSION_QUOTES
    )
    review = await session.scalar(
        select(KnowledgeReview).where(KnowledgeReview.draft_id == draft.id)
    )
    assert review.verified_reference_url == EXTENSION_URL


@pytest.mark.parametrize(
    "source_key",
    ["layer2-promo-days-7", "layer2-question-unverified", PROMO_AGE],
)
async def test_draft_without_matching_authority_cannot_attach_source(
    setup, session, source_key
):
    data, _, _, client = setup
    draft = KnowledgeDraft(
        organization_id=data.northwind.id,
        topic_id=data.approved_entry.topic_id,
        source_key=source_key,
        answer_text="Standard promo codes expire after 7 days.",
    )
    session.add(draft)
    await session.commit()
    path = f"/api/manager/knowledge/drafts/{draft.id}"
    headers = {"X-Dev-User": MAYA}
    detail = (await client.get(path, headers=headers)).json()["entry"]
    assert detail["canAttachVerification"] is False
    response = await client.put(
        path + "/verification",
        headers=headers,
        json={
            "title": "Unverified policy",
            "url": GUIDELINE_URL
            if source_key == PROMO_AGE
            else "https://example.test/unrelated",
            "quote": GUIDELINES[PROMO_AGE].quote
            if source_key == PROMO_AGE
            else draft.answer_text,
            "version": detail["version"],
        },
    )
    assert response.status_code == 409
    await session.refresh(draft)
    assert draft.verification_reference is None
