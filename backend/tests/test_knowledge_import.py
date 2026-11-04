import copy
import json
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

import httpx
import pytest
from sqlalchemy import func, select

from backend.core.config import Settings
from backend.main import create_app
from backend.models import (
    DraftStatus,
    EntryStatus,
    KnowledgeConflict,
    KnowledgeDraft,
    KnowledgeDraftEntryMatch,
    KnowledgeDraftPassage,
    KnowledgeEntry,
    KnowledgeReview,
    ReviewAction,
    knowledge_draft_conversations,
)
from backend.providers import create_fixture_providers
from backend.providers.database import create_database_providers
from backend.services.knowledge_import import (
    ImportRejectedError,
    KnowledgeImportService,
)
from tests.database_seed import ALEX, HARBOR, MAYA, NORTHWIND, seed, sessions_for

FIXTURE = Path(__file__).parent / "fixtures" / "knowledge_pipeline_output.json"
NOW = datetime(2026, 11, 3, 8, 0, tzinfo=UTC)


def pipeline_output(data) -> dict:
    """The fixed pipeline output, pointed at this test's approved entry."""
    text = FIXTURE.read_text().replace("{approved_entry}", data.id(data.approved_entry))
    return json.loads(text)


@pytest.fixture
async def data(session):
    return await seed(session)


def service_for(session, adapter=None):
    kwargs = {"adapter": adapter} if adapter is not None else {}
    return KnowledgeImportService(sessions_for(session), now=lambda: NOW, **kwargs)


async def import_fixture(session, data, output=None):
    result = await service_for(session).import_output(
        NORTHWIND, output if output is not None else pipeline_output(data)
    )
    session.expunge_all()
    return result


async def draft_by_key(session, key) -> KnowledgeDraft:
    return await session.scalar(
        select(KnowledgeDraft).where(KnowledgeDraft.source_key == key)
    )


async def table_counts(session) -> dict[str, int]:
    counts = {}
    for name, table in [
        ("drafts", KnowledgeDraft),
        ("passages", KnowledgeDraftPassage),
        ("matches", KnowledgeDraftEntryMatch),
        ("conflicts", KnowledgeConflict),
        ("reviews", KnowledgeReview),
        ("entries", KnowledgeEntry),
    ]:
        counts[name] = await session.scalar(select(func.count()).select_from(table))
    counts["sources"] = await session.scalar(
        select(func.count()).select_from(knowledge_draft_conversations)
    )
    return counts


# --- storing ----------------------------------------------------------------------------


async def test_drafts_are_stored_pending_with_their_evidence(session, data):
    result = await import_fixture(session, data)
    assert (result.created, result.updated, result.unchanged) == (3, 0, 0)
    assert {item.get("draftId"): item["reason"] for item in result.skipped} == {
        "draft_not_stored": "conversation-not-found",
        "draft_misquoted": "passage-not-in-transcript",
        None: "unresolved-side",
    }
    assert result.conflicts_stored == 2

    draft = await draft_by_key(session, "draft_refund_assessed")
    assert draft.status is DraftStatus.PENDING
    assert draft.question == "My jacket arrived torn and I would like a refund."
    assert draft.ml_verification == "supported"
    passages = (
        await session.scalars(
            select(KnowledgeDraftPassage)
            .where(KnowledgeDraftPassage.draft_id == draft.id)
            .order_by(KnowledgeDraftPassage.position)
        )
    ).all()
    assert [(p.role, p.turn_number, p.speaker) for p in passages] == [
        ("question", 1, "customer"),
        ("answer", 2, "agent"),
        ("condition", 5, "system_action"),
    ]
    assert {(p.source_key, p.source_version) for p in passages} == {
        ("Synthetic:assessed", "authored")
    }
    assert {p.conversation_id for p in passages} == {data.assessed.id}


async def test_duplicates_matches_and_groups_are_kept(session, data):
    await import_fixture(session, data)
    original = await draft_by_key(session, "draft_refund_assessed")
    duplicate = await draft_by_key(session, "draft_refund_sam")
    assert duplicate.duplicate_of_id == original.id
    assert float(duplicate.duplicate_similarity) == 1.0
    assert original.group_key == duplicate.group_key == "group_refund_original_card"
    matches = (await session.scalars(select(KnowledgeDraftEntryMatch))).all()
    assert {(m.draft_id, m.entry_id) for m in matches} == {
        (original.id, data.approved_entry.id),
        (duplicate.id, data.approved_entry.id),
    }


