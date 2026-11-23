"""Canonical assessment input, output and evidence validation. No engine or database."""

import hashlib
import json
from dataclasses import dataclass
from typing import Any, Protocol

from backend.entities.results import FindingResult

CRITERION_IDS = ("procedure", "answer-support", "completeness", "communication-style")
REPORT_SCHEMA_VERSION = 1
RESULTS = {
    "meets-criteria": FindingResult.PASS,
    "needs-review": FindingResult.NEEDS_WORK,
    "cannot-assess": FindingResult.CANNOT_ASSESS,
}


@dataclass(frozen=True)
class AnalysisRequest:
    """Everything the analysis may use, with the versions it must cite."""

    # {"id", "transcript_version", "events": [{"turn_id", "kind", "speaker",
    #  "text", "source_pointer"}]}; turn_id is the original turn number.
    conversation: dict[str, Any]
    # Approved entries that apply: {"id", "section_id", "version", "title",
    # "text", "status"}. Only these may be cited.
    references: list[dict[str, Any]]
    # The active evaluation form version's criteria, in order.
    criteria: list[dict[str, Any]]
    evaluation_form_version: int
    as_of: str
    scope: str
    canonical_evidence: dict[str, Any] | None = None


class AnalysisAdapter(Protocol):
    def analyse(self, request: AnalysisRequest) -> dict[str, Any]:
        """Return a feedback report. May block; it runs in a worker thread."""
        ...


class AnalysisUnavailableError(Exception):
    """No analysis is configured, or it could not be reached."""


class UnconfiguredAnalysisAdapter:
    """The default until an analysis service is configured: every run fails visibly."""

    def analyse(self, request: AnalysisRequest) -> dict[str, Any]:
        raise AnalysisUnavailableError("No analysis adapter is configured.")


