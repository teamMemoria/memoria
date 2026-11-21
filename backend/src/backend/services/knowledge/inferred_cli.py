"""Command line for inferred knowledge (Layer 2).

``infer`` learns a company's rules from its calls, ``score`` checks calls,
``override`` records a manager's change and ``evaluate-inferred`` runs the
hidden-guidelines test. Everything is JSON files; nothing touches the database.
This module is also where the use cases are wired to their file adapters.
"""

from __future__ import annotations

import argparse
import functools
import gzip
import json
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

from backend.core.config import Settings
from backend.entities.inferred_knowledge import (
    InferenceSettings,
    InvalidKnowledgeInput,
    Override,
)
from backend.use_cases.inferred_knowledge import (
    InferKnowledgeBase,
    KnowledgeBaseNotBuilt,
    RecordOverride,
    ScoreCall,
)

from .errors import PipelineError
from .fact_claims import ConversationClaimSource, normalise_value
from .inferred_evaluation import evaluate_inferred, read_abcd_dump, render_markdown
from .knowledge_base_files import (
    JsonKnowledgeBaseStore,
    call_score_to_dict,
    knowledge_base_to_dict,
)
from .text import quantities

BACKEND = Path(__file__).resolve().parents[4]
SPLITS = ("train", "dev", "test")


def settings_from_app(settings: Settings | None = None) -> InferenceSettings:
    """Reuse the team's thresholds: a fact needs the draft threshold in calls
    (10 by default) and a common conflict needs the conflict threshold (5)."""
    settings = settings or Settings()
    return InferenceSettings(
        min_calls=settings.knowledge_draft_threshold,
        conflict_calls=settings.knowledge_conflict_threshold,
    )


def _errors_as_pipeline_errors(command: Callable[[argparse.Namespace], int]):
    """Turn expected failures into the typed error the CLI prints, never a traceback."""

    @functools.wraps(command)
    def run(args: argparse.Namespace) -> int:
        try:
            return command(args)
        except KnowledgeBaseNotBuilt as error:
            raise PipelineError("invalid_input", str(error), "store") from error
        except (InvalidKnowledgeInput, ValueError, KeyError, TypeError) as error:
            raise PipelineError(
                "invalid_input", str(error), command.__name__
            ) from error
        except OSError as error:
            raise PipelineError(
                "invalid_input", f"{type(error).__name__}: {error}", command.__name__
            ) from error

    return run


def _read_json(path: Path) -> Any:
    try:
        if path.suffix == ".gz":
            with gzip.open(path, "rt", encoding="utf-8") as handle:
                return json.load(handle)
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise PipelineError(
            "invalid_input",
            f"cannot read {path} as JSON: {type(error).__name__}",
            str(path),
        ) from error


def _is_abcd_dump(data: Any) -> bool:
    return isinstance(data, dict) and all(isinstance(data.get(s), list) for s in SPLITS)


def read_conversations(paths: list[str], split: str) -> list[dict[str, Any]]:
    """Conversation files or folders, or the full ABCD v1.1 file (one split of it)."""
    records: list[dict[str, Any]] = []
    for raw in paths:
        path = Path(raw)
        files = sorted(path.glob("*.json")) if path.is_dir() else [path]
        for file in files:
            data = _read_json(file)
            records.extend(data[split] if _is_abcd_dump(data) else [data])
    if not records:
        raise PipelineError("invalid_input", "no conversations found", ", ".join(paths))
    return records


def _print(value: Any) -> None:
    sys.stdout.write(json.dumps(value, indent=2, ensure_ascii=False) + "\n")


@_errors_as_pipeline_errors
def cmd_infer(args: argparse.Namespace) -> int:
    source = ConversationClaimSource(read_conversations(args.conversations, args.split))
    store = JsonKnowledgeBaseStore(Path(args.store))
    kb = InferKnowledgeBase(source, store, settings_from_app()).execute(args.company)
    _print(
        {
            "company_id": kb.company_id,
            "version": kb.version,
            "calls_read": source.calls_read,
            "calls_with_values": kb.calls_with_values,
            "counts": knowledge_base_to_dict(kb)["counts"],
            "failures": source.failures,
            "saved_to": str(store.folder / f"{kb.company_id}.json"),
        }
    )
    return 1 if source.failures else 0


