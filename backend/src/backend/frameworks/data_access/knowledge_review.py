"""The knowledge review queue: drafts waiting on an authorized reviewer.

Every query is scoped to the reviewer's organization, and drafts
are never shown to agents: the approved-knowledge routes read
``knowledge_entries`` only.
"""

from collections import defaultdict

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from backend.entities.identity import Permission
from backend.entities.knowledge import (
    DraftDecisionState,
    KnowledgeDecisionRejected,
    KnowledgeInput,
)
from backend.frameworks.data_access.database import (
    SPEAKER_NAMES,
    SessionFactory,
    current_user_for,
    load_membership,
    parse_id,
    unavailable_on_database_error,
)
from backend.frameworks.data_access.knowledge_approval import approve_draft
from backend.frameworks.database.models import (
    DraftStatus,
    KnowledgeConflict,
    KnowledgeDraft,
    KnowledgeDraftEntryMatch,
    KnowledgeReview,
    OrganizationMembership,
    ReviewAction,
    knowledge_draft_conversations,
)
from backend.interface_adapters.ports import RecordNotFoundError
from backend.interface_adapters.presenters.knowledge_review import (
    _decision,
    draft_schema,
    draft_version,
)
from backend.schemas.knowledge_review import KnowledgeDraft as KnowledgeDraftSchema
from backend.schemas.knowledge_review import (
    KnowledgeQueueCounts,
    KnowledgeReviewDetail,
)
from backend.use_cases.knowledge import KnowledgeInteractor

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

    @unavailable_on_database_error
    async def decide(self, organization_id, user_id, draft_id, outcome, decision):
        key = parse_id(draft_id)
        async with self._sessions() as session:
            membership = await _approver(session, organization_id, user_id)
            # Serialize with pipeline imports so newly discovered conflicts cannot race approval.
            await session.execute(
                select(func.pg_advisory_xact_lock(7901, membership.organization_id))
            )
            draft = await session.scalar(
                select(KnowledgeDraft)
                .where(
                    KnowledgeDraft.organization_id == membership.organization_id,
                    KnowledgeDraft.id == key,
                )
                .with_for_update()
                .options(selectinload(KnowledgeDraft.topic))
            )
            if draft is None:
                raise RecordNotFoundError("Knowledge draft not found")
            await KnowledgeInteractor().execute(
                KnowledgeInput(
                    outcome,
                    decision.version,
                    decision.verified_reference_url,
                    decision.reason,
                ),
                KnowledgeTransaction(session, draft, membership),
            )
            await session.commit()
        detail = await self.get_for_approver(organization_id, user_id, draft_id)
        return detail.entry


class KnowledgeTransaction:
    """Draft and conflict snapshot protected by the original advisory/row locks."""

    def __init__(self, session, draft, membership):
        self.session, self.draft, self.membership = session, draft, membership

    async def state(self):
        draft, membership, session = self.draft, self.membership, self.session
        conflicts = await session.scalar(
            select(KnowledgeConflict.id)
            .where(
                KnowledgeConflict.organization_id == membership.organization_id,
                (KnowledgeConflict.draft_id == draft.id)
                | (KnowledgeConflict.other_draft_id == draft.id),
                KnowledgeConflict.status.in_(["possible_conflict", "unresolved"]),
            )
            .limit(1)
        )
        return DraftDecisionState(
            draft.status == DraftStatus.PENDING,
            draft_version(draft),
            draft.verification_reference,
            bool(conflicts),
            bool(draft.duplicate_of_id),
        )

    async def save(self, decision):
        session, draft, membership = self.session, self.draft, self.membership
        if decision.outcome == "approved":
            entry = await approve_draft(session, draft, membership)
            entry.approved_review.verified_reference_url = draft.verification_reference[
                "url"
            ]
        else:
            draft.status = DraftStatus.REJECTED
            session.add(
                KnowledgeReview(
                    organization_id=draft.organization_id,
                    draft=draft,
                    reviewer_membership=membership,
                    action=ReviewAction.REJECTED,
                    note=decision.reason.strip(),
                )
            )


__all__ = ["KnowledgeDecisionRejected", "_decision", "draft_schema", "draft_version"]
