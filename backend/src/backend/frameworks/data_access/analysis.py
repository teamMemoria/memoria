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
import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from functools import partial
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from backend.entities.assessments import (
    REPORT_SCHEMA_VERSION,
    RESULTS,
    AlreadyAnalysedError,
    AnalysisAdapter,
    AnalysisRequest,
    AnalysisUnavailableError,
    CategoryResult,
    ConversationNotFoundError,
    ParsedReport,
    ReportRejectedError,
    RetryRequiredError,
    UnconfiguredAnalysisAdapter,
    _check_citation,
    _parse_report,
    _reject,
    _text,
    parse_report,
    require_new_run,
    reuse_active_run,
    transcript_version,
)
from backend.entities.policies import SOURCE_PREFIX
from backend.entities.score_policy import PercentagePolicy
from backend.frameworks.data_access.database import (
    CATEGORY_FOR_CRITERION,
    CRITERION_FOR_CATEGORY,
    SessionFactory,
    parse_id,
    unavailable_on_database_error,
)
from backend.frameworks.database.models import (
    ACTIVE_RUN_STATUSES,
    AnalysisRun,
    AnalysisRunStatus,
    Audit,
    Conversation,
    EntryStatus,
    EvaluationFormVersion,
    Finding,
    KnowledgeConflict,
    KnowledgeDraft,
    KnowledgeEntry,
    KnowledgeReview,
    Organization,
    Speaker,
    Topic,
)
from backend.services.clock import utc_now
from backend.use_cases.assessment_runs import RunOutput, StartOutput
from backend.use_cases.assessments import AssessmentInputBoundary, AssessmentInteractor

logger = logging.getLogger(__name__)

STALE_RUN_AFTER = timedelta(minutes=15)

EVENT_SPEAKERS = {
    Speaker.AGENT: "agent",
    Speaker.CUSTOMER: "customer",
    Speaker.SYSTEM_ACTION: "action",
}


