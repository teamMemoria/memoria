"""Measure the pipeline against labelled cases (#20).

``evaluate(split)`` reads the label sets for ``dev`` or ``heldout`` from
``tests/knowledge/labels/`` (held-out ones under ``heldout/``), runs each stage
on the cases' conversations and reports, per stage, counts and rates next to
the human judgements they are compared with, plus the release checks over a
full pipeline run.

Held-out cases are for reporting only. Nothing in this module tunes a
threshold, and the label files say so; change a rule or a threshold only
against ``dev`` and re-run ``heldout`` once to report.

Verification labels assume the reference snapshot has been reviewed. The
committed snapshot is unreviewed, so the evaluation approves an in-memory copy
and says so in the report. That copy is never written anywhere.
"""

from __future__ import annotations

import copy
import json
import time
from collections import Counter
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from .abcd import read_conversation
from .conflicts import find_conflicts
from .extraction import Extractor, RuleExtractor, check_draft_citations, extract_drafts
from .grouping import group_drafts
from .pipeline import output_text, release_checks, repeat_processing_check, run_pipeline
from .privacy import Redactor
from .verification import check_drafts, load_reference_snapshot

EVALUATION_SCHEMA_VERSION = "knowledge-evaluation/1"
COMPANY = "acme-eval"
STAGES = ("extraction", "grouping", "conflicts", "verification")


class Paths:
    def __init__(self, backend: Path) -> None:
        self.backend = backend
        self.abcd = backend / "data" / "abcd" / "conversations"
        self.synthetic = backend / "tests" / "knowledge" / "conversations"
        self.labels = backend / "tests" / "knowledge" / "labels"
        self.snapshot = (
            backend / "data" / "references" / "abcd-guidelines.snapshot.json"
        )

    def label_file(self, stage: str, split: str) -> Path:
        return (
            self.labels / f"{stage}.json"
            if split == "dev"
            else self.labels / split / f"{stage}.json"
        )

    def conversation(self, ref: str) -> dict[str, Any]:
        if ref.endswith(".json"):
            return json.loads((self.backend / ref).read_text(encoding="utf-8"))
        if ref.startswith("ABCD"):
            return json.loads((self.abcd / f"{ref}.json").read_text(encoding="utf-8"))
        for folder in (self.synthetic, self.synthetic / "heldout"):
            path = folder / f"{ref}.json"
            if path.exists():
                return json.loads(path.read_text(encoding="utf-8"))
        raise FileNotFoundError(ref)


def _rate(hits: int, total: int) -> float | None:
    return round(hits / total, 4) if total else None


def _drafts(record: Mapping[str, Any], extractor: Extractor) -> list[dict[str, Any]]:
    return extract_drafts(record, COMPANY, extractor=extractor).drafts


# --------------------------------------------------------------------------- stages


def eval_extraction(
    labels: Mapping[str, Any], paths: Paths, extractor: Extractor
) -> dict[str, Any]:
    decisions = answer_hits = answer_total = condition_hits = condition_total = 0
    drafts_total = exact_drafts = privacy_errors = failures = 0
    cases = []
    for case in labels["cases"]:
        record = paths.conversation(case["conversation"])
        result = extract_drafts(record, COMPANY, extractor=extractor)
        if result.status == "error":
            failures += 1
        conversation = read_conversation(record, COMPANY)
        wants = case["expect"] == "draft"
        decided = wants == bool(result.drafts)
        decisions += decided
        answers = " ".join(d["answer"] for d in result.drafts).lower()
        conditions = " ".join(
            c["text"] for d in result.drafts for c in d["conditions"]
        ).lower()
        missed_answers = [
            p for p in case.get("answer_must_include", []) if p.lower() not in answers
        ]
        missed_conditions = [
            p
            for p in case.get("conditions_must_include", [])
            if p.lower() not in conditions
        ]
        answer_total += len(case.get("answer_must_include", []))
        answer_hits += len(case.get("answer_must_include", [])) - len(missed_answers)
        condition_total += len(case.get("conditions_must_include", []))
        condition_hits += len(case.get("conditions_must_include", [])) - len(
            missed_conditions
        )
        output = output_text(result.to_dict())
        # Report which kinds of value leaked, never the values themselves.
        leaked = [
            f"must_not_include[{i}]"
            for i, v in enumerate(case.get("must_not_include", []))
            if v.lower() in output.lower()
        ]
        leaked += Redactor(conversation.customer_record).leaks(output)
        privacy_errors += len(leaked)
        citation_problems = []
        for draft in result.drafts:
            drafts_total += 1
            problems = check_draft_citations(draft, conversation)
            exact_drafts += not problems
            citation_problems += problems
        cases.append(
            {
                "conversation": case["conversation"],
                "expected": case["expect"],
                "got": "draft"
                if result.drafts
                else ("error" if result.status == "error" else "no_draft"),
                "missed_answer_phrases": missed_answers,
                "missed_condition_phrases": missed_conditions,
                "privacy_errors": leaked,
                "citation_problems": citation_problems,
                "passed": decided
                and not missed_answers
                and not missed_conditions
                and not leaked
                and not citation_problems,
            }
        )
    return {
        "cases": len(labels["cases"]),
        "draft_decision_accuracy": _rate(decisions, len(labels["cases"])),
        "answer_phrase_recall": _rate(answer_hits, answer_total),
        "condition_phrase_recall": _rate(condition_hits, condition_total),
        "faithfulness_exact_citation_rate": _rate(exact_drafts, drafts_total),
        "privacy_errors": privacy_errors,
        "technical_failures": failures,
        "details": cases,
    }


