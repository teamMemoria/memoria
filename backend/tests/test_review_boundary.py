"""Review invariants and outputs do not depend on transport validation or an ORM."""

from dataclasses import replace
from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from backend.entities.reviews import ReviewInput, ReviewOutput, validate_review_input
from backend.schemas.reviews import DecisionInput
from backend.use_cases.reviews import ReviewInteractor


class Store:
    def __init__(self):
        self.writes = []

    async def existing(self):
        return None

    async def save(self, value):
        self.writes.append(value)
        return ReviewOutput(
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
    value = replace(ReviewInput("confirmed", None, "Reason", "Feedback"), **changes)
    store = Store()
    with pytest.raises(ValueError):
        await ReviewInteractor().execute(value, store)
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
    value = ReviewInput("corrected", "needs-review", "  Reason  ", "  Feedback  ")
    output, created = await ReviewInteractor().execute(value, store)
    assert type(output) is ReviewOutput and created
    assert output.reason == "Reason" and output.feedback == "Feedback"
    assert store.writes == [validate_review_input(value)]
