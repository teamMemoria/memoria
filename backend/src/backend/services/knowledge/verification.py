"""Check drafts against approved, independent reference passages (#19).

``check_drafts(drafts, company_id, references, ...)`` breaks each draft into
claims (its answer passages), finds the reference passages that apply, and
reports, claim by claim, whether each is supported, partly supported,
contradicted or unverifiable, with citations to the exact reference passages
(reference id, version, approval and eligibility). It also lists conditions the
references set that the draft leaves out, the possible conflicts from #18, the
conversations that repeat the answer, and everything still needed before a
person could verify it.

Rules that cannot be bent from here:

* Only references that are approved, eligible (not stale, disputed or out of
  scope) and for the same company and scope can support or contradict a claim.
  Every other reference is listed under ``ignored_references`` with the reason.
* Support has to come from an authoritative reference passage. Other drafts,
  repeated agent answers and existing knowledge entries never count.
* The output carries no decision. ``ml_recommendation`` is advice for the
  reviewer; ``requirements_remaining`` always includes a human verification,
  because having permission is not the same as having checked. Approval,
  rejection, replacement, verification dates and audit use belong to the
  backend and an authorized person.
"""

from __future__ import annotations

import datetime as dt
import json
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from . import text as tx
from .conflicts import ConflictConfig, _claim, _compare, _draft_owner, _Owner
from .errors import PipelineError, invalid

VERIFICATION_SCHEMA_VERSION = "knowledge-verification/1"
MAX_REFERENCES = 50_000
REFERENCE_KIND = "authoritative_reference"
HUMAN_STEP = "An authorized person must review the evidence and record the verification decision in the backend."


@dataclass(frozen=True)
class VerificationConfig:
    """Choices the team still has to agree (issue #19).

    ``support_threshold``: share of a claim's subject words a reference passage must contain to support it.
    ``partial_threshold``: share below which a claim is unverifiable rather than partly supported.
    ``require_every_claim``: whether a draft needs every claim supported to be recommended
    (False lets claims that are only procedural, like "A link will be sent.", be partly supported).
    """

    support_threshold: float = 0.6
    partial_threshold: float = 0.35
    require_every_claim: bool = True

    def __post_init__(self) -> None:
        if not 0 <= self.partial_threshold <= self.support_threshold <= 1:
            raise invalid(
                "config", "need 0 <= partial_threshold <= support_threshold <= 1"
            )


# --------------------------------------------------------------------------- references


def load_reference_snapshot(path: Path, company_id: str) -> list[dict[str, Any]]:
    """Read a snapshot file and return its passages as references for ``company_id``.

    The caller states which company the snapshot is a source for; the snapshot
    itself is company-neutral so the same reviewed file can be reused.
    """
    snapshot = json.loads(Path(path).read_text(encoding="utf-8"))
    if snapshot.get("kind") != "authoritative_reference_snapshot":
        raise PipelineError(
            "reference_invalid", "not a reference snapshot", "references"
        )
    return [
        {
            **p,
            "company_id": company_id,
            "kind": REFERENCE_KIND,
            "snapshot_id": snapshot["snapshot_id"],
        }
        for p in snapshot["passages"]
    ]


def _applies(reference: Mapping[str, Any], scope: Mapping[str, str]) -> bool:
    ref_scope = reference.get("scope") or {}
    if ref_scope.get("flow") != scope.get("flow"):
        return False
    if "subflow" in ref_scope:
        return ref_scope["subflow"] == scope.get("subflow")
    prefix = ref_scope.get("subflow_prefix")
    return bool(prefix) and str(scope.get("subflow", "")).startswith(prefix)


def _ineligible(
    reference: Mapping[str, Any], company_id: str, as_of: dt.date | None
) -> str | None:
    """Why a reference cannot verify anything, or None when it can."""
    if reference.get("kind") != REFERENCE_KIND:
        return "not an authoritative reference (drafts, agent answers and knowledge entries never verify)"
    if reference.get("company_id") != company_id:
        return "belongs to another company"
    approval = (reference.get("approval") or {}).get("status")
    if approval != "approved":
        return f"not approved (approval status: {approval or 'missing'})"
    eligibility = reference.get("eligibility") or {}
    status = eligibility.get("status")
    if status != "eligible":
        return f"not eligible ({status or 'missing'}{': ' + eligibility['reason'] if eligibility.get('reason') else ''})"
    valid_until = eligibility.get("valid_until")
    if valid_until:
        if as_of is None:
            return "has an expiry date but no as_of date was given, so it cannot be shown to be current"
        try:
            if dt.date.fromisoformat(str(valid_until)) < as_of:
                return f"stale (valid until {valid_until})"
        except ValueError:
            return f"unreadable valid_until {valid_until!r}"
    return None


