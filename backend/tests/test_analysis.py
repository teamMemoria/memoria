import copy
import hashlib
import json
from datetime import UTC, datetime

import httpx
import pytest
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from backend.core.config import Settings
from backend.main import create_app
from backend.models import (
    AnalysisRun,
    AnalysisRunStatus,
    Audit,
    EvaluationFormVersion,
)
from backend.providers.database import create_database_providers
from backend.services.analysis import (
    AlreadyAnalysedError,
    AnalysisRequest,
    AnalysisService,
    RetryRequiredError,
    parse_report,
)
from tests.database_seed import ALEX, MAYA, NORTHWIND, seed, sessions_for

NOW = datetime(2026, 11, 2, 9, 0, tzinfo=UTC)
CATEGORIES = ("procedure", "answer-support", "completeness", "communication-style")


def conversation_citation(request, turn_id):
    event = next(e for e in request.conversation["events"] if e["turn_id"] == turn_id)
    return {
        "kind": "conversation",
        "conversation_id": request.conversation["id"],
        "transcript_version": request.conversation["transcript_version"],
        "turn_id": turn_id,
        "event_kind": event["kind"],
        "quote": event["text"],
    }


def reference_citation(reference):
    return {
        "kind": "reference",
        "reference_id": reference["id"],
        "reference_version": reference["version"],
        "section_id": reference["section_id"],
        "quote": reference["text"].split("\n")[0],
    }


def category(name, result, findings=(), limitations=()):
    return {
        "category": name,
        "status": "completed",
        "error": None,
        "result": {
            "category": name,
            "result": result,
            "explanation": f"{name} explanation.",
            "findings": list(findings),
            "limitations": list(limitations),
            "details": {},
        },
    }


def complete_report(request):
    """A report in the shape run_feedback_report returns, built from the request."""
    [reference] = request.references
    return {
        "schema_version": 1,
        "processing_status": "complete",
        "conversation_id": request.conversation["id"],
        "transcript_version": request.conversation["transcript_version"],
        "categories": [
            category(
                "procedure",
                "needs-review",
                findings=[
                    {
                        "id": "finding-1",
                        "rule_id": "refund-before-check",
                        "explanation": "The refund was offered before the order was checked.",
                        "advice": "Check the order before offering a refund.",
                        "citations": [
                            conversation_citation(request, 2),
                            conversation_citation(request, 5),
                            reference_citation(reference),
                        ],
                    }
                ],
            ),
            category("answer-support", "meets-criteria"),
            category(
                "completeness",
                "cannot-assess",
                limitations=["The call ends before the customer replies."],
            ),
            category("communication-style", "meets-criteria"),
        ],
        "summary": {
            "claims": [{"kind": "request", "text": "Refund for a torn jacket."}],
            "limitations": [],
        },
        "versions": {"report": "local-feedback-v1"},
        "errors": [],
    }


class ScriptedAdapter:
    """Deterministic analysis: records each request and returns a scripted report."""

    def __init__(self, build=complete_report, error=None):
        self.build = build
        self.error = error
        self.requests = []

    def analyse(self, request):
        self.requests.append(request)
        if self.error is not None:
            raise self.error
        return self.build(request)


@pytest.fixture
async def data(session):
    return await seed(session)


def service_for(session, adapter):
    return AnalysisService(sessions_for(session), adapter, now=lambda: NOW)


async def run_once(session, data, adapter, *, retry=False):
    service = service_for(session, adapter)
    started = await service.start(
        NORTHWIND, data.id(data.processing), requested_by=MAYA, retry=retry
    )
    run = await service.execute(started.run.id)
    session.expunge_all()
    return run


async def agent_call(session, data):
    providers = create_database_providers(sessions_for(session))
    return await providers.calls.get_for_agent(
        NORTHWIND, ALEX, data.id(data.processing)
    )


# --- successful runs -------------------------------------------------------------------


async def test_a_successful_run_saves_an_audit_the_agent_can_read(session, data):
    run = await run_once(session, data, ScriptedAdapter())
    assert run.status is AnalysisRunStatus.SUCCEEDED
    assert run.report_version == "local-feedback-v1"

    call = await agent_call(session, data)
    assert call.status == "ready"
    assert call.summary == "Refund for a torn jacket."
    results = {criterion.id: criterion.result for criterion in call.criteria}
    assert results == {
        "procedure": "needs-review",
        "answer-support": "meets-criteria",
        "completeness": "cannot-assess",
        "communication-style": "meets-criteria",
    }
    [finding] = call.findings
    assert finding.suggestion == "Check the order before offering a refund."
    # Turn 5 is a system action: saved as evidence, not shown in the transcript.
    assert finding.evidence_turn_numbers == [2]
    assert finding.reference_id == data.id(data.approved_entry)
    completeness = next(c for c in call.criteria if c.id == "completeness")
    assert "The call ends before the customer replies." in completeness.explanation


