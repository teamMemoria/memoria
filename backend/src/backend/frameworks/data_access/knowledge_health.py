"""Organization-scoped knowledge health queries and explicit reviewer actions."""

from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import DateTime, cast, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.config import Settings, get_settings
from backend.entities.knowledge import require_approver
from backend.frameworks.database.models import (
    Conversation,
    DraftStatus,
    EntryStatus,
    KnowledgeConflict,
    KnowledgeDraft,
    KnowledgeEntry,
    KnowledgeReview,
    OrganizationMembership,
    Topic,
    knowledge_draft_conversations,
)


@dataclass(frozen=True)
class SupportedConflict:
    conflict_id: int
    draft_id: int
    entry_id: int
    recent_calls: int
    threshold: int


async def find_supported_conflicts(
    session: AsyncSession,
    *,
    organization_id: int,
    now: datetime,
    settings: Settings | None = None,
) -> list[SupportedConflict]:
    """Report stored disagreements backed by enough distinct recent calls.

    The pipeline/reviewer supplies the disagreement link; different answer text
    alone is not evidence of a contradiction. This query never opens a dispute.
    """
    settings = settings or get_settings()
    call_time = func.coalesce(
        Conversation.synthetic_started_at,
        cast(Conversation.conversation_date, DateTime(timezone=True)),
    )
    support = (
        select(func.count(func.distinct(Conversation.id)))
        .select_from(knowledge_draft_conversations)
        .join(
            Conversation,
            (Conversation.id == knowledge_draft_conversations.c.conversation_id)
            & (
                Conversation.organization_id
                == knowledge_draft_conversations.c.organization_id
            ),
        )
        .where(
            knowledge_draft_conversations.c.draft_id == KnowledgeDraft.id,
            knowledge_draft_conversations.c.organization_id == organization_id,
            call_time >= now - timedelta(days=settings.knowledge_recent_call_days),
            call_time <= now,
        )
        .correlate(KnowledgeDraft)
        .scalar_subquery()
    )
    statement = (
        select(KnowledgeConflict.id, KnowledgeDraft.id, KnowledgeEntry.id, support)
        .select_from(KnowledgeConflict)
        .join(
            KnowledgeDraft,
            (KnowledgeDraft.id == KnowledgeConflict.draft_id)
            & (KnowledgeDraft.organization_id == KnowledgeConflict.organization_id),
        )
        .join(
            KnowledgeEntry,
            (KnowledgeEntry.id == KnowledgeConflict.other_entry_id)
            & (KnowledgeEntry.organization_id == KnowledgeConflict.organization_id),
        )
        .where(
            KnowledgeConflict.organization_id == organization_id,
            KnowledgeConflict.lifecycle_status == "open",
            KnowledgeDraft.status == DraftStatus.PENDING,
            KnowledgeEntry.status == EntryStatus.APPROVED,
            KnowledgeDraft.topic_id == KnowledgeEntry.topic_id,
            support >= settings.knowledge_conflict_threshold,
        )
        .order_by(KnowledgeConflict.id)
    )
    return [
        SupportedConflict(*row, settings.knowledge_conflict_threshold)
        for row in (await session.execute(statement)).all()
    ]


async def find_stale_entries(
    session: AsyncSession,
    *,
    organization_id: int,
    now: datetime,
    settings: Settings | None = None,
) -> list[KnowledgeEntry]:
    """Unconfirmed entries age from approval, confirmed ones from confirmation."""
    settings = settings or get_settings()
    return list(
        await session.scalars(
            select(KnowledgeEntry)
            .join(KnowledgeEntry.approved_review)
            .where(
                KnowledgeEntry.organization_id == organization_id,
                KnowledgeEntry.status == EntryStatus.APPROVED,
                func.coalesce(
                    KnowledgeEntry.last_confirmed_at, KnowledgeReview.reviewed_at
                )
                < now - timedelta(days=settings.knowledge_stale_entry_days),
            )
            .order_by(KnowledgeEntry.id)
        )
    )


async def _review_topic(session, membership, topic_id):
    # Share the import/approval lock so a disappearing pipeline conflict cannot
    # race a reviewer's dispute action.
    require_approver(
        membership.can_approve_knowledge,
        membership.organization_id,
        membership.organization_id,
    )
    await session.execute(
        select(func.pg_advisory_xact_lock(7901, membership.organization_id))
    )
    topic = await session.scalar(
        select(Topic)
        .where(
            Topic.id == topic_id, Topic.organization_id == membership.organization_id
        )
        .with_for_update()
    )
    if topic is None:
        raise ValueError("Topic not found in reviewer's organization")
    return topic


async def mark_topic_disputed(
    session: AsyncSession,
    membership: OrganizationMembership,
    *,
    topic_id: int,
) -> Topic:
    """Explicit reviewer action: pause scoring for a topic with an open conflict."""
    topic = await _review_topic(session, membership, topic_id)
    open_conflict = await session.scalar(
        select(KnowledgeConflict.id)
        .join(KnowledgeDraft, KnowledgeDraft.id == KnowledgeConflict.draft_id)
        .where(
            KnowledgeConflict.organization_id == membership.organization_id,
            KnowledgeConflict.lifecycle_status == "open",
            KnowledgeDraft.topic_id == topic_id,
        )
        .limit(1)
    )
    if open_conflict is None:
        raise ValueError("Topic has no open conflict")
    topic.disputed = True
    await session.flush()
    return topic


async def resolve_knowledge_conflict(
    session: AsyncSession,
    membership: OrganizationMembership,
    *,
    conflict_id: int,
    now: datetime,
) -> KnowledgeConflict:
    require_approver(
        membership.can_approve_knowledge,
        membership.organization_id,
        membership.organization_id,
    )
    await session.execute(
        select(func.pg_advisory_xact_lock(7901, membership.organization_id))
    )
    conflict = await session.scalar(
        select(KnowledgeConflict)
        .where(
            KnowledgeConflict.id == conflict_id,
            KnowledgeConflict.organization_id == membership.organization_id,
        )
        .with_for_update()
    )
    if conflict is None:
        raise ValueError("Conflict not found in reviewer's organization")
    draft = await session.get(KnowledgeDraft, conflict.draft_id)
    topic = await _review_topic(session, membership, draft.topic_id)
    if conflict.lifecycle_status == "open":
        conflict.lifecycle_status = "resolved"
        conflict.resolved_at = now
        conflict.updated_at = now
        await session.flush()
    remaining = await session.scalar(
        select(KnowledgeConflict.id)
        .join(KnowledgeDraft, KnowledgeDraft.id == KnowledgeConflict.draft_id)
        .where(
            KnowledgeConflict.organization_id == membership.organization_id,
            KnowledgeDraft.topic_id == topic.id,
            KnowledgeConflict.lifecycle_status == "open",
        )
        .limit(1)
    )
    if remaining is None:
        topic.disputed = False
        await session.flush()
    return conflict
