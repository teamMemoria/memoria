"""Decide once; the repository preserves the transaction and concurrent winner."""

from typing import Protocol

from backend.entities.reviews import (
    ReviewInput,
    ReviewOutput,
    require_same_decision,
    validate_review_input,
)


class ReviewDataAccess(Protocol):
    async def existing(self) -> ReviewInput | None: ...
    async def save(self, decision: ReviewInput) -> tuple[ReviewOutput, bool]: ...
    async def result(self) -> ReviewOutput: ...


class ReviewInteractor:
    async def execute(
        self, decision: ReviewInput, repository: ReviewDataAccess
    ) -> tuple[ReviewOutput, bool]:
        decision = validate_review_input(decision)
        existing = await repository.existing()
        if existing is not None:
            require_same_decision(existing, decision)
            return await repository.result(), False
        return await repository.save(decision)
