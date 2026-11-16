"""The presentation/storage contract works without a scoring implementation."""

from copy import deepcopy

import httpx
import pytest
from ml.test_evidence import prepared
from sqlalchemy import select, update

from backend.core.config import Settings
from backend.main import create_app
from backend.models import (
    AnalysisRunStatus,
    Audit,
    EvaluationCriterion,
    EvaluationFormVersion,
    FindingCategory,
)
from backend.providers.database import create_database_providers
from backend.services.analysis import AnalysisService, parse_report
from backend.services.assessment_storage import import_prepared
from tests.database_seed import ALEX, HARBOR, MAYA, NORTHWIND, SAM, seed, sessions_for
from tests.test_analysis import NOW, category, conversation_citation, reference_citation


async def scoring_data(session):
    data = await seed(session)
    # Used evaluation versions are immutable. Configure a fresh test-only version.
    await session.execute(update(EvaluationFormVersion).values(is_active=False))
    await session.flush()
    version = EvaluationFormVersion(
        form_id=data.form_version.form_id, version_number=2, is_active=True
    )
    session.add(version)
    await session.flush()
    data.form_version = version
    for position, category_id in enumerate(
        (
            FindingCategory.PROCEDURE,
            FindingCategory.ANSWER_SUPPORT,
            FindingCategory.COMPLETENESS,
            FindingCategory.COMMUNICATION,
        ),
        1,
    ):
        session.add(
            EvaluationCriterion(
                form_version_id=data.form_version.id,
                position=position,
                category=category_id,
                name=category_id.value,
                weight=0.25,
                pass_threshold=0.7,
                enabled=True,
            )
        )
    await session.commit()
    return data


def scored_output(request):
    """Authored fixture with an explicit test-only policy and independent reference."""
    refs = [reference_citation(request.references[0])]
    passages = [
        conversation_citation(request, e["turn_id"])
        for e in request.conversation["events"]
        if e["speaker"] in ("customer", "agent")
    ]
    rows = []
    for name in ("procedure", "answer-support", "completeness", "communication-style"):
        rows.append(
            {
                **category(name, "meets-criteria"),
                "scoring": {
                    "score": 100,
                    "coverage": 100,
                    "earned": 25,
                    "assessable": 25,
                    "possible": 25,
                    "checks": [
                        {
                            "id": name,
                            "rule_id": "test-only-approved-plan",
                            "requirement": "Authored criterion",
                            "outcome": "supported",
                            "earned": 25,
                            "maximum": 25,
                            "explanation": "Synthetic supported judgment",
                            "advice": "",
                            "citations": passages + refs,
                            "critical": False,
                        }
                    ],
                    "limitations": [],
                    "processing_error": None,
                    "interpretation_limits": [],
                    "inventory_complete": True,
                },
            }
        )
    configured = {
        c["category"]: float(c["weight"]) for c in request.criteria if c["enabled"]
    }
    weights = {
        key: value * 100 / sum(configured.values()) for key, value in configured.items()
    }
    return {
        "schema_version": "assessment-v1",
        "processing_status": "completed",
        "conversation_id": request.conversation["id"],
        "transcript_version": request.conversation["transcript_version"],
        "evaluation_form_version": request.evaluation_form_version,
        "as_of": request.as_of,
        "versions": {"rules": "test-adapter"},
        "categories": rows,
        "overall": {
            "score": 100,
            "coverage": 100,
            "profile_id": "test-form",
            "profile_version": str(request.evaluation_form_version),
            "reason": None,
            "weights": weights,
        },
        "human_review": None,
        "approval": None,
        "requests": [],
    }


def fixture_policy_parser(request, report):
    # Only the test fixture's frozen plan is eligible here. Real scorers must
    # provide their own approved-policy parser; tests approve no real catalogue.
    assert all(
        c["rule_id"] == "test-only-approved-plan" and c["maximum"] == 25
        for r in report["categories"]
        for c in r["scoring"]["checks"]
    )
    legacy = {
        **report,
        "schema_version": 1,
        "processing_status": "complete",
        "categories": [
            {k: v for k, v in r.items() if k != "scoring"} for r in report["categories"]
        ],
        "versions": {"report": "test-adapter"},
    }
    failed = [r["category"] for r in legacy["categories"] if r["status"] == "failed"]
    legacy["categories"] = [
        category(
            r["category"], "cannot-assess", limitations=["Test processing failure"]
        )
        if r["status"] == "failed"
        else r
        for r in legacy["categories"]
    ]
    parsed = parse_report(request, {k: v for k, v in legacy.items() if k != "overall"})
    for name in failed:
        parsed.categories.pop(name)
    parsed.assessment_report = deepcopy(report)
    return parsed


