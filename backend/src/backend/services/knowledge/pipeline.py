"""The whole knowledge pipeline behind one function, plus its release checks (#20).

``run_pipeline(payload)`` takes fixed JSON in and returns fixed JSON out:

    {
      "company_id": "acme",
      "conversations": [<ABCD records>],
      "existing_entries": [...],          # optional, from the backend
      "references": [...],                # optional, approved reference passages
      "as_of": "2026-10-22",              # optional, for reference expiry
      "config": {"extraction": {...}, "grouping": {...}, "conflicts": {...}, "verification": {...}}
    }

It runs extraction (#16), grouping (#17), conflict finding (#18) and
verification (#19) and returns all of their outputs. A conversation that
fails (invalid, oversized, model failure) is reported under
``technical_failures`` and the rest still run; a draft that simply has no
supporting reference shows up as ``unverifiable`` in ``verification``. The two
are never mixed up.

``release_checks(output, payload)`` is the gate before anything is shown to
people: fabricated citations, unsupported "supported" claims, leaked personal
data, or any sign of the pipeline approving something or changing a status
block release.
"""

from __future__ import annotations

import json
import time
from collections.abc import Mapping
from typing import Any

from .abcd import Conversation, read_conversation
from .conflicts import ConflictConfig, find_conflicts
from .errors import PipelineError, invalid
from .extraction import (
    ExtractionConfig,
    Extractor,
    RuleExtractor,
    check_draft_citations,
    extract_drafts,
)
from .grouping import GroupingConfig, group_drafts
from .privacy import Redactor
from .verification import VerificationConfig, check_drafts

PIPELINE_SCHEMA_VERSION = "knowledge-pipeline/1"
_FORBIDDEN_KEYS = {
    "approved",
    "approved_at_by_ml",
    "verified_at",
    "dispute_flag",
    "replaced_by",
    "audit_ready",
}


def _config(raw: Any, cls: type, name: str):
    if raw is None:
        return cls()
    if not isinstance(raw, Mapping):
        raise invalid(f"config.{name}", "must be an object")
    try:
        if cls is ExtractionConfig and "topics" in raw and raw["topics"] is not None:
            raw = {**raw, "topics": frozenset(raw["topics"])}
        return cls(**raw)
    except TypeError as error:
        raise invalid(f"config.{name}", str(error)) from error


