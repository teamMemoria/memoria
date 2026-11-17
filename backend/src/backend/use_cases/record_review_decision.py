"""Record one Manager decision without changing the automated finding."""

from dataclasses import dataclass, replace
from datetime import datetime
from typing import Protocol

from backend.errors import ConflictError


@dataclass(frozen=True)
class ReviewDecisionInput:
    outcome: str
    reviewed_result: str | None
    reason: str
    feedback: str


@dataclass(frozen=True)
class ReviewDecisionResult:
    outcome: str
    reviewed_result: str | None
    reason: str
    feedback: str
    reviewer_id: str
    reviewer_name: str
    reviewed_at: datetime


class ReviewDecisionRepository(Protocol):
    async def existing(self) -> ReviewDecisionInput | None: ...
    async def save(
        self, decision: ReviewDecisionInput
    ) -> tuple[ReviewDecisionResult, bool]: ...
    async def result(self) -> ReviewDecisionResult: ...


def require_same_decision(
    existing: ReviewDecisionInput, proposed: ReviewDecisionInput
) -> None:
    if existing != proposed:
        raise ConflictError("A decision was already recorded for this request")


def validate_review_decision(decision: ReviewDecisionInput) -> ReviewDecisionInput:
    """The same decision invariants for HTTP and any other caller."""
    if decision.outcome not in {"confirmed", "corrected", "dismissed", "cannot-assess"}:
        raise ValueError("Unknown review outcome")
    if (decision.outcome == "corrected") != (decision.reviewed_result is not None):
        raise ValueError(
            "reviewedResult is required when the outcome is corrected, and only then"
        )
    if decision.reviewed_result is not None and decision.reviewed_result not in {
        "meets-criteria",
        "needs-review",
        "cannot-assess",
    }:
        raise ValueError("Unknown corrected result")

    def text(value: str, maximum: int) -> str:
        if (
            not isinstance(value, str)
            or not value.strip()
            or "\x00" in value
            or len(value.strip()) > maximum
        ):
            raise ValueError("Review text must be nonempty, bounded and contain no NUL")
        return value.strip()

    return replace(
        decision,
        reason=text(decision.reason, 2000),
        feedback=text(decision.feedback, 4000),
    )


class RecordReviewDecision:
    async def execute(
        self, decision: ReviewDecisionInput, repository: ReviewDecisionRepository
    ) -> tuple[ReviewDecisionResult, bool]:
        decision = validate_review_decision(decision)
        existing = await repository.existing()
        if existing is not None:
            require_same_decision(existing, decision)
            return await repository.result(), False
        return await repository.save(decision)
