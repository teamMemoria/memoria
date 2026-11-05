from __future__ import annotations

import datetime as dt
import re
import time
from collections.abc import Mapping
from typing import Any

from .abcd import MAX_BATCH_CONVERSATIONS, Conversation, read_conversation
from .conflicts import ConflictConfig, find_conflicts
from .errors import INTERNAL_ERROR, PipelineError, invalid
from .extraction import (
    ExtractionConfig,
    Extractor,
    RuleExtractor,
    check_draft_citations,
    check_passage,
    extract_drafts,
    redact_conversation,
)
from .grouping import GroupingConfig, group_drafts
from .privacy import Redactor, pattern_leaks
from .verification import (
    VerificationConfig,
    _framing,
    _ineligible,
    check_drafts,
    combine_texts,
)

# **Output format version and fields the pipeline must never produce**
PIPELINE_SCHEMA_VERSION = "knowledge-pipeline/1"
_FORBIDDEN_KEYS = {
    "approved",
    "approved_at_by_ml",
    "verified_at",
    "dispute_flag",
    "replaced_by",
    "audit_ready",
}


# **Reads the settings for one step**
def _config(raw: Any, cls: type, name: str):
    if raw is None:
        return cls()
    if not isinstance(raw, Mapping):
        raise invalid(f"config.{name}", "must be an object")
    try:
        return cls(**raw)
    except TypeError as error:
        raise invalid(f"config.{name}", str(error)) from error


# **Reads the settings for grouping, conflicts and verification**
def _assessment_configs(config):
    return (
        _config(config.get("grouping"), GroupingConfig, "grouping"),
        _config(config.get("conflicts"), ConflictConfig, "conflicts"),
        _config(config.get("verification"), VerificationConfig, "verification"),
    )


# **Main entry point: runs every step, then the release checks**
def run_pipeline(
    payload: Any,
    extractor: Extractor | None = None,
    include_timings: bool = False,
) -> dict[str, Any]:
    """Run every stage and the release checks.

    Returns ``status: "error"`` (and nothing else) only when the payload itself
    is unusable. Otherwise the output carries ``release_checks``; nothing should
    be shown to people unless ``release_checks.release_allowed`` is true.
    """
    output = _run_stages(payload, extractor, include_timings)
    if output["status"] != "error":
        output["release_checks"] = release_checks(output, payload, extractor=extractor)
    return output


# **Runs the four steps in order: extraction, grouping, conflicts, verification**
def _run_stages(
    payload: Any,
    extractor: Extractor | None = None,
    include_timings: bool = False,
) -> dict[str, Any]:
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
        if len(records) > MAX_BATCH_CONVERSATIONS:
            raise PipelineError(
                "oversized_input",
                f"has {len(records)} conversations; the limit is {MAX_BATCH_CONVERSATIONS}",
                "conversations",
            )
        config = payload.get("config") or {}
        if not isinstance(config, Mapping):
            raise invalid("config", "must be an object")
        extraction_config = _config(
            config.get("extraction"), ExtractionConfig, "extraction"
        )
        grouping_config, conflict_config, verification_config = _assessment_configs(
            config
        )
        entries = payload.get("existing_entries", [])
        references = payload.get("references", [])
    except PipelineError as error:
        return {
            "schema": PIPELINE_SCHEMA_VERSION,
            "status": "error",
            "errors": [error.to_dict()],
        }

    # **Step 1: extract knowledge drafts from conversations (#16)**
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
        # **Step 2: group drafts and find duplicates (#17)**
        groups = group_drafts(
            draft_list, company_id, existing_entries=entries, config=grouping_config
        )
        timings["grouping_ms"] = (time.perf_counter() - tick) * 1000
        tick = time.perf_counter()
        # **Step 3: find possible conflicts (#18)**
        conflicts = find_conflicts(
            draft_list,
            company_id,
            existing_entries=entries,
            groups=groups,
            config=conflict_config,
        )
        timings["conflicts_ms"] = (time.perf_counter() - tick) * 1000
        tick = time.perf_counter()
        # **Step 4: check drafts against approved sources (#19)**
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
    except Exception as error:  # noqa: BLE001 - a bug must surface as an error, never as an empty result
        failure = PipelineError(
            INTERNAL_ERROR, f"pipeline failed: {type(error).__name__}", "pipeline"
        )
        return {
            "schema": PIPELINE_SCHEMA_VERSION,
            "status": "error",
            "errors": [failure.to_dict()],
            "technical_failures": failures,
        }
