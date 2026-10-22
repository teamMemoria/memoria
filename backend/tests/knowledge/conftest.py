from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

BACKEND = Path(__file__).resolve().parents[2]
ABCD_DIR = BACKEND / "data" / "abcd" / "conversations"
SPLITS = BACKEND / "data" / "abcd" / "splits.json"
SYNTHETIC_DIR = Path(__file__).resolve().parent / "conversations"
LABELS_DIR = Path(__file__).resolve().parent / "labels"
COMPANY = "acme-test"


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def abcd(cid: str) -> dict[str, Any]:
    return load_json(ABCD_DIR / f"{cid}.json")


def synthetic(cid: str) -> dict[str, Any]:
    return load_json(SYNTHETIC_DIR / f"{cid}.json")


@pytest.fixture(scope="session")
def abcd_records() -> list[dict[str, Any]]:
    return [load_json(path) for path in sorted(ABCD_DIR.glob("*.json"))]


@pytest.fixture(scope="session")
def synthetic_records() -> list[dict[str, Any]]:
    return [load_json(path) for path in sorted(SYNTHETIC_DIR.glob("*.json"))]
