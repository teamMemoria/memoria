"""Pure point arithmetic and approval/citation boundaries for rule assessments."""

import json
from copy import deepcopy
from hashlib import sha256

from .abcd import validate_evidence
from .audit import CATEGORIES, category_result, eligible_criteria
from .citations import validate_citations
from .references import eligible_references, reference_version, review_issues

VERSION = "rule-scoring-v1"
SCOPE = "rule-assessment-scoring"
OUTCOMES = {"supported", "breach", "unresolved", "not-applicable"}
REVIEW_FIELDS = {
    "status",
    "approved_by",
    "approved_version",
    "approved_at",
    "verified_at",
    "review_due",
    "version",
}


def content_version(value):
    encoded = json.dumps(
        value,
        sort_keys=True,
        ensure_ascii=False,
        separators=(",", ":"),
        allow_nan=False,
    ).encode()
    return "sha256:" + sha256(encoded).hexdigest()


def policy_version(tables):
    from .rule_assessment import RULE_VERSION
    from .rule_links import VERSION as LINK_VERSION

    content = {
        key: value
        for key, value in tables.items()
        if key not in {"review_package", "version"}
    }
    return content_version(
        {
            "tables": content,
            "scoring": VERSION,
            "metrics": RULE_VERSION,
            "links": LINK_VERSION,
        }
    )


def policy_issues(tables, *, as_of):
    version = policy_version(tables)
    review = tables.get("review_package", {})
    issues = review_issues(review, as_of=as_of, scope=SCOPE)
    if review.get("version") != version:
        issues.append("Scoring approval does not bind the current decision tables.")
    return issues


def eligible_sources(references, rubric, tables, *, as_of, workflows):
    """Local criteria have local provenance; ABCD retains its existing checks."""
    supplied = references + tables.get("references", []) + rubric["references"]
    identifiers = [row["id"] for row in supplied]
    if len(set(identifiers)) != len(identifiers):
        raise ValueError("Reference IDs must be unique across supplied catalogs.")
    selected = {}
    scopes = list(workflows)
    if "product-defect-initiate-refund" in scopes:
        scopes.append("refund-initiation")
    for scope in scopes:
        for row in eligible_references(references, as_of=as_of, scope=scope):
            selected[row["id"]] = row
        for row in eligible_criteria(rubric["references"], as_of=as_of, scope=scope):
            selected[row["id"]] = row
        for index, row in enumerate(tables.get("references", [])):
            source = row.get("source", {})
            if source.get("dataset") == "ABCD":
                if eligible_references([row], as_of=as_of, scope=scope):
                    selected[row["id"]] = row
            elif (
                source
                == {
                    "kind": "memoria-authored-scoring",
                    "path": "ml/rule_tables.json",
                    "pointer": f"/references/{index}/text",
                }
                and row.get("version") == reference_version(row)
                and not review_issues(row, as_of=as_of, scope=scope)
            ):
                selected[row["id"]] = row
    return list(selected.values())


def critical_rule(rule_id, tables):
    # Severity is a reviewed rule property, never inferred from the score.
    family = rule_id.split(":", 1)[0]
    if ":prerequisite:" in rule_id:
        family = "procedure-prerequisite"
    elif ":order:" in rule_id:
        family = "procedure-order"
    elif ":action:" in rule_id:
        family = "procedure-action"
    return any(
        row["rule_id"] == family and row.get("critical") is True
        for row in tables.get("checks", [])
    )


def score_checks(
    checks,
    *,
    limitations=(),
    interpretation_limits=(),
    error=None,
    inventory_complete=True,
):
    """Unknown checks affect coverage, never earned points or deductions."""
    seen = set()
    for check in checks:
        if (
            check["id"] in seen
            or check["outcome"] not in OUTCOMES
            or type(check["maximum"]) is not int
            or check["maximum"] != 1
        ):
            raise ValueError("Invalid or duplicate atomic scoring check.")
        seen.add(check["id"])
        expected = {"supported": 1, "breach": 0}.get(check["outcome"])
        if check["earned"] != expected or isinstance(check["earned"], bool):
            raise ValueError("Earned points do not match the evidence outcome.")
    assessed = [row for row in checks if row["outcome"] in {"supported", "breach"}]
    earned = sum(row["earned"] for row in assessed)
    possible = sum(row["outcome"] != "not-applicable" for row in checks)
    return {
        "score": 100 * earned / len(assessed) if assessed and not error else None,
        "coverage": 100 * len(assessed) / possible
        if possible and not error and inventory_complete
        else None,
        "earned": earned,
        "assessable": len(assessed),
        "possible": possible if inventory_complete else None,
        "inventoryComplete": inventory_complete,
        "checks": deepcopy(checks),
        "limitations": list(dict.fromkeys(limitations)),
        "processingError": error,
        "interpretationLimits": list(dict.fromkeys(interpretation_limits)),
    }


