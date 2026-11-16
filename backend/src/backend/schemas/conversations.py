from typing import Literal, Self

from pydantic import model_validator

from backend.schemas.base import ApiModel
from backend.schemas.call_review import OverallScoring

# Matches frontend/src/features/conversations/conversations.ts.
AutomatedResult = Literal[
    "needs-review", "meets-criteria", "cannot-assess", "processing", "unavailable"
]
ReviewStatus = Literal["feedback-ready", "review-requested", "review-complete"]


class Conversation(ApiModel):
    source_id: str | None = None
    id: str
    topic: str
    agent_id: str
    agent_name: str
    # YYYY-MM-DD, the frontend appends T00:00:00Z itself. None when the source
    # recorded no date; it is never filled with a guess.
    date: str | None
    automated_result: AutomatedResult
    review_status: ReviewStatus | None
    overall_scoring: OverallScoring | None = None

    @model_validator(mode="after")
    def processing_has_no_review_status(self) -> Self:
        # Human review cannot start before the automated result exists.
        if (
            self.automated_result in ("processing", "unavailable")
            and self.review_status is not None
        ):
            raise ValueError("a processing conversation cannot have a review status")
        return self
