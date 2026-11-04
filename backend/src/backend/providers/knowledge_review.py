"""The knowledge review queue: drafts waiting on an authorized reviewer.

Reads only. Every query is scoped to the reviewer's organization, and drafts
are never shown to agents: the approved-knowledge routes read
``knowledge_entries`` only.
"""

from collections import defaultdict

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from backend.core.auth import Permission
from backend.models import (
    DraftStatus,
    KnowledgeConflict,
    KnowledgeDraft,
    KnowledgeDraftEntryMatch,
    KnowledgeReview,
    OrganizationMembership,
    ReviewAction,
    Speaker,
    knowledge_draft_conversations,
)
from backend.providers.base import RecordNotFoundError
from backend.providers.database import (
    SPEAKER_NAMES,
    SessionFactory,
    current_user_for,
    iso_timestamp,
    load_membership,
    parse_id,
    unavailable_on_database_error,
)
from backend.schemas.knowledge_review import (
    ConversationPassage,
    EntryMatch,
    KnowledgeDecision,
    KnowledgeQueueCounts,
    KnowledgeReviewDetail,
    PossibleConflict,
)
from backend.schemas.knowledge_review import KnowledgeDraft as KnowledgeDraftSchema

STATUS_NAMES = {
    DraftStatus.PENDING: "draft",
    DraftStatus.APPROVED: "approved",
    DraftStatus.REJECTED: "rejected",
}
SPEAKERS_BY_VALUE = {speaker.value: name for speaker, name in SPEAKER_NAMES.items()}


async def _approver(
    session: AsyncSession, organization_id: str, user_id: str
) -> OrganizationMembership:
    membership = await load_membership(session, organization_id, user_id)
    if membership is None or not current_user_for(membership).has(
        Permission.KNOWLEDGE_APPROVE
    ):
        # Routes check the permission first; this keeps the provider safe on its own.
        raise RecordNotFoundError("Knowledge draft not found")
    return membership


async def _group_counts(
    session: AsyncSession, organization_id: int, drafts: list[KnowledgeDraft]
) -> dict[int, int]:
    """Distinct stored conversations behind each draft's group (or the draft alone)."""
    groups = {draft.group_key for draft in drafts if draft.group_key}
    by_group: dict[str, int] = {}
    if groups:
        rows = await session.execute(
            select(
                KnowledgeDraft.group_key,
                func.count(
                    func.distinct(knowledge_draft_conversations.c.conversation_id)
                ),
            )
            .join(
                knowledge_draft_conversations,
                (knowledge_draft_conversations.c.draft_id == KnowledgeDraft.id)
                & (
                    knowledge_draft_conversations.c.organization_id
                    == KnowledgeDraft.organization_id
                ),
            )
            .where(
                KnowledgeDraft.organization_id == organization_id,
                KnowledgeDraft.group_key.in_(groups),
            )
            .group_by(KnowledgeDraft.group_key)
        )
        by_group = dict(rows.all())
    return {
        draft.id: by_group.get(draft.group_key, 0)
        if draft.group_key
        else len({c.id for c in draft.supporting_conversations})
        for draft in drafts
    }


def _decision(draft: KnowledgeDraft) -> KnowledgeDecision | None:
    decisions = [
        review
        for review in draft.reviews
        if review.action in (ReviewAction.APPROVED, ReviewAction.REJECTED)
    ]
    if not decisions:
        return None
    review = max(decisions, key=lambda review: (review.reviewed_at, review.id))
    member = review.reviewer_membership
    return KnowledgeDecision(
        outcome=review.action.value,
        reason=review.note,
        manager_name=member.user.display_name if member else "Unknown reviewer",
        decided_at=iso_timestamp(review.reviewed_at),
    )


def draft_schema(
    draft: KnowledgeDraft,
    distinct_conversations: int,
    conflicts: list[KnowledgeConflict],
    matches: list[KnowledgeDraftEntryMatch],
) -> KnowledgeDraftSchema:
    passages = [
        ConversationPassage(
            conversation_id=str(passage.conversation_id),
            turn_number=passage.turn_number,
            speaker=SPEAKERS_BY_VALUE[passage.speaker],
            text=passage.quote,
            role=passage.role,
            source_key=passage.source_key,
            source_version=passage.source_version,
        )
        for passage in sorted(draft.passages, key=lambda p: p.position)
        # Recorded system actions are kept in the database but are not part
        # of the frontend's passage type.
        if passage.speaker != Speaker.SYSTEM_ACTION.value
    ]
    return KnowledgeDraftSchema(
        id=str(draft.id),
        title=draft.question or draft.topic.name,
        topic=draft.topic.name,
        kind="knowledge",
        status=STATUS_NAMES[draft.status],
        # Drafts are not available to any agent.
        available_to_agent_ids=[],
        version=f"draft-{draft.id}",
        approved_at=None,
        approved_by=None,
        effective_at=None,
        last_confirmed_at=None,
        owner=None,
        source=None,
        paragraphs=[
            paragraph.strip()
            for paragraph in draft.answer_text.split("\n\n")
            if paragraph.strip()
        ],
        steps=[],
        source_conversation_ids=sorted(
            str(conversation.id) for conversation in draft.supporting_conversations
        ),
        updated_at=iso_timestamp(draft.updated_at or draft.created_at),
        passages=passages,
        verification_reference=None,
        decision=_decision(draft),
        question=draft.question,
        distinct_conversation_count=distinct_conversations,
        duplicate_of_id=(
            str(draft.duplicate_of_id) if draft.duplicate_of_id is not None else None
        ),
        possible_conflicts=[
            PossibleConflict(
                id=str(conflict.id),
                kind=conflict.kind,
                status=conflict.status,
                explanation=conflict.explanation,
                other_draft_id=str(
                    conflict.other_draft_id
                    if conflict.draft_id == draft.id
                    else conflict.draft_id
                )
                if conflict.other_entry_id is None
                else None,
                other_entry_id=(
                    str(conflict.other_entry_id)
                    if conflict.other_entry_id is not None
                    else None
                ),
            )
            for conflict in conflicts
        ],
        existing_matches=[
            EntryMatch(
                entry_id=str(match.entry_id),
                kind=match.kind,
                similarity=float(match.similarity),
            )
            for match in matches
        ],
        ml_verification=draft.ml_verification,
    )


