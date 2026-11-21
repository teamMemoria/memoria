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
    # **Builds the final report**
    extraction = [r.to_dict() for r in results]
    output: dict[str, Any] = {
        "schema": PIPELINE_SCHEMA_VERSION,
        "status": "completed_with_failures" if failures else "ok",
        "company_id": company_id,
        "counts": _counts(extraction, draft_list, groups, conflicts, verification),
        "extraction": extraction,
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


# **Reports model usage**
def _usage(extractor: Extractor) -> dict[str, Any]:
    client = getattr(extractor, "client", None)
    usage = getattr(client, "usage", None)
    if usage is None:
        return {"model": None, "calls": 0, "input_tokens": 0, "output_tokens": 0}
    return {"model": getattr(client, "name", None), **usage.to_dict()}


# **Counts drafts by verification result**
def _tally(results: list[dict[str, Any]]) -> dict[str, int]:
    tally: dict[str, int] = {}
    for result in results:
        tally[result["verification_status"]] = (
            tally.get(result["verification_status"], 0) + 1
        )
    return dict(sorted(tally.items()))


# **Summary counts for the report**
def _counts(extraction, drafts, groups, conflicts, verification) -> dict[str, Any]:
    return {
        "conversations": len(extraction),
        "technical_failures": sum(r["status"] == "error" for r in extraction),
        "no_draft": sum(r["status"] == "ok" and not r["drafts"] for r in extraction),
        "drafts": len(drafts),
        "groups": len(groups["groups"]),
        "possible_conflicts": sum(
            c["status"] == "possible_conflict" for c in conflicts["possible_conflicts"]
        ),
        "unresolved_conflicts": sum(
            c["status"] == "unresolved" for c in conflicts["possible_conflicts"]
        ),
        "verification": _tally(verification["results"]),
    }





# **Goes through every field in the report**
def _walk(value: Any, path: str = "$"):
    if isinstance(value, Mapping):
        for key, item in value.items():
            yield f"{path}.{key}", key, item
            yield from _walk(item, f"{path}.{key}")
    elif isinstance(value, list):
        for index, item in enumerate(value):
            yield from _walk(item, f"{path}[{index}]")


# **Fields that are IDs, not text**
_ID_KEYS = {
    "schema",
    "source_key",
    "source_keys",
    "version",
    "source_version",
    "dataset_version",
    "snapshot_id",
    "span",
}


# **Collects the report text for the privacy check**
def output_text(value: Any) -> str:
    """Every human-readable string in an output, one per line, leaving out ids, keys and versions.

    Personal-data checks run on this, so an id such as "ABCD:8620" is never
    mistaken for a zip code and a number in a hash for a card number.
    """
    lines: list[str] = []

    def visit(item: Any, key: str = "") -> None:
        if (
            key in _ID_KEYS
            or key.endswith(("_id", "_ids"))
            or key in {"combined_from", "parent"}
        ):
            return
        if isinstance(item, str):
            lines.append(item)
        elif isinstance(item, Mapping):
            for k, v in item.items():
                visit(v, str(k))
        elif isinstance(item, list):
            for v in item:
                visit(v, key)

    visit(value)
    return "\n".join(lines)


# **Allowed values for results and statuses**
_VERDICTS = {"supported", "partially_supported", "contradicted", "unverifiable"}
_RECOMMENDATIONS = {
    "supported_by_references",
    "needs_more_evidence",
    "contradicted_by_references",
    "cannot_be_verified",
}
_CONFLICT_STATUSES = {"possible_conflict", "unresolved"}
# Where a copy of a reference's approval may appear: inside a citation.
_CITATION_LISTS = (".citations[", ".contradicted_by[", ".possibly_contradicted_by[")


# **Report without timing fields, for comparison**
def _comparable(output: Mapping[str, Any]) -> dict[str, Any]:
    return {
        k: v
        for k, v in output.items()
        if k not in {"timings", "release_checks", "model_usage"}
    }


# **Spots a quoted passage**
def _is_passage(value: Any) -> bool:
    return (
        isinstance(value, Mapping)
        and {"conversation_id", "turn_id", "span", "quote"} <= value.keys()
    )


# **Release checks: everything must pass before anyone sees the results (#20)**
def release_checks(
    output: Mapping[str, Any],
    payload: Mapping[str, Any],
    extractor: Extractor | None = None,
) -> dict[str, Any]:
    """Checks that must all pass before results are shown to people.

    They are checked against the payload, never against values copied into
    the output, so an edited output cannot vouch for itself.
    """
    required = {
        "company_id",
        "extraction",
        "groups",
        "conflicts",
        "verification",
        "counts",
        "technical_failures",
        "model_usage",
    }
    if (
        not isinstance(output, Mapping)
        or not required <= output.keys()
        or output.get("schema") != PIPELINE_SCHEMA_VERSION
        or output.get("company_id") != payload.get("company_id")
        or output.get("status") not in ("ok", "completed_with_failures")
        or not isinstance(output.get("drafts"), list)
    ):
        return {
            "release_allowed": False,
            "checks": [
                {
                    "check": "output_is_well_formed",
                    "passed": False,
                    "blocks_release": True,
                    "problems": ["missing or invalid report fields"],
                }
            ],
        }
    checks: list[dict[str, Any]] = []
    company_id = payload.get("company_id", "")
    conversations: dict[str, Conversation] = {}
    for record in payload.get("conversations", []):
        try:
            conversation = read_conversation(record, company_id)
        except PipelineError:
            continue
        conversations[conversation.conversation_id] = conversation
    redacted = {cid: redact_conversation(c) for cid, c in conversations.items()}
    references = {
        r.get("reference_id"): r
        for r in payload.get("references", []) or []
        if isinstance(r, Mapping)
    }
    entries = {
        (e.get("entry_id"), str(e.get("version"))): e
        for e in payload.get("existing_entries", []) or []
        if isinstance(e, Mapping)
    }
    as_of = None
    try:
        as_of = (
            dt.date.fromisoformat(payload["as_of"]) if payload.get("as_of") else None
        )
    except (TypeError, ValueError):
        as_of = None

    def add(name: str, problems: list[str], blocks: bool = True) -> None:
        checks.append(
            {
                "check": name,
                "passed": not problems,
                "blocks_release": blocks,
                "problems": problems[:50],
            }
        )

    try:
        drafts = {
            d.get("draft_id"): d for d in output["drafts"] if isinstance(d, Mapping)
        }
        counts = output["counts"]
        integers = [v for k, v in counts.items() if k != "verification"]
        integers.extend(counts["verification"].values())
        expected_counts = _counts(
            output["extraction"],
            output["drafts"],
            output["groups"],
            output["conflicts"],
            output["verification"],
        )
        add(
            "counts_match_assessment",
            []
            if counts == expected_counts
            and all(type(n) is int and n >= 0 for n in integers)
            else ["counts must be nonnegative integers derived from the assessment"],
        )
        _citation_checks(
            output, conversations, redacted, references, entries, drafts, add
        )
        _support_checks(output, references, company_id, as_of, add)
        _privacy_checks(output, conversations, add)
        _status_checks(output, entries, add)
        _recompute_check(output, payload, extractor, add)
    except (KeyError, TypeError, AttributeError, ValueError, PipelineError) as error:
        # A malformed output is never released, and never crashes the check.
        add(
            "output_is_well_formed",
            [f"the output is malformed: {type(error).__name__}"],
        )

    passed = all(c["passed"] for c in checks if c["blocks_release"])
    return {"release_allowed": passed, "checks": checks}


# **Release check 1: every quote matches its source**
def _citation_checks(
    output, conversations, redacted, references, entries, drafts, add
) -> None:
    """1. Every quoted text is exactly what its source says, wherever it appears."""
    problems: list[str] = []
    for draft_id, draft in drafts.items():
        conversation = conversations.get(
            (draft.get("source") or {}).get("conversation_id")
        )
        if conversation is None:
            problems.append(
                f"{draft_id}: cites a conversation that was not in the input"
            )
            continue
        problems += [
            f"{draft_id}: {p}" for p in check_draft_citations(draft, conversation)
        ]
    # Any passage anywhere in the output (groups, conflicts, verification).
    for path, _, value in _walk(output):
        if _is_passage(value):
            conversation = conversations.get(value["conversation_id"])
            if conversation is None:
                problems.append(
                    f"{path}: cites a conversation that was not in the input"
                )
                continue
            problems += [
                f"{path}: {p}"
                for p in check_passage(
                    value, conversation, redacted[conversation.conversation_id]
                )
            ]
    for group in output.get("groups", {}).get("groups", []):
        rep = group.get("representative") or {}
        draft = drafts.get(rep.get("draft_id"))
        if draft is None or any(
            rep.get(k) != draft.get(k)
            for k in (
                "question",
                "answer",
                "question_passages",
                "answer_passages",
                "conditions",
            )
        ):
            problems.append(
                f"{group.get('group_id')}: representative is not its draft, unchanged"
            )
    conflicts = output.get("conflicts", {})
    for conflict in conflicts.get("possible_conflicts", []) + conflicts.get(
        "explained_differences", []
    ):
        for side_name in ("a", "b"):
            side = conflict[side_name]
            where = f"{conflict['conflict_id']} side {side_name}"
            if side.get("type") == "draft":
                draft = drafts.get(side.get("draft_id"))
                if draft is None or side["passage"] not in draft.get(
                    "answer_passages", []
                ):
                    problems.append(
                        f"{where}: quotes a passage its draft does not have"
                    )
                elif side.get("claim") not in side["passage"]["quote"]:
                    problems.append(f"{where}: claim is not the text of its passage")
            elif side.get("type") == "existing_entry":
                entry = entries.get((side.get("entry_id"), str(side.get("version"))))
                quote = (side.get("passage") or {}).get("quote")
                if (
                    entry is None
                    or not isinstance(quote, str)
                    or quote not in str(entry.get("answer", ""))
                    or side.get("claim") != quote
                ):
                    problems.append(
                        f"{where}: quotes an entry version that was not supplied"
                    )
            else:
                problems.append(f"{where}: unknown side type")
    for result in output.get("verification", {}).get("results", []):
        draft = drafts.get(result["draft_id"])
        if draft is None:
            problems.append(
                f"{result['draft_id']}: verifies a draft that is not in the output"
            )
            continue
        for claim in result["claims"]:
            if claim["passage"] not in draft.get("answer_passages", []) or claim[
                "claim"
            ] not in claim["passage"].get("quote", ""):
                problems.append(
                    f"{result['draft_id']}: a claim is not one of its draft's passages"
                )
            for citation in (
                claim["citations"]
                + claim["contradicted_by"]
                + claim.get("possibly_contradicted_by", [])
            ):
                problem = _citation_problem(citation, references)
                if problem:
                    problems.append(f"{result['draft_id']}: {problem}")
    add("no_fabricated_citations", problems)


# **Checks one citation against its reference**
def _citation_problem(
    citation: Mapping[str, Any], references: Mapping[str, Any]
) -> str | None:
    reference = references.get(citation.get("reference_id"))
    if reference is None:
        return f"cites {citation.get('reference_id')}, which was not supplied"
    combined = citation.get("combined_from")
    if combined:
        parts = [references.get(r) for r in combined]
        if combined[0] != reference.get("reference_id") or any(
            p is None for p in parts
        ):
            return f"cites {citation['reference_id']} combined with passages that were not supplied"
        expected = combine_texts([p["text"] for p in parts])
    else:
        expected = reference.get("text")
    if citation.get("quote") != expected:
        return f"cites {citation['reference_id']} with text it does not have"
    if citation.get("version") != reference.get("version"):
        return f"cites {citation['reference_id']} at a version that was not supplied"
    for key in ("approval", "eligibility"):
        if citation.get(key) != reference.get(key):
            return f"cites {citation['reference_id']} with a changed {key}"
    return None


# **Release check 2: "supported" needs an approved, current source**
def _support_checks(output, references, company_id, as_of, add) -> None:
    """2. A "supported" claim needs a citation the payload shows is usable today."""
    problems: list[str] = []
    for result in output.get("verification", {}).get("results", []):
        for claim in result["claims"]:
            if claim["status"] != "supported":
                continue
            good = [
                c
                for c in claim["citations"]
                if (ref := references.get(c.get("reference_id"))) is not None
                and all(
                    _ineligible(references.get(r, {}), company_id, as_of) is None
                    for r in (c.get("combined_from") or [c["reference_id"]])
                )
                and _framing(ref) is None
            ]
            if not good:
                problems.append(
                    f"{result['draft_id']}: supported claim without an approved, eligible, current citation"
                )
            if claim.get("contradicted_by") or claim.get("possibly_contradicted_by"):
                problems.append(
                    f"{result['draft_id']}: supported claim that a reference contradicts"
                )
        if result["verification_status"] == "supported" and any(
            c["status"] != "supported" for c in result["claims"]
        ):
            problems.append(
                f"{result['draft_id']}: marked supported with unsupported claims"
            )
    add("no_unsupported_verified_claims", problems)


# **Release check 3: no personal data in the report**
def _privacy_checks(output, conversations, add) -> None:
    """3. No personal data, by each record's values and by pattern alone."""
    problems: list[str] = []
    text = output_text(output)
    for conversation in conversations.values():
        leaks = Redactor(conversation.customer_record).leaks(text)
        if leaks:
            problems.append(f"{conversation.conversation_id}: {', '.join(leaks)}")
    # Independent of any record, so a missing or wrong record cannot hide a leak.
    patterns = pattern_leaks(text)
    if patterns:
        problems.append(f"output: {', '.join(patterns)}")
    add("no_personal_data_leaks", problems)


# **Release check 4: the pipeline approves nothing**
def _status_checks(output, entries, add) -> None:
    """4. The pipeline approved nothing and changed no status: every status is an allowed one."""
    problems: list[str] = []
    for draft in output.get("drafts", []):
        if (
            draft.get("status") != "draft"
            or draft.get("trusted") is not False
            or draft.get("audit_eligible") is not False
            or (draft.get("verification") or {}).get("status") != "not_verified"
        ):
            problems.append(
                f"{draft.get('draft_id')}: is not an untrusted, unverified draft"
            )
    for group in output.get("groups", {}).get("groups", []):
        if (
            group.get("status") != "draft"
            or (group.get("representative") or {}).get("status") != "draft"
        ):
            problems.append(f"{group.get('group_id')}: group status is not draft")
    conflicts = output.get("conflicts", {})
    for conflict in conflicts.get("possible_conflicts", []):
        if conflict.get("status") not in _CONFLICT_STATUSES:
            problems.append(
                f"{conflict.get('conflict_id')}: status {conflict.get('status')!r} is not allowed"
            )
    for conflict in conflicts.get("explained_differences", []):
        if conflict.get("status") != "explained_difference":
            problems.append(
                f"{conflict.get('conflict_id')}: status {conflict.get('status')!r} is not allowed"
            )
    for conflict in conflicts.get("possible_conflicts", []) + conflicts.get(
        "explained_differences", []
    ):
        for side_name in ("a", "b"):
            side = conflict.get(side_name) or {}
            if side.get("type") == "draft" and side.get("status") != "draft":
                problems.append(
                    f"{conflict.get('conflict_id')}: side {side_name} changed a draft status"
                )
            if side.get("type") == "existing_entry":
                entry = (
                    entries.get((side.get("entry_id"), str(side.get("version")))) or {}
                )
                if side.get("status") != entry.get("status", "unknown"):
                    problems.append(
                        f"{conflict.get('conflict_id')}: side {side_name} changed an entry status"
                    )
    for result in output.get("verification", {}).get("results", []):
        if "decision" not in result or result["decision"] is not None:
            problems.append(f"{result.get('draft_id')}: has a decision")
        if (
            result.get("verification_status") not in _VERDICTS
            or result.get("ml_recommendation") not in _RECOMMENDATIONS
        ):
            problems.append(
                f"{result.get('draft_id')}: verdict or recommendation is not an allowed value"
            )
        for claim in result.get("claims", []):
            if claim.get("status") not in _VERDICTS:
                problems.append(
                    f"{result.get('draft_id')}: claim status is not an allowed value"
                )
    for path, key, _ in _walk(output):
        if key in _FORBIDDEN_KEYS:
            problems.append(f"{path}: forbidden field")
        elif key == "approval" and not any(
            marker in path for marker in _CITATION_LISTS
        ):
            problems.append(f"{path}: an approval outside a citation")
        elif key == "decision" and not re.fullmatch(
            r"\$\.verification\.results\[\d+\]\.decision", path
        ):
            problems.append(f"{path}: a decision outside a verification result")
    add("ml_approves_nothing", problems)


# **Release check 5: the report matches a fresh run**
def _recompute_check(output, payload, extractor, add) -> None:
    """5. The output is exactly what a fresh run on the same payload gives.

    Model generation is not repeated; its drafts still go through the same
    deterministic grouping, conflict and verification rules.
    """
    names = {
        (d.get("extractor") or {}).get("name")
        for d in output.get("drafts", [])
        if isinstance(d, Mapping)
    }
    if (extractor is not None and not isinstance(extractor, RuleExtractor)) or names - {
        RuleExtractor.name
    }:
        drafts = output["drafts"]
        extracted = {}
        for result in output["extraction"]:
            for draft in result["drafts"]:
                extracted.setdefault(draft["draft_id"], draft)
        if len(output["extraction"]) != len(payload["conversations"]) or extracted != {
            d["draft_id"]: d for d in drafts
        }:
            add("matches_validated_drafts", ["extraction and report drafts differ"])
            return
        company = payload["company_id"]
        config = payload.get("config") or {}
        entries = payload.get("existing_entries", [])
        grouping_config, conflict_config, verification_config = _assessment_configs(
            config
        )
        groups = group_drafts(drafts, company, entries, grouping_config)
        conflicts = find_conflicts(drafts, company, entries, groups, conflict_config)
        verification = check_drafts(
            drafts,
            company,
            payload.get("references", []),
            conflicts,
            groups,
            payload.get("as_of"),
            verification_config,
        )
        expected = {
            "groups": groups,
            "conflicts": conflicts,
            "verification": verification,
        }
        add(
            "matches_validated_drafts",
            [
                f"{key} differs from its validated drafts"
                for key, value in expected.items()
                if output[key] != value
            ],
        )
        return
    fresh = _run_stages(payload, RuleExtractor())
    add(
        "matches_a_fresh_run",
        []
        if _comparable(fresh) == _comparable(output)
        else ["the output differs from a fresh run on the same payload"],
    )


# **Repeat check: running twice gives the same result and counts**
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
    if _comparable(first) != _comparable(second):
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
