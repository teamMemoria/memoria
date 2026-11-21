"""Test inferred knowledge with the guidelines hidden.

The knowledge base is learned from the ABCD ``train`` calls only, from what
agents said, with system actions left out (see ``fact_claims.py``). The ABCD
guidelines are never read while learning. Only afterwards are the rules
compared with the guideline passages that state a value, which act as the
answer key:

* precision: of the rules in categories the guidelines cover, how many give a
  value the guidelines give for that category;
* recall: of the values the guidelines give, how many became rules. A second
  recall only counts values agents actually said at least once, since nothing
  can be learned from a value nobody says;
* growth: the same numbers with more and more calls, to show Layer 2 improving
  while Layer 1 stays fixed;
* held-out scoring: the ABCD ``test`` calls scored against the final rules.

Matching is on category and value only. It is a simple check, not proof that
two sentences mean the same thing, so the report lists every rule with the
guideline passage it matched for a person to read.
"""

from __future__ import annotations

import gzip
import json
from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
from pathlib import Path
from typing import Any

from backend.entities.inferred_knowledge import (
    FactClaim,
    InferenceSettings,
    KnowledgeBase,
    Rule,
    build_knowledge_base,
    score_call,
)

from .fact_claims import ConversationClaimSource, normalise_value
from .text import membership_levels, quantities

EVALUATION_SCHEMA = "inferred-knowledge-evaluation/1"
COMPANY = "acme-eval"
GROWTH_SIZES = (500, 1000, 2000, 4000, 8000)


def read_abcd_dump(path: Path) -> dict[str, list[dict[str, Any]]]:
    """The full ABCD v1.1 file (``abcd_v1.1.json`` or ``.json.gz``), by split."""
    opener = gzip.open if str(path).endswith(".gz") else open
    with opener(path, "rt", encoding="utf-8") as handle:
        data = json.load(handle)
    if not all(isinstance(data.get(s), list) for s in ("train", "dev", "test")):
        raise ValueError("expected the ABCD v1.1 file with train, dev and test splits")
    return data


def answer_key(
    snapshot: Mapping[str, Any], categories: Iterable[str]
) -> dict[str, list[dict[str, str]]]:
    """Values the guidelines give, per category: the hidden answer key."""
    categories = sorted(set(categories))
    key: dict[str, list[dict[str, str]]] = defaultdict(list)
    for passage in snapshot["passages"]:
        found = quantities(passage["text"])
        if not found:
            continue
        scope = passage["scope"]
        if "subflow" in scope:
            applies = [scope["subflow"]] if scope["subflow"] in categories else []
        else:
            applies = [c for c in categories if c.startswith(scope["subflow_prefix"])]
        levels = sorted(membership_levels(passage["text"]))
        for category in applies:
            for value in sorted({normalise_value(q) for q in found}):
                key[category].append(
                    {
                        "value": value,
                        "levels": levels,
                        "reference_id": passage["reference_id"],
                        "text": passage["text"],
                    }
                )
    return dict(key)


def _claims_by_call(records: Sequence[Mapping[str, Any]]) -> list[list[FactClaim]]:
    """Claims for each call, in the order the calls are given."""
    out = []
    for record in records:
        out.append(ConversationClaimSource([record]).claims(COMPANY))
    return out


def _key_values(key: Mapping[str, list[dict[str, str]]]) -> set[tuple[str, str]]:
    return {
        (category, item["value"]) for category, items in key.items() for item in items
    }


def _guideline_matches(
    rule: Rule, key: Mapping[str, list[dict[str, Any]]]
) -> list[dict]:
    """Guideline passages in the rule's category giving the rule's value.

    If the rule names membership levels, the passage has to name them too, so
    "silver: 30 days" doesn't match a passage about guests. A rule with no
    levels can match any passage with its value.
    """
    return [
        item
        for item in key.get(rule.topic.category, [])
        if item["value"] == rule.value and set(rule.topic.levels) <= set(item["levels"])
    ]


