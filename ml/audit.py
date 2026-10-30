"""Shared audit records and trust boundaries, not a general language evaluator.

Rule implementations supply explicit checks. Constructed tests establish only
those documented patterns, not language understanding or human label agreement.
Callers supply parsed values and explicit assessment context.
"""

import json
from copy import deepcopy
from hashlib import sha256
from math import isfinite

from . import wording
from .abcd import transcript_version
from .citations import validate_citations
from .references import (
    OPTIONAL_CONTENT_FIELDS,
    RECORD_FIELDS,
    reference_issues,
    reference_passages,
    reference_version,
    review_issues,
)

quotation_context = wording.quotation_context

CATEGORIES = ("procedure", "answer-support", "completeness", "communication-style")
RESULTS = ("meets-criteria", "needs-review", "cannot-assess")
CRITERIA_IDS = {
    "clarity": "memoria-wording-clarity",
    "respect": "memoria-wording-respect",
    "acknowledgement": "memoria-wording-acknowledgement",
}


def validate_report_limits(limits):
    """Validate the complete execution settings recorded with a report."""
    if not isinstance(limits, dict) or limits.keys() != {
        "max_events",
        "max_input_bytes",
        "max_output_bytes",
        "timeout_seconds",
    }:
        raise ValueError("Report limits must include every execution setting.")
    for name, value in limits.items():
        if name == "timeout_seconds":
            try:
                valid = type(value) in (int, float) and isfinite(value) and value > 0
            except OverflowError:
                valid = False
        else:
            valid = type(value) is int and value > 0
        if not valid:
            raise ValueError("Report limits must be positive finite values.")
    if limits["max_output_bytes"] < 4096:
        raise ValueError(
            "Output budget must allow at least 4096 bytes for an error report."
        )


def validate_rubric(rubric: dict) -> None:
    """Validate catalog shape, source positions and versions without approving it."""
    if (
        not isinstance(rubric, dict)
        or rubric.keys() != {"schema_version", "references"}
        or type(rubric["schema_version"]) is not int
        or rubric["schema_version"] != 1
        or not isinstance(rubric["references"], list)
        or any(
            not isinstance(section, dict)
            or section.keys() - OPTIONAL_CONTENT_FIELDS != RECORD_FIELDS
            for section in rubric["references"]
        )
    ):
        raise ValueError("Unsupported review rubric schema.")
    for index, section in enumerate(rubric["references"]):
        source = section.get("source")
        if (
            not isinstance(source, dict)
            or source.get("pointer") != f"/references/{index}/text"
        ):
            raise ValueError(
                "Rubric provenance does not match its local section position."
            )
    reference_passages(rubric["references"])


def criteria_issues(criterion: dict, *, as_of: str, scope: str) -> list[str]:
    """Validate authored provenance separately from ABCD's source requirements."""
    issues = review_issues(criterion, as_of=as_of, scope=scope)
    if (
        not isinstance(criterion, dict)
        or criterion.keys() - OPTIONAL_CONTENT_FIELDS != RECORD_FIELDS
    ):
        return ["Rubric section fields are missing or unsupported."]
    if (
        not isinstance(criterion["section_id"], str)
        or CRITERIA_IDS.get(criterion["section_id"]) != criterion["id"]
    ):
        issues.append("Unsupported rubric section ID.")
    expected_pointer = (
        f"/references/{tuple(CRITERIA_IDS).index(criterion['section_id'])}/text"
        if isinstance(criterion["section_id"], str)
        and criterion["section_id"] in CRITERIA_IDS
        else None
    )
    if any(
        not isinstance(criterion[field], str) or not criterion[field].strip()
        for field in ("id", "section_id", "title", "text", "version")
    ):
        issues.append("Rubric identifiers and text must be nonempty strings.")
    for field in (
        "conditions",
        "exclusions",
        "scope",
        "safety_flags",
        "interpretation_limits",
    ):
        value = criterion.get(field)
        if not isinstance(value, list) or any(
            not isinstance(item, str) or not item.strip() for item in value
        ):
            issues.append(
                "Rubric conditions, scope and interpretation limits must be text lists."
            )
            break
    source = criterion["source"]
    if (
        not isinstance(source, dict)
        or source.keys() != {"kind", "path", "pointer"}
        or source.get("kind") != "memoria-authored-rubric"
        or source.get("path") != "ml/rubric.json"
        or not isinstance(source.get("pointer"), str)
        or source["pointer"] != expected_pointer
    ):
        issues.append(
            "Rubric provenance must identify its actual authored local section."
        )
    try:
        if criterion["version"] != reference_version(criterion):
            issues.append("Rubric version does not match its content.")
    except ValueError:
        issues.append("Rubric content is not valid JSON.")
    return issues


