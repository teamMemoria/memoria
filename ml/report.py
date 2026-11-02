"""Local feedback assembly; only the runner measures execution time.

Deadlines are cooperative checks around synchronous rule groups, not cancellation.
Summary claims quote recognised source passages; they do not verify transactions.
"""

import json
from copy import deepcopy
from time import perf_counter

from .abcd import validate_evidence
from .audit import (
    CATEGORIES,
    eligible_criteria,
    validate_report_limits,
    validate_results,
    validate_rubric,
)
from .citations import validate_citations
from .completeness_style import RULE_VERSION as WORDING_VERSION
from .completeness_style import check_completeness_style
from .procedure_support import RULE_VERSION as PROCEDURE_VERSION
from .procedure_support import check_procedure_support
from .references import (
    OPTIONAL_CONTENT_FIELDS,
    RECORD_FIELDS,
    SOURCE_FIELDS,
    _has_text_fields,
    _text_list,
    eligible_references,
    reference_passages,
)

REPORT_VERSION = "local-feedback-v1"
DEFAULT_LIMITS = {
    "max_events": 200,
    "max_input_bytes": 256 * 1024,
    "max_output_bytes": 256 * 1024,
    "timeout_seconds": 2.0,
}


def _size(value):
    return len(
        json.dumps(
            value, ensure_ascii=False, allow_nan=False, separators=(",", ":")
        ).encode()
    )


def _limits(overrides):
    if overrides is not None and (
        not isinstance(overrides, dict) or overrides.keys() - DEFAULT_LIMITS.keys()
    ):
        raise ValueError("Unsupported report limits.")
    limits = DEFAULT_LIMITS | (overrides or {})
    validate_report_limits(limits)
    return limits


def _empty_report(limits):
    return {
        "schema_version": 1,
        "processing_status": "failed",
        "conversation_id": None,
        "transcript_version": None,
        "as_of": None,
        "scope": None,
        "source": None,
        "masking_version": None,
        "licence": None,
        "categories": [
            {"category": name, "status": "not-run", "result": None, "error": None}
            for name in CATEGORIES
        ],
        "topic": {"labels": [], "citations": [], "limitations": []},
        "summary": {"claims": [], "limitations": []},
        "versions": {
            "report": REPORT_VERSION,
            "limits": dict(limits),
            "rules": {
                "procedure-support": PROCEDURE_VERSION,
                "completeness-style": WORDING_VERSION,
            },
            "references": [],
            "rubric": [],
        },
        "metrics": {
            "engine": "local-rules",
            "elapsed_ms": 0.0,
            "model": None,
            "prompt": None,
            "token_usage": None,
            "model_call_cost_usd": 0.0,
        },
        "errors": [],
    }


def _error(report, code, message, names=(), *, status="failed"):
    for row in report["categories"]:
        if row["category"] in names:
            row.update(status=status, result=None, error=code)
    report["errors"].append(
        {
            "code": code,
            "category": names[0] if len(names) == 1 else None,
            "message": message,
        }
    )


def _sources(references, rubric, context):
    if not isinstance(references, list) or any(
        not isinstance(reference, dict)
        or reference.keys() - OPTIONAL_CONTENT_FIELDS != RECORD_FIELDS
        or not isinstance(reference["status"], str)
        for reference in references
    ):
        raise ValueError("Invalid reference catalog.")
    reference_passages(references)
    validate_rubric(rubric)
    sections = rubric["references"]
    for records, source_fields in (
        (references, SOURCE_FIELDS),
        (sections, {"kind", "path", "pointer"}),
    ):
        for reference in records:
            if not _has_text_fields(
                reference, ("id", "section_id", "title", "text", "version", "status")
            ):
                raise ValueError("Reference text fields are invalid.")
            if any(
                not _text_list(reference[field])
                for field in {"conditions", "exclusions", "scope", "safety_flags"}
                | (OPTIONAL_CONTENT_FIELDS & reference.keys())
            ):
                raise TypeError("Reference list fields are invalid.")
            source = reference["source"]
            if (
                not isinstance(source, dict)
                or source.keys() != source_fields
                or not _has_text_fields(source, source_fields)
            ):
                raise ValueError("Reference source fields are invalid.")
    eligible = eligible_references(references, **context) + eligible_criteria(
        sections, **context
    )
    identifiers = [reference["id"] for reference in eligible]
    if len(identifiers) != len(set(identifiers)):
        raise ValueError("Eligible guideline and rubric IDs must be unique.")
    return sections, eligible


