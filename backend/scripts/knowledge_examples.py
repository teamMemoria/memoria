"""Regenerate the fixed input/output examples under examples/knowledge/.

Usage (from backend/):
    uv run python scripts/knowledge_examples.py          # rewrite the examples
    uv run python scripts/knowledge_examples.py --check  # exit 1 if any example is stale

The examples are the contract with the backend: each ``*.input.json`` is passed
to the named function and its result is ``*.output.json``. Tests run ``--check``.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

from backend.services.knowledge.conflicts import find_conflicts
from backend.services.knowledge.errors import PipelineError
from backend.services.knowledge.extraction import extract_drafts
from backend.services.knowledge.grouping import group_drafts

BACKEND = Path(__file__).resolve().parents[1]
EXAMPLES = BACKEND / "examples" / "knowledge"


def _dump(value: Any) -> str:
    return json.dumps(value, indent=2, ensure_ascii=False) + "\n"


def _load(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _conversation(payload: dict[str, Any]) -> Any:
    if "conversation_file" in payload:
        return _load(BACKEND / payload["conversation_file"])
    return payload["conversation"]


def run_extraction(payload: dict[str, Any]) -> Any:
    return extract_drafts(_conversation(payload), payload["company_id"]).to_dict()


def _drafts(payload: dict[str, Any]) -> list[dict[str, Any]]:
    """Drafts given inline, or extracted from the listed conversation files."""
    drafts = list(payload.get("drafts", []))
    for path in payload.get("conversation_files", []):
        drafts.extend(
            extract_drafts(_load(BACKEND / path), payload["company_id"]).drafts
        )
    return drafts


def run_grouping(payload: dict[str, Any]) -> Any:
    try:
        return group_drafts(
            _drafts(payload),
            payload["company_id"],
            existing_entries=payload.get("existing_entries", []),
        )
    except PipelineError as error:
        return {"status": "error", "errors": [error.to_dict()]}


def run_conflicts(payload: dict[str, Any]) -> Any:
    drafts = _drafts(payload)
    entries = payload.get("existing_entries", [])
    try:
        groups = group_drafts(drafts, payload["company_id"], existing_entries=entries)
        return find_conflicts(
            drafts, payload["company_id"], existing_entries=entries, groups=groups
        )
    except PipelineError as error:
        return {"status": "error", "errors": [error.to_dict()]}


RUNNERS: dict[str, Callable[[dict[str, Any]], Any]] = {
    "extraction": run_extraction,
    "grouping": run_grouping,
    "conflicts": run_conflicts,
}


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args(argv)
    stale = []
    for stage, runner in RUNNERS.items():
        for input_path in sorted((EXAMPLES / stage).glob("*.input.json")):
            output_path = input_path.with_name(
                input_path.name.replace(".input.json", ".output.json")
            )
            expected = _dump(runner(_load(input_path)))
            current = (
                output_path.read_text(encoding="utf-8")
                if output_path.exists()
                else None
            )
            if current != expected:
                stale.append(str(output_path.relative_to(BACKEND)))
                if not args.check:
                    output_path.write_text(expected, encoding="utf-8")
    if args.check and stale:
        print(
            "stale examples (run scripts/knowledge_examples.py):",
            *stale,
            sep="\n  ",
            file=sys.stderr,
        )
        return 1
    if not args.check:
        print(f"updated {len(stale)} example(s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
