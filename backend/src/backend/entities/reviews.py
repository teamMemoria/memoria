"""Review decisions are separate from automated findings."""

from dataclasses import dataclass, replace
from datetime import datetime

from backend.entities.errors import ConflictError


@dataclass(frozen=True)
class ReviewInput:
    outcome: str
    reviewed_result: str | None
    reason: str
    feedback: str


def require_same_decision(existing: ReviewInput, proposed: ReviewInput) -> None:
    if existing != proposed:
        raise ConflictError("A decision was already recorded for this request")


def require_reviewer(
    can_review: bool, member_organization: int, record_organization: int
):
    if not can_review:
        raise PermissionError("Manager role required for feedback review")
    if member_organization != record_organization:
        raise PermissionError("Feedback review must stay within one organization")


@dataclass(frozen=True)
class ReviewOutput:
    outcome: str
    reviewed_result: str | None
    reason: str
    feedback: str
    reviewer_id: str
    reviewer_name: str
    reviewed_at: datetime


def validate_review_input(decision: ReviewInput) -> ReviewInput:
    """The same decision invariants for HTTP, tests and any other caller."""
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

    def text(value, maximum):
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