def _narrative(conversation, completeness, eligible):
    limitations = (
        list(completeness["limitations"])
        if completeness
        else [
            "Request summary is unavailable because Completeness processing did not finish."
        ]
    )
    topic = {"labels": [], "citations": [], "limitations": list(limitations)}
    summary = {"claims": [], "limitations": limitations}
    if completeness is None:
        return topic, summary
    events = {event["turn_id"]: event for event in conversation["events"]}
    requests = completeness["details"].get("requests", [])
    if not isinstance(requests, list):
        raise TypeError("Request links are unavailable.")
    seen = set()
    for request in requests:
        if request["topic"] not in {
            "refund",
            "return",
            "method",
            "next-step",
        } or request["state"] not in {"active", "withdrawn", "superseded", "uncertain"}:
            raise ValueError("Unsupported request interpretation.")
        if request["topic"] not in topic["labels"]:
            topic["labels"].append(request["topic"])
        if request["state"] != "active":
            limitation = f"A recognised {request['topic']} request is {request['state']}; its original wording does not establish a current instruction."
            summary["limitations"].append(limitation)
            topic["limitations"].append(limitation)
        for field, kind in (
            ("request_citations", "request"),
            ("change_citations", "request-change"),
            ("response_citations", "agent-claim"),
        ):
            citations = request[field]
            if not isinstance(citations, list) or (
                field == "request_citations" and not citations
            ):
                raise ValueError("Request links require source citations.")
            if validate_citations(citations, [conversation], eligible):
                raise ValueError("Narrative citation is invalid.")
            for index, citation in enumerate(citations):
                if citation["kind"] != "conversation":
                    raise ValueError("Narrative claims require conversation evidence.")
                event = events[citation["turn_id"]]
                claim_kind = kind
                if field == "response_citations":
                    if event["speaker"] not in {"agent", "action"}:
                        raise ValueError("Response evidence has the wrong speaker.")
                    if event["kind"] == "action":
                        claim_kind = "recorded-action"
                    elif (
                        request["response_kind"] == "promise"
                        and index == len(citations) - 1
                    ):
                        claim_kind = "agent-promise"
                elif event["speaker"] != "customer":
                    raise ValueError("Request evidence has the wrong speaker.")
                identity = (claim_kind, json.dumps(citation, sort_keys=True))
                if identity not in seen:
                    seen.add(identity)
                    summary["claims"].append(
                        {
                            "kind": claim_kind,
                            "text": citation["quote"],
                            "citations": [deepcopy(citation)],
                        }
                    )
                if field == "request_citations" and citation not in topic["citations"]:
                    topic["citations"].append(deepcopy(citation))
    if not requests:
        reason = "No request topic was recognised within the supported wording forms."
        topic["limitations"].append(reason)
        summary["limitations"].append(reason)
    return topic, summary


def _accept_results(report, output, names, conversation, eligible, context):
    if not isinstance(output, list):
        _error(
            report,
            "invalid-result",
            "A rule group returned an invalid result collection.",
            names,
        )
        return
    if any(
        not isinstance(result, dict) or result.get("category") not in names
        for result in output
    ):
        _error(
            report, "invalid-result", "A rule group returned an unexpected category."
        )
    for name in names:
        matches = [
            result
            for result in output
            if isinstance(result, dict) and result.get("category") == name
        ]
        accepted = [
            row["result"]
            for row in report["categories"]
            if row["status"] == "completed"
        ]
        try:
            if len(matches) != 1:
                raise ValueError("Missing or duplicate category.")
            _size(matches[0])
            validate_results(
                conversation, accepted + matches, eligible, **context, require_all=False
            )
        except (ValueError, TypeError, KeyError, RecursionError):
            _error(
                report,
                "invalid-result",
                "A category result failed validation.",
                (name,),
            )
        else:
            row = next(row for row in report["categories"] if row["category"] == name)
            row.update(status="completed", result=deepcopy(matches[0]), error=None)