def eligible_criteria(criteria: list[dict], *, as_of: str, scope: str) -> list[dict]:
    if not isinstance(criteria, list):
        raise TypeError("Rubric sections must be a list.")
    review_issues({}, as_of=as_of, scope=scope)
    ids = [
        section.get("id")
        for section in criteria
        if isinstance(section, dict) and isinstance(section.get("id"), str)
    ]
    if len(ids) != len(set(ids)):
        raise ValueError("Rubric section IDs must be unique.")
    return [
        section
        for section in criteria
        if not criteria_issues(section, as_of=as_of, scope=scope)
    ]


def category_result(
    conversation: dict, category: str, checks: list[dict], *, details=None
) -> dict:
    """Aggregate applicable checks; uncertainty cannot become a blanket pass."""
    if category not in CATEGORIES or not isinstance(checks, list):
        raise ValueError("Unsupported category or checks.")
    fields = {"rule_id", "result", "explanation", "advice", "citations"}
    for check in checks:
        if (
            not isinstance(check, dict)
            or check.keys() != fields
            or check["result"] not in RESULTS
            or any(
                not isinstance(check[field], str) or not check[field].strip()
                for field in ("rule_id", "explanation", "advice")
            )
            or not isinstance(check["citations"], list)
        ):
            raise ValueError("Audit check fields are missing or invalid.")
    statuses = [check["result"] for check in checks]
    result = (
        "needs-review"
        if "needs-review" in statuses
        else "cannot-assess"
        if not checks or "cannot-assess" in statuses
        else "meets-criteria"
    )
    findings = []
    for check in checks:
        if check["result"] != "needs-review":
            continue
        identity = [
            conversation["id"],
            conversation["transcript_version"],
            category,
            check["rule_id"],
            sorted(
                json.dumps(citation, sort_keys=True) for citation in check["citations"]
            ),
        ]
        identifier = sha256(json.dumps(identity, sort_keys=True).encode()).hexdigest()[
            :24
        ]
        findings.append(
            {
                "id": "finding-" + identifier,
                "rule_id": check["rule_id"],
                "explanation": check["explanation"],
                "advice": check["advice"],
                "citations": deepcopy(check["citations"]),
            }
        )
    limitations = list(
        dict.fromkeys(
            check["explanation"]
            for check in checks
            if check["result"] == "cannot-assess"
        )
    )
    if not checks:
        limitations.append(
            "No applicable check could be established from the supplied evidence."
        )
    explanations = {
        "meets-criteria": "All applicable, recognised checks are supported within the stated limits.",
        "needs-review": "Direct evidence supports a finding requiring review; limitations remain separate.",
        "cannot-assess": "The supplied evidence or approved guidance does not support a complete assessment.",
    }
    return {
        "category": category,
        "result": result,
        "explanation": explanations[result],
        "findings": findings,
        "limitations": limitations,
        "details": {**deepcopy(details or {}), "checks": deepcopy(checks)},
    }


def _result_citations(value):
    if isinstance(value, dict):
        for key, item in value.items():
            if key == "citations" or key.endswith("_citations"):
                if not isinstance(item, list):
                    raise ValueError("Result citations must be lists.")
                yield from item
            elif key == "citation":
                yield item
            else:
                yield from _result_citations(item)
    elif isinstance(value, list):
        for item in value:
            yield from _result_citations(item)