def _check_reference(reference: Any, index: int) -> Mapping[str, Any]:
    where = f"references[{index}]"
    if not isinstance(reference, Mapping):
        raise PipelineError("reference_invalid", "must be an object", where)
    for key in ("reference_id", "text", "version"):
        if not isinstance(reference.get(key), str) or not reference[key]:
            raise PipelineError(
                "reference_invalid",
                f"{key} must be a non-empty string",
                f"{where}.{key}",
            )
    if not isinstance(reference.get("scope"), Mapping):
        raise PipelineError(
            "reference_invalid", "scope must be an object", f"{where}.scope"
        )
    return reference


@dataclass
class _Unit:
    """One reference passage (or an action with its sub-points) ready to compare."""

    reference: Mapping[str, Any]
    claim: Any
    topic: set[str]


def _unit(reference: Mapping[str, Any]) -> _Unit:
    owner = _Owner(
        kind="entry",
        owner_id=reference["reference_id"],
        scope=dict(reference["scope"]),
        question_terms=set(),
        context_levels=set(),
        condition_texts=[],
        info={"type": "reference", "reference_id": reference["reference_id"]},
    )
    claim = _claim(
        owner,
        reference["text"],
        {"reference_id": reference["reference_id"]},
        from_action=False,
    )
    # A guideline sub-point ("Guest > ... you cannot help them") is about its
    # subflow even when it does not repeat it. The subflow's words count when
    # deciding whether a level is excluded, never as support.
    title = (reference.get("guideline") or {}).get("subflow", "")
    return _Unit(
        reference,
        claim,
        claim.subject | {t for t in tx.content_terms(title) if t != "faq"},
    )


def _units(usable: Sequence[Mapping[str, Any]]) -> list[_Unit]:
    """Each usable passage, plus each action read together with its usable sub-points.

    Guidelines often state a rule as a heading and a list ("Ask for 3 out of 4
    items below" / "Zip Code" / "Phone number" ...); only the two together say it.
    """
    units = [_unit(r) for r in usable]
    children: dict[str, list[Mapping[str, Any]]] = {}
    for reference in usable:
        if reference.get("parent"):
            children.setdefault(reference["parent"], []).append(reference)
    for reference in usable:
        kids = children.get(reference["reference_id"])
        if kids:
            combined = {
                **reference,
                "text": " ".join([reference["text"], *(k["text"] for k in kids)]),
                "combined_from": [
                    reference["reference_id"],
                    *(k["reference_id"] for k in kids),
                ],
            }
            units.append(_unit(combined))
    return units


def _citation(reference: Mapping[str, Any], support: float) -> dict[str, Any]:
    return {
        "reference_id": reference["reference_id"],
        "combined_from": reference.get("combined_from"),
        "version": reference["version"],
        "snapshot_id": reference.get("snapshot_id"),
        "quote": reference["text"],
        "approval": reference.get("approval"),
        "eligibility": reference.get("eligibility"),
        "guideline": reference.get("guideline"),
        "support": round(support, 4),
    }


# --------------------------------------------------------------------------- claims


def _support(claim_subject: set[str], reference_subject: set[str]) -> float:
    if not claim_subject:
        return 0.0
    return len(claim_subject & reference_subject) / len(claim_subject)


def _contradiction(claim, unit: _Unit) -> str | None:
    """A reason the reference contradicts the claim, or None."""
    ref_claim = unit.claim
    shared = claim.subject & ref_claim.subject
    clash = claim.allowed & ref_claim.denied
    if clash and claim.subject & unit.topic:
        return f"The reference excludes {', '.join(sorted(clash))}, which the claim includes."
    for measure in sorted(claim.quantities.keys() & ref_claim.quantities.keys()):
        if (
            not claim.quantities[measure] & ref_claim.quantities[measure]
            and len(shared) >= 2
        ):
            if (
                claim.levels
                and ref_claim.levels
                and not claim.levels & ref_claim.levels
            ):
                continue  # a figure for another membership level
            return (
                f"The reference gives {sorted(ref_claim.quantities[measure])} {measure}; "
                f"the claim gives {sorted(claim.quantities[measure])}."
            )
    finding = _compare(claim, ref_claim, ConflictConfig())
    if finding and finding.kind == "polarity" and finding.status == "possible_conflict":
        return "The reference says the opposite."
    return None


