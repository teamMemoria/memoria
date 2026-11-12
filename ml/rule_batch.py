"""Frozen training-cohort execution with content-bound, resumable checkpoints."""

from copy import deepcopy
from time import perf_counter

from .abcd import (
    ABCD_COMMIT,
    ABCD_SHA256,
    MIT_NOTICE,
    ORDER_FIELDS,
    PERSONAL_FIELDS,
    UNMASKED_DEMO_VERSION,
    prepare_conversation,
    validate_evidence,
)
from .rule_assessment import RULE_VERSION, assess_conversation
from .rule_links import VERSION as LINK_VERSION
from .scoring import VERSION, content_version, eligible_sources, validate_scored_report


def restore_demo_text(report, evidence, original_record):
    """Restore original training text without reinterpreting scored checks.

    Recognition used the historical masked representation. Reproduce that exact
    representation from the source before restoring whole-turn citations. The
    caller must verify the source file's pinned hash and validate both reports
    with their original rules and policies.
    This is an evidence representation change, not a new assessment or approval.
    """
    from .audit import category_result
    from .citations import validate_citations
    from .scoring import prioritise_findings

    validate_evidence(evidence)
    if len(evidence["conversations"]) != 1 or evidence["masking_version"] not in (
        "4",
        "5",
    ):
        raise ValueError("Restoration requires one historical masked conversation.")
    old = evidence["conversations"][0]
    if old["split"] != "train":
        raise ValueError("Only training demo text can be restored.")
    # Research annotations never enter preparation or the output.
    allowed = {
        key: original_record[key]
        for key in ("convo_id", "original", "scenario")
        if key in original_record
    }
    options = {
        "split": "train",
        "index": int(old["source_pointer"].rsplit("/", 1)[1]),
        "turn_ids": [e["turn_id"] for e in old["events"]],
    }
    if (
        prepare_conversation(
            allowed, **options, masking_version=evidence["masking_version"]
        )
        != old
    ):
        raise ValueError("Original text does not reproduce the historical evidence.")
    if any(
        report.get(key) != expected
        for key, expected in {
            "conversation_id": old["id"],
            "transcript_version": old["transcript_version"],
            "masking_version": evidence["masking_version"],
            "source": evidence["source"],
        }.items()
    ):
        raise ValueError("Report and historical evidence differ.")
    original = prepare_conversation(
        allowed, **options, masking_version=UNMASKED_DEMO_VERSION
    )
    restored_evidence = {
        **deepcopy(evidence),
        "masking_version": UNMASKED_DEMO_VERSION,
        "conversations": [original],
    }
    validate_evidence(restored_evidence)
    old_turns = {e["turn_id"]: e for e in old["events"]}
    turns = {e["turn_id"]: e for e in original["events"]}

    def restore(value):
        if isinstance(value, list):
            return [restore(item) for item in value]
        if not isinstance(value, dict):
            return value
        if value.get("kind") == "conversation":
            if validate_citations([value], [old], []):
                raise ValueError("Historical citation is invalid.")
            if value["quote"] != old_turns[value["turn_id"]]["text"]:
                raise ValueError(
                    "Restore only exact whole-turn citations, not guessed spans."
                )
            return {
                **value,
                "transcript_version": original["transcript_version"],
                "quote": turns[value["turn_id"]]["text"],
            }
        return {key: restore(item) for key, item in value.items()}

    restored = restore(report)
    restored.update(
        transcript_version=original["transcript_version"],
        masking_version=UNMASKED_DEMO_VERSION,
        evidence_restoration={
            "version": "original-demo-text-v1",
            "recognition_transcript_version": old["transcript_version"],
            "recognition_masking_version": evidence["masking_version"],
            "original_report_version": content_version(report),
        },
    )
    for row in restored["categories"]:
        if row["result"] is not None:
            row["result"] = category_result(
                original, row["category"], row["result"]["details"]["checks"]
            )
    restored["priorities"] = prioritise_findings(
        restored["categories"], restored["overall"]
    )
    return {"evidence": restored_evidence, "report": restored}