async def test_the_adapter_gets_versioned_evidence_references_and_criteria(
    session, data
):
    adapter = ScriptedAdapter()
    await run_once(session, data, adapter)
    [request] = adapter.requests

    events = request.conversation["events"]
    assert [event["turn_id"] for event in events] == [1, 2, 4, 5, 7]
    assert [event["kind"] for event in events] == [
        "message",
        "message",
        "message",
        "action",
        "message",
    ]
    expected_version = (
        "sha256:"
        + hashlib.sha256(
            json.dumps(
                {"id": request.conversation["id"], "events": events},
                sort_keys=True,
                ensure_ascii=False,
                separators=(",", ":"),
            ).encode()
        ).hexdigest()
    )
    assert request.conversation["transcript_version"] == expected_version
    # Only approved guidance for the conversation's topic, with its version.
    assert [reference["id"] for reference in request.references] == [
        data.id(data.approved_entry)
    ]
    assert request.references[0]["version"] == (
        f"review-{data.approved_entry.approved_review_id}"
    )
    assert request.evaluation_form_version == data.form_version.id
    assert (request.as_of, request.scope) == ("2026-11-02", NORTHWIND)

    run = await session.scalar(select(AnalysisRun))
    assert run.transcript_version == expected_version


# --- duplicates, failures and retries -------------------------------------------------


async def test_a_second_start_returns_the_active_run(session, data):
    service = service_for(session, ScriptedAdapter())
    first = await service.start(NORTHWIND, data.id(data.processing), requested_by=MAYA)
    second = await service.start(NORTHWIND, data.id(data.processing), requested_by=MAYA)
    assert first.created and not second.created
    assert second.run.id == first.run.id
    assert await session.scalar(select(func.count()).select_from(AnalysisRun)) == 1


async def test_the_database_allows_one_active_run_per_conversation(session, data):
    for attempt in (1, 2):
        session.add(
            AnalysisRun(
                organization_id=data.northwind.id,
                conversation_id=data.processing.id,
                status=AnalysisRunStatus.QUEUED,
                attempt=attempt,
            )
        )
    with pytest.raises(IntegrityError):
        await session.flush()


async def test_a_technical_failure_is_not_a_cannot_assess_result(session, data):
    run = await run_once(session, data, ScriptedAdapter(error=RuntimeError("boom")))
    assert run.status is AnalysisRunStatus.FAILED
    assert run.error_code == "analysis-error"
    assert await session.scalar(select(func.count()).select_from(Audit)) == 4

    call = await agent_call(session, data)
    assert call.status == "processing"
    assert call.criteria == []


async def test_an_unconfigured_adapter_fails_the_run_visibly(session, data):
    service = AnalysisService(sessions_for(session), now=lambda: NOW)
    started = await service.start(
        NORTHWIND, data.id(data.processing), requested_by=MAYA
    )
    run = await service.execute(started.run.id)
    assert (run.status, run.error_code) == (
        AnalysisRunStatus.FAILED,
        "analysis-unavailable",
    )


def partial(request):
    report = complete_report(request)
    report["processing_status"] = "partial"
    report["errors"] = [{"code": "check-failed", "category": None, "message": "x"}]
    return report


def cites_unknown_turn(request):
    report = complete_report(request)
    citation = report["categories"][0]["result"]["findings"][0]["citations"][0]
    citation["turn_id"] = 99
    return report


def cites_old_reference_version(request):
    report = complete_report(request)
    citation = report["categories"][0]["result"]["findings"][0]["citations"][2]
    citation["reference_version"] = "review-0"
    return report


def finding_without_turns(request):
    report = complete_report(request)
    finding = report["categories"][0]["result"]["findings"][0]
    finding["citations"] = finding["citations"][2:]
    return report


def other_transcript(request):
    report = complete_report(request)
    report["transcript_version"] = "sha256:other"
    return report


def missing_category(request):
    report = complete_report(request)
    report["categories"].pop()
    return report


def misquoted(request):
    report = complete_report(request)
    citation = report["categories"][0]["result"]["findings"][0]["citations"][0]
    citation["quote"] = "words the agent never said"
    return report


@pytest.mark.parametrize(
    ("build", "code"),
    [
        (partial, "report-check-failed"),
        (cites_unknown_turn, "invalid-citation"),
        (cites_old_reference_version, "invalid-citation"),
        (finding_without_turns, "missing-evidence"),
        (other_transcript, "evidence-mismatch"),
        (missing_category, "invalid-report"),
        (misquoted, "invalid-citation"),
    ],
)
async def test_reports_that_fail_validation_save_nothing(session, data, build, code):
    run = await run_once(session, data, ScriptedAdapter(build))
    assert (run.status, run.error_code) == (AnalysisRunStatus.FAILED, code)
    assert (await agent_call(session, data)).status == "processing"


async def test_no_active_evaluation_form_fails_the_run(session, data):
    version = await session.get(EvaluationFormVersion, data.form_version.id)
    version.is_active = False
    await session.commit()
    run = await run_once(session, data, ScriptedAdapter())
    assert run.error_code == "no-evaluation-form"