async def test_reimporting_the_same_output_changes_nothing(session, data):
    await import_fixture(session, data)
    before = await table_counts(session)
    again = await import_fixture(session, data)
    assert (again.created, again.updated, again.unchanged) == (0, 0, 3)
    assert await table_counts(session) == before


async def test_a_changed_pending_draft_is_updated_in_place(session, data):
    await import_fixture(session, data)
    output = pipeline_output(data)
    draft = output["drafts"][0]
    checked = "I have checked the order and the refund is on its way."
    draft["answer"] = checked
    draft["answer_passages"][0].update(
        turn_id="assessed#t7", quote=checked, span=[0, len(checked)]
    )
    result = await import_fixture(session, data, output)
    assert (result.created, result.updated) == (0, 1)
    stored = await draft_by_key(session, "draft_refund_assessed")
    assert stored.answer_text == checked
    assert stored.updated_at == NOW
    imported = select(func.count()).where(KnowledgeDraft.source_key.is_not(None))
    assert await session.scalar(imported) == 3


async def test_a_reviewed_draft_is_never_overwritten(session, data):
    await import_fixture(session, data)
    draft = await draft_by_key(session, "draft_refund_assessed")
    draft.status = DraftStatus.REJECTED
    session.add(
        KnowledgeReview(
            organization_id=data.northwind.id,
            draft_id=draft.id,
            action=ReviewAction.REJECTED,
            reviewer_membership_id=data.maya.id,
            note="Refunds need the order checked first.",
        )
    )
    await session.commit()
    session.expunge_all()

    output = pipeline_output(data)
    output["drafts"][0]["question"] = "A different question?"
    result = await import_fixture(session, data, output)
    stored = await draft_by_key(session, "draft_refund_assessed")
    assert stored.status is DraftStatus.REJECTED
    assert stored.question == "My jacket arrived torn and I would like a refund."
    assert result.updated == 0


async def test_the_pipeline_cannot_approve_dispute_or_renew_guidance(session, data):
    entry_before = await session.get(KnowledgeEntry, data.approved_entry.id)
    snapshot = (entry_before.status, entry_before.last_confirmed_at)
    session.expunge_all()
    before = await table_counts(session)
    await import_fixture(session, data)
    after = await table_counts(session)
    assert (after["entries"], after["reviews"]) == (
        before["entries"],
        before["reviews"],
    )

    entry = await session.get(KnowledgeEntry, data.approved_entry.id)
    # A possible conflict with the entry is stored, but the entry is not disputed.
    assert (entry.status, entry.last_confirmed_at) == snapshot
    assert entry.status is EntryStatus.APPROVED
    conflict = await session.scalar(
        select(KnowledgeConflict).where(
            KnowledgeConflict.source_key == "conflict_checked_vs_entry"
        )
    )
    assert (conflict.status, conflict.other_entry_id) == (
        "possible_conflict",
        data.approved_entry.id,
    )


async def test_new_drafts_never_reach_approved_guidance(session, data):
    providers = create_database_providers(sessions_for(session))
    before = await providers.knowledge.list_for_agent(NORTHWIND, ALEX)
    await import_fixture(session, data)
    assert await providers.knowledge.list_for_agent(NORTHWIND, ALEX) == before


def trusted(output):
    output["drafts"][0]["trusted"] = True


def approved(output):
    output["drafts"][1]["status"] = "approved"


def other_company(output):
    output["company_id"] = HARBOR


def failed(output):
    output["status"] = "error"


def release_blocked(output):
    output["release_checks"]["release_allowed"] = False


def other_schema(output):
    output["schema"] = "knowledge-pipeline/2"


@pytest.mark.parametrize(
    "change", [trusted, approved, other_company, failed, release_blocked, other_schema]
)
async def test_untrustworthy_output_is_refused_whole(session, data, change):
    output = copy.deepcopy(pipeline_output(data))
    change(output)
    before = await table_counts(session)
    with pytest.raises(ImportRejectedError):
        await service_for(session).import_output(NORTHWIND, output)
    assert await table_counts(session) == before


# --- the review queue ---------------------------------------------------------------------


