"""Run-management boundary: neutral data, no ORM or HTTP types."""

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol


@dataclass(frozen=True)
class RunOutput:
    id: int
    attempt: int
    status: str
    error_code: str | None
    error_message: str | None
    requested_by: str | None
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None


@dataclass(frozen=True)
class StartOutput:
    run: RunOutput
    created: bool


class RunDataAccess(Protocol):
    async def runs(
        self, organization_id: str, conversation_id: str
    ) -> list[RunOutput]: ...
    async def start(
        self,
        organization_id: str,
        conversation_id: str,
        *,
        requested_by: str | None,
        retry: bool = False,
    ) -> StartOutput: ...
    async def execute(self, run_id: int) -> None: ...


@dataclass(frozen=True)
class RunStatusOutput:
    conversation_id: str
    status: str
    runs: list[RunOutput]


class AssessmentRunsInputBoundary(Protocol):
    async def status(
        self, organization_id: str, conversation_id: str
    ) -> RunStatusOutput: ...
    async def start(
        self,
        organization_id: str,
        conversation_id: str,
        *,
        requested_by: str | None,
        retry: bool = False,
    ) -> tuple[StartOutput, RunStatusOutput]: ...
    async def execute(self, run_id: int) -> None: ...


class AssessmentRunsInteractor:
    def __init__(self, repository: RunDataAccess):
        self.repository = repository

    async def status(
        self, organization_id: str, conversation_id: str
    ) -> RunStatusOutput:
        runs = await self.repository.runs(organization_id, conversation_id)
        return RunStatusOutput(
            conversation_id, runs[0].status if runs else "not-started", runs
        )

    async def start(
        self,
        organization_id: str,
        conversation_id: str,
        *,
        requested_by: str | None,
        retry: bool = False,
    ) -> tuple[StartOutput, RunStatusOutput]:
        started = await self.repository.start(
            organization_id, conversation_id, requested_by=requested_by, retry=retry
        )
        return started, await self.status(organization_id, conversation_id)

    async def execute(self, run_id: int) -> None:
        await self.repository.execute(run_id)
