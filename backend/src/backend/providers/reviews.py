"""A Manager's review queue and decisions.

Managers see every conversation in their own organization; there is no team
model yet, so the organization is the review scope. A decision is a
ManagerReview on the agent's FeedbackFlag. It is stored beside the automated
finding and never changes it.
"""

from collections.abc import Callable
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from backend.core.auth import Permission
from backend.models import (
    Agent,
    Audit,
    Conversation,
    FeedbackFlag,
    Finding,
    ManagerReview,
    OrganizationMembership,
    User,
)
from backend.models import AgentContext as AgentContextRecord
from backend.providers.base import ConflictError, RecordNotFoundError
from backend.providers.database import (
    OUTCOME_NAMES,
    AgentIdentity,
    SessionFactory,
    assessment,
    audits_by_conversation,
    call_review,
    conversation_summary,
    current_flag,
    current_user_for,
    iso_timestamp,
    load_membership,
    parse_id,
    review_request_schema,
    unavailable_on_database_error,
)
from backend.schemas import AgentContext, ManagerDecision
from backend.schemas.reviews import (
    DecisionInput,
    FindingReviewDetail,
    FlaggedFeedback,
    TeamConversation,
)
from backend.services.clock import utc_now

OUTCOMES = {name: outcome for outcome, name in OUTCOME_NAMES.items()}


async def agent_identities(
    session: AsyncSession, organization_id: int
) -> dict[int, AgentIdentity]:
    """Who each agent record belongs to: the linked person, else the source label."""
    agents = await session.scalars(
        select(Agent).where(Agent.organization_id == organization_id)
    )
    identities = {
        agent.id: AgentIdentity(
            id=agent.external_id, name=agent.name or agent.external_id
        )
        for agent in agents
    }
    linked = await session.execute(
        select(OrganizationMembership.agent_id, User.external_id, User.display_name)
        .join(User, User.id == OrganizationMembership.user_id)
        .where(
            OrganizationMembership.organization_id == organization_id,
            OrganizationMembership.agent_id.is_not(None),
        )
    )
    for agent_id, external_id, display_name in linked:
        identities[agent_id] = AgentIdentity(id=external_id, name=display_name)
    return identities


def decision_schema(review: ManagerReview) -> ManagerDecision:
    return ManagerDecision(
        outcome=OUTCOME_NAMES[review.outcome],
        reason=review.reason,
        feedback=review.feedback,
        manager_name=review.reviewer,
        decided_at=iso_timestamp(review.reviewed_at),
    )


def matches(conversation: TeamConversation, query: str) -> bool:
    """The same fields the frontend's filterTeamConversations searches."""
    if not query:
        return True
    fields = [conversation.id, conversation.topic, conversation.agent_name]
    if conversation.flag is not None:
        fields += [conversation.flag.reason, conversation.flag.finding_title]
    return query.casefold() in " ".join(fields).casefold()


def has_status(conversation: TeamConversation, status: str) -> bool:
    if status == "all":
        return True
    if status == "processing":
        return conversation.automated_result == "processing"
    return conversation.review_status == status


