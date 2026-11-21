"""Keep inferred knowledge bases as JSON files, and read them back.

One folder holds every company: ``<company>.json`` is the latest knowledge base
and ``<company>.overrides.json`` is the list of managers' changes. Overrides
are kept in their own file so relearning never loses them. This is the file
version of ``KnowledgeBaseStore``; a database store can replace it later
without changing the use cases.
"""

from __future__ import annotations

import json
import os
import re
import tempfile
from pathlib import Path
from typing import Any

from backend.entities.inferred_knowledge import (
    SCHEMA_VERSION,
    Answer,
    CallScore,
    Conflict,
    InferenceSettings,
    KnowledgeBase,
    Override,
    Rule,
    Topic,
)

_SAFE_NAME = re.compile(r"^[A-Za-z0-9_-]+$")


# ------------------------------------------------------------------ to JSON


def topic_to_dict(topic: Topic) -> dict[str, Any]:
    return {
        "topic_id": topic.topic_id,
        "category": topic.category,
        "levels": list(topic.levels),
        "unit": topic.unit,
        "subject": list(topic.subject),
        "total_calls": topic.total_calls,
        "unclear_calls": topic.unclear_calls,
        "answers": [
            {"value": a.value, "calls": a.calls, "example": a.example}
            for a in topic.answers
        ],
        "terms": [[term, count] for term, count in topic.terms],
    }


def knowledge_base_to_dict(kb: KnowledgeBase) -> dict[str, Any]:
    return {
        "schema": SCHEMA_VERSION,
        "company_id": kb.company_id,
        "version": kb.version,
        "calls_with_values": kb.calls_with_values,
        "settings": vars(kb.settings).copy(),
        "counts": {
            "rules": len(kb.rules),
            "conflicts": len(kb.conflicts),
            "undecided": len(kb.undecided),
            "removed": len(kb.removed),
            "unmatched_overrides": len(kb.unmatched_overrides),
        },
        "rules": [
            {
                "value": r.value,
                "share": r.share,
                "supporting_calls": r.supporting_calls,
                "source": r.source,
                "note": r.note,
                "topic": topic_to_dict(r.topic),
            }
            for r in kb.rules
        ],
        "conflicts": [{"topic": topic_to_dict(c.topic)} for c in kb.conflicts],
        "undecided": [topic_to_dict(t) for t in kb.undecided],
        "removed": [override_to_dict(o) for o in kb.removed],
        "unmatched_overrides": [override_to_dict(o) for o in kb.unmatched_overrides],
    }


def override_to_dict(override: Override) -> dict[str, Any]:
    return {
        "topic_id": override.topic_id,
        "value": override.value,
        "changed_by": override.changed_by,
        "reason": override.reason,
    }


def call_score_to_dict(score: CallScore) -> dict[str, Any]:
    return {
        "company_id": score.company_id,
        "call_id": score.call_id,
        "knowledge_base_version": score.knowledge_base_version,
        "score": score.score,
        "matches": score.matches,
        "differences": score.differences,
        "checked": [
            {
                "verdict": item.verdict,
                "value": item.claim.value,
                "rule_value": item.rule_value,
                "topic_id": item.topic_id,
                "category": item.claim.category,
                "quote": item.claim.quote,
            }
            for item in score.checked
        ],
    }


# ---------------------------------------------------------------- from JSON


def topic_from_dict(data: dict[str, Any]) -> Topic:
    return Topic(
        topic_id=data["topic_id"],
        category=data["category"],
        levels=tuple(data["levels"]),
        unit=data["unit"],
        terms=tuple((term, int(count)) for term, count in data["terms"]),
        answers=tuple(
            Answer(a["value"], int(a["calls"]), a["example"]) for a in data["answers"]
        ),
        total_calls=int(data["total_calls"]),
        unclear_calls=int(data.get("unclear_calls", 0)),
    )


def knowledge_base_from_dict(data: dict[str, Any]) -> KnowledgeBase:
    if data.get("schema") != SCHEMA_VERSION:
        raise ValueError(f"not an inferred knowledge base ({SCHEMA_VERSION})")
    return KnowledgeBase(
        company_id=data["company_id"],
        version=int(data["version"]),
        calls_with_values=int(data["calls_with_values"]),
        rules=tuple(
            Rule(
                topic_from_dict(r["topic"]),
                r["value"],
                int(r["supporting_calls"]),
                r["source"],
                r.get("note"),
            )
            for r in data["rules"]
        ),
        conflicts=tuple(
            Conflict(topic_from_dict(c["topic"])) for c in data["conflicts"]
        ),
        undecided=tuple(topic_from_dict(t) for t in data["undecided"]),
        settings=InferenceSettings(**data["settings"]),
        removed=tuple(override_from_dict(o) for o in data.get("removed", [])),
        unmatched_overrides=tuple(
            override_from_dict(o) for o in data.get("unmatched_overrides", [])
        ),
    )


def override_from_dict(data: dict[str, Any]) -> Override:
    return Override(
        data["topic_id"], data.get("value"), data["changed_by"], data["reason"]
    )


# -------------------------------------------------------------------- store


def _write_atomically(path: Path, value: Any) -> None:
    """Write to a temporary file and swap it in, so a crash never leaves half a file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(value, indent=2, ensure_ascii=False) + "\n"
    handle, temporary = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.")
    try:
        with os.fdopen(handle, "w", encoding="utf-8") as file:
            file.write(text)
        os.replace(temporary, path)
    except BaseException:
        Path(temporary).unlink(missing_ok=True)
        raise


class JsonKnowledgeBaseStore:
    """``KnowledgeBaseStore`` backed by a folder of JSON files.

    Writes are atomic, but there is no locking: two people recording overrides
    at the same moment can still lose one. A database store fixes that.
    """

    def __init__(self, folder: Path):
        self.folder = Path(folder)

    def _path(self, company_id: str, suffix: str) -> Path:
        if not _SAFE_NAME.match(company_id):
            raise ValueError("company_id may only use letters, digits, '_' and '-'")
        return self.folder / f"{company_id}{suffix}"

    def load(self, company_id: str) -> KnowledgeBase | None:
        path = self._path(company_id, ".json")
        if not path.exists():
            return None
        kb = knowledge_base_from_dict(json.loads(path.read_text(encoding="utf-8")))
        if kb.company_id != company_id:
            raise ValueError(f"{path.name} holds another company's knowledge base")
        return kb

    def save(self, knowledge_base: KnowledgeBase) -> None:
        path = self._path(knowledge_base.company_id, ".json")
        _write_atomically(path, knowledge_base_to_dict(knowledge_base))

    def overrides(self, company_id: str) -> list[Override]:
        path = self._path(company_id, ".overrides.json")
        if not path.exists():
            return []
        return [
            override_from_dict(o) for o in json.loads(path.read_text(encoding="utf-8"))
        ]

    def add_override(self, company_id: str, override: Override) -> None:
        """Record a manager's change. It takes effect on the next rebuild."""
        existing = [override_to_dict(o) for o in self.overrides(company_id)]
        existing.append(override_to_dict(override))
        _write_atomically(self._path(company_id, ".overrides.json"), existing)
