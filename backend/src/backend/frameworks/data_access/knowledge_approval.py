from sqlalchemy.ext.asyncio import AsyncSession

from backend.entities.knowledge import require_approver
from backend.frameworks.database.models import (
    DraftStatus,
    KnowledgeDraft,
    KnowledgeEntry,
    KnowledgeReview,
    OrganizationMembership,
    ReviewAction,
)


async def approve_draft(
    session: AsyncSession,
    draft: KnowledgeDraft,
    membership: OrganizationMembership,
) -> KnowledgeEntry:
    """Approve a draft through a Manager membership in the same organization."""
    require_approver(
        membership.can_approve_knowledge,
        membership.organization_id,
        draft.organization_id,
    )

    review = KnowledgeReview(
        organization_id=draft.organization_id,
        draft=draft,
        reviewer_membership=membership,
        action=ReviewAction.APPROVED,
    )
    entry = KnowledgeEntry(
        organization_id=draft.organization_id,
        topic=draft.topic,
        answer_text=draft.answer_text,
        embedding=draft.embedding,
        approved_review=review,
    )
    draft.status = DraftStatus.APPROVED
    session.add(entry)
    await session.flush()
    return entry