def prepare_cohort(
    training: list, source: dict, manifest: dict, *, masking_version="5"
) -> dict:
    """Prepare selected training records after the caller verifies source bytes.

    Invalid records are isolated; optional research-annotation alignment is a
    warning because only original dialogue/actions enter the canonical evidence.
    """
    expected_source = {
        "dataset": "ABCD",
        "commit": ABCD_COMMIT,
        "path": "data/abcd_v1.1.json",
        "sha256": ABCD_SHA256,
    }
    if not isinstance(training, list) or not isinstance(manifest, dict):
        raise TypeError(
            "Preparation requires the parsed training list and frozen manifest."
        )
    if source != expected_source or manifest.get("source") != source:
        raise ValueError("Training source pin does not match the frozen cohort.")
    if manifest.get("version") != content_version(
        {key: value for key, value in manifest.items() if key != "version"}
    ):
        raise ValueError("Frozen cohort version does not match its content.")
    records = manifest.get("conversations")
    if not isinstance(records, list) or not records:
        raise ValueError("Frozen cohort requires training record identities.")
    seen_ids, seen_positions = set(), set()
    for row in records:
        if (
            not isinstance(row, dict)
            or not isinstance(row.get("id"), str)
            or not row["id"].isdigit()
            or row.get("split") != "train"
            or type(row.get("source_index")) is not int
            or row["source_index"] < 0
            or row["id"] in seen_ids
            or row["source_index"] in seen_positions
        ):
            raise ValueError(
                "Cohort identities and training positions must be valid and unique."
            )
        seen_ids.add(row["id"])
        seen_positions.add(row["source_index"])
    evidence = {
        "schema_version": 1,
        "source": deepcopy(source),
        "masking_version": masking_version,
        "conversations": [],
        "licence": {"name": "MIT", "notice": MIT_NOTICE},
    }
    errors, warnings = {}, {}
    for row in records:
        identifier, index = row["id"], row["source_index"]
        try:
            if index >= len(training):
                raise ValueError(
                    "Frozen training position is missing; records are not replaced."
                )
            record = training[index]
            if (
                not isinstance(record, dict)
                or str(record.get("convo_id")) != identifier
            ):
                raise ValueError(
                    "Conversation ID does not match its frozen training position."
                )
            scenario = record.get("scenario", {})
            if not isinstance(scenario, dict):
                raise TypeError("Customer masking metadata must be an object.")
            masking = {}
            for group, fields in (
                ("personal", PERSONAL_FIELDS),
                ("order", ORDER_FIELDS),
            ):
                values = scenario.get(group, {})
                if not isinstance(values, dict):
                    raise TypeError("Customer masking groups must be objects.")
                masking[group] = {
                    key: value for key, value in values.items() if key in fields
                }
            allowed = {
                "convo_id": record["convo_id"],
                "original": record.get("original"),
                "scenario": masking,
            }
            if record.get("delexed") is not None:
                annotations = record["delexed"]
                allowed["delexed"] = (
                    [
                        {key: item.get(key) for key in ("speaker", "turn_count")}
                        if isinstance(item, dict)
                        else {}
                        for item in annotations
                    ]
                    if isinstance(annotations, list)
                    else {}
                )
            try:
                conversation = prepare_conversation(
                    allowed, split="train", index=index, masking_version=masking_version
                )
            except ValueError as error:
                if "/delexed" not in str(error):
                    raise
                warnings[identifier] = str(error)
                allowed.pop("delexed", None)
                conversation = prepare_conversation(
                    allowed, split="train", index=index, masking_version=masking_version
                )
            validate_evidence({**evidence, "conversations": [conversation]})
            evidence["conversations"].append(conversation)
        except (ValueError, TypeError) as error:
            errors[identifier] = f"{type(error).__name__}: {error}"
    return {"evidence": evidence, "errors": errors, "warnings": warnings}