def _claim_result(
    claim, units: Sequence[_Unit], config: VerificationConfig
) -> dict[str, Any]:
    scored = []
    contradictions = []
    for unit in units:
        reference, ref_claim = unit.reference, unit.claim
        reason = _contradiction(claim, unit)
        if reason:
            contradictions.append(
                {
                    **_citation(reference, _support(claim.subject, ref_claim.subject)),
                    "reason": reason,
                }
            )
            continue
        support = _support(claim.subject, ref_claim.subject)
        if claim.quantities:
            # A figure only counts as supported when the reference states the same
            # figure, and the same figure on both sides is strong evidence.
            same = all(
                claim.quantities[u] & ref_claim.quantities.get(u, set())
                for u in claim.quantities
            )
            support = (
                min(1.0, support + 0.3)
                if same and support > 0
                else min(support, config.support_threshold - 1e-6)
            )
        if (
            claim.allowed
            and ref_claim.allowed
            and not claim.allowed & ref_claim.allowed
        ):
            support = min(support, config.partial_threshold - 1e-6)
        specificity = tx.jaccard(claim.subject, ref_claim.subject)
        scored.append((support, reference, ref_claim, specificity))
    scored.sort(key=lambda s: (-s[0], -s[3], s[1]["reference_id"]))
    best = scored[0][0] if scored else 0.0
    if contradictions:
        status = "contradicted"
    elif best >= config.support_threshold:
        status = "supported"
    elif best >= config.partial_threshold:
        status = "partially_supported"
    else:
        status = "unverifiable"
    citations = [
        _citation(r, s) for s, r, _, _ in scored[:3] if s >= config.partial_threshold
    ]
    missing = []
    # Conditions the references attach to what the agent said, that the draft
    # does not state. Recorded actions are outcomes, not statements, so they are
    # not held to this; combined passages mix several levels, so only single
    # passages that apply to the claim's own levels are used.
    effective_levels = claim.levels | claim.owner.context_levels
    if (
        status in {"supported", "partially_supported"}
        and claim.passage.get("speaker") == "agent"
    ):
        seen: set[tuple[str, str]] = set()
        for support, reference, ref_claim, _ in scored:
            if support < config.support_threshold or reference.get("combined_from"):
                continue
            if (
                ref_claim.levels
                and effective_levels
                and not ref_claim.levels & effective_levels
            ):
                continue
            needed = []
            if ref_claim.levels and not effective_levels:
                needed.append(
                    f"membership level ({', '.join(sorted(ref_claim.levels))})"
                )
            for unit in sorted(ref_claim.quantities.keys() - claim.quantities.keys()):
                needed.append(f"{unit} limit {sorted(ref_claim.quantities[unit])}")
            for condition in needed:
                if (reference["reference_id"], condition) not in seen:
                    seen.add((reference["reference_id"], condition))
                    missing.append(
                        {
                            "reference_id": reference["reference_id"],
                            "condition": condition,
                            "quote": reference["text"],
                        }
                    )
    return {
        "claim": claim.text,
        "passage": claim.passage,
        "status": status,
        "best_support": round(best, 4),
        "citations": citations,
        "contradicted_by": contradictions,
        "missing_conditions": missing,
    }


