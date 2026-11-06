"""Command line: ``uv run python -m backend.services.knowledge <command> ...``.

Commands read and write JSON files only; nothing touches a database or the API.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from .conflicts import find_conflicts
from .errors import PipelineError
from .evaluation import evaluate, render_markdown
from .extraction import ModelExtractor, RuleExtractor, extract_drafts
from .grouping import group_drafts
from .llm import OpenAICompatibleClient
from .pipeline import run_pipeline
from .verification import check_drafts, load_reference_snapshot


def _read(path: str) -> Any:
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise PipelineError(
            "invalid_input", f"cannot read {path} as JSON: {type(error).__name__}", path
        ) from error


def _write(value: Any, path: str | None) -> None:
    text = json.dumps(value, indent=2, ensure_ascii=False, sort_keys=False) + "\n"
    if path:
        Path(path).write_text(text, encoding="utf-8")
    else:
        sys.stdout.write(text)


def _extractor(name: str):
    if name == "rule":
        return RuleExtractor()
    return ModelExtractor(OpenAICompatibleClient.from_env())


def cmd_extract(args: argparse.Namespace) -> int:
    records = []
    for path in args.conversations:
        p = Path(path)
        files = sorted(p.glob("*.json")) if p.is_dir() else [p]
        records.extend(_read(str(f)) for f in files)
    extractor = _extractor(args.extractor)
    results = [
        extract_drafts(r, args.company, extractor=extractor).to_dict() for r in records
    ]
    _write({"company_id": args.company, "results": results}, args.out)
    return 1 if any(r["status"] == "error" for r in results) else 0


def _drafts_from(path: str) -> list[dict[str, Any]]:
    """Drafts from an `extract` output file, or a plain JSON array of drafts."""
    data = _read(path)
    if isinstance(data, dict) and "results" in data:
        return [d for r in data["results"] for d in r.get("drafts", [])]
    return data


def cmd_group(args: argparse.Namespace) -> int:
    entries = _read(args.existing) if args.existing else []
    try:
        result = group_drafts(
            _drafts_from(args.drafts), args.company, existing_entries=entries
        )
    except PipelineError as error:
        _write({"status": "error", "errors": [error.to_dict()]}, args.out)
        return 1
    _write(result, args.out)
    return 0


def cmd_conflicts(args: argparse.Namespace) -> int:
    entries = _read(args.existing) if args.existing else []
    groups = _read(args.groups) if args.groups else None
    try:
        result = find_conflicts(
            _drafts_from(args.drafts),
            args.company,
            existing_entries=entries,
            groups=groups,
        )
    except PipelineError as error:
        _write({"status": "error", "errors": [error.to_dict()]}, args.out)
        return 1
    _write(result, args.out)
    return 0


def cmd_verify(args: argparse.Namespace) -> int:
    try:
        references = load_reference_snapshot(Path(args.references), args.company)
        result = check_drafts(
            _drafts_from(args.drafts),
            args.company,
            references,
            conflicts=_read(args.conflicts) if args.conflicts else None,
            groups=_read(args.groups) if args.groups else None,
            as_of=args.as_of,
        )
    except PipelineError as error:
        _write({"status": "error", "errors": [error.to_dict()]}, args.out)
        return 1
    _write(result, args.out)
    return 0


def cmd_run(args: argparse.Namespace) -> int:
    payload = _read(args.payload)
    if isinstance(payload, dict) and "conversation_files" in payload:
        # Convenience for local files (paths relative to the working directory),
        # as in examples/knowledge/pipeline/. The backend sends conversations inline.
        files = payload.pop("conversation_files")
        payload["conversations"] = [
            *payload.get("conversations", []),
            *(_read(f) for f in files),
        ]
    output = run_pipeline(
        payload, extractor=_extractor(args.extractor), include_timings=args.timings
    )
    _write(output, args.out)
    if output["status"] == "error":
        return 1
    return 0 if output["release_checks"]["release_allowed"] else 3


def cmd_evaluate(args: argparse.Namespace) -> int:
    backend = Path(__file__).resolve().parents[4]
    report = evaluate(args.split, backend, extractor=_extractor(args.extractor))
    report["notes"] += args.note or []
    out = Path(args.out_dir) if args.out_dir else backend / "results" / "knowledge"
    out.mkdir(parents=True, exist_ok=True)
    (out / f"eval-{args.split}.json").write_text(
        json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    (out / f"eval-{args.split}.md").write_text(
        render_markdown(report), encoding="utf-8"
    )
    sys.stdout.write(render_markdown(report))
    return 0 if report["release_checks"]["release_allowed"] else 3


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m backend.services.knowledge")
    sub = parser.add_subparsers(dest="command", required=True)

    extract = sub.add_parser(
        "extract", help="extract knowledge drafts from ABCD conversation files (#16)"
    )
    extract.add_argument(
        "conversations", nargs="+", help="conversation JSON files or directories"
    )
    extract.add_argument(
        "--company",
        required=True,
        help="company id; knowledge never mixes across companies",
    )
    extract.add_argument("--extractor", choices=["rule", "model"], default="rule")
    extract.add_argument("--out", help="write JSON here instead of stdout")
    extract.set_defaults(func=cmd_extract)

    group = sub.add_parser("group", help="group drafts and find duplicates (#17)")
    group.add_argument("drafts", help="output of `extract`, or a JSON array of drafts")
    group.add_argument("--company", required=True)
    group.add_argument("--existing", help="JSON array of existing knowledge entries")
    group.add_argument("--out")
    group.set_defaults(func=cmd_group)

    conflicts = sub.add_parser(
        "conflicts", help="find possible knowledge conflicts (#18)"
    )
    conflicts.add_argument(
        "drafts", help="output of `extract`, or a JSON array of drafts"
    )
    conflicts.add_argument("--company", required=True)
    conflicts.add_argument(
        "--existing", help="JSON array of existing knowledge entries"
    )
    conflicts.add_argument("--groups", help="output of `group`, to label each side")
    conflicts.add_argument("--out")
    conflicts.set_defaults(func=cmd_conflicts)

    verify = sub.add_parser(
        "verify", help="check drafts against approved sources (#19)"
    )
    verify.add_argument("drafts", help="output of `extract`, or a JSON array of drafts")
    verify.add_argument("--company", required=True)
    verify.add_argument("--references", required=True, help="a reference snapshot file")
    verify.add_argument("--conflicts", help="output of `conflicts`")
    verify.add_argument("--groups", help="output of `group`")
    verify.add_argument("--as-of", help="ISO date used for reference expiry")
    verify.add_argument("--out")
    verify.set_defaults(func=cmd_verify)

    run = sub.add_parser(
        "run",
        help="run the whole pipeline on one payload file, with release checks (#20)",
    )
    run.add_argument(
        "payload",
        help="JSON: {company_id, conversations, existing_entries?, references?, as_of?, config?}",
    )
    run.add_argument("--extractor", choices=["rule", "model"], default="rule")
    run.add_argument("--timings", action="store_true")
    run.add_argument("--out")
    run.set_defaults(func=cmd_run)

    evaluation = sub.add_parser(
        "evaluate", help="score the pipeline against labelled cases (#20)"
    )
    evaluation.add_argument("--split", choices=["dev", "heldout"], default="dev")
    evaluation.add_argument("--extractor", choices=["rule", "model"], default="rule")
    evaluation.add_argument("--out-dir", help="default: backend/results/knowledge")
    evaluation.add_argument(
        "--note", action="append", help="add a note to the report (repeatable)"
    )
    evaluation.set_defaults(func=cmd_evaluate)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return args.func(args)
    except PipelineError as error:
        # Unreadable input files and the like: a typed error, never a traceback.
        _write(
            {"status": "error", "errors": [error.to_dict()]}, getattr(args, "out", None)
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