def run_cohort(
    evidence,
    manifest,
    references,
    rubric,
    tables,
    *,
    as_of,
    checkpoint=None,
    development=False,
    preparation_errors=None,
):
    """Timing stays outside the pure evaluator; cached successes are revalidated."""
    expected_version = content_version(
        {key: value for key, value in manifest.items() if key != "version"}
    )
    if manifest.get("version") != expected_version or evidence.get(
        "source"
    ) != manifest.get("source"):
        raise ValueError("Frozen cohort version or source pin does not match.")
    records = manifest["conversations"]
    ids = [record["id"] for record in records]
    if len(ids) != len(set(ids)) or any(
        record["split"] != "train" for record in records
    ):
        raise ValueError("Cohort must contain unique official training records.")
    selected = manifest["development_ids"] if development else ids
    if len(selected) != len(set(selected)) or not set(selected) <= set(ids):
        raise ValueError(
            "Development records must be a distinct subset of the frozen cohort."
        )
    preparation_errors = preparation_errors or {}
    if not isinstance(preparation_errors, dict) or any(
        not isinstance(value, str) or not value for value in preparation_errors.values()
    ):
        raise ValueError("Preparation failures need explicit messages.")
    conversations = evidence["conversations"]
    supplied_ids = [conversation["id"] for conversation in conversations]
    if (
        len(supplied_ids) != len(set(supplied_ids))
        or set(supplied_ids) & set(preparation_errors)
        or set(supplied_ids) | set(preparation_errors) != set(ids)
    ):
        raise ValueError(
            "Prepared evidence must contain exactly the frozen cohort; no replacement records."
        )
    by_id = {conversation["id"]: conversation for conversation in conversations}
    positions = {record["id"]: f"/train/{record['source_index']}" for record in records}
    common = content_version(
        {
            "manifest": manifest,
            "references": references,
            "rubric": rubric,
            "tables": tables,
            "as_of": as_of,
            "report": VERSION,
            "rules": RULE_VERSION,
            "links": LINK_VERSION,
        }
    )
    previous = (checkpoint or {}).get("records", {})
    if not isinstance(previous, dict) or not set(previous) <= set(ids):
        raise ValueError("Checkpoint records do not belong to this frozen cohort.")
    result = {
        "schema_version": VERSION,
        "cohort_version": manifest["version"],
        "run_version": common,
        "records": {},
        "history": deepcopy((checkpoint or {}).get("history", [])),
        "human_review": deepcopy(manifest["human_spotcheck"]),
    }
    for identifier in selected:
        if identifier in preparation_errors:
            old = previous.get(identifier)
            if old:
                result["history"].append(
                    {"conversation_id": identifier, "attempt": deepcopy(old)}
                )
            result["records"][identifier] = {
                "key": content_version(
                    [common, identifier, preparation_errors[identifier]]
                ),
                "cached": False,
                "report": None,
                "error": preparation_errors[identifier],
                "elapsed_ms": 0.0,
            }
            continue
        single = {**evidence, "conversations": [by_id[identifier]]}
        key = content_version([common, single])
        old = previous.get(identifier)
        if (
            isinstance(old, dict)
            and old.get("key") == key
            and isinstance(old.get("report"), dict)
            and old["report"].get("processing_status") == "completed"
        ):
            try:
                report = old["report"]
                eligible = eligible_sources(
                    references,
                    rubric,
                    tables,
                    as_of=as_of,
                    workflows=report["workflows"],
                )
                validate_scored_report(report, single, eligible, tables, as_of=as_of)
            except (ValueError, TypeError, KeyError):
                pass
            else:
                result["records"][identifier] = {**deepcopy(old), "cached": True}
                continue
        if old:
            result["history"].append(
                {"conversation_id": identifier, "attempt": deepcopy(old)}
            )
        started = perf_counter()
        attempt = {"key": key, "cached": False, "report": None, "error": None}
        try:
            validate_evidence(single)
            conversation = single["conversations"][0]
            if (
                conversation["split"] != "train"
                or conversation["source_pointer"] != positions[identifier]
            ):
                raise ValueError("Original training split or source position changed.")
            attempt["report"] = assess_conversation(
                single, references, rubric, tables, as_of=as_of
            )
        except (ValueError, TypeError, KeyError) as error:
            attempt["error"] = f"{type(error).__name__}: {error}"
        attempt["elapsed_ms"] = round((perf_counter() - started) * 1000, 3)
        result["records"][identifier] = attempt
    # Resuming development then all records preserves every prior failure and result.
    for identifier, old in previous.items():
        if identifier not in result["records"]:
            result["history"].append(
                {"conversation_id": identifier, "attempt": deepcopy(old)}
            )
    return result


def cohort_summary(checkpoint):
    counts = {"completed": 0, "partial": 0, "failed": 0, "cached": 0}
    groups = {}
    for attempt in checkpoint["records"].values():
        report = attempt["report"]
        counts[report["processing_status"] if report else "failed"] += 1
        counts["cached"] += bool(attempt["cached"])
        if not report:
            continue
        for workflow in report["workflows"] or ["unresolved-purpose"]:
            for row in report["categories"]:
                group = groups.setdefault(
                    workflow + "/" + row["category"],
                    {
                        "records": 0,
                        "scored": 0,
                        "assessable": 0,
                        "possible": 0,
                        "unknown_inventory": 0,
                        "semantic_errors": None,
                    },
                )
                group["records"] += 1
                group["scored"] += row["scoring"]["score"] is not None
                group["assessable"] += row["scoring"]["assessable"]
                if row["scoring"]["possible"] is None:
                    group["unknown_inventory"] += 1
                else:
                    group["possible"] += row["scoring"]["possible"]
    return {
        "counts": counts,
        "candidate_workflow_metrics": groups,
        "semantic_accuracy": "not evaluated",
        "human_review": checkpoint["human_review"],
        "limitations": [
            "Candidate workflows overlap; their counts are not disjoint.",
            "Mechanical validation does not establish semantic accuracy.",
            "New approval records and human judgments remain pending.",
        ],
    }