def eval_grouping(
    labels: Mapping[str, Any], paths: Paths, extractor: Extractor
) -> dict[str, Any]:
    tallies = Counter()
    details = []
    for case in labels["cases"]:
        drafts = {
            cid: _drafts(paths.conversation(cid), extractor)
            for cid in case["conversations"]
        }
        missing = [cid for cid, d in drafts.items() if not d]
        if missing:
            details.append(
                {
                    "name": case["name"],
                    "passed": False,
                    "problems": [f"no draft for {missing}"],
                }
            )
            for key in (
                "same_group",
                "different_group",
                "duplicates",
                "not_duplicates",
            ):
                tallies[f"{key}_total"] += len(case.get(key, []))
            continue
        ids = {cid: d[0]["draft_id"] for cid, d in drafts.items()}
        result = group_drafts([d[0] for d in drafts.values()], COMPANY)
        group_of = {
            i: g["group_id"] for g in result["groups"] for i in g["member_draft_ids"]
        }
        dup_pairs = {
            frozenset((d["draft_id"], d["duplicate_of"]))
            for g in result["groups"]
            for d in g["duplicates"]
        }
        problems = []
        for key in ("same_group", "different_group", "duplicates", "not_duplicates"):
            for a, b in case.get(key, []):
                same = group_of[ids[a]] == group_of[ids[b]]
                duplicate = frozenset((ids[a], ids[b])) in dup_pairs
                ok = {
                    "same_group": same,
                    "different_group": not same,
                    "duplicates": duplicate,
                    "not_duplicates": not duplicate,
                }[key]
                tallies[f"{key}_total"] += 1
                if ok:
                    tallies[f"{key}_correct"] += 1
                else:
                    problems.append(f"{key}: {a} / {b}")
        details.append(
            {"name": case["name"], "passed": not problems, "problems": problems}
        )
    return {
        "cases": len(labels["cases"]),
        "same_group_recall": _rate(
            tallies["same_group_correct"], tallies["same_group_total"]
        ),
        "different_group_accuracy": _rate(
            tallies["different_group_correct"], tallies["different_group_total"]
        ),
        "duplicate_recall": _rate(
            tallies["duplicates_correct"], tallies["duplicates_total"]
        ),
        "paraphrase_not_duplicate_accuracy": _rate(
            tallies["not_duplicates_correct"], tallies["not_duplicates_total"]
        ),
        "labelled_pairs": sum(v for k, v in tallies.items() if k.endswith("_total")),
        "details": details,
    }


