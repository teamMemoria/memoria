from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from backend.data.conversations.models import Conversation, parse_conversation


@dataclass(frozen=True)
class ValidationIssue:
    file: Path
    field: str
    message: str


@dataclass(frozen=True)
class CorpusValidation:
    conversations: tuple[Conversation, ...]
    issues: tuple[ValidationIssue, ...]


def _field_path(location: tuple[Any, ...]) -> str:
    if not location:
        return "$"

    result = ""
    for part in location:
        if isinstance(part, int):
            result += f"[{part}]"
        elif result:
            result += f".{part}"
        else:
            result = str(part)
    return result


def _sort_issues(issues: list[ValidationIssue]) -> tuple[ValidationIssue, ...]:
    return tuple(sorted(issues, key=lambda issue: (issue.file.name, issue.field, issue.message)))


def validate_corpus(directory: Path) -> CorpusValidation:
    if not directory.is_dir():
        issue = ValidationIssue(directory, "$", "expected a readable directory")
        return CorpusValidation((), (issue,))

    paths = sorted(directory.glob("*.json"), key=lambda path: path.name)
    if not paths:
        issue = ValidationIssue(directory, "$", "no JSON files found")
        return CorpusValidation((), (issue,))

    conversations: list[Conversation] = []
    issues: list[ValidationIssue] = []
    first_file_by_id: dict[str, Path] = {}

    for path in paths:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            issues.append(
                ValidationIssue(
                    path,
                    "$",
                    f"invalid JSON at line {exc.lineno}, column {exc.colno}",
                )
            )
            continue
        except (OSError, UnicodeError) as exc:
            issues.append(ValidationIssue(path, "$", f"could not read file: {exc}"))
            continue

        if not isinstance(payload, dict):
            issues.append(ValidationIssue(path, "$", "expected an object"))
            continue

        try:
            conversation = parse_conversation(payload)
        except ValidationError as exc:
            issues.extend(
                ValidationIssue(
                    file=path,
                    field=_field_path(tuple(error["loc"])),
                    message=error["msg"],
                )
                for error in exc.errors()
            )
            continue

        if first_file := first_file_by_id.get(conversation.id):
            issues.append(
                ValidationIssue(
                    path,
                    "id",
                    f"duplicate conversation ID first seen in {first_file.name}",
                )
            )
            continue

        first_file_by_id[conversation.id] = path
        conversations.append(conversation)

    sorted_issues = _sort_issues(issues)
    if sorted_issues:
        return CorpusValidation((), sorted_issues)
    return CorpusValidation(tuple(conversations), ())


def format_issue(issue: ValidationIssue) -> str:
    return f"{issue.file.name}: {issue.field}: {issue.message}"