def _measure(
    kb: KnowledgeBase,
    key: Mapping[str, list[dict[str, str]]],
    said: set[tuple[str, str]],
) -> dict[str, Any]:
    expected = _key_values(key)
    checkable = [r for r in kb.rules if r.topic.category in key]
    correct = [r for r in checkable if _guideline_matches(r, key)]
    learned = {(r.topic.category, r.value) for r in correct}
    reachable = expected & said
    return {
        "calls_with_values": kb.calls_with_values,
        "rules": len(kb.rules),
        "conflicts": len(kb.conflicts),
        "undecided": len(kb.undecided),
        "checkable_rules": len(checkable),
        "correct_rules": len(correct),
        "precision": round(len(correct) / len(checkable), 4) if checkable else None,
        "answer_key_values": len(expected),
        "found_values": len(expected & learned),
        "recall": round(len(expected & learned) / len(expected), 4)
        if expected
        else None,
        "values_said_in_train": len(reachable),
        "recall_of_said": round(len(reachable & learned) / len(reachable), 4)
        if reachable
        else None,
    }


def _rule_rows(
    kb: KnowledgeBase, key: Mapping[str, list[dict[str, str]]]
) -> list[dict[str, Any]]:
    rows = []
    for rule in sorted(kb.rules, key=lambda r: (r.topic.category, r.value)):
        matches = _guideline_matches(rule, key)
        rows.append(
            {
                "category": rule.topic.category,
                "levels": list(rule.topic.levels),
                "value": rule.value,
                "share": rule.share,
                "calls": rule.topic.total_calls,
                "example": next(
                    (a.example for a in rule.topic.answers if a.value == rule.value), ""
                ),
                "guideline": (
                    "no answer key for this category"
                    if rule.topic.category not in key
                    else ("matches" if matches else "not in the guidelines")
                ),
                "guideline_passage": matches[0]["text"] if matches else None,
            }
        )
    return rows


def _held_out(
    kb: KnowledgeBase, test_claims: Sequence[list[FactClaim]]
) -> dict[str, Any]:
    scores = [
        score_call(COMPANY, claims[0].call_id, claims, kb)
        for claims in test_claims
        if claims
    ]
    covered = [s for s in scores if s.score is not None]
    return {
        "test_calls": len(test_claims),
        "calls_with_values": len(scores),
        "calls_checked_against_a_rule": len(covered),
        "values_matching_a_rule": sum(s.matches for s in scores),
        "values_differing_from_a_rule": sum(s.differences for s in scores),
        "values_without_a_rule": sum(
            len(s.checked) - s.matches - s.differences for s in scores
        ),
        "average_call_score": (
            round(sum(s.score for s in covered) / len(covered), 4) if covered else None
        ),
    }


def evaluate_inferred(
    dump: Mapping[str, list[dict[str, Any]]],
    snapshot: Mapping[str, Any],
    settings: InferenceSettings | None = None,
    sizes: Sequence[int] = GROWTH_SIZES,
) -> dict[str, Any]:
    settings = settings or InferenceSettings()
    train = _claims_by_call(dump["train"])
    test = _claims_by_call(dump["test"])
    all_train = [c for claims in train for c in claims]
    key = answer_key(snapshot, {c.category for c in all_train})
    said = {(c.category, c.value) for c in all_train}

    growth = []
    kb = None
    for n in [n for n in sizes if n < len(train)] + [len(train)]:
        claims = [c for call in train[:n] for c in call]
        kb = build_knowledge_base(COMPANY, claims, settings, previous=kb)
        growth.append({"train_calls": n, **_measure(kb, key, said)})

    return {
        "schema": EVALUATION_SCHEMA,
        "note": (
            "Learned from ABCD train calls, from agent speech only. The guidelines and the recorded "
            "system actions were not used while learning; the guidelines are only the answer key."
        ),
        "settings": vars(settings).copy(),
        "guidelines_used_for_learning": False,
        "answer_key": {
            "categories": len(key),
            "values": len(_key_values(key)),
            "source": snapshot.get("snapshot_id"),
        },
        "growth": growth,
        "final": growth[-1],
        "held_out": _held_out(kb, test),
        "rules": _rule_rows(kb, key),
        "conflicts": [
            {
                "category": c.topic.category,
                "levels": list(c.topic.levels),
                "calls": c.topic.total_calls,
                "answers": [
                    {"value": a.value, "calls": a.calls} for a in c.topic.answers[:5]
                ],
                "example": c.topic.answers[0].example,
            }
            for c in kb.conflicts
        ],
    }


