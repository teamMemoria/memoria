"""Group related drafts and find duplicates, without treating repetition as truth (#17).

``group_drafts(drafts, existing_entries, config)`` returns groups of drafts that
answer the same question in the same scope under compatible conditions, the
duplicates inside each group, and matches against knowledge that already
exists. It never merges text: every group keeps its original drafts and
passages, and its representative is one of those drafts, unchanged and still
unapproved.

Counts are of **distinct source conversations** (``source_key``), not drafts
or turns, so reprocessing a conversation, or reading it from both the curated
and the raw ABCD file, never raises a count. A count, a similarity score or a
match with an approved entry is not verification; ``meets_source_threshold``
only says whether a group has enough independent conversations to be worth a
reviewer's time.
"""

from __future__ import annotations

import hashlib
import json
import math
from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import asdict, dataclass, field
from typing import Any

from . import text as tx
from .errors import PipelineError, invalid

GROUPING_SCHEMA_VERSION = "knowledge-groups/1"
MAX_DRAFTS = 5_000
MAX_EXISTING_ENTRIES = 20_000


@dataclass(frozen=True)
class GroupingConfig:
    """Thresholds the team still has to agree (issue #17). None of them is an approval rule.

    ``group_threshold``: similarity at which a draft joins a group.
    ``duplicate_threshold``: similarity at which two drafts are duplicates.
    ``existing_match_threshold``: similarity at which a group is shown next to an existing entry.
    ``scope_level``: "subflow" (default) or "flow"; drafts only group within one scope.
    ``min_distinct_conversations``: how many distinct conversations a group needs before
    ``meets_source_threshold`` is true. Repetition is not evidence that an answer is right.
    """

    group_threshold: float = 0.25
    duplicate_threshold: float = 0.8
    existing_match_threshold: float = 0.45
    scope_level: str = "subflow"
    min_distinct_conversations: int = 3
    question_weight: float = 0.4

    def __post_init__(self) -> None:
        if self.scope_level not in {"flow", "subflow"}:
            raise invalid("config.scope_level", "must be flow or subflow")
        for name in (
            "group_threshold",
            "duplicate_threshold",
            "existing_match_threshold",
            "question_weight",
        ):
            value = getattr(self, name)
            if not 0.0 <= value <= 1.0:
                raise invalid(f"config.{name}", "must be between 0 and 1")
        if self.min_distinct_conversations < 1:
            raise invalid("config.min_distinct_conversations", "must be at least 1")


# --------------------------------------------------------------------------- items


@dataclass
class _Item:
    """A draft or an existing entry, reduced to what grouping compares."""

    item_id: str
    company_id: str
    scope: dict[str, str]
    question: str
    answer: str
    condition_text: str
    source_key: str | None = None
    status: str | None = None
    version: str | None = None
    answer_sentences: list[str] = field(default_factory=list)
    q_vec: dict[str, float] = field(default_factory=dict)
    a_vec: dict[str, float] = field(default_factory=dict)
    s_vecs: list[dict[str, float]] = field(default_factory=list)

    @property
    def levels(self) -> set[str]:
        return tx.membership_levels(self.condition_text)

    @property
    def quantities(self) -> set[tuple[str, str]]:
        return {(q.unit, q.value) for q in tx.quantities(self.condition_text)}


def scope_key(scope: Mapping[str, str], company_id: str, level: str) -> tuple[str, ...]:
    if level == "flow":
        return (company_id, scope.get("flow", ""))
    return (company_id, scope.get("flow", ""), scope.get("subflow", ""))


def _require(mapping: Mapping[str, Any], key: str, where: str) -> Any:
    if key not in mapping:
        raise invalid(f"{where}.{key}", "is required")
    return mapping[key]