class DatabaseKnowledgeReviewProvider:
    def __init__(self, sessions: SessionFactory):
        self._sessions = sessions

    async def _load(
        self, session: AsyncSession, organization_id: int, draft_ids: list[int] | None
    ) -> list[KnowledgeDraftSchema]:
        query = (
            select(KnowledgeDraft)
            .where(KnowledgeDraft.organization_id == organization_id)
            .options(
                selectinload(KnowledgeDraft.topic),
                selectinload(KnowledgeDraft.passages),
                selectinload(KnowledgeDraft.supporting_conversations),
                selectinload(KnowledgeDraft.reviews)
                .selectinload(KnowledgeReview.reviewer_membership)
                .selectinload(OrganizationMembership.user),
            )
            .order_by(KnowledgeDraft.id)
        )
        if draft_ids is not None:
            query = query.where(KnowledgeDraft.id.in_(draft_ids))
        drafts = list(await session.scalars(query))
        ids = [draft.id for draft in drafts]
        conflicts: dict[int, list[KnowledgeConflict]] = defaultdict(list)
        matches: dict[int, list[KnowledgeDraftEntryMatch]] = defaultdict(list)
        if ids:
            for conflict in await session.scalars(
                select(KnowledgeConflict)
                .where(
                    KnowledgeConflict.organization_id == organization_id,
                    KnowledgeConflict.draft_id.in_(ids)
                    | KnowledgeConflict.other_draft_id.in_(ids),
                )
                .order_by(KnowledgeConflict.id)
            ):
                for draft_id in {conflict.draft_id, conflict.other_draft_id}:
                    if draft_id in ids:
                        conflicts[draft_id].append(conflict)
            for match in await session.scalars(
                select(KnowledgeDraftEntryMatch)
                .where(
                    KnowledgeDraftEntryMatch.organization_id == organization_id,
                    KnowledgeDraftEntryMatch.draft_id.in_(ids),
                )
                .order_by(
                    KnowledgeDraftEntryMatch.similarity.desc(),
                    KnowledgeDraftEntryMatch.entry_id,
                )
            ):
                matches[match.draft_id].append(match)
        counts = await _group_counts(session, organization_id, drafts)
        return [
            draft_schema(
                draft, counts[draft.id], conflicts[draft.id], matches[draft.id]
            )
            for draft in drafts
        ]

    @unavailable_on_database_error
    async def list_for_approver(
        self,
        organization_id,
        user_id,
        status="all",
        query="",
        possible_conflicts_only=False,
    ):
        async with self._sessions() as session:
            membership = await _approver(session, organization_id, user_id)
            drafts = await self._load(session, membership.organization_id, None)
        search = query.strip().casefold()
        selected = [
            draft
            for draft in drafts
            if (status == "all" or draft.status == status)
            and (not possible_conflicts_only or draft.possible_conflicts)
            and (
                not search
                or search
                in " ".join(
                    [draft.id, draft.topic, draft.title, *draft.paragraphs]
                ).casefold()
            )
        ]
        # Newest first, as the frontend's queue shows them.
        return sorted(
            selected, key=lambda draft: (draft.updated_at, draft.id), reverse=True
        )

    @unavailable_on_database_error
    async def counts(self, organization_id, user_id):
        drafts = await self.list_for_approver(organization_id, user_id)
        return KnowledgeQueueCounts(
            total=len(drafts),
            draft=sum(draft.status == "draft" for draft in drafts),
            approved=sum(draft.status == "approved" for draft in drafts),
            rejected=sum(draft.status == "rejected" for draft in drafts),
            with_possible_conflicts=sum(
                bool(draft.possible_conflicts) for draft in drafts
            ),
        )

    @unavailable_on_database_error
    async def get_for_approver(self, organization_id, user_id, draft_id):
        key = parse_id(draft_id)
        async with self._sessions() as session:
            membership = await _approver(session, organization_id, user_id)
            if key is None:
                return None
            drafts = await self._load(session, membership.organization_id, [key])
        if not drafts:
            return None
        # Only knowledge approvers reach this, so they hold the permission to decide.
        return KnowledgeReviewDetail(entry=drafts[0], can_decide=True)