def overall_score(categories, profiles, workflows, *, as_of):
    result = {
        "score": None,
        "coverage": None,
        "profileId": None,
        "profileVersion": None,
        "weights": None,
        "reason": None,
    }
    if len(workflows) != 1:
        result["reason"] = (
            "A unique supported conversation purpose is required; ambiguous purposes are not assigned weights."
        )
        return result
    candidates = [
        profile
        for profile in profiles
        if workflows
        and set(workflows) <= set(profile.get("workflows", []))
        and not profile.get("unsupported", False)
    ]
    approved = []
    for profile in candidates:
        content = {
            key: value for key, value in profile.items() if key not in REVIEW_FIELDS
        }
        if profile.get("version") == content_version(content) and not review_issues(
            profile, as_of=as_of, scope=SCOPE
        ):
            approved.append(profile)
    if len(approved) != 1:
        result["reason"] = (
            "A unique applicable, current and approved weight profile is required."
        )
        return result
    profile = approved[0]
    weights = profile["weights"]
    if (
        set(weights) != set(CATEGORIES)
        or any(
            type(value) not in (int, float) or not 0 <= value <= 100
            for value in weights.values()
        )
        or sum(weights.values()) != 100
    ):
        raise ValueError("All four finite weights must sum to 100 percent.")
    result.update(
        profileId=profile["id"], profileVersion=profile["version"], weights=weights
    )
    by_category = {row["category"]: row for row in categories}
    if set(by_category) != set(CATEGORIES):
        raise ValueError("Overall requires exactly four categories.")
    if any(
        row["status"] != "completed"
        or row["scoring"]["score"] is None
        or row["scoring"]["coverage"] is None
        for row in categories
    ):
        result["reason"] = (
            "All four scores are required; unavailable weights are never redistributed."
        )
        return result
    for field in ("score", "coverage"):
        result[field] = sum(
            by_category[name]["scoring"][field] * weights[name] / 100
            for name in CATEGORIES
        )
    return result


def prioritise_findings(categories, overall):
    priorities = []
    weights = overall["weights"] or {}
    for row in categories:
        if row["result"] is None:
            continue
        checks = {check["ruleId"]: check for check in row["scoring"]["checks"]}
        for finding in row["result"]["findings"]:
            priorities.append(
                {
                    "finding_id": finding["id"],
                    "category": row["category"],
                    "critical": checks[finding["rule_id"]]["critical"],
                    "weight": weights.get(row["category"]),
                }
            )
    return sorted(
        priorities,
        key=lambda item: (
            not item["critical"],
            -(item["weight"] or 0),
            CATEGORIES.index(item["category"]),
            item["finding_id"],
        ),
    )