class FakeScorer:
    def __init__(self, version="test-adapter", mutate=lambda _: None):
        self.version, self.mutate = version, mutate

    def analyse(self, request):
        result = scored_output(request)
        result["versions"]["rules"] = self.version
        self.mutate(result)
        return result


async def run(session, data, adapter, parser=fixture_policy_parser, retry=False):
    service = AnalysisService(
        sessions_for(session), adapter=adapter, now=lambda: NOW, report_parser=parser
    )
    started = await service.start(
        NORTHWIND, data.id(data.processing), requested_by=MAYA, retry=retry
    )
    return await service.execute(started.run.id)


@pytest.mark.parametrize("engine", ["authored-rules-fixture", "authored-model-fixture"])
async def test_different_scorers_share_one_api_without_approving_anything(
    session, engine
):
    data = await scoring_data(session)
    result = await run(session, data, FakeScorer(engine))
    assert result.status is AnalysisRunStatus.SUCCEEDED, result.error_message
    audit = await session.get(Audit, result.audit_id)
    assert audit.assessment_report["approval"] is None
    assert audit.assessment_report["human_review"] is None
    providers = create_database_providers(sessions_for(session))
    call = await providers.calls.get_for_agent(
        NORTHWIND, ALEX, data.id(data.processing)
    )
    assert call.overall_scoring.score == 100
    assert all(c.scoring.score == 100 for c in call.criteria)
    assert call.assessment_version.rules == engine
    assert call.decision is None and call.review_request is None
    assert call.references[0].id == data.id(data.approved_entry)
    assert all(c.evidence_turn_numbers for c in call.criteria)
    app = create_app(providers=providers, settings=Settings(app_env="test"))
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app), base_url="http://test"
    ) as client:
        response = await client.get(
            f"/api/agent/conversations/{data.id(data.processing)}",
            headers={"X-Dev-User": ALEX},
        )
        assert response.status_code == 200
        body = response.json()
        assert body["overallScoring"]["score"] == 100
        assert all(c["scoring"]["score"] == 100 for c in body["criteria"])
        assert body["assessmentVersion"]["rules"] == engine
        assert (
            await client.get(
                f"/api/agent/conversations/{data.id(data.processing)}",
                headers={"X-Dev-User": SAM},
            )
        ).status_code == 404

    assert (
        await providers.calls.get_for_agent(NORTHWIND, SAM, data.id(data.processing))
        is None
    )
    assert (
        await providers.calls.get_for_agent(HARBOR, ALEX, data.id(data.processing))
        is None
    )
    manager = await providers.reviews.get_for_manager(
        NORTHWIND, MAYA, data.id(data.processing)
    )
    assert manager.call.criteria == call.criteria


@pytest.mark.parametrize(
    "defect",
    [
        "score",
        "quote",
        "uncited-pass",
        "unapproved-reference",
        "source-version",
        "approval",
        "weights",
        "coverage",
        "unknown-points",
    ],
)
async def test_storage_rejects_invalid_or_unsupported_numbers_even_after_policy_parser(
    session, defect
):
    data = await scoring_data(session)

    def mutate(r):
        scoring = r["categories"][0]["scoring"]
        check = scoring["checks"][0]
        if defect == "score":
            scoring["score"] = 71
        elif defect == "quote":
            check["citations"][0]["quote"] = "Fabricated text"
        elif defect == "uncited-pass":
            check["citations"] = []
        elif defect == "unapproved-reference":
            check["citations"][-1]["reference_id"] = "not-supplied"
        elif defect == "source-version":
            r["transcript_version"] = "stale"
        elif defect == "approval":
            r["approval"] = {"status": "approved"}
        elif defect == "coverage":
            r["overall"].update(score=None, coverage=0)
        elif defect == "weights":
            r["overall"]["weights"]["procedure"] = 99
        else:
            check["outcome"] = "unresolved"

    result = await run(session, data, FakeScorer(mutate=mutate))
    assert result.status is AnalysisRunStatus.FAILED
    assert result.audit_id is None and result.assessment_report is None
    assert (
        await session.scalar(
            select(Audit).where(Audit.conversation_id == data.processing.id)
        )
        is None
    )


