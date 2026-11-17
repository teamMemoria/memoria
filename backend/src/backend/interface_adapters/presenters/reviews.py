"""Review response formatting and query presentation."""

from backend.data.demo_profiles import profile_display_name
from backend.entities.results import OUTCOME_NAMES, RESULT_NAMES
from backend.interface_adapters.presenters.assessments import iso_timestamp
from backend.interface_adapters.records import ManagerReview
from backend.schemas import ManagerDecision
from backend.schemas.reviews import TeamConversation
from backend.use_cases.record_review_decision import ReviewDecisionResult


def decision_output(review: ManagerReview) -> ReviewDecisionResult:
    """Detach the result before it crosses the application boundary."""
    user = review.reviewer_membership.user
    return ReviewDecisionResult(
        OUTCOME_NAMES[review.outcome],
        RESULT_NAMES[review.reviewed_result]
        if review.reviewed_result is not None
        else None,
        review.reason,
        review.feedback,
        user.external_id,
        user.display_name,
        review.reviewed_at,
    )


def present_decision(review: ReviewDecisionResult) -> ManagerDecision:
    return ManagerDecision(
        outcome=review.outcome,
        reason=review.reason,
        feedback=review.feedback,
        manager_name=profile_display_name(review.reviewer_id, review.reviewer_name),
        decided_at=iso_timestamp(review.reviewed_at),
    )


def decision_schema(review: ManagerReview) -> ManagerDecision:
    """Compatibility formatter for callers holding an already-loaded record."""
    return present_decision(decision_output(review))


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
    if status in ("processing", "unavailable"):
        return conversation.automated_result == status
    return conversation.review_status == status