def eval_conflicts(
    labels: Mapping[str, Any], paths: Paths, extractor: Extractor
) -> dict[str, Any]:
    correct = missed = false_alarms = 0
    details = []
    for case in labels["cases"]:
        drafts = [
            _drafts(paths.conversation(case["a"]), extractor),
            _drafts(paths.conversation(case["b"]), extractor),
        ]
        if not all(drafts):
            got = "no_draft"
        else:
            result = find_conflicts([drafts[0][0], drafts[1][0]], COMPANY)
            statuses = {f["status"] for f in result["possible_conflicts"]} | {
                f["status"] for f in result["explained_differences"]
            }
            got = (
                "conflict"
                if "possible_conflict" in statuses
                else "unresolved"
                if "unresolved" in statuses
                else "explained"
                if "explained_difference" in statuses
                else "none"
            )
        expected = case["expect"]
        ok = got == expected or (expected == "none" and got == "explained")
        correct += ok
        missed += expected == "conflict" and got != "conflict"
        false_alarms += expected in {"none", "explained"} and got == "conflict"
        details.append(
            {
                "a": case["a"],
                "b": case["b"],
                "expected": expected,
                "got": got,
                "passed": ok,
            }
        )
    return {
        "cases": len(labels["cases"]),
        "accuracy": _rate(correct, len(labels["cases"])),
        "missed_conflicts": missed,
        "false_alarms": false_alarms,
        "details": details,
    }


def eval_verification(
    labels: Mapping[str, Any], paths: Paths, extractor: Extractor, references
) -> dict[str, Any]:
    correct = unsupported_verified = 0
    confusion: Counter[tuple[str, str]] = Counter()
    details = []
    for case in labels["cases"]:
        drafts = _drafts(paths.conversation(case["conversation"]), extractor)
        if not drafts:
            got = "no_draft"
        else:
            [result] = check_drafts([drafts[0]], COMPANY, references)["results"]
            got = result["verification_status"]
        expected = case["expect"]
        correct += got == expected
        unsupported_verified += got == "supported" and expected in {
            "contradicted",
            "unverifiable",
        }
        confusion[(expected, got)] += 1
        details.append(
            {
                "conversation": case["conversation"],
                "expected": expected,
                "got": got,
                "passed": got == expected,
            }
        )
    return {
        "cases": len(labels["cases"]),
        "status_accuracy": _rate(correct, len(labels["cases"])),
        "unsupported_verified": unsupported_verified,
        "confusion": [
            {"expected": e, "got": g, "count": n}
            for (e, g), n in sorted(confusion.items())
        ],
        "details": details,
    }


# --------------------------------------------------------------------------- whole run


