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
from functools import wraps

from sqlalchemy import Select, false, func, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from backend.data.demo_profiles import DEMO_PREFIX
from backend.entities.identity import CurrentUser, permissions_for_membership
from backend.entities.results import (
    CATEGORY_FOR_CRITERION,
    CRITERION_FOR_CATEGORY,
    CRITERION_TITLES,
    OUTCOME_NAMES,
    RESULT_NAMES,
)
from backend.frameworks.database.models import AgentContext as AgentContextRecord
from backend.frameworks.database.models import (
    AnalysisRun,
    Audit,
    Conversation,
    EntryStatus,
    FeedbackFlag,
    Finding,
    KnowledgeEntry,
    KnowledgeReview,
    ManagerReview,
    Organization,
    OrganizationMembership,
    User,
    UserRole,
)
from backend.interface_adapters.ports import Providers, ProviderUnavailableError
from backend.interface_adapters.presenters.assessments import (
    NO_STORED_RESULT,
    NO_TOPIC,
    NO_VISIBLE_EVIDENCE,
    SPEAKER_NAMES,
    AgentIdentity,
    agent_context_schema,
    agent_identity,
    assessment,
    call_review,
    conversation_summary,
    current_flag,
    current_review_request,
    finding_suggestion,
    flags_of,
    iso_date,
    iso_timestamp,
    knowledge_entry_schema,
    latest_decision,
    overall_result,
    report_overall,
    review_request_schema,
    review_status,
    transcript_of,
    visible_evidence,
    with_scoring,
)
from backend.interface_adapters.presenters.profiles import (
    demo_profile,
    viewer,
)

SessionFactory = Callable[[], AbstractAsyncContextManager[AsyncSession]]


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
            demo_profile(external_id, name, role is UserRole.AGENT, count)
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
        return viewer(
            membership.user.external_id,
            membership.user.display_name,
            membership.role is UserRole.AGENT,
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
    from backend.frameworks.data_access.feedback import DatabaseFeedbackProvider
    from backend.frameworks.data_access.knowledge_review import (
        DatabaseKnowledgeReviewProvider,
    )
    from backend.frameworks.data_access.reviews import DatabaseReviewProvider

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


__all__ = [
    "CATEGORY_FOR_CRITERION",
    "CRITERION_FOR_CATEGORY",
    "CRITERION_TITLES",
    "NO_STORED_RESULT",
    "NO_TOPIC",
    "NO_VISIBLE_EVIDENCE",
    "OUTCOME_NAMES",
    "RESULT_NAMES",
    "SPEAKER_NAMES",
    "AgentIdentity",
    "agent_context_schema",
    "agent_identity",
    "assessment",
    "call_review",
    "conversation_summary",
    "current_flag",
    "current_review_request",
    "finding_suggestion",
    "flags_of",
    "iso_date",
    "iso_timestamp",
    "knowledge_entry_schema",
    "latest_decision",
    "latest_report",
    "overall_result",
    "report_overall",
    "review_request_schema",
    "review_status",
    "transcript_of",
    "visible_evidence",
    "with_scoring",
]


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