def client_for(session, adapter=None):
    app = create_app(
        providers=create_database_providers(sessions_for(session)),
        settings=Settings(app_env="test"),
        knowledge_import=service_for(session, adapter),
    )
    return httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    )


APPROVER = {"X-Dev-User": MAYA}


async def drafts(client, **params):
    response = await client.get(
        "/api/manager/knowledge/drafts", params=params, headers=APPROVER
    )
    assert response.status_code == 200
    return response.json()


async def test_queue_lists_stored_drafts_with_counts_and_filters(session, data):
    await import_fixture(session, data)
    async with client_for(session) as client:
        pending = await drafts(client, status="draft")
        assert len(pending) == 3
        assert all(d["availableToAgentIds"] == [] for d in pending)
        # The seeded approved entries came from drafts that were approved earlier.
        approved = await drafts(client, status="approved")
        assert len(approved) == 3
        assert len(await drafts(client)) == 6

        refund = next(d for d in pending if d["paragraphs"][0].startswith("I can"))
        # Two stored conversations back the group; the pipeline's count of 3
        # included a conversation that is not stored.
        assert refund["distinctConversationCount"] == 2
        assert refund["existingMatches"][0]["entryId"] == data.id(data.approved_entry)

        conflicted = await drafts(client, possibleConflicts="true")
        assert len(conflicted) == 2
        assert {c["status"] for d in conflicted for c in d["possibleConflicts"]} == {
            "possible_conflict",
            "unresolved",
        }
        assert len(await drafts(client, q="ON ITS WAY")) == 1

        counts = await client.get(
            "/api/manager/knowledge/drafts/counts", headers=APPROVER
        )
        assert counts.json() == {
            "total": 6,
            "draft": 3,
            "approved": 3,
            "rejected": 0,
            "withPossibleConflicts": 2,
        }


async def test_detail_keeps_source_ids_and_versions(session, data):
    await import_fixture(session, data)
    draft = await draft_by_key(session, "draft_refund_assessed")
    async with client_for(session) as client:
        response = await client.get(
            f"/api/manager/knowledge/drafts/{draft.id}", headers=APPROVER
        )
    detail = response.json()
    assert detail["canDecide"] is True
    entry = detail["entry"]
    assert entry["sourceConversationIds"] == [data.id(data.assessed)]
    assert entry["passages"] == [
        {
            "conversationId": data.id(data.assessed),
            "turnNumber": 1,
            "speaker": "Customer",
            "text": "My jacket arrived torn and I would like a refund.",
            "role": "question",
            "sourceKey": "Synthetic:assessed",
            "sourceVersion": "authored",
        },
        {
            "conversationId": data.id(data.assessed),
            "turnNumber": 2,
            "speaker": "Agent",
            "text": "I can refund that to your original card.",
            "role": "answer",
            "sourceKey": "Synthetic:assessed",
            "sourceVersion": "authored",
        },
    ]
    assert entry["decision"] is None
    assert entry["mlVerification"] == "supported"


async def test_the_queue_is_for_knowledge_approvers_in_their_organization(
    session, data
):
    await import_fixture(session, data)
    draft = await draft_by_key(session, "draft_refund_assessed")
    async with client_for(session) as client:
        agent = await client.get(
            "/api/manager/knowledge/drafts", headers={"X-Dev-User": ALEX}
        )
        assert agent.status_code == 403
        harbor = await client.get(
            "/api/manager/knowledge/drafts", headers={"X-Dev-User": "manager-harbor"}
        )
        assert str(draft.id) not in {d["id"] for d in harbor.json()}
        assert {d["status"] for d in harbor.json()} == {"approved"}
        other_org_detail = await client.get(
            f"/api/manager/knowledge/drafts/{draft.id}",
            headers={"X-Dev-User": "manager-harbor"},
        )
        assert other_org_detail.status_code == 404


class FixedPipeline:
    def __init__(self, output):
        self.output = output

    def run(self, organization_id):
        return self.output


async def test_import_route_runs_the_pipeline(session, data):
    async with client_for(session, FixedPipeline(pipeline_output(data))) as client:
        first = await client.post("/api/manager/knowledge/imports", headers=APPROVER)
        second = await client.post("/api/manager/knowledge/imports", headers=APPROVER)
        agent = await client.post(
            "/api/manager/knowledge/imports", headers={"X-Dev-User": ALEX}
        )
    assert first.status_code == 200
    assert (first.json()["created"], second.json()["unchanged"]) == (3, 3)
    assert agent.status_code == 403