def run_feedback_report(evidence, references, rubric, *, as_of, scope, limits=None):
    """Run bounded local checks; callers own input/output files and scheduling.

    The output byte budget measures compact UTF-8 JSON. Budgets below 4096 bytes
    are invalid because the fixed, data-free error envelope must also fit.
    Model, prompt and token usage are unavailable because no model is executed.
    """
    limits = _limits(limits)
    started = perf_counter()
    report = _empty_report(limits)
    context = {"as_of": as_of, "scope": scope}
    try:
        if _size([evidence, references, rubric, context]) > limits["max_input_bytes"]:
            _error(
                report,
                "input-limit",
                "Combined input exceeds the configured byte limit.",
            )
            return _finish(report, started, limits)
        validate_evidence(evidence)
        if len(evidence["conversations"]) != 1:
            raise ValueError("A report requires one conversation.")
        conversation = evidence["conversations"][0]
        if len(conversation["events"]) > limits["max_events"]:
            _error(
                report,
                "input-limit",
                "Conversation exceeds the configured event limit.",
            )
            return _finish(report, started, limits)
        sections, eligible = _sources(references, rubric, context)
    except (ValueError, TypeError, KeyError, RecursionError):
        _error(
            report,
            "invalid-input",
            "Prepared evidence, context or reference catalogs are invalid.",
        )
        return _finish(report, started, limits)
    report.update(
        conversation_id=conversation["id"],
        transcript_version=conversation["transcript_version"],
        as_of=as_of,
        scope=scope,
    )
    for field in ("source", "masking_version", "licence"):
        report[field] = deepcopy(evidence[field])
    for field, catalog in (("references", references), ("rubric", sections)):
        report["versions"][field] = [
            {"id": reference["id"], "version": reference["version"]}
            for reference in catalog
        ]
    groups = (
        (
            ("procedure", "answer-support"),
            check_procedure_support,
            (conversation, references),
        ),
        (
            ("completeness", "communication-style"),
            check_completeness_style,
            (conversation, references, sections),
        ),
    )
    for names, check, arguments in groups:
        if perf_counter() - started > limits["timeout_seconds"]:
            _error(
                report,
                "deadline",
                "The cooperative deadline elapsed before this rule group.",
                names,
                status="not-run",
            )
            continue
        try:
            output = check(*arguments, **context)
        except Exception:  # noqa: BLE001 - Isolate failed checks without exposing their exceptions.
            _error(
                report, "check-failed", "A local rule group could not finish.", names
            )
            continue
        if perf_counter() - started > limits["timeout_seconds"]:
            _error(
                report,
                "deadline",
                "A rule group completed after the cooperative deadline.",
                names,
            )
        else:
            _accept_results(report, output, names, conversation, eligible, context)
    completeness = next(
        row["result"]
        for row in report["categories"]
        if row["category"] == "completeness"
    )
    if perf_counter() - started <= limits["timeout_seconds"]:
        try:
            report["topic"], report["summary"] = _narrative(
                conversation, completeness, eligible
            )
        except (ValueError, TypeError, KeyError):
            _error(
                report,
                "invalid-summary",
                "Recognised request links could not form a validated summary.",
            )
            report["summary"]["limitations"] = [
                "Summary processing failed; the category results remain separate."
            ]
    else:
        _error(
            report,
            "deadline",
            "The cooperative deadline elapsed before summary processing.",
        )
    completed = sum(row["status"] == "completed" for row in report["categories"])
    report["processing_status"] = (
        "complete"
        if completed == 4 and not report["errors"]
        else "partial"
        if completed
        else "failed"
    )
    return _finish(report, started, limits)


def _finish(report, started, limits):
    report["metrics"]["elapsed_ms"] = max(0.0, (perf_counter() - started) * 1000)
    if (
        report["processing_status"] != "failed"
        and report["metrics"]["elapsed_ms"] >= limits["timeout_seconds"] * 1000
        and not any(error["code"] == "deadline" for error in report["errors"])
    ):
        _error(
            report,
            "deadline",
            "The cooperative deadline elapsed during report assembly.",
        )
        report["processing_status"] = "partial"
    if _size(report) > limits["max_output_bytes"]:
        report = _empty_report(limits)
        _error(
            report,
            "output-limit",
            "The report exceeds the byte budget; no evidence was truncated.",
            CATEGORIES,
        )
        report["metrics"]["elapsed_ms"] = max(0.0, (perf_counter() - started) * 1000)
        if _size(report) > limits["max_output_bytes"]:
            raise ValueError("Output budget cannot contain the fixed error report.")
    return report
