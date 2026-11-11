"""Rebuild data/abcd/splits.json: which ABCD split (train/dev/test) each curated record came from.

Usage (from backend/):
    uv run python scripts/build_abcd_splits.py path/to/abcd_v1.1.json.gz

abcd_v1.1.json.gz is in https://github.com/asappresearch/abcd at commit
6b8700ce67c6b37b062dd7a60abc76d7ef832a97 (data/abcd_v1.1.json.gz). The split is
kept so held-out evaluation cases never come from conversations used for tuning.
"""

from __future__ import annotations

import gzip
import json
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
CURATED = BACKEND / "data" / "abcd" / "conversations"
OUT = BACKEND / "data" / "abcd" / "splits.json"


def main(argv: list[str]) -> int:
    if len(argv) != 1:
        print(__doc__, file=sys.stderr)
        return 2
    with gzip.open(argv[0], "rt", encoding="utf-8") as handle:
        raw = json.load(handle)
    split_of = {
        str(c["convo_id"]): split for split, convos in raw.items() for c in convos
    }
    out = {}
    for path in sorted(CURATED.glob("*.json")):
        record = json.loads(path.read_text(encoding="utf-8"))
        original_id = record["source"]["original_id"]
        out[record["id"]] = {
            "original_id": original_id,
            "split": split_of.get(original_id),
        }
    missing = [cid for cid, v in out.items() if v["split"] is None]
    if missing:
        print(f"not found in the ABCD file: {missing}", file=sys.stderr)
        return 1
    OUT.write_text(json.dumps(out, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"wrote {len(out)} entries to {OUT.relative_to(BACKEND)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