def _draft_item(draft: Any, index: int, company_id: str) -> _Item:
    where = f"drafts[{index}]"
    if not isinstance(draft, Mapping):
        raise invalid(where, "must be an object")
    if draft.get("kind") != "knowledge_draft" or draft.get("status") != "draft":
        raise invalid(
            where, "must be a knowledge draft from extract_drafts (status 'draft')"
        )
    if draft.get("company_id") != company_id:
        raise invalid(
            f"{where}.company_id",
            "belongs to another company; knowledge bases never mix",
        )
    scope = _require(draft, "scope", where)
    if not isinstance(scope, Mapping) or not all(
        isinstance(scope.get(k), str) for k in ("flow", "subflow")
    ):
        raise invalid(f"{where}.scope", "must have flow and subflow")
    source = _require(draft, "source", where)
    if not isinstance(source, Mapping) or not isinstance(source.get("source_key"), str):
        raise invalid(f"{where}.source.source_key", "is required")
    for key in ("draft_id", "question", "answer"):
        if not isinstance(draft.get(key), str) or not draft[key]:
            raise invalid(f"{where}.{key}", "must be a non-empty string")
    conditions = draft.get("conditions", [])
    condition_text = " ".join(
        c.get("text", "")
        for c in conditions
        if isinstance(c, Mapping) and isinstance(c.get("text"), str)
    )
    return _Item(
        item_id=draft["draft_id"],
        company_id=company_id,
        scope={"flow": scope["flow"], "subflow": scope["subflow"]},
        question=draft["question"],
        answer=draft["answer"],
        condition_text=condition_text,
        source_key=source["source_key"],
        answer_sentences=[
            p["quote"]
            for p in draft.get("answer_passages", [])
            if isinstance(p, Mapping) and isinstance(p.get("quote"), str)
        ]
        or [draft["answer"]],
    )


def _entry_item(entry: Any, index: int, company_id: str) -> _Item | None:
    where = f"existing_entries[{index}]"
    if not isinstance(entry, Mapping):
        raise invalid(where, "must be an object")
    for key in ("entry_id", "company_id", "question", "answer"):
        if not isinstance(entry.get(key), str):
            raise invalid(f"{where}.{key}", "must be a string")
    if entry["company_id"] != company_id:
        return None  # another company's knowledge is never compared
    scope = entry.get("scope") or {}
    if not isinstance(scope, Mapping):
        raise invalid(f"{where}.scope", "must be an object")
    conditions = entry.get("conditions", [])
    condition_text = " ".join(
        c if isinstance(c, str) else c.get("text", "")
        for c in conditions
        if isinstance(c, str | Mapping)
    )
    return _Item(
        item_id=entry["entry_id"],
        company_id=company_id,
        scope={
            "flow": str(scope.get("flow", "")),
            "subflow": str(scope.get("subflow", "")),
        },
        question=entry["question"],
        answer=entry["answer"],
        condition_text=condition_text,
        answer_sentences=[
            entry["answer"][a:b] for a, b in tx.sentences(entry["answer"])
        ]
        or [entry["answer"]],
        status=str(entry.get("status", "unknown")),
        version=str(entry["version"]) if entry.get("version") is not None else None,
    )


# --------------------------------------------------------------------------- similarity


def _vectorise(items: Sequence[_Item]) -> None:
    """TF-IDF vectors for question and answer, with IDF over everything compared together."""

    def terms(text: str) -> Counter[str]:
        # Quantities as tokens, so "one week" and "7 days" count as the same words.
        counts = Counter(tx.content_terms(text))
        counts.update(f"<{q.value}_{q.unit}>" for q in tx.quantities(text))
        return counts

    docs: list[Counter[str]] = []
    for item in items:
        docs.append(Counter(tx.content_terms(item.question)))
        docs.append(terms(item.answer))
    df: Counter[str] = Counter()
    for doc in docs:
        df.update(doc.keys())
    n = max(1, len(docs))

    def vec(counts: Counter[str]) -> dict[str, float]:
        weights = {
            t: (1 + math.log(c)) * (math.log((1 + n) / (1 + df[t])) + 1)
            for t, c in counts.items()
        }
        norm = math.sqrt(sum(w * w for w in weights.values())) or 1.0
        return {t: w / norm for t, w in weights.items()}

    for i, item in enumerate(items):
        item.q_vec = vec(docs[2 * i])
        item.a_vec = vec(docs[2 * i + 1])
        item.s_vecs = [v for v in (vec(terms(s)) for s in item.answer_sentences) if v]


def _cos(a: Mapping[str, float], b: Mapping[str, float]) -> float:
    if len(a) > len(b):
        a, b = b, a
    return sum(w * b.get(t, 0.0) for t, w in a.items())