class ReportRejectedError(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass
class CategoryResult:
    result: FindingResult
    feedback: str
    suggestion: str | None
    turn_numbers: list[int]
    reference_ids: list[int]


@dataclass(frozen=True)
class WeightProfile:
    id: str
    version: str
    weights: dict[str, int]


@dataclass
class ParsedReport:
    categories: dict[str, CategoryResult]
    summary: str | None
    report_version: str | None
    assessment_report: dict[str, Any] | None = None
    weight_profile: WeightProfile | None = None


def transcript_version(conversation_id: str, events: list[dict[str, Any]]) -> str:
    """A content hash of the evidence, so a report can be matched to it."""
    encoded = json.dumps(
        {"id": conversation_id, "events": events},
        sort_keys=True,
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode()
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


def _text(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _reject(code: str, message: str):
    raise ReportRejectedError(code, message)


def _check_citation(
    citation: Any,
    request: AnalysisRequest,
    events: dict[int, dict[str, Any]],
    references: dict[str, dict[str, Any]],
) -> tuple[str, int | str]:
    if not isinstance(citation, dict):
        _reject("invalid-citation", "A citation is not an object.")
    kind = citation.get("kind")
    if kind == "conversation":
        turn = citation.get("turn_id")
        event = events.get(turn) if type(turn) is int else None
        if (
            citation.get("conversation_id") != request.conversation["id"]
            or citation.get("transcript_version")
            != request.conversation["transcript_version"]
            or event is None
            or citation.get("event_kind") != event["kind"]
            or not _text(citation.get("quote"))
            or citation["quote"] not in event["text"]
        ):
            _reject(
                "invalid-citation",
                "A finding cites a turn or transcript version that was not supplied.",
            )
        return "conversation", turn
    if kind == "reference":
        reference = references.get(citation.get("reference_id"))
        if (
            reference is None
            or citation.get("reference_version") != reference["version"]
            or citation.get("section_id") != reference["section_id"]
            or not _text(citation.get("quote"))
            or citation["quote"] not in reference["text"]
        ):
            _reject(
                "invalid-citation",
                "A finding cites a reference or version that was not supplied.",
            )
        return "reference", reference["id"]
    _reject("invalid-citation", "A citation has an unknown kind.")


def parse_report(request: AnalysisRequest, report: Any) -> ParsedReport:
    """Check a report against the request and turn it into category results.

    Any malformed value, including one of the wrong type, rejects the report;
    nothing from it is saved.
    """
    try:
        if isinstance(report, dict) and (
            "overall" in report
            or any(
                isinstance(row, dict) and "scoring" in row
                for row in report.get("categories", [])
            )
        ):
            _reject(
                "unconfigured-assessment-validator",
                "Scored output requires an explicitly configured policy validator.",
            )
        return _parse_report(request, report)
    except (TypeError, KeyError, AttributeError, ValueError):
        raise ReportRejectedError(
            "invalid-report", "The report has a value of the wrong type."
        ) from None


def _parse_report(request: AnalysisRequest, report: Any) -> ParsedReport:
    if not isinstance(report, dict) or report.get("schema_version") != (
        REPORT_SCHEMA_VERSION
    ):
        _reject("invalid-report", "The report schema is not supported.")
    status = report.get("processing_status")
    if status != "complete":
        errors = report.get("errors")
        code = (
            errors[0].get("code")
            if isinstance(errors, list) and errors and isinstance(errors[0], dict)
            else None
        )
        _reject(
            f"report-{code}" if isinstance(code, str) and code else "report-incomplete",
            f"The analysis finished with status {status!r}.",
        )
    if (
        report.get("conversation_id") != request.conversation["id"]
        or report.get("transcript_version")
        != request.conversation["transcript_version"]
    ):
        _reject(
            "evidence-mismatch",
            "The report is for a different conversation or transcript version.",
        )

    rows = report.get("categories")
    if not isinstance(rows, list):
        _reject("invalid-report", "The report has no category list.")
    by_name = {}
    for row in rows:
        if not isinstance(row, dict) or row.get("category") not in CRITERION_IDS:
            _reject("invalid-report", "The report has an unknown category.")
        if row["category"] in by_name:
            _reject("invalid-report", "The report repeats a category.")
        by_name[row["category"]] = row
    if set(by_name) != set(CRITERION_IDS):
        _reject("invalid-report", "The report does not cover all four categories.")

    events = {event["turn_id"]: event for event in request.conversation["events"]}
    references = {reference["id"]: reference for reference in request.references}
    categories = {}
    for name in CRITERION_IDS:
        row = by_name[name]
        result = row.get("result")
        if row.get("status") != "completed" or not isinstance(result, dict):
            _reject("invalid-report", f"The {name} category did not complete.")
        verdict = RESULTS.get(result.get("result"))
        findings = result.get("findings")
        limitations = result.get("limitations")
        if (
            verdict is None
            or result.get("category") != name
            or not _text(result.get("explanation"))
            or not isinstance(findings, list)
            or not isinstance(limitations, list)
            or not all(_text(limitation) for limitation in limitations)
            or (verdict is FindingResult.NEEDS_WORK) != bool(findings)
            or (verdict is FindingResult.CANNOT_ASSESS and not limitations)
        ):
            _reject("invalid-report", f"The {name} result is malformed.")

        turns: set[int] = set()
        cited_references: list[int] = []
        explanations, suggestions = [], []
        for finding in findings:
            if (
                not isinstance(finding, dict)
                or not _text(finding.get("explanation"))
                or not _text(finding.get("advice"))
                or not isinstance(finding.get("citations"), list)
            ):
                _reject("invalid-report", f"A {name} finding is malformed.")
            kinds = set()
            for citation in finding["citations"]:
                kind, value = _check_citation(citation, request, events, references)
                kinds.add(kind)
                if kind == "conversation":
                    turns.add(value)
                elif int(value) not in cited_references:
                    cited_references.append(int(value))
            # A finding needing review must point at what the agent said.
            if "conversation" not in kinds:
                _reject("missing-evidence", f"A {name} finding cites no turn.")
            explanations.append(finding["explanation"].strip())
            suggestions.append(finding["advice"].strip())

        if verdict is FindingResult.NEEDS_WORK:
            feedback = " ".join(dict.fromkeys(explanations))
        elif verdict is FindingResult.CANNOT_ASSESS:
            feedback = " ".join(
                [result["explanation"].strip(), *dict.fromkeys(limitations)]
            )
        else:
            feedback = result["explanation"].strip()
        categories[name] = CategoryResult(
            result=verdict,
            feedback=feedback,
            suggestion=" ".join(dict.fromkeys(suggestions)) or None,
            turn_numbers=sorted(turns),
            reference_ids=cited_references,
        )

    summary = report.get("summary")
    claims = summary.get("claims") if isinstance(summary, dict) else None
    texts = [
        claim["text"].strip()
        for claim in claims or []
        if isinstance(claim, dict) and _text(claim.get("text"))
    ]
    versions = report.get("versions")
    report_version = versions.get("report") if isinstance(versions, dict) else None
    if report_version is not None and (
        not isinstance(report_version, str) or len(report_version) > 100
    ):
        _reject("invalid-report", "The report version is not a short text.")
    return ParsedReport(
        categories=categories,
        summary=" ".join(texts) or None,
        report_version=report_version,
    )


class ConversationNotFoundError(Exception):
    pass


class AlreadyAnalysedError(Exception):
    """A completed audit must never be replaced by a new attempt."""


class RetryRequiredError(Exception):
    """Failed attempts require explicit retry authorization."""


def reuse_active_run(active: bool, stale: bool, retry: bool) -> bool:
    return active and not (retry and stale)


def require_new_run(*, has_audit: bool, failed: bool, retry: bool):
    if has_audit:
        raise AlreadyAnalysedError
    if failed and not retry:
        raise RetryRequiredError
