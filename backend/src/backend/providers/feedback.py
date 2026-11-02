"""An agent's writes on their own calls: context notes and review requests.

Both check ownership the same way the reads do (organization, then the agent
record linked to the requester's membership), so an agent can only write on
calls they can read. The automated finding is never modified; a review
request is a separate FeedbackFlag row.
"""

from collections.abc import Callable
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from backend.models import AgentContext as AgentContextRecord
from backend.models import Conversation, FeedbackFlag
from backend.providers.base import RecordNotFoundError
from backend.providers.database import (
    SessionFactory,
    assessment,
    audits_by_conversation,
    iso_timestamp,
    load_membership,
    owned_conversations,
    parse_id,
    review_request_schema,
    unavailable_on_database_error,
)
from backend.schemas import AgentContext
from backend.services.clock import utc_now

CONVERSATION_NOT_FOUND = "Conversation not found"
FINDING_NOT_FOUND = "Finding not found"


async def owned_conversation(
    session: AsyncSession, organization_id: str, agent_id: str, conversation_id: str
) -> Conversation:
    key = parse_id(conversation_id)
    membership = (
        await load_membership(session, organization_id, agent_id)
        if key is not None
        else None
    )
    conversation = (
        await session.scalar(
            owned_conversations(membership).where(Conversation.id == key)
        )
        if membership is not None
        else None
    )
    if conversation is None:
        raise RecordNotFoundError(CONVERSATION_NOT_FOUND)
    return conversation


class DatabaseFeedbackProvider:
    def __init__(self, sessions: SessionFactory, now: Callable[[], datetime] = utc_now):
        self._sessions = sessions
        self._now = now

    @unavailable_on_database_error
    async def save_context(self, organization_id, agent_id, conversation_id, text):
        async with self._sessions() as session:
            conversation = await owned_conversation(
                session, organization_id, agent_id, conversation_id
            )
            saved_at = self._now()
            # One note per call; saving again replaces the text atomically.
            row = (
                await session.execute(
                    insert(AgentContextRecord)
                    .values(
                        organization_id=conversation.organization_id,
                        conversation_id=conversation.id,
                        agent_id=conversation.agent_id,
                        text=text,
                        saved_at=saved_at,
                    )
                    .on_conflict_do_update(
                        index_elements=[AgentContextRecord.conversation_id],
                        set_={"text": text, "saved_at": saved_at},
                    )
                    .returning(AgentContextRecord.text, AgentContextRecord.saved_at)
                )
            ).one()
            await session.commit()
        return AgentContext(text=row.text, saved_at=iso_timestamp(row.saved_at))

    @unavailable_on_database_error
    async def request_review(
        self, organization_id, agent_id, conversation_id, finding_id, reason
    ):
        async with self._sessions() as session:
            conversation = await owned_conversation(
                session, organization_id, agent_id, conversation_id
            )
            audit = (await audits_by_conversation(session, [conversation.id])).get(
                conversation.id
            )
            if audit is None:
                raise RecordNotFoundError(FINDING_NOT_FOUND)
            # Only findings the agent can see in the call view can be flagged.
            _, visible, _ = assessment(
                audit, conversation.id, conversation.organization_id
            )
            finding = next(
                (
                    stored
                    for stored in audit.findings
                    if str(stored.id) == finding_id
                    and finding_id in {item.id for item in visible}
                ),
                None,
            )
            if finding is None:
                raise RecordNotFoundError(FINDING_NOT_FOUND)
            if finding.feedback_flag is not None:
                return review_request_schema(finding.feedback_flag), False

            context = await session.scalar(
                select(AgentContextRecord.text).where(
                    AgentContextRecord.conversation_id == conversation.id
                )
            )
            flag = FeedbackFlag(
                finding_id=finding.id,
                agent_id=conversation.agent_id,
                reason=reason,
                # The context as it was when the review was asked for.
                agent_context=context,
                flagged_at=self._now(),
            )
            session.add(flag)
            try:
                await session.commit()
            except IntegrityError:
                # The same finding was flagged by a concurrent request.
                await session.rollback()
                existing = await session.scalar(
                    select(FeedbackFlag).where(FeedbackFlag.finding_id == finding.id)
                )
                if existing is None:
                    raise
                await session.refresh(existing, ["manager_review"])
                return review_request_schema(existing), False
            await session.refresh(flag, ["manager_review"])
            return review_request_schema(flag), True