async def test_default_parser_rejects_scored_payload_without_configured_policy_validator(
    session,
):
    data = await scoring_data(session)
    result = await run(session, data, FakeScorer(), parser=parse_report)
    assert result.error_code == "unconfigured-assessment-validator"
    assert result.audit_id is None


async def test_prepared_import_keeps_exact_evidence_and_ownership(session):
    data = await scoring_data(session)
    evidence = prepared()
    item = await import_prepared(
        session, data.northwind.id, data.alex_agent.id, evidence
    )
    assert item.canonical_evidence == evidence
    assert (
        await import_prepared(session, data.northwind.id, data.alex_agent.id, evidence)
    ).id == item.id
    for organization, agent in [
        (data.harbor.id, data.alex_agent.id),
        (data.northwind.id, data.sam_agent.id),
    ]:
        with pytest.raises(ValueError):
            await import_prepared(session, organization, agent, evidence)
    for change in (
        lambda e: e["conversations"][0].update(split="test"),
        lambda e: e.update(answer_label="do-not-use"),
    ):
        altered = deepcopy(evidence)
        change(altered)
        with pytest.raises(ValueError):
            await import_prepared(
                session, data.northwind.id, data.alex_agent.id, altered
            )


async def test_application_starts_without_importing_any_scoring_engine(monkeypatch):
    import builtins

    real_import = builtins.__import__

    def reject_engine(name, *args, **kwargs):
        if name.startswith(
            ("ml.rule_", "ml.scoring", "ml.metrics", "ollama", "openai", "groq")
        ):
            raise AssertionError("Unexpected scoring dependency: " + name)
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", reject_engine)
    app = create_app(settings=Settings(app_env="development", data_source="fixtures"))
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app), base_url="http://test"
    ) as client:
        assert (await client.get("/health")).status_code == 200
        assert (await client.get("/api/demo/profiles")).status_code == 200


async def test_partial_output_keeps_independent_scores_and_failed_history(session):
    data = await scoring_data(session)

    def partial(report):
        row = report["categories"][-1]
        row.update(status="failed", result=None)
        row["scoring"].update(
            score=None,
            coverage=None,
            earned=0,
            assessable=0,
            possible=None,
            checks=[],
            processing_error="Test failure",
            inventory_complete=False,
        )
        report["processing_status"] = "partial"
        report["overall"].update(score=None, coverage=None, reason="One metric failed")

    result = await run(session, data, FakeScorer(mutate=partial))
    assert result.status is AnalysisRunStatus.FAILED and result.audit_id is None
    history = deepcopy(result.assessment_report)
    providers = create_database_providers(sessions_for(session))
    call = await providers.calls.get_for_agent(
        NORTHWIND, ALEX, data.id(data.processing)
    )
    assert call.overall_scoring.score is None
    assert [c.scoring.score for c in call.criteria] == [100, 100, 100, None]
    assert call.criteria[-1].scoring.processing_error == "Test failure"
    completed = await run(session, data, FakeScorer(), retry=True)
    assert completed.status is AnalysisRunStatus.SUCCEEDED
    assert completed.attempt == 2 and result.assessment_report == history


async def test_unknown_checks_stay_unscored_without_becoming_failures(session):
    data = await scoring_data(session)

    def unknown(report):
        row = report["categories"][0]
        row["result"] = category(
            "procedure", "cannot-assess", limitations=["Required fact unavailable"]
        )["result"]
        row["scoring"].update(score=None, coverage=0, earned=0, assessable=0)
        row["scoring"]["checks"][0].update(
            outcome="unresolved", earned=None, citations=[]
        )
        report["overall"].update(score=None, coverage=None, reason="Missing evidence")

    result = await run(session, data, FakeScorer(mutate=unknown))
    assert result.status is AnalysisRunStatus.SUCCEEDED, result.error_message
    providers = create_database_providers(sessions_for(session))
    call = await providers.calls.get_for_agent(
        NORTHWIND, ALEX, data.id(data.processing)
    )
    assert call.criteria[0].result == "cannot-assess"
    assert call.criteria[0].scoring.score is None and call.overall_scoring.score is None


async def test_numeric_overall_without_configured_evaluation_criteria_is_rejected(
    session,
):
    data = await seed(session)
    result = await run(session, data, FakeScorer())
    assert result.status is AnalysisRunStatus.FAILED
    assert result.audit_id is None
