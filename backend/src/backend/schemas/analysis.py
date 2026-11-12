from typing import Literal

from backend.schemas.base import ApiModel

RunStatus = Literal["queued", "running", "succeeded", "failed"]


class AnalysisRunView(ApiModel):
    id: str
    attempt: int
    status: RunStatus
    # Set only for failed runs. A failure is a processing error, not a result.
    error_code: str | None
    error_message: str | None
    requested_by: str | None
    requested_at: str
    started_at: str | None
    finished_at: str | None


class AnalysisStatus(ApiModel):
    conversation_id: str
    # The latest run's status, or "not-started" when there has been none.
    status: Literal["not-started", "queued", "running", "succeeded", "failed"]
    runs: list[AnalysisRunView]


class StartAnalysis(ApiModel):
    # Starting again after a failed run must be asked for explicitly.
    retry: bool = False
