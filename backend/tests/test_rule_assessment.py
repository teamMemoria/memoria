"""Prepared evidence crosses the existing ownership and analysis boundaries intact."""

from copy import deepcopy
from datetime import UTC, datetime

import pytest
from ml.test_evidence import prepared
from sqlalchemy import select

from backend.models import AnalysisRunStatus, Audit, Finding
from backend.providers.database import create_database_providers, with_scoring
from backend.schemas.call_review import CallFinding
from backend.schemas.reviews import DecisionInput
from backend.services.analysis import AnalysisService
from backend.services.rule_assessment import (
    LocalRuleAdapter,
    import_prepared,
    load_rule_context,
)
from tests.database_seed import ALEX, HARBOR, MAYA, NORTHWIND, SAM, seed, sessions_for

NOW = datetime(2026, 11, 9, tzinfo=UTC)


@pytest.fixture
async def imported(session):
    data = await seed(session)
    evidence = prepared()
    conversation = await import_prepared(
        session,
        data.northwind.id,
        data.alex_agent.id,
        evidence,
    )
    await session.commit()
    return data, conversation, evidence


def rules(session, adapter=None):
    context = load_rule_context()
    context["tables"]["review_package"]["status"] = "draft"
    return AnalysisService(
        sessions_for(session),
        adapter=adapter or LocalRuleAdapter(),
        now=lambda: NOW,
        scoring_context=context,
    )


async def run(session, data, conversation, adapter=None):
    service = rules(session, adapter)
    started = await service.start(NORTHWIND, str(conversation.id), requested_by=MAYA)
    return await service.execute(started.run.id)


async def test_import_preserves_masked_evidence_and_ownership(session, imported):
    data, conversation, evidence = imported
    again = await import_prepared(
        session, data.northwind.id, data.alex_agent.id, evidence
    )
    assert again.id == conversation.id
    assert again.canonical_evidence == evidence
    assert again.source_fields == {} and again.customer_record is None
    assert [turn.line_number for turn in again.turns] == [1, 2, 3, 4, 5, 6]
    with pytest.raises(ValueError, match="organization"):
        await import_prepared(session, data.harbor.id, data.alex_agent.id, evidence)
    with pytest.raises(ValueError, match="ownership"):
        await import_prepared(session, data.northwind.id, data.sam_agent.id, evidence)


async def test_unmasked_modified_or_held_out_evidence_is_rejected(session, imported):
    data, _, evidence = imported
    for mutate in (
        lambda item: item["conversations"][0]["events"][0].update(text="changed"),
        lambda item: item.update(answer_label="gold-canary"),
        lambda item: item["conversations"][0].update(split="test"),
    ):
        invalid = deepcopy(evidence)
        mutate(invalid)
        with pytest.raises(ValueError):
            await import_prepared(
                session, data.northwind.id, data.alex_agent.id, invalid
            )


async def test_rule_run_persists_full_report_and_keeps_approvals_pending(
    session, imported
):
    data, conversation, evidence = imported
    completed = await run(session, data, conversation)
    assert completed.status is AnalysisRunStatus.SUCCEEDED, completed.error_message
    audit = await session.get(Audit, completed.audit_id)
    assert audit.assessment_report == completed.assessment_report
    assert (
        audit.assessment_report["transcript_version"]
        == evidence["conversations"][0]["transcript_version"]
    )
    assert audit.assessment_report["overall"]["score"] is None
    assert all(
        row["scoring"]["score"] is None for row in audit.assessment_report["categories"]
    )
    providers = create_database_providers(sessions_for(session))
    own = await providers.calls.get_for_agent(NORTHWIND, ALEX, str(conversation.id))
    assert own.overall_scoring.score is None
    assert own.decision is None and own.review_request is None
    assert len(own.criteria) == 4
    assert all(row.scoring is not None for row in own.criteria)
    assert [
        (turn.number, turn.speaker)
        for turn in own.transcript.turns
        if turn.speaker == "System action"
    ] == [(3, "System action"), (5, "System action")]
    assert (
        await providers.calls.get_for_agent(NORTHWIND, SAM, str(conversation.id))
        is None
    )
    assert (
        await providers.calls.get_for_agent(HARBOR, ALEX, str(conversation.id)) is None
    )
    manager = await providers.reviews.get_for_manager(
        NORTHWIND, MAYA, str(conversation.id)
    )
    assert manager.call.criteria == own.criteria
    summary = next(
        item
        for item in await providers.conversations.list_for_agent(NORTHWIND, ALEX)
        if item.id == str(conversation.id)
    )
    assert summary.overall_scoring == own.overall_scoring

    findings = [
        CallFinding(
            id=criterion.id,
            title=criterion.title,
            criterion_id=criterion.id,
            explanation="Directly evidenced test finding",
            suggestion="Inspect the cited evidence",
            evidence_turn_numbers=[],
            reference_id=None,
            reference_step=None,
            procedure_steps=[],
        )
        for criterion in own.criteria
    ]
    report = deepcopy(audit.assessment_report)
    report["priorities"] = [{"category": findings[-1].criterion_id}]
    projected = with_scoring(own.model_copy(update={"findings": findings}), report)
    assert projected.findings == [findings[-1], *findings[:-1]]