def _aligned(
    a: Sequence[Mapping[str, float]], b: Sequence[Mapping[str, float]]
) -> float:
    """How well each sentence of one answer is matched by some sentence of the other.

    Real answers carry filler around the part that matters; matching sentence
    by sentence stops the filler from hiding two answers that say the same thing.
    """
    if not a or not b:
        return 0.0
    forward = sum(max(_cos(x, y) for y in b) for x in a) / len(a)
    backward = sum(max(_cos(x, y) for x in a) for y in b) / len(b)
    return (forward + backward) / 2


def similarity(a: _Item, b: _Item, config: GroupingConfig) -> float:
    w = config.question_weight
    answer = max(_cos(a.a_vec, b.a_vec), _aligned(a.s_vecs, b.s_vecs))
    return round(w * _cos(a.q_vec, b.q_vec) + (1 - w) * answer, 6)


def conditions_compatible(a: _Item, b: _Item) -> tuple[bool, str | None]:
    """Whether two items can share a group. Returns (ok, reason when not)."""
    if a.levels and b.levels and not (a.levels & b.levels):
        return False, f"membership {sorted(a.levels)} vs {sorted(b.levels)}"
    if bool(a.levels) != bool(b.levels):
        # An answer that depends on membership is not the same answer as one that
        # does not mention it, even when the wording is close.
        return False, "only one depends on membership level"
    units_a: dict[str, set[str]] = {}
    for unit, value in a.quantities:
        units_a.setdefault(unit, set()).add(value)
    units_b: dict[str, set[str]] = {}
    for unit, value in b.quantities:
        units_b.setdefault(unit, set()).add(value)
    for unit in units_a.keys() & units_b.keys():
        if not units_a[unit] & units_b[unit]:
            return False, f"{unit} {sorted(units_a[unit])} vs {sorted(units_b[unit])}"
    return True, None


# --------------------------------------------------------------------------- grouping


def _group_id(company_id: str, members: Iterable[str]) -> str:
    key = json.dumps([company_id, sorted(members)])
    return "group_" + hashlib.sha256(key.encode("utf-8")).hexdigest()[:20]


def _cluster(items: list[_Item], config: GroupingConfig) -> list[list[_Item]]:
    """Greedy average-link clustering in draft-id order, with a compatibility veto."""
    groups: list[list[_Item]] = []
    for item in sorted(items, key=lambda i: i.item_id):
        best: tuple[float, int] | None = None
        for index, group in enumerate(groups):
            if not all(conditions_compatible(item, member)[0] for member in group):
                continue
            score = sum(similarity(item, member, config) for member in group) / len(
                group
            )
            if score >= config.group_threshold and (best is None or score > best[0]):
                best = (score, index)
        if best is None:
            groups.append([item])
        else:
            groups[best[1]].append(item)
    return groups


def _representative(group: Sequence[_Item], config: GroupingConfig) -> _Item:
    if len(group) == 1:
        return group[0]

    def centrality(item: _Item) -> tuple[float, str]:
        others = [
            similarity(item, other, config) for other in group if other is not item
        ]
        return (-sum(others) / len(others), item.item_id)

    return min(group, key=centrality)


