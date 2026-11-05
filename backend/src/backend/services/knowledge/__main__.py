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

from .errors import PipelineError
from .extraction import ModelExtractor, RuleExtractor, extract_drafts
from .grouping import group_drafts
from .llm import OpenAICompatibleClient


def _read(path: str) -> Any:
    return json.loads(Path(path).read_text(encoding="utf-8"))


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
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