def check_drafts(
    drafts: Any,
    company_id: str,
    references: Any,
    conflicts: Mapping[str, Any] | None = None,
    groups: Mapping[str, Any] | None = None,
    as_of: str | None = None,
    config: VerificationConfig | None = None,
) -> dict[str, Any]:
    """Build a verification packet for each draft. Raises ``PipelineError`` on bad input."""
    config = config or VerificationConfig()
    if not isinstance(company_id, str) or not company_id:
        raise invalid("company_id", "must be a non-empty string")
    if not isinstance(drafts, list | tuple):
        raise invalid("drafts", "must be an array")
    if not isinstance(references, list | tuple):
        raise PipelineError("reference_invalid", "must be an array", "references")
    if len(references) > MAX_REFERENCES:
        raise PipelineError(
            "oversized_input", f"more than {MAX_REFERENCES} references", "references"
        )
    as_of_date = None
    if as_of is not None:
        try:
            as_of_date = dt.date.fromisoformat(as_of)
        except ValueError as error:
            raise invalid("as_of", "must be an ISO date (YYYY-MM-DD)") from error
    checked = [_check_reference(r, i) for i, r in enumerate(references)]
    owners = [_draft_owner(d, i, company_id) for i, d in enumerate(drafts)]

    supporting: dict[str, list[str]] = {}
    for group in (groups or {}).get("groups", []):
        for draft_id in group.get("member_draft_ids", []):
            supporting[draft_id] = list(group.get("source_keys", []))
    conflicts_of: dict[str, list[dict[str, Any]]] = {}
    for item in (conflicts or {}).get("possible_conflicts", []):
        for side in ("a", "b"):
            draft_id = item[side].get("draft_id")
            if draft_id:
                conflicts_of.setdefault(draft_id, []).append(
                    {
                        "conflict_id": item["conflict_id"],
                        "status": item["status"],
                        "kind": item["kind"],
                        "explanation": item["explanation"],
                    }
                )

    packets = []
    for owner in owners:
        in_scope = [r for r in checked if _applies(r, owner.scope)]
        usable, ignored = [], []
        for reference in in_scope:
            reason = _ineligible(reference, company_id, as_of_date)
            if reason:
                ignored.append(
                    {
                        "reference_id": reference["reference_id"],
                        "version": reference["version"],
                        "reason": reason,
                    }
                )
            else:
                usable.append(reference)
        units = _units(usable)
        claims = [_claim_result(c, units, config) for c in owner.claims]
        packets.append(
            _packet(
                company_id,
                owner,
                claims,
                usable,
                ignored,
                supporting,
                conflicts_of,
                config,
            )
        )
    return {
        "schema": VERIFICATION_SCHEMA_VERSION,
        "status": "ok",
        "company_id": company_id,
        "as_of": as_of,
        "config": asdict(config),
        "results": packets,
        "note": (
            "Findings for an authorized reviewer. Nothing here approves, rejects or replaces an entry, "
            "renews a verification date or makes a draft available for audit use."
        ),
    }


def _packet(
    company_id, owner, claims, usable, ignored, supporting, conflicts_of, config
) -> dict[str, Any]:
    statuses = [c["status"] for c in claims]
    draft_conflicts = conflicts_of.get(owner.owner_id, [])
    requirements = []
    if not usable:
        requirements.append(
            "No approved, eligible reference covers this topic; add or approve one."
        )
    for claim in claims:
        if claim["status"] == "unverifiable":
            requirements.append(
                f"Find an authoritative passage for: {claim['claim']!r}"
            )
        elif claim["status"] == "partially_supported":
            requirements.append(
                f"Confirm the part of this claim the references do not state: {claim['claim']!r}"
            )
        elif claim["status"] == "contradicted":
            requirements.append(
                f"Resolve the contradiction with {claim['contradicted_by'][0]['reference_id']}: {claim['claim']!r}"
            )
        for missing in claim["missing_conditions"]:
            requirements.append(
                f"State the {missing['condition']} the reference {missing['reference_id']} sets."
            )
    for conflict in draft_conflicts:
        requirements.append(
            f"Resolve {conflict['status'].replace('_', ' ')} {conflict['conflict_id']}."
        )
    requirements.append(HUMAN_STEP)

    if "contradicted" in statuses:
        overall, advice = "contradicted", "contradicted_by_references"
    elif statuses and all(s == "supported" for s in statuses):
        overall, advice = "supported", "supported_by_references"
    elif "supported" in statuses or "partially_supported" in statuses:
        overall, advice = "partially_supported", "needs_more_evidence"
    else:
        overall, advice = "unverifiable", "cannot_be_verified"
    if (
        not config.require_every_claim
        and overall == "partially_supported"
        and "unverifiable" not in statuses
        and "supported" in statuses
    ):
        overall, advice = "supported", "supported_by_references"
    blocking = any(c["missing_conditions"] for c in claims) or any(
        c["status"] == "possible_conflict" for c in draft_conflicts
    )
    if advice == "supported_by_references" and blocking:
        advice = "needs_more_evidence"
    return {
        "draft_id": owner.owner_id,
        "company_id": company_id,
        "scope": owner.scope,
        "verification_status": overall,
        "ml_recommendation": advice,
        "decision": None,
        "claims": claims,
        "possible_conflicts": draft_conflicts,
        "supporting_conversations": {
            "source_keys": supporting.get(
                owner.owner_id, [owner.info.get("source_key")]
            ),
            "note": "Conversations that repeat the answer. Repetition is not verification.",
        },
        "references_considered": len(usable),
        "ignored_references": ignored,
        "requirements_remaining": requirements,
    }
