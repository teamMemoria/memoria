"""Knowledge decisions and imports with injected persistence and execution."""

from typing import Protocol, TypeVar

from backend.entities.knowledge import (
    DraftDecisionState,
    KnowledgeInput,
    validate_decision,
)
from backend.entities.knowledge_import import (
    ImportResult,
    KnowledgePipelineUnavailableError,
    check_output,
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


class ImportDataAccess(Protocol):
    async def import_output(
        self, organization_id: str, output: dict
    ) -> ImportResult: ...


class KnowledgeImportInteractor:
    def __init__(self, repository: ImportDataAccess, run_pipeline):
        self.repository = repository
        self.run_pipeline = run_pipeline

    async def execute(self, organization_id: str) -> ImportResult:
        try:
            output = await self.run_pipeline(organization_id)
        except KnowledgePipelineUnavailableError:
            raise
        except Exception as error:
            raise KnowledgePipelineUnavailableError(
                f"The knowledge pipeline failed with {type(error).__name__}."
            ) from error
        check_output(organization_id, output)
        return await self.repository.import_output(organization_id, output)