def validate_scored_report(report, evidence, eligible_refs, tables, *, as_of):
    """Validate arithmetic and source integrity; this is not semantic accuracy."""
    validate_evidence(evidence)
    if len(evidence["conversations"]) != 1:
        raise ValueError("A scored report requires one canonical conversation.")
    conversation = evidence["conversations"][0]
    if (
        report.get("schema_version") != VERSION
        or report.get("as_of") != as_of
        or report.get("conversation_id") != conversation["id"]
        or report.get("transcript_version") != conversation["transcript_version"]
        or report.get("source") != evidence["source"]
        or report.get("masking_version") != evidence["masking_version"]
        or report.get("versions", {}).get("tables") != policy_version(tables)
    ):
        raise ValueError(
            "Scored report source, versions or assessment context changed."
        )
    from .rule_assessment import RULE_VERSION, workflow_candidates
    from .rule_links import VERSION as LINK_VERSION

    if (
        report.get("workflows") != list(workflow_candidates(conversation, tables))
        or report["versions"].get("rules") != RULE_VERSION
        or report["versions"].get("links") != LINK_VERSION
    ):
        raise ValueError("Workflow applicability or rule versions changed.")
    identifiers = [row["id"] for row in eligible_refs]
    if len(identifiers) != len(set(identifiers)):
        raise ValueError("Eligible reference IDs must be unique.")
    scopes = report["workflows"] + (
        ["refund-initiation"]
        if "product-defect-initiate-refund" in report["workflows"]
        else []
    )
    for reference in eligible_refs:
        if not any(
            not review_issues(reference, as_of=as_of, scope=scope) for scope in scopes
        ):
            raise ValueError(
                "An assessment reference is not currently eligible for its workflow."
            )
        if reference["version"] != reference_version(reference):
            raise ValueError("Reference content or interpretation limits changed.")
    expected_trace = [
        {
            "id": ref["id"],
            "version": ref["version"],
            "interpretation_limits": ref.get("interpretation_limits", []),
        }
        for ref in eligible_refs
    ]
    if report.get("reference_trace") != expected_trace:
        raise ValueError(
            "Reference versions and interpretation limits must remain in the report trace."
        )

    categories = report["categories"]
    if len(categories) != 4 or {row["category"] for row in categories} != set(
        CATEGORIES
    ):
        raise ValueError("Scored report requires four distinct categories.")
    approval_errors = policy_issues(tables, as_of=as_of)
    answer_selections = {
        (selection["reference_id"], selection["reference_version"], selection["quote"])
        for workflow in tables.get("workflows", [])
        if workflow["id"] in report["workflows"]
        for selection in workflow.get("answer_statements", [])
        if selection["reference_id"] in workflow["reference_ids"]
    }
    failures = [row for row in categories if row["status"] == "failed"]
    expected_status = (
        "failed" if len(failures) == 4 else "partial" if failures else "completed"
    )
    if report.get("processing_status") != expected_status or len(
        report.get("errors", [])
    ) != len(failures):
        raise ValueError("Processing status and errors must match failed categories.")
    for row in categories:
        scoring = row["scoring"]
        if row["status"] not in {"completed", "failed"}:
            raise ValueError("Invalid processing state.")
        failed = row["status"] == "failed"
        if scoring["inventoryComplete"] and (
            len(report["workflows"]) != 1
            or any(
                check["ruleId"].endswith("unresolved-inventory")
                for check in scoring["checks"]
            )
        ):
            raise ValueError(
                "Unknown applicability must not invent a coverage denominator."
            )
        if failed != bool(scoring["processingError"]) or failed != (
            row["result"] is None
        ):
            raise ValueError(
                "Processing failures must remain separate from performance."
            )
        if not failed and not scoring["checks"]:
            raise ValueError("A completed assessment must explain its check inventory.")
        for check in scoring["checks"]:
            if set(check) != {
                "id",
                "ruleId",
                "requirement",
                "outcome",
                "earned",
                "maximum",
                "explanation",
                "advice",
                "citations",
                "critical",
            }:
                raise ValueError("Scoring check fields are missing or unexpected.")
            if any(
                not isinstance(check[field], str) or not check[field].strip()
                for field in ("id", "ruleId", "requirement", "explanation", "advice")
            ):
                raise ValueError("Check identity and explanation must be nonempty.")
            citations = check["citations"]
            if validate_citations(citations, [conversation], eligible_refs):
                raise ValueError(
                    "Scoring citation does not match eligible canonical evidence."
                )
            if check["outcome"] in {"supported", "breach", "not-applicable"}:
                kinds = {citation["kind"] for citation in citations}
                if approval_errors or not {"conversation", "reference"} <= kinds:
                    raise ValueError(
                        "Every resolved check requires approved rules and direct evidence plus authority."
                    )
                if row["category"] == "answer-support" and check["ruleId"].startswith(
                    "answer-assertion:"
                ):
                    for citation in citations:
                        if (
                            citation["kind"] == "reference"
                            and (
                                citation["reference_id"],
                                citation["reference_version"],
                                citation["quote"],
                            )
                            not in answer_selections
                        ):
                            raise ValueError(
                                "Answer citation is not a selected factual quotation."
                            )
            expected_critical = (
                not approval_errors
                and check["outcome"] == "breach"
                and critical_rule(check["ruleId"], tables)
            )
            if (
                type(check["critical"]) is not bool
                or check["critical"] != expected_critical
            ):
                raise ValueError(
                    "Critical findings require an approved, evidenced breach."
                )
        if not failed:
            legacy = [
                {
                    "rule_id": check["ruleId"],
                    "result": {
                        "supported": "meets-criteria",
                        "breach": "needs-review",
                    }.get(check["outcome"], "cannot-assess"),
                    "explanation": check["explanation"],
                    "advice": check["advice"],
                    "citations": check["citations"],
                }
                for check in scoring["checks"]
            ]
            if row["result"] != category_result(conversation, row["category"], legacy):
                raise ValueError(
                    "Legacy findings must exactly reflect the scored checks."
                )
        expected = score_checks(
            scoring["checks"],
            limitations=scoring["limitations"],
            interpretation_limits=scoring["interpretationLimits"],
            error=scoring["processingError"],
            inventory_complete=scoring["inventoryComplete"],
        )
        if scoring != expected:
            raise ValueError(
                "Stored category arithmetic differs from its point ledger."
            )
    expected = overall_score(
        categories, tables.get("profiles", []), report["workflows"], as_of=as_of
    )
    if report["overall"] != expected:
        raise ValueError("Overall score differs from approved profile and categories.")

    if report.get("priorities") != prioritise_findings(categories, expected):
        raise ValueError(
            "Finding priorities must retain criticality and approved weights."
        )
