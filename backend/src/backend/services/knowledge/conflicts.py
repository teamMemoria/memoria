"""Show where drafts may disagree with each other or with existing knowledge (#18).

``find_conflicts(drafts, company_id, existing_entries=..., groups=...)``
compares the claims of drafts in the same company and scope with each other
and with the existing entries the backend supplies. It reports:

* ``possible_conflicts`` -- both exact passages with their sources and
  versions, the conditions that were compared, a short explanation, and a
  status: ``possible_conflict`` when the claims look incompatible under the
  same conditions, ``unresolved`` when they might be but the evidence is
  uncertain (hedged wording, time-bound statements, partial overlap);
* ``explained_differences`` -- pairs that look contradictory but are
  explained by different conditions or an explicit exception. They are kept
  visible because a reviewer may still want to see them.

Missing evidence is never a conflict: if only one side states a figure or a
condition, nothing is reported. This module only reports. It does not mark
entries disputed, remove them from use, replace them or touch earlier audits;
an authorized person decides that through the backend.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass, field
from typing import Any

from . import text as tx
from .errors import PipelineError, invalid
from .grouping import MAX_DRAFTS, MAX_EXISTING_ENTRIES, scope_key

CONFLICTS_SCHEMA_VERSION = "knowledge-conflicts/1"
MEMBER_LEVELS = frozenset({"gold", "silver", "bronze"})
ALL_LEVELS = MEMBER_LEVELS | {"guest"}

_HEDGE = re.compile(
    r"\b(i think|i believe|i'?m not (completely |totally |entirely )?sure|not sure|might|maybe|perhaps|possibly"
    r"|probably|usually|typically|generally|normally|sometimes|often|around|about|roughly|approximately)\b",
    re.IGNORECASE,
)
_TIME_BOUND = re.compile(
    r"\b(this (year|month|week)|last (year|month|week)|today|tomorrow|yesterday|right now|currently|at the moment"
    r"|for now|this time)\b|\[DATE\]|\b(19|20)\d\d\b",
    re.IGNORECASE,
)
_EXCEPTION = re.compile(
    r"\b(unless|except(?: for| when| if)?|other than|apart from)\b(?P<rest>[^.;!?]*)",
    re.IGNORECASE,
)
_ONLY_LEVEL = re.compile(
    r"\bonly\b(?:\s+(?:to|for|our|existing|the|a|an))*\s+(?:gold|silver|bronze|guest)s?\b"
    r"|\b(?:gold|silver|bronze|guest)s?(?:\s+members?)?\s+only\b",
    re.IGNORECASE,
)
_ONLY_MEMBERS = re.compile(
    r"\bonly\b.*\bmembers?\b|\bmembers? only\b|\bexisting members?\b", re.IGNORECASE
)
# "If you are a gold, silver or bronze member I can ..." limits it to those levels.
_IF_LEVEL = re.compile(
    r"\bif (you('re| are)|they('re| are)|the customer is) (a |an )?(\w+,? )*(gold|silver|bronze|guest|member)",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class ConflictConfig:
    """Choices the team still has to agree (issue #18).

    ``claim_overlap``: share of subject words two claims need before they are compared.
    ``polarity_overlap``: higher bar for "X" vs "not X" claims, which are easy to over-match.
    ``question_overlap``: drafts are compared only when their questions are about this similar
    (existing entries are always compared within the scope).
    ``scope_level``: as in grouping.
    """

    claim_overlap: float = 0.3
    polarity_overlap: float = 0.5
    question_overlap: float = 0.1
    scope_level: str = "subflow"

    def __post_init__(self) -> None:
        if self.scope_level not in {"flow", "subflow"}:
            raise invalid("config.scope_level", "must be flow or subflow")
        for name in ("claim_overlap", "polarity_overlap", "question_overlap"):
            if not 0.0 <= getattr(self, name) <= 1.0:
                raise invalid(f"config.{name}", "must be between 0 and 1")


@dataclass
class _Owner:
    kind: str  # draft | entry
    owner_id: str
    scope: dict[str, str]
    question_terms: set[str]
    context_levels: set[str]
    condition_texts: list[str]
    info: dict[str, Any]
    claims: list[_Claim] = field(default_factory=list)


@dataclass
class _Claim:
    owner: _Owner
    text: str
    passage: dict[str, Any]
    subject: set[str]
    quantities: dict[str, set[str]]
    negated: bool
    hedged: bool
    time_bound: bool
    levels: set[str]
    allowed: set[str]
    denied: set[str]
    exclusive: bool
    exception_terms: set[str]
    negated_terms: set[str]


def _subject(text: str) -> set[str]:
    drop = {"not", *ALL_LEVELS, "member"}
    return {t for t in tx.content_terms(text) if t not in drop and not t.isdigit()}


# Verbs that make a negation about eligibility ("cannot get", "can't help",
# "not eligible") rather than about something else ("not valid", "not charged").
_ELIGIBILITY_TERMS = {
    "get",
    "receiv",
    "help",
    "issu",
    "return",
    "refund",
    "qualif",
    "qualify",
    "eligibl",
    "allow",
    "use",
    "offer",
    "provid",
    "giv",
    "give",
    "new",
    "extension",
    "ship",
    "cancel",
    "do",
    "can",
}
_PARTS = re.compile(r"\s*(?:>|;|(?<=[.!?])\s+)\s*")


def _eligibility(text: str, levels: set[str]) -> tuple[set[str], set[str]]:
    """Membership levels a statement allows and denies, part by part.

    "Gold, Silver and Bronze all qualify. > ... even if the code is not valid ..."
    allows the three levels: the negation is about validity, not about them.
    "Guest > If they are just a regular user, ... you cannot help them" denies guests.
    """
    if not levels:
        return set(), set()
    parts = [p for p in _PARTS.split(text) if p.strip()]
    merged: list[str] = []
    carry = ""
    for part in parts:
        if len(part.split()) <= 2:
            carry += part + " "  # a heading such as "Guest" belongs to what follows it
            continue
        merged.append(carry + part)
        carry = ""
    if carry:
        merged.append(carry)
    allowed: set[str] = set()
    denied: set[str] = set()
    for part in merged:
        part_levels = tx.membership_levels(part) or (
            levels if len(merged) == 1 else set()
        )
        if not part_levels:
            continue
        scope = tx.negated_terms(part, window=5)
        about_eligibility = bool(scope & _ELIGIBILITY_TERMS) or bool(
            re.search(
                r"\b(cannot|can't|can not|unable to|not able to|not eligible|no longer)\b",
                tx.normalise(part),
            )
        )
        if tx.is_negated(part) and about_eligibility:
            denied |= part_levels
        else:
            allowed |= part_levels
    return allowed - denied, denied


def _claim(
    owner: _Owner, text: str, passage: dict[str, Any], from_action: bool
) -> _Claim:
    levels = tx.membership_levels(text)
    negated = tx.is_negated(text)
    exclusive = (
        bool(_ONLY_MEMBERS.search(text))
        # "only" has to be about the level ("only gold members", "members only"),
        # not about something else in the sentence ("if they are only 1 day late").
        or bool(_ONLY_LEVEL.search(text))
        or bool(_IF_LEVEL.search(text))
    )
    if not levels and _ONLY_MEMBERS.search(text):
        levels = set(MEMBER_LEVELS)
    if not levels and from_action:
        # "A promo code has been created." happened for this customer's level.
        levels = set(owner.context_levels)
    allowed, denied = _eligibility(text, levels)
    if exclusive and allowed:
        denied |= ALL_LEVELS - allowed
    quantities: dict[str, set[str]] = {}
    for q in tx.quantities(text):
        quantities.setdefault(q.unit, set()).add(q.value)
    exception_terms: set[str] = set()
    for match in _EXCEPTION.finditer(text):
        exception_terms |= _subject(match.group("rest"))
    return _Claim(
        owner=owner,
        text=text,
        passage=passage,
        subject=_subject(text),
        quantities=quantities,
        negated=negated,
        hedged=bool(_HEDGE.search(text)),
        time_bound=bool(_TIME_BOUND.search(text)),
        levels=levels,
        allowed=allowed,
        denied=denied,
        exclusive=exclusive,
        exception_terms=exception_terms,
        negated_terms=tx.negated_terms(text),
    )


def _levels_of(texts: Sequence[str]) -> set[str]:
    found: set[str] = set()
    for text in texts:
        found |= tx.membership_levels(text)
    return found


def _draft_owner(draft: Any, index: int, company_id: str) -> _Owner:
    where = f"drafts[{index}]"
    if not isinstance(draft, Mapping) or draft.get("kind") != "knowledge_draft":
        raise invalid(where, "must be a knowledge draft from extract_drafts")
    if draft.get("company_id") != company_id:
        raise invalid(
            f"{where}.company_id",
            "belongs to another company; knowledge bases never mix",
        )
    passages = draft.get("answer_passages")
    if not isinstance(passages, list) or not passages:
        raise invalid(f"{where}.answer_passages", "must be a non-empty array")
    scope = draft.get("scope")
    if not isinstance(scope, Mapping):
        raise invalid(f"{where}.scope", "must be an object")
    raw_conditions = draft.get("conditions") or []
    if not isinstance(raw_conditions, list):
        raise invalid(f"{where}.conditions", "must be an array")
    conditions = [
        c["text"]
        for c in raw_conditions
        if isinstance(c, Mapping) and isinstance(c.get("text"), str)
    ]
    source = draft.get("source")
    if not isinstance(source, Mapping) or not isinstance(source.get("source_key"), str):
        raise invalid(f"{where}.source.source_key", "is required")
    if not isinstance(draft.get("draft_id"), str) or not draft["draft_id"]:
        raise invalid(f"{where}.draft_id", "must be a non-empty string")
    owner = _Owner(
        kind="draft",
        owner_id=str(draft.get("draft_id")),
        scope={
            "flow": str(scope.get("flow", "")),
            "subflow": str(scope.get("subflow", "")),
        },
        question_terms=_subject(str(draft.get("question", ""))),
        context_levels=_levels_of(conditions),
        condition_texts=conditions,
        info={
            "type": "draft",
            "draft_id": draft.get("draft_id"),
            "status": draft.get("status"),
            "source_key": source.get("source_key"),
            "source_version": source.get("version"),
            "dataset_version": source.get("dataset_version"),
            "reference_status": "unverified draft",
        },
    )
    for passage in passages:
        if not isinstance(passage, Mapping) or not isinstance(
            passage.get("quote"), str
        ):
            raise invalid(f"{where}.answer_passages", "every passage needs a quote")
        owner.claims.append(
            _claim(
                owner,
                passage["quote"],
                dict(passage),
                from_action=passage.get("speaker") == "system_action",
            )
        )
    return owner


def _entry_owner(entry: Any, index: int, company_id: str) -> _Owner | None:
    where = f"existing_entries[{index}]"
    if not isinstance(entry, Mapping):
        raise invalid(where, "must be an object")
    for key in ("entry_id", "company_id", "answer"):
        if not isinstance(entry.get(key), str):
            raise invalid(f"{where}.{key}", "must be a string")
    if entry["company_id"] != company_id:
        return None
    scope = entry.get("scope") or {}
    if not isinstance(scope, Mapping):
        raise invalid(f"{where}.scope", "must be an object")
    raw_conditions = entry.get("conditions") or []
    if not isinstance(raw_conditions, list):
        raise invalid(f"{where}.conditions", "must be an array")
    conditions = [
        c if isinstance(c, str) else str(c.get("text", ""))
        for c in raw_conditions
        if isinstance(c, str | Mapping)
    ]
    owner = _Owner(
        kind="entry",
        owner_id=entry["entry_id"],
        scope={
            "flow": str(scope.get("flow", "")),
            "subflow": str(scope.get("subflow", "")),
        },
        question_terms=_subject(str(entry.get("question", ""))),
        context_levels=_levels_of(conditions),
        condition_texts=conditions,
        info={
            "type": "existing_entry",
            "entry_id": entry["entry_id"],
            "status": entry.get("status", "unknown"),
            "version": entry.get("version"),
            "reference_status": entry.get("status", "unknown"),
        },
    )
    answer = entry["answer"]
    for start, end in tx.sentences(answer) or [(0, len(answer))]:
        passage = {
            "entry_id": entry["entry_id"],
            "version": entry.get("version"),
            "span": [start, end],
            "quote": answer[start:end],
        }
        owner.claims.append(
            _claim(owner, answer[start:end], passage, from_action=False)
        )
    return owner


# --------------------------------------------------------------------------- comparison


@dataclass
class _Finding:
    status: str  # possible_conflict | unresolved | explained
    kind: str  # value | polarity | eligibility
    explanation: str
    uncertainty: list[str]


def _overlap(a: _Claim, b: _Claim) -> float:
    return tx.jaccard(a.subject, b.subject) if a.subject and b.subject else 0.0


def _uncertainty(a: _Claim, b: _Claim) -> list[str]:
    reasons = []
    if a.hedged or b.hedged:
        reasons.append("hedged wording (usually / I think / might ...)")
    if a.time_bound or b.time_bound:
        reasons.append(
            "time-bound statement (this year / currently / a date); may differ by date, not by policy"
        )
    return reasons


def _compare(a: _Claim, b: _Claim, config: ConflictConfig) -> _Finding | None:
    overlap = _overlap(a, b)
    shared = len(a.subject & b.subject)
    if shared < 2 or overlap < min(config.claim_overlap, 0.2):
        return None
    uncertain = _uncertainty(a, b)

    # 0. An exception one claim states ("... unless the item was on final sale")
    #    is what the other, negative claim describes: not a disagreement.
    if a.negated != b.negated:
        negative, positive = (a, b) if a.negated else (b, a)
        if positive.exception_terms and positive.exception_terms & negative.subject:
            return _Finding(
                "explained",
                "polarity",
                "The negative claim matches an exception the other claim states (unless / except).",
                [],
            )

    # 1. Eligibility: one side allows a level the other side excludes.
    clash_levels = (a.allowed & b.denied) | (b.allowed & a.denied)
    if clash_levels:
        levels = ", ".join(sorted(clash_levels))
        return _Finding(
            "unresolved" if uncertain else "possible_conflict",
            "eligibility",
            f"One says this applies to {levels}; the other says it does not.",
            uncertain,
        )

    # Members-only on one side and "guests cannot" on the other say the same thing.
    if a.negated != b.negated:
        negative, positive = (a, b) if a.negated else (b, a)
        if (
            positive.exclusive
            and negative.denied
            and negative.denied <= positive.denied
        ):
            return None

    # 2. Values: the same unit with different figures.
    for unit in sorted(a.quantities.keys() & b.quantities.keys()):
        if a.quantities[unit] & b.quantities[unit] or overlap < config.claim_overlap:
            continue
        figures = f"{sorted(a.quantities[unit])} vs {sorted(b.quantities[unit])} {unit}"
        if a.levels and b.levels and not (a.levels & b.levels):
            return _Finding(
                "explained",
                "value",
                f"Different figures ({figures}) for different membership levels "
                f"({sorted(a.levels)} vs {sorted(b.levels)}).",
                [],
            )
        return _Finding(
            "unresolved" if uncertain else "possible_conflict",
            "value",
            f"Different figures for the same thing: {figures}.",
            uncertain,
        )

    # 3. Polarity: "X" vs "not X" about the same thing.
    negative, positive = (a, b) if a.negated else (b, a)
    if (
        a.negated != b.negated
        and overlap >= config.polarity_overlap * 0.6
        # The negation has to be about something the other claim asserts:
        # "you will not be charged" says nothing against "I cancelled the order".
        and negative.negated_terms & positive.subject
    ):
        if a.levels and b.levels and not (a.levels & b.levels):
            return _Finding(
                "explained",
                "polarity",
                f"Opposite answers for different membership levels ({sorted(a.levels)} vs {sorted(b.levels)}).",
                [],
            )
        if overlap < config.polarity_overlap:
            uncertain = [
                *uncertain,
                f"claims only partly overlap ({overlap:.0%} of their subject words)",
            ]
        return _Finding(
            "unresolved" if uncertain else "possible_conflict",
            "polarity",
            "One claim says this is the case and the other says it is not.",
            uncertain,
        )
    return None


def _side(claim: _Claim) -> dict[str, Any]:
    return {
        **claim.owner.info,
        "passage": claim.passage,
        "claim": claim.text,
        "conditions": claim.owner.condition_texts,
    }


def _conditions(claim: _Claim) -> dict[str, Any]:
    return {
        "membership_levels": sorted(claim.levels),
        "allowed_levels": sorted(claim.allowed),
        "excluded_levels": sorted(claim.denied),
        "quantities": {u: sorted(v) for u, v in sorted(claim.quantities.items())},
        "negative": claim.negated,
        "exceptions": sorted(claim.exception_terms),
    }


def _conflict_id(company_id: str, a: _Claim, b: _Claim) -> str:
    key = sorted(
        [
            [
                a.owner.owner_id,
                json.dumps([a.passage.get("turn_id"), a.passage.get("span")]),
            ],
            [
                b.owner.owner_id,
                json.dumps([b.passage.get("turn_id"), b.passage.get("span")]),
            ],
        ]
    )
    return (
        "conflict_"
        + hashlib.sha256(json.dumps([company_id, key]).encode()).hexdigest()[:20]
    )


def find_conflicts(
    drafts: Any,
    company_id: str,
    existing_entries: Any = (),
    groups: Mapping[str, Any] | None = None,
    config: ConflictConfig | None = None,
) -> dict[str, Any]:
    """Compare one company's drafts and existing entries. Raises ``PipelineError`` on bad input."""
    config = config or ConflictConfig()
    if not isinstance(company_id, str) or not company_id:
        raise invalid("company_id", "must be a non-empty string")
    if not isinstance(drafts, list | tuple) or not isinstance(
        existing_entries, list | tuple
    ):
        raise invalid("drafts", "drafts and existing_entries must be arrays")
    # The same limits as grouping, so a batch that groups also gets compared.
    if len(drafts) > MAX_DRAFTS:
        raise PipelineError(
            "oversized_input", f"more than {MAX_DRAFTS} drafts in one call", "drafts"
        )
    if len(existing_entries) > MAX_EXISTING_ENTRIES:
        raise PipelineError(
            "oversized_input",
            f"more than {MAX_EXISTING_ENTRIES} entries in one call",
            "existing_entries",
        )
    owners: dict[str, _Owner] = {}
    for index, draft in enumerate(drafts):
        owner = _draft_owner(draft, index, company_id)
        owners.setdefault(owner.owner_id, owner)
    entries = [
        o
        for i, e in enumerate(existing_entries)
        if (o := _entry_owner(e, i, company_id))
    ]
    group_of: dict[str, str] = {}
    if groups is not None:
        if not isinstance(groups, Mapping) or not isinstance(
            groups.get("groups", []), list
        ):
            raise invalid("groups", "must be the output of group_drafts")
        for group in groups.get("groups", []):
            if not isinstance(group, Mapping) or not isinstance(
                group.get("group_id"), str
            ):
                raise invalid("groups", "every group needs a group_id")
            for draft_id in group.get("member_draft_ids", []):
                group_of[draft_id] = group["group_id"]

    buckets: dict[tuple[str, ...], list[_Owner]] = {}
    for owner in [*sorted(owners.values(), key=lambda o: o.owner_id), *entries]:
        buckets.setdefault(
            scope_key(owner.scope, company_id, config.scope_level), []
        ).append(owner)

    conflicts: list[dict[str, Any]] = []
    explained: list[dict[str, Any]] = []
    for key in sorted(buckets):
        members = buckets[key]
        for i, first in enumerate(members):
            for second in members[i + 1 :]:
                if first.kind == "entry" and second.kind == "entry":
                    continue  # existing knowledge against itself is not this pipeline's job
                if (
                    first.kind == second.kind == "draft"
                    and tx.jaccard(first.question_terms, second.question_terms)
                    < config.question_overlap
                ):
                    continue
                if (
                    first.kind == second.kind == "draft"
                    and first.info["source_key"] == second.info["source_key"]
                ):
                    continue  # one conversation read twice does not disagree with itself
                for a in first.claims:
                    for b in second.claims:
                        finding = _compare(a, b, config)
                        if finding is None:
                            continue
                        record = {
                            "conflict_id": _conflict_id(company_id, a, b),
                            "company_id": company_id,
                            "scope": dict(first.scope),
                            "kind": finding.kind,
                            "status": finding.status
                            if finding.status != "explained"
                            else "explained_difference",
                            "explanation": finding.explanation,
                            "uncertainty": finding.uncertainty,
                            "a": {**_side(a), "group_id": group_of.get(first.owner_id)},
                            "b": {
                                **_side(b),
                                "group_id": group_of.get(second.owner_id),
                            },
                            "compared_conditions": {
                                "a": _conditions(a),
                                "b": _conditions(b),
                            },
                            "subject_overlap": round(_overlap(a, b), 4),
                        }
                        (
                            explained if finding.status == "explained" else conflicts
                        ).append(record)
    conflicts.sort(key=lambda c: (c["status"] != "possible_conflict", c["conflict_id"]))
    explained.sort(key=lambda c: c["conflict_id"])
    return {
        "schema": CONFLICTS_SCHEMA_VERSION,
        "status": "ok",
        "company_id": company_id,
        "config": asdict(config),
        "possible_conflicts": conflicts,
        "explained_differences": explained,
        "note": (
            "Possible conflicts are for an authorized reviewer. This step does not mark entries disputed, "
            "remove them from use, replace them or change earlier audits."
        ),
    }