async def test_fabricated_percentage_rejected_before_persistence(session, imported):
    data, conversation, _ = imported

    class Tampered(LocalRuleAdapter):
        def analyse(self, request):
            report = super().analyse(request)
            report["categories"][0]["scoring"]["score"] = 100
            return report

    failed = await run(session, data, conversation, Tampered())
    assert failed.status is AnalysisRunStatus.FAILED
    assert failed.audit_id is None and failed.assessment_report is None
    assert (
        await session.scalar(
            select(Audit).where(Audit.conversation_id == conversation.id)
        )
        is None
    )


async def test_legacy_turns_cannot_forge_canonical_source_or_use_gold_topic(session):
    data = await seed(session)
    failed = await run(session, data, data.processing)
    assert failed.status is AnalysisRunStatus.FAILED
    assert failed.error_code == "missing-canonical-evidence"
    assert failed.audit_id is None


async def test_changed_database_turns_fail_instead_of_using_stale_canonical_evidence(
    session, imported
):
    data, conversation, _ = imported
    conversation.turns[0].text = "changed after preparation"
    await session.commit()
    failed = await run(session, data, conversation)
    assert failed.error_code == "invalid-canonical-evidence"
    assert (
        await session.scalar(
            select(Finding).join(Audit).where(Audit.conversation_id == conversation.id)
        )
        is None
    )


def test_manager_correction_requires_a_separate_explicit_result():
    decision = {
        "outcome": "corrected",
        "reason": "Separate evidence",
        "feedback": "Reviewed",
    }
    with pytest.raises(ValueError, match="reviewedResult"):
        DecisionInput(**decision)
    assert (
        DecisionInput(**decision, reviewed_result="meets-criteria").reviewed_result
        == "meets-criteria"
    )
    with pytest.raises(ValueError):
        DecisionInput(
            **{**decision, "outcome": "dismissed"}, reviewed_result="meets-criteria"
        )


async def test_partial_results_survive_and_retry_preserves_failure_history(
    session, imported, monkeypatch
):
    from ml import rule_assessment

    data, conversation, _ = imported
    original = rule_assessment._style

    def failed_category(*args):
        raise ValueError("Simulated category failure")

    monkeypatch.setattr(rule_assessment, "_style", failed_category)
    failed = await run(session, data, conversation)
    assert failed.status is AnalysisRunStatus.FAILED and failed.audit_id is None
    assert failed.assessment_report["processing_status"] == "partial"
    history = deepcopy(failed.assessment_report)
    providers = create_database_providers(sessions_for(session))
    call = await providers.calls.get_for_agent(NORTHWIND, ALEX, str(conversation.id))
    assert len(call.criteria) == 4 and call.decision is None
    style = next(row for row in call.criteria if row.id == "communication-style")
    assert style.scoring.score is None and style.scoring.processing_error
    assert all(
        row.scoring.processing_error is None
        for row in call.criteria
        if row.id != style.id
    )
    monkeypatch.setattr(rule_assessment, "_style", original)
    service = rules(session)
    next_run = await service.start(
        NORTHWIND, str(conversation.id), requested_by=MAYA, retry=True
    )
    completed = await service.execute(next_run.run.id)
    assert completed.status is AnalysisRunStatus.SUCCEEDED
    assert completed.attempt == 2 and failed.assessment_report == history