def _pct(value: float | None) -> str:
    return "n/a" if value is None else f"{value * 100:.0f}%"


def render_markdown(report: Mapping[str, Any]) -> str:
    final, held = report["final"], report["held_out"]
    lines = [
        "# Inferred knowledge (Layer 2): hidden-guidelines test",
        "",
        "Generated by `python -m backend.services.knowledge evaluate-inferred`. Do not edit by hand.",
        "",
        report["note"],
        "",
        f"Settings: {report['settings']}",
        "",
        "## Result",
        "",
        (
            f"- {final['rules']} rules learned from {final['train_calls']} calls, "
            f"{final['conflicts']} conflicts for a manager, {final['undecided']} topics still undecided."
        ),
        (
            f"- Precision: {_pct(final['precision'])} ({final['correct_rules']} of "
            f"{final['checkable_rules']} rules in categories the guidelines cover give a guideline value). "
            f"The other {final['rules'] - final['checkable_rules']} rules are in categories where the "
            "guidelines don't state values (mostly FAQ answers), so they can't be checked; read them below."
        ),
        (
            f"- Recall: {_pct(final['recall'])} of the {final['answer_key_values']} values in the guidelines; "
            f"{_pct(final['recall_of_said'])} of the {final['values_said_in_train']} that agents said "
            "at least once anywhere in the train calls."
        ),
        "",
        "## Growth",
        "",
        "| Calls | Rules | Conflicts | Precision | Recall | Recall of values said in train |",
        "|---|---|---|---|---|---|",
    ]
    for row in report["growth"]:
        lines.append(
            f"| {row['train_calls']} | {row['rules']} | {row['conflicts']} | {_pct(row['precision'])} | "
            f"{_pct(row['recall'])} | {_pct(row['recall_of_said'])} |"
        )
    lines += [
        "",
        "## Held-out calls scored against the rules",
        "",
        (
            f"- {held['test_calls']} test calls; {held['calls_with_values']} gave at least one value; "
            f"{held['calls_checked_against_a_rule']} had a value a rule covers."
        ),
        (
            f"- Values matching a rule: {held['values_matching_a_rule']}. Differing: "
            f"{held['values_differing_from_a_rule']}. No rule yet: {held['values_without_a_rule']}."
        ),
        f"- Average call score: {_pct(held['average_call_score'])}.",
        "",
        "## Rules",
        "",
        "| Category | Levels | Value | Share | Calls | Guidelines | Example |",
        "|---|---|---|---|---|---|---|",
    ]
    for row in report["rules"]:
        example = row["example"].replace("|", "/")[:90]
        lines.append(
            f"| {row['category']} | {', '.join(row['levels']) or '-'} | {row['value']} | "
            f"{_pct(row['share'])} | {row['calls']} | {row['guideline']} | {example} |"
        )
    lines += [
        "",
        "## Conflicts for a manager",
        "",
        "| Category | Levels | Calls | Answers |",
        "|---|---|---|---|",
    ]
    for row in report["conflicts"]:
        answers = ", ".join(f"{a['value']} ({a['calls']})" for a in row["answers"])
        lines.append(
            f"| {row['category']} | {', '.join(row['levels']) or '-'} | {row['calls']} | {answers} |"
        )
    return "\n".join(lines) + "\n"
