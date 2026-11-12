"""Post-call analysis: start a run, call the analysis adapter, save the audit.

The adapter follows the post-call feedback report contract in ``ml/report.py``
(``run_feedback_report``): it receives one conversation's versioned evidence,
the approved references that apply to it and the active evaluation criteria,
and returns a report whose ``categories`` hold the four category results.

Nothing from the report is trusted until ``parse_report`` has checked it
against the evidence that was sent. A report that is not complete, cites turns
or reference versions that were not supplied, or does not match the transcript
version is a technical failure of the run. Technical failures never become
cannot-assess results and never create an audit.

A conversation has at most one audit. A finished audit is never replaced by a
later run, and a failed run is only retried when someone asks for it.
"""

import asyncio
import hashlib
import json
import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Protocol

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from backend.models import (
    ACTIVE_RUN_STATUSES,
    AnalysisRun,
    AnalysisRunStatus,
    Audit,
    Conversation,
    EntryStatus,
    EvaluationFormVersion,
    Finding,
    FindingResult,
    KnowledgeEntry,
    Organization,
    Speaker,
)
from backend.providers.database import (
    CATEGORY_FOR_CRITERION,
    CRITERION_FOR_CATEGORY,
    SessionFactory,
    parse_id,
    unavailable_on_database_error,
)
from backend.schemas.call_review import CRITERION_IDS
from backend.services.clock import utc_now

logger = logging.getLogger(__name__)

STALE_RUN_AFTER = timedelta(minutes=15)

REPORT_SCHEMA_VERSION = 1
RESULTS = {
    "meets-criteria": FindingResult.PASS,
    "needs-review": FindingResult.NEEDS_WORK,
    "cannot-assess": FindingResult.CANNOT_ASSESS,
}
EVENT_SPEAKERS = {
    Speaker.AGENT: "agent",
    Speaker.CUSTOMER: "customer",
    Speaker.SYSTEM_ACTION: "action",
}


# --- what the adapter receives and returns ---------------------------------------------


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
    scoring_context: dict[str, Any] | None = None


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


@dataclass
class ParsedReport:
    categories: dict[str, CategoryResult]
    summary: str | None
    report_version: str | None
    assessment_report: dict[str, Any] | None = None


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
        if (
            isinstance(report, dict)
            and report.get("schema_version") == "rule-scoring-v1"
        ):
            from backend.services.rule_assessment import parse_rule_report

            return parse_rule_report(request, report)
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


# --- runs -----------------------------------------------------------------------------


class ConversationNotFoundError(Exception):
    pass


class AlreadyAnalysedError(Exception):
    """The conversation has an audit; a new run would replace it."""


class RetryRequiredError(Exception):
    """The last run failed; starting again must be an explicit retry."""


@dataclass
class StartResult:
    run: AnalysisRun
    created: bool


