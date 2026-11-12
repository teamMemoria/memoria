"""PostgreSQL implementations of the provider interfaces.

Every query is scoped to the requester's organization, and agent reads are
scoped again to the agent record linked to the requester's membership. Records
outside that scope are treated as missing, so routes return the same 404 for
"not yours" and "does not exist".

Stored values are mapped to the frontend's names here (``needs_work`` becomes
``needs-review``, ``communication`` becomes ``communication-style`` and so on),
so nothing above this module sees database enums.
"""

from collections.abc import Awaitable, Callable
from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass
from datetime import UTC, date, datetime
from functools import wraps

from sqlalchemy import Select, false, func, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from backend.core.auth import CurrentUser, permissions_for_membership
from backend.data.demo_profiles import DEMO_PREFIX, profile_display_name
from backend.models import AgentContext as AgentContextRecord
from backend.models import (
    AnalysisRun,
    Audit,
    Conversation,
    EntryStatus,
    FeedbackFlag,
    Finding,
    FindingCategory,
    FindingResult,
    KnowledgeEntry,
    KnowledgeReview,
    ManagerReview,
    ManagerReviewOutcome,
    Organization,
    OrganizationMembership,
    Speaker,
    User,
    UserRole,
)
from backend.providers.base import Providers, ProviderUnavailableError
from backend.schemas import (
    AgentContext,
    AuditCriterion,
    CallFinding,
    CallReview,
    DemoProfile,
    ManagerDecision,
    ReviewRequest,
    Transcript,
    TranscriptTurn,
    Viewer,
)
from backend.schemas import Conversation as ConversationSummary
from backend.schemas import KnowledgeEntry as KnowledgeEntrySchema
from backend.schemas.call_review import (
    CRITERION_IDS,
    AssessmentVersion,
    AuditResult,
    CategoryScoring,
    CriterionId,
    OverallScoring,
    RequestLink,
)
from backend.schemas.conversations import AutomatedResult, ReviewStatus

SessionFactory = Callable[[], AbstractAsyncContextManager[AsyncSession]]

CRITERION_FOR_CATEGORY: dict[FindingCategory, CriterionId] = {
    FindingCategory.PROCEDURE: "procedure",
    FindingCategory.ANSWER_SUPPORT: "answer-support",
    FindingCategory.COMPLETENESS: "completeness",
    FindingCategory.COMMUNICATION: "communication-style",
}
CATEGORY_FOR_CRITERION = {value: key for key, value in CRITERION_FOR_CATEGORY.items()}
CRITERION_TITLES: dict[CriterionId, str] = {
    "procedure": "Procedure",
    "answer-support": "Answer support",
    "completeness": "Completeness",
    "communication-style": "Communication style",
}
RESULT_NAMES: dict[FindingResult, AuditResult] = {
    FindingResult.PASS: "meets-criteria",
    FindingResult.NEEDS_WORK: "needs-review",
    FindingResult.CANNOT_ASSESS: "cannot-assess",
}
OUTCOME_NAMES = {
    ManagerReviewOutcome.CONFIRMED: "confirmed",
    ManagerReviewOutcome.CORRECTED: "corrected",
    ManagerReviewOutcome.DISMISSED: "dismissed",
    ManagerReviewOutcome.CANNOT_ASSESS: "cannot-assess",
}
SPEAKER_NAMES = {
    Speaker.AGENT: "Agent",
    Speaker.CUSTOMER: "Customer",
    Speaker.SYSTEM_ACTION: "System action",
}

NO_TOPIC = "Unassigned"
NO_STORED_RESULT = "No result was stored for this criterion."
NO_VISIBLE_EVIDENCE = (
    "A finding was stored without transcript evidence, so it cannot be shown as "
    "needing review."
)


def unavailable_on_database_error[**P, T](
    method: Callable[P, Awaitable[T]],
) -> Callable[P, Awaitable[T]]:
    """Report a database failure as ProviderUnavailableError (a 503), never as "not found"."""

    @wraps(method)
    async def wrapper(*args: P.args, **kwargs: P.kwargs) -> T:
        try:
            return await method(*args, **kwargs)
        except (SQLAlchemyError, OSError) as exc:
            raise ProviderUnavailableError("database unavailable") from exc

    return wrapper


# Primary keys are PostgreSQL integers; a larger number cannot name a record.
MAX_ID = 2**31 - 1