# --- runs -----------------------------------------------------------------------------


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
    # Engine-specific approval and point-policy validation is explicitly composed.
    # The default legacy parser cannot accept a proposed scored payload.
    report_parser: Callable[[AnalysisRequest, Any], ParsedReport] = parse_report
    include_knowledge_provenance: bool = False
    percentage_policy: PercentagePolicy | None = None

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
                if reuse_active_run(True, self._is_stale(latest), retry):
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
            require_new_run(
                has_audit=bool(has_audit),
                failed=latest is not None and latest.status is AnalysisRunStatus.FAILED,
                retry=retry,
            )

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

            from backend.interface_adapters.controllers.assessments import (
                validate_report_payload,
            )

            async def generate(request):
                try:
                    return await asyncio.to_thread(self.adapter.analyse, request)
                except AnalysisUnavailableError:
                    raise
                except Exception as error:
                    raise ReportRejectedError(
                        "analysis-error", f"The analysis raised {type(error).__name__}."
                    ) from error

            interactor: AssessmentInputBoundary = AssessmentInteractor(
                generate,
                self.report_parser,
                partial(validate_report_payload, policy=self.percentage_policy),
            )
            try:
                parsed = await interactor.execute(request)
            except AnalysisUnavailableError as error:
                return await self._fail(
                    session, run, "analysis-unavailable", str(error)
                )
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
        topic_matches = KnowledgeEntry.topic_id == conversation.topic_id
        if self.include_knowledge_provenance:
            # The normalized draft topic may differ from the imported call's topic.
            # The pilot checks the supported claim and reference scope explicitly.
            topic_matches |= KnowledgeEntry.approved_review.has(
                KnowledgeReview.draft.has(
                    KnowledgeDraft.source_key.startswith(SOURCE_PREFIX)
                )
            )
        entries = await session.scalars(
            select(KnowledgeEntry)
            .join(KnowledgeEntry.topic)
            .where(
                Topic.disputed.is_(False),
                KnowledgeEntry.organization_id == conversation.organization_id,
                KnowledgeEntry.status == EntryStatus.APPROVED,
                *([topic_matches] if conversation.topic_id is not None else []),
            )
            .options(
                selectinload(KnowledgeEntry.topic),
                *(
                    [
                        selectinload(KnowledgeEntry.approved_review)
                        .selectinload(KnowledgeReview.draft)
                        .selectinload(KnowledgeDraft.supporting_conversations)
                    ]
                    if self.include_knowledge_provenance
                    else []
                ),
            )
            .order_by(KnowledgeEntry.id)
        )
        entries = list(entries)
        conflicted_drafts = set()
        if self.include_knowledge_provenance:
            draft_ids = [
                entry.approved_review.draft_id
                for entry in entries
                if (entry.approved_review.draft.source_key or "").startswith(
                    SOURCE_PREFIX
                )
            ]
            if draft_ids:
                conflicts = await session.execute(
                    select(
                        KnowledgeConflict.draft_id, KnowledgeConflict.other_draft_id
                    ).where(
                        KnowledgeConflict.organization_id
                        == conversation.organization_id,
                        KnowledgeConflict.lifecycle_status == "open",
                        (
                            KnowledgeConflict.draft_id.in_(draft_ids)
                            | KnowledgeConflict.other_draft_id.in_(draft_ids)
                        ),
                    )
                )
                conflicted_drafts = {draft for pair in conflicts for draft in pair}
        references = [
            {
                "id": str(entry.id),
                "section_id": str(entry.id),
                "version": f"review-{entry.approved_review_id}",
                "title": entry.topic.name,
                "text": entry.answer_text,
                "status": entry.status.value,
                **(
                    self._knowledge_provenance(entry)
                    if self.include_knowledge_provenance
                    else {}
                ),
            }
            for entry in entries
            if not self.include_knowledge_provenance
            or entry.approved_review.draft_id not in conflicted_drafts
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
        if canonical is not None:
            from backend.frameworks.data_access.assessment_storage import (
                validate_prepared,
            )

            try:
                prepared = validate_prepared(canonical)
                stored = [
                    (t.line_number, EVENT_SPEAKERS[t.speaker], t.text)
                    for t in conversation.turns
                ]
                expected = [
                    (e["turn_id"], e["speaker"], e["text"]) for e in prepared["events"]
                ]
                if stored != expected:
                    raise ValueError("Stored turns differ from canonical evidence")
            except (TypeError, ValueError, KeyError) as error:
                raise ReportRejectedError(
                    "invalid-canonical-evidence", str(error)
                ) from None
        request = AnalysisRequest(
            conversation={
                "id": public_id,
                "transcript_version": transcript_version(public_id, events),
                "events": events,
            },
            references=references,
            criteria=criteria,
            evaluation_form_version=form_version.id,
            as_of=self.now().date().isoformat(),
            scope=conversation.organization.slug,
            canonical_evidence=canonical,
        )
        return request, form_version

    @staticmethod
    def _knowledge_provenance(entry):
        review = entry.approved_review
        draft = review.draft
        return {
            "draft_source_key": draft.source_key,
            "draft_conversation_ids": [
                str(c.id) for c in draft.supporting_conversations
            ],
            "verified_reference_url": review.verified_reference_url,
            "verification": draft.verification_reference,
        }

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


__all__ = [
    "REPORT_SCHEMA_VERSION",
    "RESULTS",
    "AlreadyAnalysedError",
    "AnalysisAdapter",
    "AnalysisRequest",
    "AnalysisUnavailableError",
    "CategoryResult",
    "ConversationNotFoundError",
    "ParsedReport",
    "ReportRejectedError",
    "RetryRequiredError",
    "UnconfiguredAnalysisAdapter",
    "_check_citation",
    "_parse_report",
    "_reject",
    "_text",
    "parse_report",
    "transcript_version",
]


def run_output(run: AnalysisRun) -> RunOutput:
    return RunOutput(
        run.id,
        run.attempt,
        run.status.value,
        run.error_code,
        run.error_message,
        run.requested_by,
        run.created_at,
        run.started_at,
        run.finished_at,
    )


class AnalysisRunsAdapter:
    """Expose detached run data; keep the legacy service and transactions intact."""

    def __init__(self, service: AnalysisService):
        self.service = service

    async def runs(self, organization_id: str, conversation_id: str) -> list[RunOutput]:
        return [
            run_output(run)
            for run in await self.service.runs(organization_id, conversation_id)
        ]

    async def start(
        self,
        organization_id: str,
        conversation_id: str,
        *,
        requested_by: str | None,
        retry: bool = False,
    ) -> StartOutput:
        result = await self.service.start(
            organization_id, conversation_id, requested_by=requested_by, retry=retry
        )
        return StartOutput(run_output(result.run), result.created)

    async def execute(self, run_id: int) -> None:
        await self.service.execute(run_id)