@dataclass
class AnalysisService:
    sessions: SessionFactory
    adapter: AnalysisAdapter = field(default_factory=UnconfiguredAnalysisAdapter)
    now: Callable[[], datetime] = utc_now
    # How long a queued or running run may go before a retry may replace it.
    stale_after: timedelta = STALE_RUN_AFTER
    scoring_context: dict[str, Any] | None = None

    async def _conversation(
        self, session: AsyncSession, organization_id: str, conversation_id: str
    ) -> Conversation | None:
        key = parse_id(conversation_id)
        if key is None:
            return None
        return await session.scalar(
            select(Conversation)
            .join(Organization, Organization.id == Conversation.organization_id)
            .where(Organization.slug == organization_id, Conversation.id == key)
        )

    @unavailable_on_database_error
    async def runs(
        self, organization_id: str, conversation_id: str
    ) -> list[AnalysisRun]:
        """Every attempt for a conversation in the organization, newest first."""
        async with self.sessions() as session:
            conversation = await self._conversation(
                session, organization_id, conversation_id
            )
            if conversation is None:
                raise ConversationNotFoundError
            return list(
                await session.scalars(
                    select(AnalysisRun)
                    .where(AnalysisRun.conversation_id == conversation.id)
                    .order_by(AnalysisRun.attempt.desc())
                )
            )

    @unavailable_on_database_error
    async def start(
        self,
        organization_id: str,
        conversation_id: str,
        *,
        requested_by: str | None,
        retry: bool = False,
    ) -> StartResult:
        """Queue a run, or return the one already queued or running.

        A run that has been queued or running for longer than ``stale_after``
        is treated as lost (the process running it stopped). With
        ``retry=True`` it is marked failed and a new run is queued.
        """
        async with self.sessions() as session:
            conversation = await self._conversation(
                session, organization_id, conversation_id
            )
            if conversation is None:
                raise ConversationNotFoundError
            # Plain values, because a rollback below expires loaded objects.
            conversation_key = conversation.id
            organization_key = conversation.organization_id
            latest = await session.scalar(
                select(AnalysisRun)
                .where(AnalysisRun.conversation_id == conversation_key)
                .order_by(AnalysisRun.attempt.desc())
                .limit(1)
            )
            if latest is not None and latest.status in ACTIVE_RUN_STATUSES:
                if not (retry and self._is_stale(latest)):
                    return StartResult(latest, created=False)
                self._mark_failed(
                    latest,
                    "timed-out",
                    "The run did not finish and was replaced by a retry.",
                )
                await session.flush()
            has_audit = await session.scalar(
                select(func.count())
                .select_from(Audit)
                .where(Audit.conversation_id == conversation_key)
            )
            if has_audit:
                raise AlreadyAnalysedError
            if (
                latest is not None
                and latest.status is AnalysisRunStatus.FAILED
                and not retry
            ):
                raise RetryRequiredError

            run = AnalysisRun(
                organization_id=organization_key,
                conversation_id=conversation_key,
                status=AnalysisRunStatus.QUEUED,
                attempt=(latest.attempt + 1) if latest else 1,
                requested_by=requested_by,
                created_at=self.now(),
            )
            session.add(run)
            try:
                await session.commit()
            except IntegrityError:
                # Another request queued a run between our check and insert.
                await session.rollback()
                active = await session.scalar(
                    select(AnalysisRun).where(
                        AnalysisRun.conversation_id == conversation_key,
                        AnalysisRun.status.in_(ACTIVE_RUN_STATUSES),
                    )
                )
                if active is None:
                    raise
                return StartResult(active, created=False)
            return StartResult(run, created=True)

    def _is_stale(self, run: AnalysisRun) -> bool:
        return self.now() - (run.started_at or run.created_at) > self.stale_after

    def _mark_failed(self, run: AnalysisRun, code: str, message: str) -> None:
        run.status = AnalysisRunStatus.FAILED
        run.error_code = code[:50]
        run.error_message = message
        run.finished_at = self.now()

    async def execute(self, run_id: int) -> AnalysisRun | None:
        """Run a queued attempt to completion. Every failure is recorded on the run.

        Called as a background task, so nothing is raised. Any error, whether
        from the adapter, its output or saving, ends the run as failed with an
        error code, so a run is never left running by a problem it hit. Only if
        the database itself cannot record the failure does the run stay
        running; a later retry replaces it once it is stale.
        """
        try:
            return await self._execute(run_id)
        except Exception:
            logger.exception("Analysis run %s failed unexpectedly", run_id)
            return await self._record_failure(
                run_id, "internal-error", "The run stopped on an unexpected error."
            )

    async def _record_failure(
        self, run_id: int, code: str, message: str
    ) -> AnalysisRun | None:
        """Mark a run failed in a fresh session, after the first one went wrong."""
        try:
            async with self.sessions() as session:
                await session.rollback()
                run = await session.get(AnalysisRun, run_id)
                if run is None or run.status not in ACTIVE_RUN_STATUSES:
                    return run
                self._mark_failed(run, code, message)
                await session.commit()
                return run
        except (SQLAlchemyError, OSError):
            logger.exception("Analysis run %s could not be marked failed", run_id)
            return None

    async def _execute(self, run_id: int) -> AnalysisRun | None:
        async with self.sessions() as session:
            run = await session.get(AnalysisRun, run_id)
            if run is None or run.status is not AnalysisRunStatus.QUEUED:
                return run
            run.status = AnalysisRunStatus.RUNNING
            run.started_at = self.now()
            await session.commit()

            try:
                request, form_version = await self._request(session, run)
            except ReportRejectedError as error:
                return await self._fail(session, run, error.code, error.message)
            run.transcript_version = request.conversation["transcript_version"]
            form_version_id = form_version.id
            await session.commit()

            try:
                report = await asyncio.to_thread(self.adapter.analyse, request)
            except AnalysisUnavailableError as error:
                return await self._fail(
                    session, run, "analysis-unavailable", str(error)
                )
            except Exception as error:  # noqa: BLE001 - recorded on the run, never hidden
                return await self._fail(
                    session,
                    run,
                    "analysis-error",
                    f"The analysis raised {type(error).__name__}.",
                )

            try:
                parsed = parse_report(request, report)
            except ReportRejectedError as error:
                return await self._fail(session, run, error.code, error.message)

            if parsed.assessment_report is not None:
                run.assessment_report = parsed.assessment_report
                run.report_version = parsed.report_version
                if parsed.assessment_report["processing_status"] != "completed":
                    return await self._fail(
                        session,
                        run,
                        "partial-report",
                        "Some categories failed; independently valid checks are retained.",
                    )
            try:
                audit = await self._save(session, run, form_version_id, parsed)
                run.status = AnalysisRunStatus.SUCCEEDED
                run.audit_id = audit.id
                run.report_version = parsed.report_version
                run.finished_at = self.now()
                await session.commit()
            except AlreadyAnalysedError:
                await session.rollback()
                return await self._record_failure(
                    run_id,
                    "already-analysed",
                    "The conversation was analysed while this run was in progress.",
                )
            except SQLAlchemyError:
                await session.rollback()
                return await self._record_failure(
                    run_id, "save-failed", "The audit could not be saved."
                )
            return run

    async def _fail(
        self, session: AsyncSession, run: AnalysisRun, code: str, message: str
    ) -> AnalysisRun:
        self._mark_failed(run, code, message)
        await session.commit()
        return run

    async def _request(
        self, session: AsyncSession, run: AnalysisRun
    ) -> tuple[AnalysisRequest, EvaluationFormVersion]:
        conversation = await session.scalar(
            select(Conversation)
            .where(Conversation.id == run.conversation_id)
            .options(
                selectinload(Conversation.turns),
                selectinload(Conversation.organization),
            )
        )
        form_version = await session.scalar(
            select(EvaluationFormVersion)
            .where(EvaluationFormVersion.is_active)
            .options(selectinload(EvaluationFormVersion.criteria))
            .order_by(EvaluationFormVersion.id)
            .limit(1)
        )
        if form_version is None:
            raise ReportRejectedError(
                "no-evaluation-form", "No evaluation form version is active."
            )
        if not conversation.turns:
            raise ReportRejectedError(
                "no-transcript", "The conversation has no stored turns."
            )

        public_id = str(conversation.id)
        events = [
            {
                "turn_id": turn.line_number,
                "kind": "action"
                if turn.speaker is Speaker.SYSTEM_ACTION
                else "message",
                "speaker": EVENT_SPEAKERS[turn.speaker],
                "text": turn.text,
                "source_pointer": f"/conversations/{public_id}/turns/{turn.line_number}",
            }
            for turn in conversation.turns
        ]
        entries = await session.scalars(
            select(KnowledgeEntry)
            .where(
                KnowledgeEntry.organization_id == conversation.organization_id,
                KnowledgeEntry.status == EntryStatus.APPROVED,
                *(
                    [KnowledgeEntry.topic_id == conversation.topic_id]
                    if conversation.topic_id is not None
                    else []
                ),
            )
            .options(selectinload(KnowledgeEntry.topic))
            .order_by(KnowledgeEntry.id)
        )
        references = [
            {
                "id": str(entry.id),
                "section_id": str(entry.id),
                "version": f"review-{entry.approved_review_id}",
                "title": entry.topic.name,
                "text": entry.answer_text,
                "status": entry.status.value,
            }
            for entry in entries
        ]
        criteria = [
            {
                "category": CRITERION_FOR_CATEGORY[criterion.category],
                "name": criterion.name,
                "description": criterion.description,
                "weight": str(criterion.weight),
                "pass_threshold": str(criterion.pass_threshold),
                "enabled": criterion.enabled,
            }
            for criterion in form_version.criteria
        ]
        canonical = conversation.canonical_evidence
        if self.scoring_context is not None:
            from backend.services.rule_assessment import validate_prepared

            if canonical is None:
                raise ReportRejectedError(
                    "missing-canonical-evidence",
                    "Import prepared masked evidence first.",
                )
            try:
                prepared = validate_prepared(canonical)
                stored = [
                    (turn.line_number, EVENT_SPEAKERS[turn.speaker], turn.text)
                    for turn in conversation.turns
                ]
                expected = [
                    (event["turn_id"], event["speaker"], event["text"])
                    for event in prepared["events"]
                ]
                if stored != expected:
                    raise ValueError("Stored turns differ from canonical evidence")
            except (TypeError, ValueError, KeyError) as error:
                raise ReportRejectedError(
                    "invalid-canonical-evidence", str(error)
                ) from None
        request = AnalysisRequest(
            conversation=prepared
            if self.scoring_context is not None
            else {
                "id": public_id,
                "transcript_version": transcript_version(public_id, events),
                "events": events,
            },
            references=[] if self.scoring_context is not None else references,
            criteria=[] if self.scoring_context is not None else criteria,
            evaluation_form_version=form_version.id,
            as_of=self.now().date().isoformat(),
            scope=""
            if self.scoring_context is not None
            else conversation.organization.slug,
            canonical_evidence=canonical if self.scoring_context is not None else None,
            scoring_context=self.scoring_context,
        )
        return request, form_version

    async def _save(
        self,
        session: AsyncSession,
        run: AnalysisRun,
        form_version_id: int,
        parsed: ParsedReport,
    ) -> Audit:
        conversation = await session.scalar(
            select(Conversation)
            .where(Conversation.id == run.conversation_id)
            .options(selectinload(Conversation.turns))
        )
        existing = await session.scalar(
            select(Audit.id).where(Audit.conversation_id == conversation.id)
        )
        if existing is not None:
            raise AlreadyAnalysedError
        turns = {turn.line_number: turn for turn in conversation.turns}
        entry_ids = {
            entry_id
            for category in parsed.categories.values()
            for entry_id in category.reference_ids
        }
        entries = {
            entry.id: entry
            for entry in await session.scalars(
                select(KnowledgeEntry).where(
                    KnowledgeEntry.id.in_(entry_ids),
                    KnowledgeEntry.organization_id == conversation.organization_id,
                )
            )
        }
        audit = Audit(
            organization_id=conversation.organization_id,
            conversation_id=conversation.id,
            evaluation_form_version_id=form_version_id,
            summary=parsed.summary,
            assessment_report=parsed.assessment_report,
            findings=[
                Finding(
                    organization_id=conversation.organization_id,
                    category=CATEGORY_FOR_CRITERION[name],
                    result=category.result,
                    feedback=category.feedback,
                    suggestion=category.suggestion,
                    evidence=[turns[number] for number in category.turn_numbers],
                    # The audit model links one entry per finding: the first cited.
                    **(
                        {"knowledge_entry": entries[category.reference_ids[0]]}
                        if category.reference_ids
                        and category.reference_ids[0] in entries
                        else {}
                    ),
                )
                for name, category in parsed.categories.items()
            ],
        )
        session.add(audit)
        await session.flush()
        return audit
