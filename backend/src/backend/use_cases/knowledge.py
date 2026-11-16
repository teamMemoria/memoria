"""Knowledge decisions and imports with injected persistence and execution."""

from typing import Protocol, TypeVar

from backend.entities.knowledge import (
    DraftDecisionState,
    KnowledgeInput,
    validate_decision,
)

T = TypeVar("T")


class KnowledgeDataAccess(Protocol[T]):
    async def state(self) -> DraftDecisionState: ...
    async def save(self, decision: KnowledgeInput) -> T: ...


class KnowledgeInteractor:
    async def execute(
        self, decision: KnowledgeInput, repository: KnowledgeDataAccess[T]
    ) -> T:
        validate_decision(await repository.state(), decision)
        return await repository.save(decision)
