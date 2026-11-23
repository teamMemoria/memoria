"""Evidence, point totals and report integrity checks before persistence."""

from math import isclose, isfinite

from backend.entities.assessments import (
    CRITERION_IDS,
    RESULTS,
    _check_citation,
    _reject,
)
from backend.entities.fulfilment import OUTCOME, VALUE, recorded_outcomes
from backend.entities.refund_amount import (
    REFUND_AMOUNT_CHECK,
    subscription_refund_claims,
)
from backend.entities.score_policy import overall_for_form, overall_for_profile


def require(condition, message):
    if not condition:
        _reject("invalid-assessment", message)


def number(value, expected):
    if expected is None:
        return value is None
    return (
        type(value) in (int, float)
        and isfinite(value)
        and isclose(value, expected, abs_tol=1e-8)
    )


def _validate_overall(request, overall, scores, coverage, *, enforce_policy, profile):
    expected = (
        overall_for_profile(profile, scores, coverage)
        if profile is not None
        else overall_for_form(
            request.criteria, request.evaluation_form_version, scores, coverage
        )
    )
    if enforce_policy:
        require(
            overall.profile_id == expected["profile_id"]
            and overall.profile_version == expected["profile_version"],
            "Overall uses a different weight profile",
        )
    elif overall.weights is None and overall.score is None and overall.coverage is None:
        return

    require(
        overall.weights == expected["weights"],
        "Overall weights differ from the configured weights",
    )
    if not enforce_policy:
        require(bool(expected["weights"]), "Every metric needs a configured weight")
    if enforce_policy or overall.score is not None:
        require(
            number(overall.score, expected["score"]),
            "Overall calculation differs from category scores",
        )
    if enforce_policy or overall.coverage is not None or overall.score is not None:
        require(
            number(overall.coverage, expected["coverage"]),
            "Overall coverage is inconsistent",
        )


def _recorded_refund_amount(check, name, events, cited_turns):
    if (
        name != "answer-support"
        or check.rule_id != REFUND_AMOUNT_CHECK
        or check.outcome != "supported"
    ):
        return False
    claims = subscription_refund_claims(list(events.values()))
    if claims is None:
        return False
    _, quote, record = claims
    cited_ids = {turn["turn_id"] for turn in cited_turns}
    return record is not None and {quote["turn_id"], record["turn_id"]} <= cited_ids


def _verified_fulfilment(check, name, profile, events, cited_turns):
    if (
        name != "answer-support"
        or profile is None
        or check.rule_id not in {OUTCOME, VALUE}
    ):
        return False
    cited_ids = {turn["turn_id"] for turn in cited_turns}
    for request in cited_turns:
        proof = recorded_outcomes(list(events.values()), profile.id, request).get(
            check.rule_id
        )
        if (
            proof
            and proof.outcome == check.outcome
            and {turn["turn_id"] for turn in proof.turns} <= cited_ids
        ):
            return True
    return False


def validate_scoring(request, parsed, categories, overall, *, policy=None):
    """Storage invariants after an injected, approval-aware policy parser.

    This never chooses obligations or grants approval. An unconfigured application
    rejects scored output; a scorer must supply its own approved-policy validator.
    """
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
    require(
        report["versions"].get("scoring") == (policy.version if policy else None),
        "The score calculation differs from the configured policy",
    )
    if parsed.weight_profile is not None:
        require(
            policy is not None
            and report["versions"].get("weight_profile")
            == parsed.weight_profile.version,
            "The weighting version differs from the configured profile",
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
        data = categories[name]
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
                if check.rule_id == REFUND_AMOUNT_CHECK:
                    require(
                        parsed.weight_profile is not None
                        and _recorded_refund_amount(check, name, events, cited_turns),
                        "The quoted refund amount needs its matching recorded action",
                    )
                else:
                    require(
                        "reference" in kinds
                        or name in ("completeness", "communication-style")
                        or _verified_fulfilment(
                            check, name, parsed.weight_profile, events, cited_turns
                        ),
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
            number(data.possible, possible if data.inventory_complete else None),
            "Applicable points differ from inventory",
        )
        coverage = (
            100 * resolved / possible if possible and data.inventory_complete else None
        )
        require(
            number(data.coverage, coverage),
            "Evidence coverage is inconsistent",
        )
        if policy is not None:
            expected_score = (
                policy.calculate(earned, resolved, possible)
                if data.inventory_complete and not data.processing_error
                else None
            )
            require(
                number(data.score, expected_score),
                "Score differs from the configured calculation",
            )
        elif data.score is not None:
            require(
                not data.processing_error
                and data.inventory_complete
                and possible > 0
                and number(resolved, possible)
                and number(data.score, 100 * earned / possible),
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
            category = parsed.categories[name]
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
    _validate_overall(
        request,
        overall,
        scores,
        covered,
        enforce_policy=policy is not None,
        profile=parsed.weight_profile if policy is not None else None,
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
