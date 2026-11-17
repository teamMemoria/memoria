"""Review invariants and outputs do not depend on transport validation or an ORM."""

from dataclasses import replace
from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from backend.schemas.reviews import DecisionInput
from backend.use_cases.record_review_decision import (
    RecordReviewDecision,
    ReviewDecisionInput,
    ReviewDecisionResult,
    validate_review_decision,
)


class Store:
    def __init__(self):
        self.writes = []

    async def existing(self):
        return None

    async def save(self, value):
        self.writes.append(value)
        return ReviewDecisionResult(
            value.outcome,
            value.reviewed_result,
            value.reason,
            value.feedback,
            "manager",
            "Manager",
            datetime(2026, 1, 1, tzinfo=UTC),
        ), True

    async def result(self):
        raise AssertionError("No existing decision")


@pytest.mark.parametrize(
    "changes",
    [
        {"outcome": "corrected"},
        {"reviewed_result": "needs-review"},
        {"outcome": "invalid"},
        {"outcome": "corrected", "reviewed_result": "invalid"},
        {"reason": "   "},
        {"feedback": "\x00"},
        {"reason": "x" * 2001},
        {"feedback": "x" * 4001},
    ],
)
async def test_invalid_decision_is_rejected_before_any_write(changes):
    value = replace(
        ReviewDecisionInput("confirmed", None, "Reason", "Feedback"), **changes
    )
    store = Store()
    with pytest.raises(ValueError):
        await RecordReviewDecision().execute(value, store)
    assert not store.writes
    with pytest.raises(ValidationError):
        DecisionInput(
            outcome=value.outcome,
            reviewed_result=value.reviewed_result,
            reason=value.reason,
            feedback=value.feedback,
        )


async def test_neutral_output_and_normalization():
    store = Store()
    value = ReviewDecisionInput(
        "corrected", "needs-review", "  Reason  ", "  Feedback  "
    )
    output, created = await RecordReviewDecision().execute(value, store)
    assert type(output) is ReviewDecisionResult and created
    assert output.reason == "Reason" and output.feedback == "Feedback"
    assert store.writes == [validate_review_decision(value)]
