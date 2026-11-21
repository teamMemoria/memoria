from __future__ import annotations

import argparse
import json
import sys
from collections import Counter, defaultdict
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

REQUIRED_KEYS = {"id", "source", "modifications", "channel", "turns", "source_fields"}
SUPPORTED_DATASETS = {"ABCD", "HarperValleyBank"}
SUPPORTED_SPEAKERS = {"agent", "customer", "system_action"}


@dataclass(frozen=True)
class ValidationIssue:
    file: Path
    field: str
    message: str


@dataclass(frozen=True)
class ValidationResult:
    records: tuple[dict[str, Any], ...]
    issues: tuple[ValidationIssue, ...]


def _issue(file: Path, field: str, message: str) -> ValidationIssue:
    return ValidationIssue(file=file, field=field, message=message)


def _is_non_empty_string(value: object) -> bool:
    return isinstance(value, str) and value.strip() != ""


def _validate_record(record: dict[str, Any], file: Path) -> list[ValidationIssue]:
    issues = [
        _issue(file, key, "required field is missing")
        for key in sorted(REQUIRED_KEYS - record.keys())
    ]

    if "id" in record and not _is_non_empty_string(record["id"]):
        issues.append(_issue(file, "id", "must be a non-empty string"))

    source = record.get("source")
    dataset: str | None = None
    if isinstance(source, dict):
        candidate = source.get("dataset")
        if candidate in SUPPORTED_DATASETS:
            dataset = candidate
        else:
            issues.append(
                _issue(file, "source.dataset", "must be HarperValleyBank or ABCD")
            )
        if not _is_non_empty_string(source.get("original_id")):
            issues.append(
                _issue(file, "source.original_id", "must be a non-empty string")
            )
    elif "source" in record:
        issues.append(_issue(file, "source", "must be an object"))

    if "channel" in record and not isinstance(record["channel"], str):
        issues.append(_issue(file, "channel", "must be a string"))

    turns = record.get("turns")
    if isinstance(turns, list):
        if not turns:
            issues.append(_issue(file, "turns", "must contain at least one turn"))
        previous_number: int | None = None
        for index, turn in enumerate(turns):
            if not isinstance(turn, dict):
                issues.append(_issue(file, f"turns[{index}]", "must be an object"))
                continue

            number = turn.get("n")
            if type(number) is not int:
                issues.append(_issue(file, f"turns[{index}].n", "must be an integer"))
            else:
                if previous_number is not None and number <= previous_number:
                    issues.append(
                        _issue(
                            file,
                            f"turns[{index}].n",
                            "must be greater than the previous turn number",
                        )
                    )
                previous_number = number

            if turn.get("speaker") not in SUPPORTED_SPEAKERS:
                issues.append(
                    _issue(
                        file,
                        f"turns[{index}].speaker",
                        "must be agent, customer, or system_action",
                    )
                )

            if not isinstance(turn.get("text"), str):
                issues.append(_issue(file, f"turns[{index}].text", "must be a string"))
    elif "turns" in record:
        issues.append(_issue(file, "turns", "must be an array"))

    source_fields = record.get("source_fields")
    if isinstance(source_fields, dict):
        if dataset == "HarperValleyBank":
            tasks = source_fields.get("task_assigned")
            if not isinstance(tasks, list) or any(
                not isinstance(task, str) for task in tasks
            ):
                issues.append(
                    _issue(
                        file,
                        "source_fields.task_assigned",
                        "must be an array of strings",
                    )
                )
            if "agent_id" in record and not isinstance(record["agent_id"], str):
                issues.append(_issue(file, "agent_id", "must be a string"))
        elif dataset == "ABCD":
            for field in ("flow", "subflow"):
                if not isinstance(source_fields.get(field), str):
                    issues.append(
                        _issue(file, f"source_fields.{field}", "must be a string")
                    )
    elif "source_fields" in record:
        issues.append(_issue(file, "source_fields", "must be an object"))

    return issues


def _duplicate_issues(
    record: dict[str, Any],
    file: Path,
    seen_ids: dict[str, Path],
    seen_sources: dict[tuple[str, str], Path],
) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []

    record_id = record.get("id")
    if _is_non_empty_string(record_id):
        if record_id in seen_ids:
            issues.append(
                _issue(file, "id", f"duplicates the id in {seen_ids[record_id].name}")
            )
        else:
            seen_ids[record_id] = file

    source = record.get("source")
    if isinstance(source, dict):
        dataset = source.get("dataset")
        original_id = source.get("original_id")
        if dataset in SUPPORTED_DATASETS and _is_non_empty_string(original_id):
            key = (dataset, original_id)
            if key in seen_sources:
                issues.append(
                    _issue(
                        file,
                        "source.original_id",
                        f"duplicates the source record in {seen_sources[key].name}",
                    )
                )
            else:
                seen_sources[key] = file

    return issues


