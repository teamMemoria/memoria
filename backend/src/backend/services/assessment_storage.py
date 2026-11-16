"""Engine-independent evidence import and the final assessment storage gate.

Scoring adapters supply a policy-aware report_parser to AnalysisService. This
module never chooses checks, grants approvals, or loads a scorer or rule catalogue.
"""

from copy import deepcopy

from sqlalchemy import select
from sqlalchemy.orm import selectinload

from backend.models import Agent, Conversation, Speaker, Turn


def validate_prepared(evidence):
    from ml.abcd import validate_evidence

    validate_evidence(evidence)
    if len(evidence["conversations"]) != 1:
        raise ValueError("Import one prepared conversation at a time")
    conversation = evidence["conversations"][0]
    if conversation["split"] != "train":
        raise ValueError("The prepared ABCD import accepts training evidence only")
    return conversation


def validate_payload(request, parsed):
    """Storage invariants after an injected, approval-aware policy parser.

    This never chooses obligations or grants approval. An unconfigured application
    rejects scored output; a scorer must supply its own approved-policy validator.
    """
    import math

    from backend.schemas.call_review import (
        CRITERION_IDS,
        CategoryScoring,
        OverallScoring,
    )
    from backend.services.analysis import RESULTS, _check_citation, _reject

    def require(condition, message):
        if not condition:
            _reject("invalid-assessment", message)

    def number(value, expected):
        return (
            type(value) in (int, float)
            and math.isfinite(value)
            and math.isclose(value, expected, abs_tol=1e-8)
        )

    report = parsed.assessment_report
    require(
        report.get("schema_version") == "assessment-v1",
        "Unsupported assessment contract",
    )
    require(
        report.get("conversation_id") == request.conversation["id"]
        and report.get("transcript_version")
        == request.conversation["transcript_version"],
        "Assessment source version differs",
    )
    require(
        report.get("evaluation_form_version") == request.evaluation_form_version
        and report.get("as_of") == request.as_of,
        "Assessment uses a different evaluation version or date",
    )
    require(
        all(report.get(k) is None for k in ("human_review", "approval")),
        "Analysis cannot create human decisions",
    )
    require(
        isinstance(report.get("versions", {}).get("rules"), str),
        "An assessment engine version is required",
    )
    rows = report["categories"]
    require(
        len(rows) == 4 and {r["category"] for r in rows} == set(CRITERION_IDS),
        "Exactly four assessment categories are required",
    )
    events = {e["turn_id"]: e for e in request.conversation["events"]}
    references = {r["id"]: r for r in request.references}
    scores, covered = {}, {}
    for row in rows:
        name = row["category"]
        data = CategoryScoring.model_validate(row["scoring"])
        require(
            len({c.id for c in data.checks}) == len(data.checks), "Duplicate check IDs"
        )
        earned = resolved = possible = 0.0
        linked_turns, linked_references = set(), set()
        for check in data.checks:
            kinds, cited_turns = set(), []
            for citation in check.citations:
                kind, key = _check_citation(citation, request, events, references)
                kinds.add(kind)
                if kind == "conversation":
                    cited_turns.append(events[key])
                    linked_turns.add(key)
                else:
                    linked_references.add(int(key))
            if check.outcome != "unresolved":
                require(
                    "conversation" in kinds,
                    "Every pass, breach and inapplicability needs evidence",
                )
            if check.outcome in ("supported", "breach"):
                require(
                    "reference" in kinds
                    or name in ("completeness", "communication-style"),
                    "Policy-dependent conclusions require eligible reference evidence",
                )
                if name == "completeness":
                    speakers = {e["speaker"] for e in cited_turns}
                    require(
                        "customer" in speakers and bool(speakers & {"agent", "action"}),
                        "Completeness needs request and response evidence",
                    )
                if name in ("answer-support", "communication-style"):
                    require(
                        any(e["speaker"] == "agent" for e in cited_turns),
                        "The Agent wording must be cited",
                    )
                require(
                    number(
                        check.earned,
                        check.maximum if check.outcome == "supported" else 0,
                    ),
                    "Check points contradict its outcome",
                )
                resolved += check.maximum
                earned += check.earned
            else:
                require(
                    check.earned is None,
                    "Unknown or inapplicable checks earn no points",
                )
            if check.outcome != "not-applicable":
                possible += check.maximum
        require(
            number(data.earned, earned) and number(data.assessable, resolved),
            "Assessment totals differ from its checks",
        )
        require(
            number(data.possible, possible)
            if data.inventory_complete
            else data.possible is None,
            "Applicable points differ from inventory",
        )
        coverage = (
            100 * resolved / possible if possible and data.inventory_complete else None
        )
        require(
            data.coverage is None
            if coverage is None
            else number(data.coverage, coverage),
            "Evidence coverage is inconsistent",
        )
        require(
            data.score is None
            or (
                not data.processing_error
                and data.inventory_complete
                and possible > 0
                and number(resolved, possible)
                and number(data.score, 100 * earned / possible)
            ),
            "Unknown or failed checks cannot produce a final score",
        )
        if data.processing_error:
            require(
                row["status"] == "failed"
                and row["result"] is None
                and name not in parsed.categories
                and data.score is None,
                "Processing failures must stay separate from Agent results",
            )
        else:
            require(
                row["status"] == "completed" and name in parsed.categories,
                "Completed categories need a validated result",
            )
        if not data.processing_error:
            verdict = row["result"]["result"]
            require(
                row["result"]["category"] == name
                and verdict in RESULTS
                and parsed.categories[name].result == RESULTS[verdict],
                "Stored category differs from validated judgment",
            )
            if verdict == "meets-criteria":
                require(
                    bool(data.checks)
                    and any(c.outcome == "supported" for c in data.checks)
                    and all(
                        c.outcome in ("supported", "not-applicable")
                        for c in data.checks
                    ),
                    "A pass needs a nonempty resolved evidence checklist",
                )
            if verdict == "needs-review":
                require(
                    any(c.outcome == "breach" for c in data.checks),
                    "A negative category needs an evidenced breach",
                )
        if not data.processing_error:
            category = parsed.categories[name]
            require(
                row["result"]["category"] == name
                and category.result == RESULTS.get(row["result"]["result"]),
                "Stored category differs from validated judgment",
            )
            if row["result"]["result"] == "meets-criteria":
                require(
                    bool(data.checks)
                    and any(c.outcome == "supported" for c in data.checks)
                    and all(
                        c.outcome in ("supported", "not-applicable")
                        for c in data.checks
                    ),
                    "A pass needs a nonempty resolved evidence checklist",
                )
            if row["result"]["result"] == "needs-review":
                require(
                    any(c.outcome == "breach" for c in data.checks),
                    "A negative category needs an evidenced breach",
                )
            # Bind validated positive evidence too, not just legacy negative findings.
            category.turn_numbers = sorted(set(category.turn_numbers) | linked_turns)
            category.reference_ids = sorted(
                set(category.reference_ids) | linked_references
            )
        scores[name], covered[name] = data.score, coverage
    partial = any(r["scoring"]["processing_error"] for r in rows)
    require(
        report["processing_status"] == ("partial" if partial else "completed"),
        "Processing status differs from category errors",
    )
    overall = OverallScoring.model_validate(report["overall"])
    if (
        overall.weights is not None
        or overall.score is not None
        or overall.coverage is not None
    ):
        configured = {
            c["category"]: float(c["weight"]) for c in request.criteria if c["enabled"]
        }
        total = sum(configured.values())
        expected = (
            {key: weight * 100 / total for key, weight in configured.items()}
            if total
            else {}
        )
        require(
            set(expected) == set(CRITERION_IDS),
            "Every metric needs a configured weight",
        )
        require(
            overall.weights == expected and number(sum(expected.values()), 100),
            "Overall weights differ from active evaluation form",
        )
        if overall.score is not None:
            require(
                all(v is not None for v in scores.values()),
                "Every metric is required for an overall score",
            )
            require(
                number(
                    overall.score, sum(scores[k] * w / 100 for k, w in expected.items())
                ),
                "Overall calculation differs from category scores",
            )
        if overall.coverage is not None or overall.score is not None:
            require(
                all(v is not None for v in covered.values())
                and number(
                    overall.coverage,
                    sum(covered[k] * w / 100 for k, w in expected.items()),
                ),
                "Overall coverage is inconsistent",
            )
    for link in report.get("requests", []):
        require(
            link["turn_id"] in events
            and events[link["turn_id"]]["speaker"] == "customer",
            "Request source must be customer evidence",
        )
        require(
            link["state"]
            in ("active", "answered", "refused", "promised", "changed", "withdrawn"),
            "Unknown request state",
        )
        turns = [
            *link.get("context_turn_ids", []),
            *(t for h in link["history"] for t in h["turn_ids"]),
        ]
        require(set(turns) <= events.keys(), "Request context cites unavailable turns")
        require(
            link["state"] not in ("changed", "withdrawn")
            or bool(link.get("context_turn_ids"))
            or len(link["history"]) > 1,
            "Request changes require contextual evidence",
        )


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