@_errors_as_pipeline_errors
def cmd_score(args: argparse.Namespace) -> int:
    store = JsonKnowledgeBaseStore(Path(args.store))
    score_call = ScoreCall(store)
    results, failures = [], []
    for record in read_conversations([args.conversation], args.split):
        source = ConversationClaimSource([record])
        claims = source.claims(args.company)
        failures += source.failures
        if source.failures:
            continue
        call = record.get("id") or record.get("convo_id")
        if not claims:
            results.append({"call": call, "score": None, "checked": []})
            continue
        results.append(
            call_score_to_dict(
                score_call.execute(args.company, claims[0].call_id, claims)
            )
        )
    output: Any = results[0] if len(results) == 1 and not failures else results
    if failures:
        output = {"results": results, "failures": failures}
    _print(output)
    return 1 if failures else 0


def parse_value(text: str) -> str:
    """A manager's value, written the way claims are ("one week" -> "7 days")."""
    found = quantities(text)
    if len(found) != 1:
        raise InvalidKnowledgeInput(
            f"give one value with a unit, like '7 days' or '$4.99', not {text!r}"
        )
    return normalise_value(found[0])


@_errors_as_pipeline_errors
def cmd_override(args: argparse.Namespace) -> int:
    value = None if args.remove else parse_value(args.value)
    override = Override(args.topic, value, args.by, args.reason)
    RecordOverride(JsonKnowledgeBaseStore(Path(args.store))).execute(
        args.company, override
    )
    _print(
        {"status": "recorded", "value": value, "applies_from": "the next `infer` run"}
    )
    return 0


@_errors_as_pipeline_errors
def cmd_evaluate_inferred(args: argparse.Namespace) -> int:
    dump = read_abcd_dump(Path(args.abcd))
    snapshot = _read_json(Path(args.references))
    # Fixed defaults (10 calls, 5 for a conflict), so results don't depend on a local .env.
    report = evaluate_inferred(dump, snapshot, InferenceSettings())
    out = Path(args.out_dir) if args.out_dir else BACKEND / "results" / "knowledge"
    out.mkdir(parents=True, exist_ok=True)
    (out / "inferred-eval.json").write_text(
        json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    (out / "inferred-eval.md").write_text(render_markdown(report), encoding="utf-8")
    sys.stdout.write(render_markdown(report))
    return 0


def add_commands(sub: Any) -> None:
    infer = sub.add_parser(
        "infer", help="learn a company's rules from its calls (Layer 2)"
    )
    infer.add_argument(
        "conversations",
        nargs="+",
        help="conversation JSON files or folders, or the ABCD abcd_v1.1.json(.gz) file",
    )
    infer.add_argument("--company", required=True)
    infer.add_argument(
        "--store", required=True, help="folder for the knowledge base files"
    )
    infer.add_argument(
        "--split", choices=SPLITS, default="train", help="ABCD split (default: train)"
    )
    infer.set_defaults(func=cmd_infer)

    score = sub.add_parser("score", help="check calls' information against the rules")
    score.add_argument(
        "conversation", help="a conversation file or folder, or the ABCD file"
    )
    score.add_argument("--company", required=True)
    score.add_argument("--store", required=True)
    score.add_argument(
        "--split", choices=SPLITS, default="test", help="ABCD split (default: test)"
    )
    score.set_defaults(func=cmd_score)

    override = sub.add_parser("override", help="record a manager's change to one topic")
    override.add_argument("--company", required=True)
    override.add_argument("--store", required=True)
    override.add_argument(
        "--topic", required=True, help="topic_id from the knowledge base"
    )
    choice = override.add_mutually_exclusive_group(required=True)
    choice.add_argument("--value", help='the right value, e.g. "7 days" or "$4.99"')
    choice.add_argument("--remove", action="store_true", help="remove the topic's rule")
    override.add_argument("--by", required=True, help="who made the change")
    override.add_argument("--reason", required=True)
    override.set_defaults(func=cmd_override)

    evaluation = sub.add_parser(
        "evaluate-inferred",
        help="learn with the guidelines hidden, then compare (Layer 2)",
    )
    evaluation.add_argument("--abcd", required=True, help="path to abcd_v1.1.json.gz")
    evaluation.add_argument(
        "--references",
        default=str(BACKEND / "data" / "references" / "abcd-guidelines.snapshot.json"),
    )
    evaluation.add_argument("--out-dir", help="default: backend/results/knowledge")
    evaluation.set_defaults(func=cmd_evaluate_inferred)