def run_pipeline(
    payload: Any,
    extractor: Extractor | None = None,
    include_timings: bool = False,
) -> dict[str, Any]:
    """Run every stage. Returns ``status: "error"`` (and nothing else) only when the payload itself is unusable."""
    started = time.perf_counter()
    timings: dict[str, float] = {}
    try:
        if not isinstance(payload, Mapping):
            raise invalid("$", "payload must be a JSON object")
        company_id = payload.get("company_id")
        if not isinstance(company_id, str) or not company_id:
            raise invalid("company_id", "must be a non-empty string")
        records = payload.get("conversations")
        if not isinstance(records, list):
            raise invalid("conversations", "must be an array")
        config = payload.get("config") or {}
        if not isinstance(config, Mapping):
            raise invalid("config", "must be an object")
        extraction_config = _config(
            config.get("extraction"), ExtractionConfig, "extraction"
        )
        grouping_config = _config(config.get("grouping"), GroupingConfig, "grouping")
        conflict_config = _config(config.get("conflicts"), ConflictConfig, "conflicts")
        verification_config = _config(
            config.get("verification"), VerificationConfig, "verification"
        )
        entries = payload.get("existing_entries", [])
        references = payload.get("references", [])
    except PipelineError as error:
        return {
            "schema": PIPELINE_SCHEMA_VERSION,
            "status": "error",
            "errors": [error.to_dict()],
        }

    extractor = extractor or RuleExtractor()
    tick = time.perf_counter()
    results = [
        extract_drafts(r, company_id, extractor=extractor, config=extraction_config)
        for r in records
    ]
    timings["extraction_ms"] = (time.perf_counter() - tick) * 1000
    drafts: dict[str, dict[str, Any]] = {}
    for result in results:
        for draft in result.drafts:
            drafts.setdefault(draft["draft_id"], draft)
    failures = [
        {"index": i, "conversation_id": r.conversation_id, "errors": r.errors}
        for i, r in enumerate(results)
        if r.status == "error"
    ]
    draft_list = list(drafts.values())
    try:
        tick = time.perf_counter()
        groups = group_drafts(
            draft_list, company_id, existing_entries=entries, config=grouping_config
        )
        timings["grouping_ms"] = (time.perf_counter() - tick) * 1000
        tick = time.perf_counter()
        conflicts = find_conflicts(
            draft_list,
            company_id,
            existing_entries=entries,
            groups=groups,
            config=conflict_config,
        )
        timings["conflicts_ms"] = (time.perf_counter() - tick) * 1000
        tick = time.perf_counter()
        verification = check_drafts(
            draft_list,
            company_id,
            references,
            conflicts=conflicts,
            groups=groups,
            as_of=payload.get("as_of"),
            config=verification_config,
        )
        timings["verification_ms"] = (time.perf_counter() - tick) * 1000
    except PipelineError as error:
        return {
            "schema": PIPELINE_SCHEMA_VERSION,
            "status": "error",
            "errors": [error.to_dict()],
            "technical_failures": failures,
        }
    output: dict[str, Any] = {
        "schema": PIPELINE_SCHEMA_VERSION,
        "status": "completed_with_failures" if failures else "ok",
        "company_id": company_id,
        "counts": {
            "conversations": len(records),
            "technical_failures": len(failures),
            "no_draft": sum(1 for r in results if r.status == "ok" and not r.drafts),
            "drafts": len(draft_list),
            "groups": len(groups["groups"]),
            "possible_conflicts": sum(
                1
                for c in conflicts["possible_conflicts"]
                if c["status"] == "possible_conflict"
            ),
            "unresolved_conflicts": sum(
                1
                for c in conflicts["possible_conflicts"]
                if c["status"] == "unresolved"
            ),
            "verification": _tally(verification["results"]),
        },
        "extraction": [r.to_dict() for r in results],
        "technical_failures": failures,
        "drafts": draft_list,
        "groups": groups,
        "conflicts": conflicts,
        "verification": verification,
        "model_usage": _usage(extractor),
        "note": (
            "Unapproved drafts and findings for an authorized reviewer. The pipeline never approves, rejects, "
            "disputes or replaces knowledge and never changes a backend status."
        ),
    }
    if include_timings:
        timings["total_ms"] = (time.perf_counter() - started) * 1000
        output["timings"] = {k: round(v, 2) for k, v in timings.items()}
    return output


def _usage(extractor: Extractor) -> dict[str, Any]:
    client = getattr(extractor, "client", None)
    usage = getattr(client, "usage", None)
    if usage is None:
        return {"model": None, "calls": 0, "input_tokens": 0, "output_tokens": 0}
    return {"model": getattr(client, "name", None), **usage.to_dict()}


def _tally(results: list[dict[str, Any]]) -> dict[str, int]:
    tally: dict[str, int] = {}
    for result in results:
        tally[result["verification_status"]] = (
            tally.get(result["verification_status"], 0) + 1
        )
    return dict(sorted(tally.items()))


# --------------------------------------------------------------------------- release checks


def _walk(value: Any, path: str = "$"):
    if isinstance(value, Mapping):
        for key, item in value.items():
            yield f"{path}.{key}", key, item
            yield from _walk(item, f"{path}.{key}")
    elif isinstance(value, list):
        for index, item in enumerate(value):
            yield from _walk(item, f"{path}[{index}]")


