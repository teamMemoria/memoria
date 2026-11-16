"""Deterministic category aggregation; missing evidence never becomes a pass."""

import json
from copy import deepcopy
from hashlib import sha256

from .entities import CATEGORIES, RESULTS


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