def parse_id(value: str) -> int | None:
    """Public IDs are database keys as strings. Anything else matches nothing."""
    if not value.isascii() or not value.isdigit() or len(value) > 10:
        return None
    number = int(value)
    return number if 0 < number <= MAX_ID else None


def iso_date(value: date | datetime | None) -> str | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        value = value.astimezone(UTC).date()
    return value.isoformat()


def iso_timestamp(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


# --- membership ------------------------------------------------------------------


async def load_membership(
    session: AsyncSession, organization_id: str, user_id: str
) -> OrganizationMembership | None:
    """The membership of ``user_id`` (a User.external_id) in the organization with slug ``organization_id``."""
    return await session.scalar(
        select(OrganizationMembership)
        .join(Organization, Organization.id == OrganizationMembership.organization_id)
        .join(User, User.id == OrganizationMembership.user_id)
        .where(Organization.slug == organization_id, User.external_id == user_id)
        .options(
            selectinload(OrganizationMembership.user),
            selectinload(OrganizationMembership.organization),
        )
    )


def current_user_for(membership: OrganizationMembership) -> CurrentUser:
    return CurrentUser(
        user_id=membership.user.external_id,
        organization_id=membership.organization.slug,
        permissions=permissions_for_membership(
            is_agent=membership.role is UserRole.AGENT,
            can_review_feedback=membership.can_review_feedback,
            can_approve_knowledge=membership.can_approve_knowledge,
        ),
    )


# --- mapping ---------------------------------------------------------------------


@dataclass(frozen=True)
class AgentIdentity:
    """How an agent is named in API responses."""

    id: str
    name: str


def visible_evidence(finding: Finding, conversation_id: int) -> list[int]:
    """Turn numbers a finding cites that are shown in this call's transcript."""
    return sorted(
        {
            turn.line_number
            for turn in finding.evidence
            if turn.conversation_id == conversation_id and turn.speaker in SPEAKER_NAMES
        }
    )


def assessment(
    audit: Audit, conversation_id: int, organization_id: int
) -> tuple[list[AuditCriterion], list[CallFinding], list[KnowledgeEntry]]:
    """Map an audit's stored findings to the frontend's criteria and findings.

    Each criterion keeps the stored result. Two cases are shown as cannot-assess
    instead: a category with no stored finding, and a needs-work finding with no
    evidence in the transcript (the contract never shows a failure without
    evidence). The references are the exact entry versions the findings cite.
    """
    by_criterion = {
        CRITERION_FOR_CATEGORY[finding.category]: finding for finding in audit.findings
    }
    criteria: list[AuditCriterion] = []
    findings: list[CallFinding] = []
    references: dict[int, KnowledgeEntry] = {}

    for criterion_id in CRITERION_IDS:
        finding = by_criterion.get(criterion_id)
        if finding is None:
            criteria.append(
                AuditCriterion(
                    id=criterion_id,
                    title=CRITERION_TITLES[criterion_id],
                    result="cannot-assess",
                    explanation=NO_STORED_RESULT,
                    evidence_turn_numbers=[],
                    finding_id=None,
                    reference_id=None,
                )
            )
            continue

        evidence = visible_evidence(finding, conversation_id)
        result = RESULT_NAMES[finding.result]
        explanation = finding.feedback
        if result == "needs-review" and not evidence:
            result = "cannot-assess"
            explanation = f"{finding.feedback} {NO_VISIBLE_EVIDENCE}"

        entry = finding.knowledge_entry
        reference_id = None
        if entry is not None and entry.organization_id == organization_id:
            references[entry.id] = entry
            reference_id = str(entry.id)

        finding_id = None
        if result == "needs-review":
            finding_id = str(finding.id)
            findings.append(
                CallFinding(
                    id=finding_id,
                    title=finding.feedback,
                    criterion_id=criterion_id,
                    explanation=finding.feedback,
                    suggestion=finding_suggestion(finding),
                    evidence_turn_numbers=evidence,
                    reference_id=reference_id,
                    reference_step=None,
                    procedure_steps=[],
                )
            )
        criteria.append(
            AuditCriterion(
                id=criterion_id,
                title=CRITERION_TITLES[criterion_id],
                result=result,
                explanation=explanation,
                evidence_turn_numbers=evidence,
                finding_id=finding_id,
                reference_id=reference_id,
            )
        )
    return criteria, findings, list(references.values())


def finding_suggestion(finding: Finding) -> str:
    return finding.suggestion or ""


def overall_result(criteria: list[AuditCriterion]) -> AutomatedResult:
    results = {criterion.result for criterion in criteria}
    if "needs-review" in results:
        return "needs-review"
    if "cannot-assess" in results:
        return "cannot-assess"
    return "meets-criteria"


def flags_of(audit: Audit | None) -> list[FeedbackFlag]:
    if audit is None:
        return []
    return [
        finding.feedback_flag
        for finding in audit.findings
        if finding.feedback_flag is not None
    ]


def review_status(audit: Audit | None) -> ReviewStatus | None:
    if audit is None:
        return None
    flags = flags_of(audit)
    if not flags:
        return "feedback-ready"
    if any(flag.manager_review is None for flag in flags):
        return "review-requested"
    return "review-complete"


def latest_decision(audit: Audit | None) -> ManagerDecision | None:
    reviews: list[ManagerReview] = [
        flag.manager_review
        for flag in flags_of(audit)
        if flag.manager_review is not None
    ]
    if not reviews:
        return None
    review = max(reviews, key=lambda review: (review.reviewed_at, review.id))
    return ManagerDecision(
        outcome=OUTCOME_NAMES[review.outcome],
        reason=review.reason,
        feedback=review.feedback,
        manager_name=profile_display_name(
            review.reviewer_membership.user.external_id,
            review.reviewer_membership.user.display_name,
        ),
        decided_at=iso_timestamp(review.reviewed_at),
    )


def transcript_of(conversation: Conversation) -> Transcript | None:
    """Preserve original positions and label recorded actions separately."""
    turns = [
        TranscriptTurn(
            number=turn.line_number,
            speaker=SPEAKER_NAMES[turn.speaker],
            text=turn.text,
            time=None,
        )
        for turn in conversation.turns
        if turn.speaker in SPEAKER_NAMES
    ]
    if not turns:
        return None
    evidence = conversation.canonical_evidence
    complete = (
        evidence["conversations"][0]["coverage"]["transcript"]["status"] == "complete"
        if evidence
        else True
    )
    return Transcript(complete=complete, turns=turns, unavailable_reason=None)


def knowledge_entry_schema(
    entry: KnowledgeEntry, available_to: list[str]
) -> KnowledgeEntrySchema:
    """Map an approved-knowledge row to the frontend's KnowledgeEntry.

    Each approval creates a new entry row, so the approving review identifies
    the version. Fields the database does not store (effective date, owner,
    source, steps) stay empty rather than guessed.
    """
    review: KnowledgeReview = entry.approved_review
    approver = review.reviewer_membership.user if review.reviewer_membership else None
    return KnowledgeEntrySchema(
        id=str(entry.id),
        title=entry.topic.name,
        topic=entry.topic.name,
        kind="knowledge",
        status=entry.status.value,
        available_to_agent_ids=available_to,
        version=f"review-{review.id}",
        approved_at=iso_date(review.reviewed_at),
        approved_by=profile_display_name(approver.external_id, approver.display_name)
        if approver
        else None,
        effective_at=None,
        last_confirmed_at=iso_date(entry.last_confirmed_at),
        owner=None,
        source={
            "title": "Verified approval reference",
            "url": review.verified_reference_url,
        }
        if review.verified_reference_url
        else None,
        paragraphs=[
            paragraph.strip()
            for paragraph in entry.answer_text.split("\n\n")
            if paragraph.strip()
        ],
        steps=[],
    )


def entry_options():
    return (
        selectinload(KnowledgeEntry.topic),
        selectinload(KnowledgeEntry.approved_review)
        .selectinload(KnowledgeReview.reviewer_membership)
        .selectinload(OrganizationMembership.user),
    )


def audit_options():
    findings = selectinload(Audit.findings)
    return (
        findings.selectinload(Finding.evidence),
        findings.selectinload(Finding.feedback_flag)
        .selectinload(FeedbackFlag.manager_review)
        .selectinload(ManagerReview.reviewer_membership)
        .selectinload(OrganizationMembership.user),
        findings.selectinload(Finding.knowledge_entry).options(*entry_options()),
    )


async def audits_by_conversation(
    session: AsyncSession, conversation_ids: list[int]
) -> dict[int, Audit]:
    if not conversation_ids:
        return {}
    audits = await session.scalars(
        select(Audit)
        .where(Audit.conversation_id.in_(conversation_ids))
        .options(*audit_options())
    )
    return {audit.conversation_id: audit for audit in audits}


def conversation_summary(
    conversation: Conversation,
    audit: Audit | None,
    agent: AgentIdentity,
    report: dict | None = None,
) -> ConversationSummary:
    if audit is None:
        automated: AutomatedResult = "unavailable"
    else:
        criteria, _, _ = assessment(
            audit, conversation.id, conversation.organization_id
        )
        automated = overall_result(criteria)
    return ConversationSummary(
        id=str(conversation.id),
        source_id=conversation.original_id
        if conversation.source_dataset == "ABCD"
        else None,
        topic=conversation.topic.name if conversation.topic else NO_TOPIC,
        agent_id=agent.id,
        agent_name=agent.name,
        date=iso_date(conversation.conversation_date),
        automated_result=automated,
        review_status=review_status(audit),
        overall_scoring=report_overall(audit.assessment_report if audit else report),
    )


def agent_context_schema(context: AgentContextRecord | None) -> AgentContext | None:
    if context is None:
        return None
    return AgentContext(text=context.text, saved_at=iso_timestamp(context.saved_at))


def review_request_schema(flag: FeedbackFlag) -> ReviewRequest:
    return ReviewRequest(
        finding_id=str(flag.finding_id),
        reason=flag.reason,
        requested_at=iso_timestamp(flag.flagged_at),
        status="requested" if flag.manager_review is None else "complete",
    )


def current_flag(audit: Audit | None, finding_ids: set[str]) -> FeedbackFlag | None:
    """The call's review request: the newest open one, else the newest completed one.

    Only flags on findings shown in the call view count.
    """
    flags = [flag for flag in flags_of(audit) if str(flag.finding_id) in finding_ids]
    if not flags:
        return None
    return max(
        flags,
        key=lambda flag: (flag.manager_review is None, flag.flagged_at, flag.id),
    )


def current_review_request(
    audit: Audit | None, finding_ids: set[str]
) -> ReviewRequest | None:
    flag = current_flag(audit, finding_ids)
    return review_request_schema(flag) if flag is not None else None


def call_review(
    conversation: Conversation,
    audit: Audit | None,
    agent: AgentIdentity,
    context: AgentContextRecord | None = None,
    report: dict | None = None,
) -> CallReview:
    common = {
        "id": str(conversation.id),
        "source_id": conversation.original_id
        if conversation.source_dataset == "ABCD"
        else None,
        "agent_id": agent.id,
        "agent_name": agent.name,
        "topic": conversation.topic.name if conversation.topic else NO_TOPIC,
        "date": iso_date(conversation.conversation_date),
        "duration": None,
        "transcript": transcript_of(conversation),
        "agent_context": agent_context_schema(context),
    }
    if audit is None:
        call = CallReview(
            **common,
            summary="",
            status="unavailable",
            criteria=[],
            findings=[],
            references=[],
            review_request=None,
            decision=None,
        )
        return with_scoring(call, report)
    criteria, findings, entries = assessment(
        audit, conversation.id, conversation.organization_id
    )
    call = CallReview(
        **common,
        summary=audit.summary or "",
        status="ready",
        criteria=criteria,
        findings=findings,
        # The versions this call was assessed against, even if since replaced.
        references=[knowledge_entry_schema(entry, [agent.id]) for entry in entries],
        review_request=current_review_request(
            audit, {finding.id for finding in findings}
        ),
        decision=latest_decision(audit),
    )
    return with_scoring(call, audit.assessment_report)


def report_overall(report):
    return OverallScoring.model_validate(report["overall"]) if report else None


def with_scoring(call, report):
    if report is None:
        return call
    prior = {criterion.id: criterion for criterion in call.criteria}
    criteria = []
    for row in report["categories"]:
        category = row["category"]
        result = row["result"]
        criterion = prior.get(category)
        if criterion is None:
            criterion = AuditCriterion(
                id=category,
                title=CRITERION_TITLES[category],
                result=result["result"] if result else "cannot-assess",
                explanation=result["explanation"]
                if result
                else "Processing failed for this category.",
                evidence_turn_numbers=sorted(
                    {
                        citation["turn_id"]
                        for check in row["scoring"]["checks"]
                        for citation in check["citations"]
                        if citation["kind"] == "conversation"
                    }
                ),
                finding_id=None,
                reference_id=None,
            )
        criteria.append(
            criterion.model_copy(
                update={
                    "scoring": CategoryScoring.model_validate(row["scoring"]),
                }
            )
        )
    critical_categories = {
        row["category"]
        for row in report["categories"]
        if any(
            check["critical"] and check["outcome"] == "breach"
            for check in row["scoring"]["checks"]
        )
    }
    findings = [
        finding.model_copy(
            update={"critical": finding.criterion_id in critical_categories}
        )
        for finding in call.findings
    ]
    priorities = report.get("priorities", [])
    order = {}
    for index, priority in enumerate(priorities):
        order.setdefault(priority["category"], index)
    findings.sort(key=lambda finding: order.get(finding.criterion_id, len(priorities)))
    return call.model_copy(
        update={
            "status": "ready",
            "criteria": criteria,
            "overall_scoring": report_overall(report),
            "assessment_version": AssessmentVersion(
                source_id=report["conversation_id"],
                as_of=report["as_of"],
                rules=report["versions"]["rules"],
                transcript=report["transcript_version"],
            ),
            "request_links": [
                RequestLink(
                    id=item["id"],
                    text=next(
                        (
                            turn.text
                            for turn in call.transcript.turns
                            if turn.number == item["turn_id"]
                        ),
                        "Source passage unavailable",
                    )
                    if call.transcript
                    else "Source passage unavailable",
                    state=item["state"],
                    request_turns=sorted(
                        {item["turn_id"], *item.get("context_turn_ids", [])}
                    ),
                    response_turns=sorted(
                        {
                            number
                            for event in item["history"][1:]
                            for number in event["turn_ids"]
                        }
                    ),
                    limitations=[event["reason"] for event in item["history"]],
                )
                for item in report.get("requests", [])
            ],
            "findings": findings,
        }
    )


async def latest_report(session, conversation_id):
    return await session.scalar(
        select(AnalysisRun.assessment_report)
        .where(
            AnalysisRun.conversation_id == conversation_id,
            AnalysisRun.assessment_report.is_not(None),
        )
        .order_by(AnalysisRun.attempt.desc())
        .limit(1)
    )


def agent_identity(membership: OrganizationMembership) -> AgentIdentity:
    return AgentIdentity(
        id=membership.user.external_id,
        name=profile_display_name(
            membership.user.external_id, membership.user.display_name
        ),
    )


# --- providers -------------------------------------------------------------------


class DatabaseIdentityProvider:
    def __init__(self, sessions: SessionFactory):
        self._sessions = sessions

    @unavailable_on_database_error
    async def resolve(self, subject, organization_id=None):
        async with self._sessions() as session:
            query = (
                select(OrganizationMembership)
                .join(User, User.id == OrganizationMembership.user_id)
                .join(
                    Organization,
                    Organization.id == OrganizationMembership.organization_id,
                )
                .where(User.external_id == subject)
                .options(
                    selectinload(OrganizationMembership.user),
                    selectinload(OrganizationMembership.organization),
                )
            )
            if organization_id is not None:
                query = query.where(Organization.slug == organization_id)
            memberships = list(await session.scalars(query.limit(2)))
        # A user in several organizations must say which one; never pick for them.
        if len(memberships) != 1:
            return None
        return current_user_for(memberships[0])


class DatabaseDemoProfileProvider:
    """Users created by seed-demo-profiles, with their imported conversation counts."""

    def __init__(self, sessions: SessionFactory):
        self._sessions = sessions

    @unavailable_on_database_error
    async def list_profiles(self):
        conversation_count = (
            select(func.count())
            .select_from(Conversation)
            .where(
                Conversation.organization_id == OrganizationMembership.organization_id,
                Conversation.agent_id == OrganizationMembership.agent_id,
            )
            .scalar_subquery()
        )
        async with self._sessions() as session:
            rows = await session.execute(
                select(
                    User.external_id,
                    User.display_name,
                    OrganizationMembership.role,
                    conversation_count,
                )
                .join(OrganizationMembership, OrganizationMembership.user_id == User.id)
                .where(User.external_id.startswith(DEMO_PREFIX))
                .order_by(OrganizationMembership.role, User.external_id)
            )
        return [
            DemoProfile(
                id=external_id,
                display_name=profile_display_name(external_id, name),
                role="agent" if role is UserRole.AGENT else "manager",
                conversation_count=count if role is UserRole.AGENT else None,
            )
            for external_id, name, role, count in rows
        ]


class DatabaseViewerProvider:
    def __init__(self, sessions: SessionFactory):
        self._sessions = sessions

    @unavailable_on_database_error
    async def get_viewer(self, organization_id, user_id):
        async with self._sessions() as session:
            membership = await load_membership(session, organization_id, user_id)
        if membership is None:
            return None
        return Viewer(
            id=membership.user.external_id,
            display_name=profile_display_name(
                membership.user.external_id, membership.user.display_name
            ),
            role="agent" if membership.role is UserRole.AGENT else "manager",
        )


def owned_conversations(membership: OrganizationMembership) -> Select:
    """Conversations handled by the agent record linked to this membership."""
    if membership.role is not UserRole.AGENT or membership.agent_id is None:
        return select(Conversation).where(false())
    return select(Conversation).where(
        Conversation.organization_id == membership.organization_id,
        Conversation.agent_id == membership.agent_id,
    )


class DatabaseConversationProvider:
    def __init__(self, sessions: SessionFactory):
        self._sessions = sessions

    @unavailable_on_database_error
    async def list_for_agent(self, organization_id, agent_id):
        async with self._sessions() as session:
            membership = await load_membership(session, organization_id, agent_id)
            if membership is None:
                return []
            query = owned_conversations(membership)
            conversations = list(
                await session.scalars(
                    query.options(selectinload(Conversation.topic)).order_by(
                        Conversation.conversation_date.desc().nulls_last(),
                        Conversation.id.desc(),
                    )
                )
            )
            audits = await audits_by_conversation(
                session, [conversation.id for conversation in conversations]
            )
        agent = agent_identity(membership)
        return [
            conversation_summary(conversation, audits.get(conversation.id), agent)
            for conversation in conversations
        ]


class DatabaseCallReviewProvider:
    def __init__(self, sessions: SessionFactory):
        self._sessions = sessions

    @unavailable_on_database_error
    async def get_for_agent(self, organization_id, agent_id, conversation_id):
        key = parse_id(conversation_id)
        if key is None:
            return None
        async with self._sessions() as session:
            membership = await load_membership(session, organization_id, agent_id)
            if membership is None:
                return None
            query = owned_conversations(membership)
            conversation = await session.scalar(
                query.where(Conversation.id == key).options(
                    selectinload(Conversation.topic),
                    selectinload(Conversation.turns),
                )
            )
            if conversation is None:
                return None
            audit = (await audits_by_conversation(session, [key])).get(key)
            report = await latest_report(session, key) if audit is None else None
            context = await session.scalar(
                select(AgentContextRecord).where(
                    AgentContextRecord.conversation_id == key
                )
            )
        return call_review(
            conversation, audit, agent_identity(membership), context, report
        )


class DatabaseKnowledgeProvider:
    def __init__(self, sessions: SessionFactory):
        self._sessions = sessions

    @unavailable_on_database_error
    async def list_for_agent(self, organization_id, agent_id):
        async with self._sessions() as session:
            membership = await load_membership(session, organization_id, agent_id)
            # Approved guidance is assigned to every agent in the organization.
            # Managers and approvers are not assigned entries, as in the fixtures.
            if membership is None or membership.role is not UserRole.AGENT:
                return []
            entries = list(
                await session.scalars(
                    select(KnowledgeEntry)
                    .where(
                        KnowledgeEntry.organization_id == membership.organization_id,
                        KnowledgeEntry.status == EntryStatus.APPROVED,
                    )
                    .options(*entry_options())
                    .order_by(KnowledgeEntry.id)
                )
            )
        return [knowledge_entry_schema(entry, [agent_id]) for entry in entries]

    async def get_for_agent(self, organization_id, agent_id, entry_id):
        # The same rule as the list, so a direct request cannot reach a hidden entry.
        for entry in await self.list_for_agent(organization_id, agent_id):
            if entry.id == entry_id:
                return entry
        return None


def create_database_providers(sessions: SessionFactory) -> Providers:
    # Imported here because the write providers build on the helpers above.
    from backend.providers.feedback import DatabaseFeedbackProvider
    from backend.providers.knowledge_review import DatabaseKnowledgeReviewProvider
    from backend.providers.reviews import DatabaseReviewProvider

    return Providers(
        viewers=DatabaseViewerProvider(sessions),
        conversations=DatabaseConversationProvider(sessions),
        calls=DatabaseCallReviewProvider(sessions),
        knowledge=DatabaseKnowledgeProvider(sessions),
        identities=DatabaseIdentityProvider(sessions),
        feedback=DatabaseFeedbackProvider(sessions),
        reviews=DatabaseReviewProvider(sessions),
        knowledge_review=DatabaseKnowledgeReviewProvider(sessions),
        demo_profiles=DatabaseDemoProfileProvider(sessions),
    )
