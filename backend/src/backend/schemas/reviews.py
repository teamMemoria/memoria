from typing import Annotated, Literal

from pydantic import StringConstraints

from backend.schemas.base import ApiModel
from backend.schemas.call_review import CallReview, ReviewRequest
from backend.schemas.conversations import Conversation

# Matches frontend/src/features/review-queue/teamQueue.ts.
DecisionOutcome = Literal["confirmed", "corrected", "dismissed", "cannot-assess"]
QueueStatus = Literal[
    "all", "feedback-ready", "review-requested", "review-complete", "processing"
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


class DecisionInput(ApiModel):
    outcome: DecisionOutcome
    # Both are required so every decision explains itself to the agent.
    reason: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=1, max_length=2000)
    ]
    feedback: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=1, max_length=4000)
    ]