def _reviewed_copy(references: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out = copy.deepcopy(references)
    for reference in out:
        reference["approval"] = {
            "status": "approved",
            "approved_by": "evaluation-only",
            "approved_at": None,
        }
    return out


def evaluate(
    split: str, backend: Path, extractor: Extractor | None = None
) -> dict[str, Any]:
    if split not in {"dev", "heldout"}:
        raise ValueError("split must be dev or heldout")
    paths = Paths(backend)
    extractor = extractor or RuleExtractor()
    labels = {
        stage: json.loads(paths.label_file(stage, split).read_text(encoding="utf-8"))
        for stage in STAGES
    }
    references = _reviewed_copy(load_reference_snapshot(paths.snapshot, COMPANY))
    started = time.perf_counter()
    report: dict[str, Any] = {
        "schema": EVALUATION_SCHEMA_VERSION,
        "split": split,
        "extractor": {"name": extractor.name, "version": extractor.version},
        "human_judgements": {
            stage: {
                "cases": len(labels[stage]["cases"]),
                "labelled_by": labels[stage].get("labelled_by"),
                "human_reviewed": labels[stage].get("human_reviewed", False),
            }
            for stage in STAGES
        },
        "extraction": eval_extraction(labels["extraction"], paths, extractor),
        "grouping": eval_grouping(labels["grouping"], paths, extractor),
        "conflicts": eval_conflicts(labels["conflicts"], paths, extractor),
        "verification": eval_verification(
            labels["verification"], paths, extractor, references
        ),
    }
    refs = set()
    for stage in STAGES:
        for case in labels[stage]["cases"]:
            for key in ("conversation", "a", "b"):
                if key in case:
                    refs.add(case[key])
            refs.update(case.get("conversations", []))
    conversations = [paths.conversation(r) for r in sorted(refs)]
    payload = {
        "company_id": COMPANY,
        "conversations": conversations,
        "references": references,
    }
    run = run_pipeline(payload, extractor=extractor, include_timings=True)
    checks = release_checks(run, payload)
    checks["checks"].append(
        {
            **repeat_processing_check(payload, extractor=extractor),
            "blocks_release": True,
        }
    )
    checks["release_allowed"] = all(
        c["passed"] for c in checks["checks"] if c["blocks_release"]
    )
    elapsed = time.perf_counter() - started
    report["pipeline_run"] = {
        "conversations": len(conversations),
        "counts": run.get("counts"),
        "technical_failures": run.get("technical_failures"),
        "missing_verification": run.get("counts", {})
        .get("verification", {})
        .get("unverifiable", 0),
        "timings_ms": run.get("timings"),
        "ms_per_conversation": round(
            run["timings"]["total_ms"] / max(1, len(conversations)), 2
        ),
        "model_usage": run.get("model_usage"),
    }
    report["release_checks"] = checks
    report["evaluation_seconds"] = round(elapsed, 2)
    report["notes"] = [
        (
            "Verification is measured against an in-memory copy of the ABCD guideline snapshot marked "
            "approved for evaluation only; the committed snapshot is unreviewed and verifies nothing."
        ),
        "Labels are first-pass and have not had a second person's review (human_reviewed: false).",
        (
            "Technical failures (invalid input, model errors) are counted separately from drafts that are "
            "merely unverifiable for lack of a reference."
        ),
    ]
    if split == "heldout":
        report["notes"].append(
            "Held-out cases: report only, never tune on them. The rule extractor's wording rules were "
            "developed while reading output over all 100 curated ABCD records, so ABCD held-out scores are "
            "optimistic; the SYN-H conversations were written after the rules were fixed."
        )
    return report


def render_markdown(report: Mapping[str, Any]) -> str:
    """A short human-readable summary of an evaluation report."""
    e, g, c, v = (report[s] for s in STAGES)
    run = report["pipeline_run"]
    allowed = "yes" if report["release_checks"]["release_allowed"] else "NO"
    counts = run["counts"]
    rows = [
        (
            f"| Extraction | {e['cases']} | draft/no-draft {e['draft_decision_accuracy']}, "
            f"answer phrases {e['answer_phrase_recall']}, conditions {e['condition_phrase_recall']}, "
            f"exact citations {e['faithfulness_exact_citation_rate']}, privacy errors {e['privacy_errors']} |"
        ),
        (
            f"| Grouping | {g['cases']} | same-group {g['same_group_recall']}, "
            f"kept apart {g['different_group_accuracy']}, duplicates {g['duplicate_recall']}, "
            f"paraphrase-not-duplicate {g['paraphrase_not_duplicate_accuracy']} |"
        ),
        (
            f"| Conflicts | {c['cases']} | accuracy {c['accuracy']}, missed {c['missed_conflicts']}, "
            f"false alarms {c['false_alarms']} |"
        ),
        (
            f"| Verification | {v['cases']} | status accuracy {v['status_accuracy']}, "
            f"unsupported marked supported {v['unsupported_verified']} |"
        ),
    ]
    run_lines = [
        (
            f"- {run['conversations']} conversations, {counts['drafts']} drafts, {counts['groups']} groups, "
            f"{counts['possible_conflicts']} possible conflicts, {counts['unresolved_conflicts']} unresolved."
        ),
        (
            f"- Verification: {counts['verification']}. Technical failures: {len(run['technical_failures'])} "
            f"(counted separately from missing verification: {run['missing_verification']} unverifiable)."
        ),
        (
            f"- About {run['ms_per_conversation']} ms per conversation on this machine; "
            f"model calls: {run['model_usage']['calls']}."
        ),
    ]
    extractor = report["extractor"]
    lines = [
        f"# Knowledge pipeline evaluation: {report['split']}",
        "",
        "Generated by `python -m backend.services.knowledge evaluate`. Do not edit by hand.",
        "",
        f"Extractor: `{extractor['name']}` v{extractor['version']}. Release allowed: **{allowed}**.",
        "",
        "| Stage | Cases | Result |",
        "|---|---:|---|",
        *rows,
        "",
        "## Release checks",
        "",
        *[
            f"- {'pass' if ch['passed'] else 'FAIL'}: `{ch['check']}`"
            + (f" ({len(ch['problems'])} problems)" if ch["problems"] else "")
            for ch in report["release_checks"]["checks"]
        ],
        "",
        "## Pipeline run",
        "",
        *run_lines,
        "",
        "## Failed cases",
        "",
    ]
    failed = []
    for stage in STAGES:
        for detail in report[stage]["details"]:
            if not detail["passed"]:
                failed.append(
                    f"- {stage}: `{json.dumps({k: v for k, v in detail.items() if k != 'passed'}, ensure_ascii=False)}`"
                )
    lines += failed or ["None."]
    lines += ["", "## Notes", "", *[f"- {n}" for n in report["notes"]], ""]
    return "\n".join(lines)