class DatabaseReviewProvider:
    def __init__(self, sessions: SessionFactory, now: Callable[[], datetime] = utc_now):
        self._sessions = sessions
        self._now = now

    async def _reviewer(
        self, session: AsyncSession, organization_id: str, manager_id: str
    ) -> OrganizationMembership:
        membership = await load_membership(session, organization_id, manager_id)
        if membership is None or not current_user_for(membership).has(
            Permission.FEEDBACK_REVIEW
        ):
            # Routes check the permission first; this keeps the provider safe on its own.
            raise RecordNotFoundError("Conversation not found")
        return membership

    @unavailable_on_database_error
    async def list_for_manager(
        self, organization_id, manager_id, status="all", query=""
    ):
        async with self._sessions() as session:
            membership = await self._reviewer(session, organization_id, manager_id)
            conversations = list(
                await session.scalars(
                    select(Conversation)
                    .where(Conversation.organization_id == membership.organization_id)
                    .options(selectinload(Conversation.topic))
                )
            )
            audits = await audits_by_conversation(
                session, [conversation.id for conversation in conversations]
            )
            agents = await agent_identities(session, membership.organization_id)

        queue = []
        for conversation in conversations:
            audit = audits.get(conversation.id)
            summary = conversation_summary(
                conversation, audit, agents[conversation.agent_id]
            )
            flag = None
            if audit is not None:
                _, findings, _ = assessment(
                    audit, conversation.id, conversation.organization_id
                )
                titles = {finding.id: finding.title for finding in findings}
                stored = current_flag(audit, set(titles))
                if stored is not None:
                    flag = FlaggedFeedback(
                        **review_request_schema(stored).model_dump(),
                        finding_title=titles[str(stored.finding_id)],
                    )
            item = TeamConversation(**summary.model_dump(), flag=flag)
            if has_status(item, status) and matches(item, query.strip()):
                queue.append(item)
        # Newest request first, then newest call, as the frontend orders the queue.
        return sorted(
            queue,
            key=lambda item: (item.flag.requested_at if item.flag else item.date) or "",
            reverse=True,
        )

    @unavailable_on_database_error
    async def get_for_manager(self, organization_id, manager_id, conversation_id):
        key = parse_id(conversation_id)
        async with self._sessions() as session:
            membership = await self._reviewer(session, organization_id, manager_id)
            if key is None:
                return None
            conversation = await session.scalar(
                select(Conversation)
                .where(
                    Conversation.organization_id == membership.organization_id,
                    Conversation.id == key,
                )
                .options(
                    selectinload(Conversation.topic),
                    selectinload(Conversation.turns),
                )
            )
            if conversation is None:
                return None
            audit = (await audits_by_conversation(session, [key])).get(key)
            context = await session.scalar(
                select(AgentContextRecord).where(
                    AgentContextRecord.conversation_id == key
                )
            )
            agents = await agent_identities(session, membership.organization_id)
        call = call_review(conversation, audit, agents[conversation.agent_id], context)
        if call.review_request is not None:
            # Show what the agent had written when they asked for the review,
            # not a note they may have changed since.
            flag = current_flag(audit, {finding.id for finding in call.findings})
            snapshot = (
                AgentContext(
                    text=flag.agent_context, saved_at=iso_timestamp(flag.flagged_at)
                )
                if flag.agent_context is not None
                else None
            )
            call = call.model_copy(update={"agent_context": snapshot})
        return FindingReviewDetail(call=call, can_decide=True)

    @unavailable_on_database_error
    async def decide(
        self, organization_id, manager_id, conversation_id, finding_id, decision
    ):
        conversation_key, finding_key = parse_id(conversation_id), parse_id(finding_id)
        async with self._sessions() as session:
            membership = await self._reviewer(session, organization_id, manager_id)
            flag = None
            if conversation_key is not None and finding_key is not None:
                flag = await session.scalar(
                    select(FeedbackFlag)
                    .join(Finding, Finding.id == FeedbackFlag.finding_id)
                    .join(Audit, Audit.id == Finding.audit_id)
                    .join(Conversation, Conversation.id == Audit.conversation_id)
                    .where(
                        FeedbackFlag.finding_id == finding_key,
                        Conversation.id == conversation_key,
                        Conversation.organization_id == membership.organization_id,
                    )
                    .options(selectinload(FeedbackFlag.manager_review))
                )
            if flag is None:
                raise RecordNotFoundError("Review request not found")

            if flag.manager_review is not None:
                return self._repeat(flag.manager_review, decision), False

            # A plain value, because a rollback below expires loaded objects.
            flag_key = flag.id
            review = ManagerReview(
                feedback_flag_id=flag_key,
                outcome=OUTCOMES[decision.outcome],
                reviewer=membership.user.display_name,
                reviewer_membership_id=membership.id,
                reason=decision.reason,
                feedback=decision.feedback,
                reviewed_at=self._now(),
            )
            session.add(review)
            try:
                await session.commit()
            except IntegrityError:
                # Another Manager decided at the same moment; theirs stands.
                await session.rollback()
                existing = await session.scalar(
                    select(ManagerReview).where(
                        ManagerReview.feedback_flag_id == flag_key
                    )
                )
                if existing is None:
                    raise
                return self._repeat(existing, decision), False
            return decision_schema(review), True

    @staticmethod
    def _repeat(existing: ManagerReview, decision: DecisionInput) -> ManagerDecision:
        """A resubmission is fine if it says the same thing; otherwise it conflicts."""
        same = (
            existing.outcome is OUTCOMES[decision.outcome]
            and existing.reason == decision.reason
            and existing.feedback == decision.feedback
        )
        if not same:
            raise ConflictError("A decision was already recorded for this request")
        return decision_schema(existing)
