import copy

import pytest
from sqlalchemy import select

from backend.models import DraftStatus, KnowledgeDraft
from backend.services.knowledge_import import KnowledgeImportService
from tests.database_seed import HARBOR, NORTHWIND, seed, sessions_for
from tests.test_knowledge_import import APPROVER, client_for, table_counts


@pytest.fixture
async def data(session):
    return await seed(session)


async def test_connected_rule_generation_is_scoped_repeatable_and_pending(
    session, data
):
    from ml.knowledge_candidates import generate_candidates
    from ml.test_knowledge_candidates import evidence

    prepared = evidence(
        [
            ["customer", "What is the return policy?"],
            ["agent", "The return policy requires a valid receipt."],
        ],
        identifier=6543,
    )
    await import_prepared(session, data.northwind.id, data.alex_agent.id, prepared)
    await session.commit()
    service = KnowledgeImportService(
        sessions_for(session), generate=generate_candidates, source_ids=("6543", "6544")
    )
    before = await table_counts(session)
    first = await service.run(NORTHWIND)
    second = await service.run(NORTHWIND)
    assert (first.created, second.created, second.unchanged) == (1, 0, 1)
    assert not first.skipped
    assert {r["status"] for r in first.generation} == {"completed", "unavailable"}
    after = await table_counts(session)
    assert after["entries"] == before["entries"]
    assert after["reviews"] == before["reviews"]
    draft = await session.scalar(
        select(KnowledgeDraft).where(KnowledgeDraft.source_key.like("linked-%"))
    )
    assert draft.status is DraftStatus.PENDING and draft.verification_reference is None
    assert draft.ml_verification == "unverifiable"
    other = await service.run(HARBOR)
    assert other.created == 0
    assert all(row["status"] == "unavailable" for row in other.generation)


async def test_generation_does_not_read_noncohort_or_held_out_content(session, data):
    from ml.knowledge_candidates import generate_candidates
    from ml.test_knowledge_candidates import evidence

    prepared = evidence(
        [["customer", "Is the hood removable?"], ["agent", "The hood is removable."]],
        identifier=6533,
    )
    call = await import_prepared(
        session, data.northwind.id, data.alex_agent.id, prepared
    )
    await session.commit()
    received = []

    def capture(organization, records):
        received.extend(records)
        return generate_candidates(organization, records)

    service = KnowledgeImportService(
        sessions_for(session), generate=capture, source_ids=("9999",)
    )
    await service.run(NORTHWIND)
    assert not received
    # Synthetic split metadata only; no actual held-out data is loaded by tests.
    modified = copy.deepcopy(prepared)
    modified["conversations"][0]["split"] = "test"
    call.canonical_evidence = modified
    await session.commit()
    service.source_ids = ("6533",)
    await service.run(NORTHWIND)
    assert not received


async def import_prepared(session, organization_id, agent_id, prepared):
    """Only authored fixtures; use main's canonical storage contract directly."""
    from backend.models import Conversation, Speaker, Turn

    source = prepared["conversations"][0]
    call = Conversation(
        organization_id=organization_id,
        agent_id=agent_id,
        source_dataset="ABCD",
        original_id=source["id"],
        channel="chat",
        canonical_evidence=prepared,
        turns=[
            Turn(
                line_number=e["turn_id"], speaker=Speaker(e["speaker"]), text=e["text"]
            )
            for e in source["events"]
        ],
    )
    session.add(call)
    await session.flush()
    return call


async def test_generation_api_retains_authorization_and_reports_progress(session, data):
    from ml.knowledge_candidates import generate_candidates
    from ml.test_knowledge_candidates import evidence

    from tests.database_seed import ALEX

    prepared = evidence(
        [["customer", "Is the hood removable?"], ["agent", "No."]], identifier=6543
    )
    await import_prepared(session, data.northwind.id, data.alex_agent.id, prepared)
    await session.commit()
    service = KnowledgeImportService(
        sessions_for(session), generate=generate_candidates, source_ids=("6543", "6544")
    )
    async with client_for(session) as client:
        client._transport.app.state.knowledge_import = service
        refused = await client.post(
            "/api/manager/knowledge/imports", headers={"X-Dev-User": ALEX}
        )
        first = await client.post("/api/manager/knowledge/imports", headers=APPROVER)
        again = await client.post("/api/manager/knowledge/imports", headers=APPROVER)
    assert refused.status_code == 403
    assert first.status_code == again.status_code == 200
    assert first.json()["created"] == again.json()["unchanged"] == 1
    assert {r["status"] for r in first.json()["generation"]} == {
        "completed",
        "unavailable",
    }


async def test_mismatched_canonical_identifier_stays_outside_generation(session, data):
    from ml.knowledge_candidates import generate_candidates
    from ml.test_knowledge_candidates import evidence

    prepared = evidence(
        [["customer", "Is the hood removable?"], ["agent", "Yes."]], identifier=6543
    )
    call = await import_prepared(
        session, data.northwind.id, data.alex_agent.id, prepared
    )
    call.original_id = "9999"
    await session.commit()
    received = []

    def capture(organization, records):
        received.extend(records)
        return generate_candidates(organization, records)

    result = await KnowledgeImportService(
        sessions_for(session), generate=capture, source_ids=("9999",)
    ).run(NORTHWIND)
    assert not received and result.created == 0
    assert result.generation[0]["status"] == "unavailable"


async def test_opt_in_composition_uses_existing_training_mapping_without_scoring():
    from backend.core.config import Settings
    from backend.data.demo_profiles import load_profiles
    from backend.main import create_app
    from backend.providers import create_fixture_providers

    app = create_app(
        providers=create_fixture_providers(),
        settings=Settings(app_env="test", knowledge_engine="rules"),
    )
    try:
        service = app.state.knowledge_import
        profiles = load_profiles()
        assert service.generate.__module__ == "ml.knowledge_candidates"
        assert service.source_ids == tuple(
            c for a in profiles.agents for c in a.conversations
        )
        assert len(service.source_ids) == len(set(service.source_ids)) == 117
        assert app.openapi()["paths"][
            "/api/manager/knowledge/drafts/{draft_id}/approve"
        ]
        assert app.openapi()["paths"]["/api/manager/knowledge/drafts/{draft_id}/reject"]
    finally:
        await app.state.database.close()