def validate_results(
    conversation: dict,
    results: list[dict],
    eligible_sources: list[dict],
    *,
    as_of: str,
    scope: str,
    require_all: bool = True,
) -> None:
    """Validate complete results or a nonempty subset against eligible sources."""
    review_issues({}, as_of=as_of, scope=scope)
    try:
        if conversation["transcript_version"] != transcript_version(conversation):
            raise ValueError("Transcript version does not match its evidence.")
    except (KeyError, TypeError):
        raise ValueError("Invalid conversation evidence.") from None
    if type(require_all) is not bool:
        raise TypeError("require_all must be a boolean.")
    if not isinstance(eligible_sources, list):
        raise TypeError("Eligible sources must be a list.")
    seen = set()
    for reference in eligible_sources:
        if not isinstance(reference, dict) or not isinstance(reference.get("id"), str):
            raise TypeError("Invalid eligible source.")
        if reference["id"] in seen:
            raise ValueError("Guideline and rubric IDs must be globally unique.")
        seen.add(reference["id"])
        source = reference.get("source", {})
        issues = (
            reference_issues(reference, as_of=as_of, scope=scope)
            if isinstance(source, dict) and source.get("dataset") == "ABCD"
            else criteria_issues(reference, as_of=as_of, scope=scope)
        )
        if issues:
            raise ValueError("An ineligible source reached the audit output boundary.")
    result_fields = {
        "category",
        "result",
        "explanation",
        "findings",
        "limitations",
        "details",
    }
    if (
        not isinstance(results, list)
        or not results
        or any(
            not isinstance(result, dict)
            or result.keys() != result_fields
            or not isinstance(result["category"], str)
            or result["category"] not in CATEGORIES
            for result in results
        )
        or len({result["category"] for result in results}) != len(results)
        or (
            require_all
            and sorted(result["category"] for result in results) != sorted(CATEGORIES)
        )
    ):
        raise ValueError(
            "An assessment requires exactly the four category records."
            if require_all
            else "Partial results require unique, known category records."
        )
    finding_ids = set()
    for result in results:
        if (
            result["result"] not in RESULTS
            or not isinstance(result["explanation"], str)
            or not result["explanation"].strip()
            or not isinstance(result["findings"], list)
            or not isinstance(result["limitations"], list)
            or not isinstance(result["details"], dict)
            or any(
                not isinstance(limit, str) or not limit.strip()
                for limit in result["limitations"]
            )
            or (result["result"] == "cannot-assess" and not result["limitations"])
            or (result["result"] == "needs-review" and not result["findings"])
            or (result["result"] != "needs-review" and result["findings"])
        ):
            raise ValueError(
                "Category results require explanations, limitations and supported findings."
            )
        for finding in result["findings"]:
            if (
                not isinstance(finding, dict)
                or finding.keys()
                != {"id", "rule_id", "explanation", "advice", "citations"}
                or any(
                    not isinstance(finding[field], str) or not finding[field].strip()
                    for field in ("id", "rule_id", "explanation", "advice")
                )
                or not isinstance(finding["citations"], list)
            ):
                raise ValueError("Invalid finding record.")
            if finding["id"] in finding_ids:
                raise ValueError("Finding IDs must be unique within an assessment.")
            finding_ids.add(finding["id"])
            kinds = [
                citation.get("kind")
                for citation in finding["citations"]
                if isinstance(citation, dict)
            ]
            if "conversation" not in kinds or (
                result["category"] != "completeness" and "reference" not in kinds
            ):
                raise ValueError(
                    "A negative finding lacks its evidence or approved requirement."
                )
    citations = list(_result_citations(results))
    if validate_citations(citations, [conversation], eligible_sources):
        raise ValueError("Audit output contains an invalid or ineligible citation.")


def build_assessment(
    conversation: dict,
    results: list[dict],
    eligible_sources: list[dict],
    *,
    as_of: str,
    scope: str,
    rule_versions: dict,
) -> dict:
    """Build a complete assessment after validating all four category records."""
    if (
        not isinstance(rule_versions, dict)
        or not rule_versions
        or any(
            not isinstance(key, str) or not isinstance(value, str) or not value
            for key, value in rule_versions.items()
        )
    ):
        raise ValueError("Explicit rule versions are required.")
    validate_results(conversation, results, eligible_sources, as_of=as_of, scope=scope)
    used_ids = {
        citation["reference_id"]
        for citation in _result_citations(results)
        if citation["kind"] == "reference"
    }
    trace = [
        {
            "id": reference["id"],
            "version": reference["version"],
            "interpretation_limits": deepcopy(
                reference.get("interpretation_limits", [])
            ),
        }
        for reference in eligible_sources
        if reference["id"] in used_ids
    ]
    version_data = {
        "rules": rule_versions,
        "references": sorted((ref["id"], ref["version"]) for ref in eligible_sources),
    }
    version = (
        "sha256:"
        + sha256(json.dumps(version_data, sort_keys=True).encode()).hexdigest()
    )
    return {
        "schema_version": 1,
        "assessment_type": "automated",
        "conversation_id": conversation["id"],
        "transcript_version": conversation["transcript_version"],
        "as_of": as_of,
        "scope": scope,
        "rule_version": version,
        "results": deepcopy(results),
        "reference_trace": trace,
    }
