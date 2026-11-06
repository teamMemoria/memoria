"""Check drafts against approved, independent reference passages
"""

from __future__ import annotations

import datetime as dt
import json
import re
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
    """
    """

    support_threshold: float = 0.6
    partial_threshold: float = 0.35

    def __post_init__(self) -> None:
        values = (self.partial_threshold, self.support_threshold)
        # A threshold of 0 would let a reference with no words in common "support" a claim.
        if (
            not all(type(v) in (int, float) for v in values)
            or not 0 < values[0] <= values[1] <= 1
        ):
            raise invalid(
                "config", "need 0 < partial_threshold <= support_threshold <= 1"
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
    ref_scope = reference["scope"]
    if ref_scope.get("flow") != scope.get("flow"):
        return False
    if "subflow" in ref_scope:
        return ref_scope["subflow"] == scope.get("subflow")
    prefix = ref_scope.get("subflow_prefix")
    return (
        isinstance(prefix, str)
        and bool(prefix)
        and str(scope.get("subflow", "")).startswith(prefix)
    )


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
        reason = eligibility.get("reason")
        detail = f": {reason}" if reason else ""
        return f"not eligible ({status or 'missing'}{detail})"
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


def _framing(reference: Mapping[str, Any]) -> str | None:
    """Guideline instruction lines frame a flow ("Customers want to know ...", a list of FAQ
    topics); they do not state policy, so they neither support nor contradict a claim."""
    if (reference.get("guideline") or {}).get("type") == "instruction":
        return "instruction line: frames the flow, does not state policy"
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
    for key in ("approval", "eligibility"):
        value = reference.get(key)
        if value is None:
            continue
        if not isinstance(value, Mapping):
            raise PipelineError(
                "reference_invalid", f"{key} must be an object", f"{where}.{key}"
            )
        for field_name in ("status", "reason", "valid_until"):
            if value.get(field_name) is not None and not isinstance(
                value[field_name], str
            ):
                raise PipelineError(
                    "reference_invalid",
                    f"{field_name} must be a string",
                    f"{where}.{key}.{field_name}",
                )
    if reference.get("parent") is not None and not isinstance(reference["parent"], str):
        raise PipelineError(
            "reference_invalid", "parent must be a string", f"{where}.parent"
        )
    scope = reference.get("scope")
    if isinstance(scope, Mapping) and not all(
        isinstance(scope.get(k), str)
        for k in ("flow", "subflow", "subflow_prefix")
        if k in scope
    ):
        raise PipelineError(
            "reference_invalid", "scope values must be strings", f"{where}.scope"
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


def _natural(reference_id: str) -> list[Any]:
    """Sort key that puts "#a2.2" before "#a2.10"."""
    return [
        int(part) if part.isdigit() else part
        for part in re.split(r"(\d+)", reference_id)
    ]


def combine_texts(texts: Sequence[str]) -> str:
    """The text of a heading read with its sub-points, one sentence each.

    Each part is kept exactly; a part without closing punctuation is followed
    by a full stop, so a short heading ("Guest") is never read as part of the
    next sub-point.
    """
    out = texts[0]
    for text in texts[1:]:
        out += (" " if out.rstrip()[-1:] in tuple(".!?:;") else ". ") + text
    return out


def _units(usable: Sequence[Mapping[str, Any]]) -> list[_Unit]:
    """Each usable passage, plus each action read together with its usable sub-points.

    Guidelines often state a rule as a heading and a list ("Ask for 3 out of 4
    items below" / "Zip Code" / "Phone number" ...); only the two together say it.
    Sub-points are read in reference-id order, so the input order never changes
    a result.
    """
    usable = sorted(usable, key=lambda r: _natural(r["reference_id"]))
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
                "text": combine_texts([reference["text"], *(k["text"] for k in kids)]),
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


_HELPERS = frozenset(
    [
        "be",
        "been",
        "being",
        "able",
        "to",
        "do",
        "does",
        "did",
        "have",
        "has",
        "had",
        "ever",
        "even",
        "always",
        "really",
        "actually",
        "just",
        "yet",
        "also",
        "the",
        "a",
        "an",
        "any",
        "your",
        "their",
        "our",
        "my",
        "his",
        "her",
        "its",
    ]
)
_CLAUSE = re.compile(r"[,;:]|\bbut\b|\bhowever\b", re.IGNORECASE)


def negated_predicates(text: str) -> tuple[set[str], set[str]]:
    """(words a negation applies to, every content word), clause by clause.

    Only the first content word after a negation counts as negated ("cannot
    *use* promo codes"), and a negation never reaches past a comma or "but", so
    "codes never expire, you can use them" negates "expire" and not "use".
    """
    negated: set[str] = set()
    for clause in _CLAUSE.split(tx.normalise(text)):
        tokens = tx.words(tx._NOT_NEGATION.sub(" ", clause))
        for i, token in enumerate(tokens):
            if token in tx.NEGATIONS or token.endswith("n't"):
                for following in tokens[i + 1 :]:
                    # Skip helpers ("be able to"), never the verb itself, even a
                    # common one: "cannot get their password" negates "get".
                    if following in _HELPERS or following in tx.NEGATIONS:
                        continue
                    negated.add(tx.stem(tx.SYNONYMS.get(following, following)))
                    break
    return negated, set(tx.content_terms(text))


def _polarity_clash(claim_text: str, reference_text: str) -> set[str]:
    """Words one side negates and the other states without a negation."""
    claim_negated, claim_terms = negated_predicates(claim_text)
    ref_negated, ref_terms = negated_predicates(reference_text)
    return (claim_negated & (ref_terms - ref_negated)) | (
        ref_negated & (claim_terms - claim_negated)
    )


def _contradiction(claim, unit: _Unit) -> str | None:
    """A reason the reference contradicts the claim, or None."""
    ref_claim = unit.claim
    shared = claim.subject & ref_claim.subject
    on_topic = bool(claim.subject & unit.topic)
    # Opposite answers about the same thing, whatever else is in the sentence
    # (hedges, time words, or a negation on both sides about different verbs).
    clash = _polarity_clash(claim.text, ref_claim.text)
    if (
        clash
        and len(shared) >= 2
        and tx.jaccard(claim.subject, ref_claim.subject) >= 0.3
        and not (
            claim.levels and ref_claim.levels and not claim.levels & ref_claim.levels
        )
    ):
        return f"The reference says the opposite about {', '.join(sorted(clash))}."
    clash = claim.allowed & ref_claim.denied
    if clash and on_topic:
        return f"The reference excludes {', '.join(sorted(clash))}, which the claim includes."
    clash = claim.denied & ref_claim.allowed
    # A level the reference merely mentions ("enter the member level, even if just
    # a Guest") is not an allowance; it has to talk about the same thing.
    if clash and len(shared) >= 2:
        return f"The reference includes {', '.join(sorted(clash))}, which the claim excludes."
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
    if finding and finding.status == "possible_conflict":
        return f"The reference says otherwise: {finding.explanation}"
    return None


def _uncertain_clash(claim, unit: _Unit) -> str | None:
    """A disagreement too hedged or time-bound to call a contradiction.

    It still rules out "supported": a reference that may say the opposite is
    not support.
    """
    finding = _compare(claim, unit.claim, ConflictConfig())
    # Only hedged or time-bound wording counts here; a clash that is uncertain
    # merely because the claims overlap little is too weak to hold support back.
    if (
        finding
        and finding.status == "unresolved"
        and any(r.startswith(("hedged", "time-bound")) for r in finding.uncertainty)
    ):
        return f"The reference may say otherwise: {finding.explanation}"
    return None


def _claim_result(
    claim, units: Sequence[_Unit], config: VerificationConfig
) -> dict[str, Any]:
    scored = []
    contradictions = []
    uncertain = []
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
        reason = _uncertain_clash(claim, unit)
        if reason:
            uncertain.append(
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
    # The same passage can score once alone and once inside a combined unit;
    # cite each reference once, keeping its best reading.
    citations = []
    cited: set[str] = set()
    for support, reference, _, _ in scored:
        if support < config.partial_threshold or reference["reference_id"] in cited:
            continue
        cited.add(reference["reference_id"])
        citations.append(_citation(reference, support))
        if len(citations) == 3:
            break
    if contradictions:
        status = "contradicted"
    elif best >= config.support_threshold and best > 0 and citations and not uncertain:
        status = "supported"
    elif best >= config.partial_threshold and best > 0 and citations:
        status = "partially_supported"
    else:
        status = "unverifiable"
    missing = {}

    def add_missing(source, condition):
        missing.setdefault(
            (source["reference_id"], condition),
            {
                "reference_id": source["reference_id"],
                "condition": condition,
                "quote": source["text"],
            },
        )

    # Conditions the references attach to what the agent said, that the draft
    # does not state. Recorded actions are outcomes, not statements, so they are
    # not held to this. Conditions can span a heading and its sub-points;
    # membership and quantity comparisons still use individual passages.
    effective_levels = claim.levels | claim.owner.context_levels
    if (
        status in {"supported", "partially_supported"}
        and claim.passage.get("speaker") == "agent"
    ):
        stated = tx.conditions(" ".join([claim.text, *claim.owner.condition_texts]))
        sources = [u for u in units if not u.reference.get("combined_from")]
        for support, reference, ref_claim, _ in scored:
            if support < config.support_threshold:
                continue
            if (
                ref_claim.levels
                and effective_levels
                and not ref_claim.levels & effective_levels
            ):
                continue
            parts = reference.get("combined_from") or [reference["reference_id"]]
            for part in sources:
                if part.reference["reference_id"] not in parts:
                    continue
                if (
                    part.claim.levels
                    and effective_levels
                    and not part.claim.levels & effective_levels
                ):
                    continue
                for condition in sorted(tx.conditions(part.reference["text"]) - stated):
                    add_missing(part.reference, condition)
            if reference.get("combined_from"):
                continue
            if ref_claim.levels and not effective_levels:
                add_missing(
                    reference,
                    f"membership level ({', '.join(sorted(ref_claim.levels))})",
                )
            for unit in sorted(ref_claim.quantities.keys() - claim.quantities.keys()):
                add_missing(
                    reference, f"{unit} limit {sorted(ref_claim.quantities[unit])}"
                )
    return {
        "claim": claim.text,
        "passage": claim.passage,
        "status": status,
        "best_support": round(best, 4),
        "citations": citations,
        "contradicted_by": contradictions,
        "possibly_contradicted_by": uncertain,
        "missing_conditions": list(missing.values()),
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
        if not isinstance(as_of, str):
            raise invalid("as_of", "must be an ISO date string (YYYY-MM-DD)")
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
    try:
        for item in (conflicts or {}).get("possible_conflicts", []):
            affected = set(item.get("affected_draft_ids", [])) | {
                item[side].get("draft_id") for side in ("a", "b")
            }
            for draft_id in affected:
                if draft_id:
                    conflicts_of.setdefault(draft_id, []).append(
                        {
                            "conflict_id": item["conflict_id"],
                            "status": item["status"],
                            "kind": item["kind"],
                            "explanation": item["explanation"],
                        }
                    )
    except (KeyError, TypeError, AttributeError) as error:
        raise invalid("conflicts", "must be the output of find_conflicts") from error

    packets = []
    for owner, draft in zip(owners, drafts, strict=True):
        # Another company's references are never looked at, not even to list them.
        in_scope = [
            r
            for r in checked
            if r.get("company_id") == company_id and _applies(r, owner.scope)
        ]
        usable, ignored = [], []
        for reference in in_scope:
            reason = _ineligible(reference, company_id, as_of_date) or _framing(
                reference
            )
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
        if draft.get("wording") == "model" and (
            any(
                tx.normalise(draft[field])
                != tx.normalise(
                    " ".join(p["quote"] for p in draft[f"{field}_passages"])
                )
                for field in ("question", "answer")
            )
            or any(
                tx.normalise(c["text"]) != tx.normalise(c["passage"]["quote"])
                for c in draft.get("conditions", [])
            )
        ):
            packets[-1].update(
                verification_status="unverifiable",
                ml_recommendation="cannot_be_verified",
            )
            packets[-1]["requirements_remaining"].insert(
                0,
                "Review the rewritten model wording; exact source quotes do not verify a paraphrase.",
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
        for doubt in claim["possibly_contradicted_by"]:
            requirements.append(
                f"Check whether {doubt['reference_id']} contradicts: {claim['claim']!r}"
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
    # Any open conflict, resolved or not, keeps a draft from being recommended.
    blocking = any(c["missing_conditions"] for c in claims) or bool(draft_conflicts)
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