def group_drafts(
    drafts: Any,
    company_id: str,
    existing_entries: Any = (),
    config: GroupingConfig | None = None,
) -> dict[str, Any]:
    """Group one company's drafts. Raises ``PipelineError`` on invalid input."""
    config = config or GroupingConfig()
    if not isinstance(company_id, str) or not company_id:
        raise invalid("company_id", "must be a non-empty string")
    if not isinstance(drafts, list | tuple):
        raise invalid("drafts", "must be an array")
    if len(drafts) > MAX_DRAFTS:
        raise PipelineError(
            "oversized_input",
            f"has {len(drafts)} drafts; the limit is {MAX_DRAFTS}",
            "drafts",
        )
    if not isinstance(existing_entries, list | tuple):
        raise invalid("existing_entries", "must be an array")
    if len(existing_entries) > MAX_EXISTING_ENTRIES:
        raise PipelineError(
            "oversized_input",
            f"has {len(existing_entries)} entries; the limit is {MAX_EXISTING_ENTRIES}",
            "existing_entries",
        )

    by_id: dict[str, _Item] = {}
    payload: dict[str, Mapping[str, Any]] = {}
    for index, draft in enumerate(drafts):
        item = _draft_item(draft, index, company_id)
        # The same draft id twice is the same draft reprocessed; it is kept once.
        if item.item_id not in by_id:
            by_id[item.item_id] = item
            payload[item.item_id] = draft
    entries = [
        e
        for i, raw in enumerate(existing_entries)
        if (e := _entry_item(raw, i, company_id))
    ]
    items = list(by_id.values())
    _vectorise([*items, *entries])

    buckets: dict[tuple[str, ...], list[_Item]] = {}
    for item in items:
        buckets.setdefault(
            scope_key(item.scope, company_id, config.scope_level), []
        ).append(item)

    groups_out = []
    for key in sorted(buckets):
        for group in _cluster(buckets[key], config):
            groups_out.append(
                _describe(group, entries, payload, company_id, key, config)
            )
    groups_out.sort(
        key=lambda g: (g["scope_key"], -g["distinct_conversation_count"], g["group_id"])
    )
    return {
        "schema": GROUPING_SCHEMA_VERSION,
        "status": "ok",
        "company_id": company_id,
        "config": asdict(config),
        "draft_count": len(items),
        "duplicate_input_drafts": len(drafts) - len(items),
        "groups": groups_out,
        "note": "Groups, counts and matches are review aids. None of them verifies or approves an answer.",
    }


def _describe(
    group: list[_Item],
    entries: Sequence[_Item],
    payload: Mapping[str, Mapping[str, Any]],
    company_id: str,
    key: tuple[str, ...],
    config: GroupingConfig,
) -> dict[str, Any]:
    representative = _representative(group, config)
    members = sorted(group, key=lambda i: i.item_id)
    duplicates = []
    for i, a in enumerate(members):
        for b in members[i + 1 :]:
            score = similarity(a, b, config)
            exact = tx.normalise(a.answer) == tx.normalise(b.answer) and tx.normalise(
                a.question
            ) == tx.normalise(b.question)
            same_conditions = a.levels == b.levels and a.quantities == b.quantities
            if exact or (score >= config.duplicate_threshold and same_conditions):
                duplicates.append(
                    {
                        "draft_id": b.item_id,
                        "duplicate_of": a.item_id,
                        "similarity": score,
                        "kind": "exact" if exact else "near",
                        "same_conversation": a.source_key == b.source_key,
                    }
                )
    source_keys = sorted({m.source_key for m in members if m.source_key})
    matches = []
    for entry in entries:
        if scope_key(entry.scope, company_id, config.scope_level) != key:
            continue
        ok, reason = conditions_compatible(representative, entry)
        score = max(similarity(m, entry, config) for m in members)
        if score < config.existing_match_threshold:
            continue
        matches.append(
            {
                "entry_id": entry.item_id,
                "entry_status": entry.status,
                "entry_version": entry.version,
                "similarity": score,
                "kind": (
                    "equivalent" if score >= config.duplicate_threshold else "related"
                )
                if ok
                else "different_conditions",
                "condition_difference": reason,
            }
        )
    matches.sort(key=lambda m: (-m["similarity"], m["entry_id"]))
    rep = payload[representative.item_id]
    return {
        "group_id": _group_id(company_id, [m.item_id for m in members]),
        "company_id": company_id,
        "scope": dict(representative.scope),
        "scope_key": "/".join(key[1:]),
        "status": "draft",
        "member_draft_ids": [m.item_id for m in members],
        "representative_draft_id": representative.item_id,
        "representative": {
            "draft_id": representative.item_id,
            "question": rep["question"],
            "answer": rep["answer"],
            "question_passages": rep.get("question_passages", []),
            "answer_passages": rep.get("answer_passages", []),
            "conditions": rep.get("conditions", []),
            "status": "draft",
        },
        "draft_count": len(members),
        "distinct_conversation_count": len(source_keys),
        "source_keys": source_keys,
        "meets_source_threshold": len(source_keys) >= config.min_distinct_conversations,
        "membership_levels": sorted(set().union(*(m.levels for m in members))),
        "duplicates": duplicates,
        "existing_matches": matches,
    }