async def test_a_failed_run_is_only_retried_explicitly(session, data):
    await run_once(session, data, ScriptedAdapter(error=RuntimeError("boom")))
    service = service_for(session, ScriptedAdapter())
    with pytest.raises(RetryRequiredError):
        await service.start(NORTHWIND, data.id(data.processing), requested_by=MAYA)

    run = await run_once(session, data, ScriptedAdapter(), retry=True)
    assert (run.status, run.attempt) == (AnalysisRunStatus.SUCCEEDED, 2)
    runs = (await session.scalars(select(AnalysisRun).order_by("attempt"))).all()
    # The failed attempt is kept, not overwritten.
    assert [r.status for r in runs] == [
        AnalysisRunStatus.FAILED,
        AnalysisRunStatus.SUCCEEDED,
    ]


async def test_an_analysed_conversation_is_never_analysed_again(session, data):
    await run_once(session, data, ScriptedAdapter())
    audit = await session.scalar(
        select(Audit).where(Audit.conversation_id == data.processing.id)
    )
    service = service_for(session, ScriptedAdapter())
    for retry in (False, True):
        with pytest.raises(AlreadyAnalysedError):
            await service.start(
                NORTHWIND, data.id(data.processing), requested_by=MAYA, retry=retry
            )
    assert (
        await session.scalar(
            select(Audit.id).where(Audit.conversation_id == data.processing.id)
        )
        == audit.id
    )


async def test_conversations_with_existing_audits_cannot_be_started(session, data):
    service = service_for(session, ScriptedAdapter())
    with pytest.raises(AlreadyAnalysedError):
        await service.start(NORTHWIND, data.id(data.assessed), requested_by=MAYA)


def test_parse_report_does_not_change_the_report():
    request = AnalysisRequest(
        conversation={
            "id": "1",
            "transcript_version": "v",
            "events": [
                {"turn_id": 2, "kind": "message", "text": "Hello there."},
                {"turn_id": 5, "kind": "action", "text": "lookup"},
            ],
        },
        references=[
            {"id": "9", "section_id": "9", "version": "review-1", "text": "Rule."}
        ],
        criteria=[],
        evaluation_form_version=1,
        as_of="2026-11-02",
        scope=NORTHWIND,
    )

    report = complete_report(request)
    before = copy.deepcopy(report)
    parse_report(request, report)
    assert report == before


# --- over HTTP --------------------------------------------------------------------------


def client_for(session, adapter):
    app = create_app(
        providers=create_database_providers(sessions_for(session)),
        settings=Settings(app_env="test"),
        analysis=service_for(session, adapter),
    )
    return httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    )


async def test_start_and_status_over_http(session, data):
    path = f"/api/manager/conversations/{data.id(data.processing)}/analysis"
    manager = {"X-Dev-User": MAYA}
    async with client_for(session, ScriptedAdapter()) as client:
        before = await client.get(path, headers=manager)
        assert before.json() == {
            "conversationId": data.id(data.processing),
            "status": "not-started",
            "runs": [],
        }
        started = await client.post(path, headers=manager)
        assert started.status_code == 202
        assert started.json()["status"] == "queued"

        # The run executes as a background task after the response.
        session.expunge_all()
        after = await client.get(path, headers=manager)
        assert after.json()["status"] == "succeeded"
        assert after.json()["runs"][0]["requestedBy"] == MAYA

        again = await client.post(path, headers=manager)
        assert again.status_code == 409

        agent = await client.get(
            f"/api/agent/conversations/{data.id(data.processing)}",
            headers={"X-Dev-User": ALEX},
        )
        assert agent.json()["status"] == "ready"


async def test_retry_must_be_explicit_over_http(session, data):
    path = f"/api/manager/conversations/{data.id(data.processing)}/analysis"
    manager = {"X-Dev-User": MAYA}
    async with client_for(session, ScriptedAdapter(error=RuntimeError())) as client:
        await client.post(path, headers=manager)
        session.expunge_all()
        status = await client.get(path, headers=manager)
        assert status.json()["status"] == "failed"
        assert status.json()["runs"][0]["errorCode"] == "analysis-error"
        assert (await client.post(path, headers=manager)).status_code == 409
        retried = await client.post(path, headers=manager, json={"retry": True})
        assert retried.status_code == 202


async def test_analysis_needs_feedback_review_in_the_same_organization(session, data):
    async with client_for(session, ScriptedAdapter()) as client:
        agent = await client.post(
            f"/api/manager/conversations/{data.id(data.processing)}/analysis",
            headers={"X-Dev-User": ALEX},
        )
        assert agent.status_code == 403
        other_org = await client.post(
            f"/api/manager/conversations/{data.id(data.harbor_call)}/analysis",
            headers={"X-Dev-User": MAYA},
        )
        assert other_org.status_code == 404
