import copy

import pytest

from sqlalchemy import select

from backend.models import DraftStatus, KnowledgeDraft
from backend.services.knowledge_import import KnowledgeImportService
from tests.database_seed import HARBOR, NORTHWIND, seed, sessions_for
from tests.test_knowledge_import import table_counts


@pytest.fixture
async def data(session):
    return await seed(session)


async def test_connected_rule_generation_is_scoped_repeatable_and_pending(
    session, data
):
    from ml.knowledge_candidates import generate_candidates
    from ml.test_rule_scoring import evidence

    from backend.services.rule_assessment import import_prepared

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
    from ml.test_rule_scoring import evidence

    from backend.services.rule_assessment import import_prepared

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
