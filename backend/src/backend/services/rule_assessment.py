"""Local rule composition and the boundary between prepared evidence and storage."""

import json
from copy import deepcopy
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import selectinload

from backend.models import Agent, Conversation, Speaker, Turn
from backend.services.analysis import (
    RESULTS,
    AnalysisRequest,
    CategoryResult,
    ParsedReport,
    ReportRejectedError,
)


def validate_prepared(evidence):
    from ml.abcd import validate_evidence

    validate_evidence(evidence)
    if len(evidence["conversations"]) != 1:
        raise ValueError("Import one prepared conversation at a time")
    conversation = evidence["conversations"][0]
    if conversation["split"] != "train":
        raise ValueError("The scoring pilot accepts training evidence only")
    return conversation


async def import_prepared(session, organization_id, agent_id, evidence):
    """Import versioned training evidence; ownership is supplied, never inferred."""
    source = validate_prepared(evidence)
    agent = await session.get(Agent, agent_id)
    if agent is None or agent.organization_id != organization_id:
        raise ValueError("The agent must belong to the importing organization")
    existing = await session.scalar(
        select(Conversation)
        .where(
            Conversation.organization_id == organization_id,
            Conversation.source_dataset == "ABCD",
            Conversation.original_id == source["id"],
        )
        .options(selectinload(Conversation.turns))
    )
    if existing is not None:
        if existing.agent_id != agent_id or existing.canonical_evidence != evidence:
            raise ValueError(
                "An existing conversation has different evidence or ownership"
            )
        return existing
    speaker = {
        "agent": Speaker.AGENT,
        "customer": Speaker.CUSTOMER,
        "action": Speaker.SYSTEM_ACTION,
    }
    conversation = Conversation(
        organization_id=organization_id,
        agent_id=agent_id,
        source_dataset="ABCD",
        original_id=source["id"],
        channel="text",
        canonical_evidence=deepcopy(evidence),
        source_fields={},
        turns=[
            Turn(
                line_number=e["turn_id"], speaker=speaker[e["speaker"]], text=e["text"]
            )
            for e in source["events"]
        ],
    )
    session.add(conversation)
    await session.flush()
    return conversation


class LocalRuleAdapter:
    def analyse(self, request: AnalysisRequest):
        from ml.rule_assessment import assess_conversation

        if request.canonical_evidence is None or request.scoring_context is None:
            raise ValueError(
                "Rule analysis requires prepared evidence and versioned policies"
            )
        validate_prepared(request.canonical_evidence)
        context = request.scoring_context
        return assess_conversation(
            request.canonical_evidence,
            context["references"],
            context["rubric"],
            context["tables"],
            as_of=request.as_of,
        )


def load_rule_context():
    """Composition reads local policy files; evaluation never reads files."""
    directory = Path(__file__).resolve().parents[4] / "ml"
    references = json.loads((directory / "references.json").read_text())
    return {
        "references": references["references"],
        "rubric": json.loads((directory / "rubric.json").read_text()),
        "tables": json.loads((directory / "rule_tables.json").read_text()),
    }


def parse_rule_report(request, report):
    from ml.scoring import eligible_sources, validate_scored_report

    if request.canonical_evidence is None or request.scoring_context is None:
        raise ReportRejectedError(
            "missing-canonical-evidence", "No prepared evidence is available"
        )
    source = validate_prepared(request.canonical_evidence)
    if source != request.conversation:
        raise ReportRejectedError(
            "evidence-mismatch", "Prepared evidence differs from the request"
        )
    context = request.scoring_context
    eligible = eligible_sources(
        context["references"],
        context["rubric"],
        context["tables"],
        as_of=request.as_of,
        workflows=report["workflows"],
    )
    validate_scored_report(
        report,
        request.canonical_evidence,
        eligible,
        context["tables"],
        as_of=request.as_of,
    )
    categories = {}
    for row in report["categories"]:
        result = row["result"]
        if result is None:
            continue
        evidence = {
            citation["turn_id"]
            for check in row["scoring"]["checks"]
            for citation in check["citations"]
            if citation["kind"] == "conversation"
        }
        categories[row["category"]] = CategoryResult(
            result=RESULTS[result["result"]],
            feedback=result["explanation"],
            suggestion=" ".join(f["advice"] for f in result["findings"]) or None,
            turn_numbers=sorted(evidence),
            reference_ids=[],
        )
    return ParsedReport(
        categories=categories,
        summary=None,
        report_version=report["schema_version"],
        assessment_report=deepcopy(report),
    )
