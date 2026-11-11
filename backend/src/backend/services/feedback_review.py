from sqlalchemy.ext.asyncio import AsyncSession

from backend.models import (
    FeedbackFlag,
    FindingResult,
    ManagerReview,
    ManagerReviewOutcome,
    OrganizationMembership,
)


async def record_manager_review(
    session: AsyncSession,
    flag: FeedbackFlag,
    membership: OrganizationMembership,
    *,
    outcome: ManagerReviewOutcome,
    reviewed_result: FindingResult | None,
    reason: str,
    feedback: str,
) -> ManagerReview:
    """Record a decision by a Manager in the flag's organization."""
    if not membership.can_review_feedback:
        raise PermissionError("Manager role required for feedback review")
    if membership.organization_id != flag.organization_id:
        raise PermissionError("Feedback review must stay within one organization")
    review = ManagerReview(
        organization_id=flag.organization_id,
        feedback_flag=flag,
        reviewer_membership=membership,
        outcome=outcome,
        reviewed_result=reviewed_result,
        reason=reason,
        feedback=feedback,
    )
    session.add(review)
    await session.flush()
    return review
