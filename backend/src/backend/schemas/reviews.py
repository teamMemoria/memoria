from typing import Literal, Self

from pydantic import model_validator

from backend.schemas.base import ApiModel
from backend.schemas.call_review import AuditResult, CallReview, ReviewRequest
from backend.schemas.conversations import Conversation
from backend.schemas.feedback import text_field

# Matches frontend/src/features/review-queue/teamQueue.ts.
DecisionOutcome = Literal["confirmed", "corrected", "dismissed", "cannot-assess"]
QueueStatus = Literal[
    "all",
    "feedback-ready",
    "review-requested",
    "review-complete",
    "processing",
    "unavailable",
]


class FlaggedFeedback(ReviewRequest):
    finding_title: str


class TeamConversation(Conversation):
    """A conversation as Managers see it, with the agent's review request if any."""

    flag: FlaggedFeedback | None


class FindingReviewDetail(ApiModel):
    call: CallReview
    # Whether the requester may record a decision, supplied by the backend.
    can_decide: bool


DecisionReason = text_field(2000)
DecisionFeedback = text_field(4000)


class DecisionInput(ApiModel):
    outcome: DecisionOutcome
    # Both are required so every decision explains itself to the agent.
    reason: DecisionReason
    feedback: DecisionFeedback
    # What the finding's result should have been. Required for "corrected" and
    # not allowed for any other outcome (422 otherwise).
    reviewed_result: AuditResult | None = None

    @model_validator(mode="after")
    def reviewed_result_only_when_corrected(self) -> Self:
        if (self.outcome == "corrected") != (self.reviewed_result is not None):
            raise ValueError(
                "reviewedResult is required when the outcome is corrected, "
                "and only then"
            )
        return self