async def test_import_route_reports_refused_and_missing_pipelines(session, data):
    output = pipeline_output(data)
    output["status"] = "error"
    async with client_for(session, FixedPipeline(output)) as client:
        refused = await client.post("/api/manager/knowledge/imports", headers=APPROVER)
    async with client_for(session) as client:
        missing = await client.post("/api/manager/knowledge/imports", headers=APPROVER)
    assert (refused.status_code, missing.status_code) == (422, 503)


async def test_the_queue_needs_the_database_when_running_on_fixtures():
    app = create_app(
        providers=replace(create_fixture_providers()),
        settings=Settings(app_env="test"),
    )
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.get(
            "/api/manager/knowledge/drafts",
            headers={"X-Dev-User": "approver-devon-park"},
        )
    assert response.status_code == 503


# --- later imports, bad values and concurrency --------------------------------------------


async def test_a_later_import_clears_facts_it_no_longer_reports(session, data):
    await import_fixture(session, data)
    output = pipeline_output(data)
    output["drafts"] = [
        d for d in output["drafts"] if d["draft_id"] != "draft_refund_sam"
    ]
    group = output["groups"]["groups"][0]
    group["member_draft_ids"] = ["draft_refund_assessed"]
    group["duplicates"] = []
    output["conflicts"]["possible_conflicts"] = []
    await import_fixture(session, data, output)

    sam = await draft_by_key(session, "draft_refund_sam")
    assert (sam.group_key, sam.duplicate_of_id) == (None, None)
    assert (
        await session.scalar(select(func.count()).select_from(KnowledgeConflict)) == 0
    )
    async with client_for(session) as client:
        pending = await drafts(client, status="draft")
    assessed = await draft_by_key(session, "draft_refund_assessed")
    refund = next(d for d in pending if d["id"] == str(assessed.id))
    assert refund["distinctConversationCount"] == 1
    assert refund["possibleConflicts"] == []


def repeated_match(output):
    group = output["groups"]["groups"][0]
    group["existing_matches"] *= 2


def long_source_version(output):
    output["drafts"][0]["answer_passages"][0]["source_version"] = "v" * 101


def question_not_text(output):
    output["drafts"][0]["question"] = ["not", "text"]


def speaker_not_text(output):
    output["drafts"][0]["answer_passages"][0]["speaker"] = ["agent"]


@pytest.mark.parametrize(
    ("change", "created"),
    [
        (repeated_match, 3),
        (long_source_version, 2),
        (question_not_text, 2),
        (speaker_not_text, 2),
    ],
)
async def test_bad_values_skip_a_draft_not_the_import(session, data, change, created):
    output = pipeline_output(data)
    change(output)
    result = await import_fixture(session, data, output)
    assert result.created == created


async def test_wrongly_typed_sections_reject_the_whole_import(session, data):
    output = pipeline_output(data)
    output["verification"] = ["x"]
    before = await table_counts(session)
    with pytest.raises(ImportRejectedError):
        await service_for(session).import_output(NORTHWIND, output)
    assert await table_counts(session) == before


class CrashingPipeline:
    def run(self, organization_id):
        raise RuntimeError("bug")


async def test_a_crashing_pipeline_is_reported_as_unavailable(session, data):
    async with client_for(session, CrashingPipeline()) as client:
        response = await client.post("/api/manager/knowledge/imports", headers=APPROVER)
    assert response.status_code == 503
    assert response.json() == {
        "detail": "The knowledge pipeline failed with RuntimeError."
    }


async def test_concurrent_imports_store_each_draft_once(committed_sessions):
    import asyncio

    async with committed_sessions() as session:
        data = await seed(session)
    service = KnowledgeImportService(committed_sessions, now=lambda: NOW)
    output = pipeline_output(data)
    results = await asyncio.gather(
        *[service.import_output(NORTHWIND, copy.deepcopy(output)) for _ in range(4)]
    )
    assert sum(result.created for result in results) == 3
    async with committed_sessions() as session:
        imported = select(func.count()).where(KnowledgeDraft.source_key.is_not(None))
        assert await session.scalar(imported) == 3