def validate_corpus(directory: Path) -> ValidationResult:
    if not directory.is_dir():
        return ValidationResult((), (_issue(directory, "$", "directory not found"),))

    paths = sorted(directory.glob("*.json"), key=lambda path: path.name)
    if not paths:
        return ValidationResult((), (_issue(directory, "$", "no JSON files found"),))

    records: list[dict[str, Any]] = []
    issues: list[ValidationIssue] = []
    # First file seen for each curated id and each (dataset, original_id) pair,
    # so a duplicate is reported against the later file, naming the earlier one.
    seen_ids: dict[str, Path] = {}
    seen_sources: dict[tuple[str, str], Path] = {}
    for path in paths:
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            issues.append(
                _issue(
                    path, "$", f"invalid JSON at line {exc.lineno}, column {exc.colno}"
                )
            )
            continue
        except (OSError, UnicodeError) as exc:
            issues.append(_issue(path, "$", f"could not read file: {exc}"))
            continue

        if not isinstance(value, dict):
            issues.append(_issue(path, "$", "must be a JSON object"))
            continue

        record_issues = _validate_record(value, path)
        record_issues.extend(_duplicate_issues(value, path, seen_ids, seen_sources))
        issues.extend(record_issues)
        if not record_issues:
            records.append(value)

    if issues:
        ordered = tuple(
            sorted(issues, key=lambda item: (item.file.name, item.field, item.message))
        )
        return ValidationResult((), ordered)
    return ValidationResult(tuple(records), ())


def _ordered(
    counter: Counter[str], key: Callable[[str], Any] | None = None
) -> dict[str, int]:
    return {name: counter[name] for name in sorted(counter, key=key)}


def _ordered_nested(
    counters: Mapping[str, Counter[str]],
    key: Callable[[str], Any] | None = None,
) -> dict[str, dict[str, int]]:
    return {dataset: _ordered(counters[dataset], key) for dataset in sorted(counters)}


def build_profile(records: Sequence[dict[str, Any]]) -> dict[str, object]:
    datasets: Counter[str] = Counter()
    channels: defaultdict[str, Counter[str]] = defaultdict(Counter)
    topics: defaultdict[str, Counter[str]] = defaultdict(Counter)
    agents: defaultdict[str, Counter[str]] = defaultdict(Counter)
    speakers: defaultdict[str, Counter[str]] = defaultdict(Counter)
    turn_counts: defaultdict[str, Counter[str]] = defaultdict(Counter)

    for record in records:
        dataset = record["source"]["dataset"]
        datasets[dataset] += 1
        channels[dataset][record["channel"]] += 1
        turns = record["turns"]
        turn_counts[dataset][str(len(turns))] += 1
        for turn in turns:
            speakers[dataset][turn["speaker"]] += 1

        if dataset == "HarperValleyBank":
            for topic in record["source_fields"]["task_assigned"]:
                topics[dataset][topic] += 1
            agents[dataset][record.get("agent_id") or "unavailable"] += 1
        else:
            fields = record["source_fields"]
            topics[dataset][f"{fields['flow']}/{fields['subflow']}"] += 1
            agents[dataset]["unavailable"] += 1

    return {
        # Keys are built in a fixed order (alphabetical, except turn counts,
        # which sort as numbers) so the output is deterministic without
        # sort_keys, which would sort "10" before "8".
        "distributions": {
            "agents": _ordered_nested(agents),
            "channels": _ordered_nested(channels),
            "datasets": _ordered(datasets),
            "speakers": _ordered_nested(speakers),
            "topics": _ordered_nested(topics),
            "turn_counts": _ordered_nested(turn_counts, key=int),
        },
        "files": len(records),
    }


def serialize_profile(profile: Mapping[str, object]) -> str:
    return json.dumps(profile, indent=2, ensure_ascii=False) + "\n"


def format_issue(issue: ValidationIssue) -> str:
    return f"{issue.file.name}: {issue.field}: {issue.message}"


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Validate and profile curated HVB and ABCD conversations."
    )
    parser.add_argument("directory", type=Path)
    args = parser.parse_args(argv)

    result = validate_corpus(args.directory)
    if result.issues:
        for issue in result.issues:
            print(format_issue(issue), file=sys.stderr)
        return 1

    print(serialize_profile(build_profile(result.records)), end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