def release_checks(
    output: Mapping[str, Any], payload: Mapping[str, Any]
) -> dict[str, Any]:
    """Checks that must all pass before results are shown to people."""
    checks: list[dict[str, Any]] = []
    company_id = payload.get("company_id", "")
    conversations: dict[str, Conversation] = {}
    for record in payload.get("conversations", []):
        try:
            conversation = read_conversation(record, company_id)
        except PipelineError:
            continue
        conversations[conversation.conversation_id] = conversation

    def add(name: str, problems: list[str], blocks: bool = True) -> None:
        checks.append(
            {
                "check": name,
                "passed": not problems,
                "blocks_release": blocks,
                "problems": problems[:50],
            }
        )

    # 1. Every draft citation is the exact text at its span.
    problems = []
    for draft in output.get("drafts", []):
        conversation = conversations.get(draft["source"]["conversation_id"])
        if conversation is None:
            problems.append(
                f"{draft['draft_id']}: cites a conversation that was not in the input"
            )
            continue
        problems += [
            f"{draft['draft_id']}: {p}"
            for p in check_draft_citations(draft, conversation)
        ]
    # Conflict passages must be the passages of the drafts they name.
    passages = {d["draft_id"]: d["answer_passages"] for d in output.get("drafts", [])}
    for conflict in output.get("conflicts", {}).get(
        "possible_conflicts", []
    ) + output.get("conflicts", {}).get("explained_differences", []):
        for side in ("a", "b"):
            draft_id = conflict[side].get("draft_id")
            if draft_id and conflict[side]["passage"] not in passages.get(draft_id, []):
                problems.append(
                    f"{conflict['conflict_id']}: side {side} quotes a passage its draft does not have"
                )
    # Verification citations must quote a reference that was supplied.
    references = {
        r.get("reference_id"): r
        for r in payload.get("references", [])
        if isinstance(r, Mapping)
    }
    for result in output.get("verification", {}).get("results", []):
        for claim in result["claims"]:
            for citation in claim["citations"] + claim["contradicted_by"]:
                reference = references.get(citation["reference_id"])
                if reference is None or not citation["quote"].startswith(
                    reference.get("text", "\0")
                ):
                    problems.append(
                        f"{result['draft_id']}: cites {citation['reference_id']} with text it does not have"
                    )
    add("no_fabricated_citations", problems)

    # 2. A "supported" claim needs an approved, eligible, authoritative citation.
    problems = []
    for result in output.get("verification", {}).get("results", []):
        for claim in result["claims"]:
            if claim["status"] != "supported":
                continue
            good = [
                c
                for c in claim["citations"]
                if (c.get("approval") or {}).get("status") == "approved"
                and (c.get("eligibility") or {}).get("status") == "eligible"
                and references.get(c["reference_id"], {}).get("kind")
                == "authoritative_reference"
            ]
            if not good:
                problems.append(
                    f"{result['draft_id']}: supported claim without an approved, eligible citation"
                )
        if result["verification_status"] == "supported" and any(
            c["status"] != "supported" for c in result["claims"]
        ):
            problems.append(
                f"{result['draft_id']}: marked supported with unsupported claims"
            )
    add("no_unsupported_verified_claims", problems)

    # 3. No personal data from any input customer record appears anywhere in the output.
    problems = []
    text = json.dumps(output, ensure_ascii=False)
    for conversation in conversations.values():
        leaks = Redactor(conversation.customer_record).leaks(text)
        if leaks:
            problems.append(f"{conversation.conversation_id}: {', '.join(leaks)}")
    add("no_personal_data_leaks", problems)

    # 4. The pipeline approved nothing and changed no status.
    problems = []
    for draft in output.get("drafts", []):
        if (
            draft.get("status") != "draft"
            or draft.get("trusted")
            or draft.get("audit_eligible")
        ):
            problems.append(f"{draft['draft_id']}: is not an untrusted draft")
    for group in output.get("groups", {}).get("groups", []):
        if group.get("status") != "draft":
            problems.append(f"{group['group_id']}: group status is not draft")
    for result in output.get("verification", {}).get("results", []):
        if result.get("decision") is not None:
            problems.append(f"{result['draft_id']}: has a decision")
    for path, key, _ in _walk(output):
        if key in _FORBIDDEN_KEYS:
            problems.append(f"{path}: forbidden field")
    add("ml_approves_nothing", problems)

    passed = all(c["passed"] for c in checks if c["blocks_release"])
    return {"release_allowed": passed, "checks": checks}


def repeat_processing_check(
    payload: Mapping[str, Any], extractor: Extractor | None = None
) -> dict[str, Any]:
    """Running twice, or with every conversation twice, must not change results or raise counts."""
    first = run_pipeline(payload, extractor=extractor)
    second = run_pipeline(payload, extractor=extractor)
    doubled = run_pipeline(
        {**payload, "conversations": list(payload.get("conversations", [])) * 2},
        extractor=extractor,
    )
    problems = []
    if first != second:
        problems.append("two runs on the same input differ")

    def counts(output: Mapping[str, Any]) -> dict[str, int]:
        return {
            g["group_id"]: g["distinct_conversation_count"]
            for g in output.get("groups", {}).get("groups", [])
        }

    if counts(first) != counts(doubled):
        problems.append(
            "processing every conversation twice changed a group or its count"
        )
    if first.get("counts", {}).get("drafts") != doubled.get("counts", {}).get("drafts"):
        problems.append(
            "processing every conversation twice changed the number of drafts"
        )
    return {"check": "repeat_processing", "passed": not problems, "problems": problems}
