from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request, status
from fastapi.responses import JSONResponse

from backend.api.auth import require_permission
from backend.core.auth import CurrentUser, Permission
from backend.models import AnalysisRun
from backend.providers.database import iso_timestamp
from backend.schemas.analysis import AnalysisRunView, AnalysisStatus, StartAnalysis
from backend.services.analysis import (
    AlreadyAnalysedError,
    AnalysisService,
    ConversationNotFoundError,
    RetryRequiredError,
)

router = APIRouter(prefix="/api/manager")

ReviewerDep = Annotated[
    CurrentUser, Depends(require_permission(Permission.FEEDBACK_REVIEW))
]


def get_analysis(request: Request) -> AnalysisService:
    return request.app.state.analysis


AnalysisDep = Annotated[AnalysisService, Depends(get_analysis)]


def run_view(run: AnalysisRun) -> AnalysisRunView:
    return AnalysisRunView(
        id=str(run.id),
        attempt=run.attempt,
        status=run.status.value,
        error_code=run.error_code,
        error_message=run.error_message,
        requested_by=run.requested_by,
        requested_at=iso_timestamp(run.created_at),
        started_at=iso_timestamp(run.started_at) if run.started_at else None,
        finished_at=iso_timestamp(run.finished_at) if run.finished_at else None,
    )


def not_found() -> HTTPException:
    return HTTPException(status.HTTP_404_NOT_FOUND, "Conversation not found")


async def analysis_status(
    analysis: AnalysisService, user: CurrentUser, conversation_id: str
) -> AnalysisStatus:
    try:
        runs = await analysis.runs(user.organization_id, conversation_id)
    except ConversationNotFoundError:
        raise not_found() from None
    return AnalysisStatus(
        conversation_id=conversation_id,
        status=runs[0].status.value if runs else "not-started",
        runs=[run_view(run) for run in runs],
    )


@router.get("/conversations/{conversation_id}/analysis", response_model=AnalysisStatus)
async def get_analysis_status(
    conversation_id: str, user: ReviewerDep, analysis: AnalysisDep
) -> AnalysisStatus:
    """Every analysis attempt for a conversation in the requester's organization."""
    return await analysis_status(analysis, user, conversation_id)


@router.post(
    "/conversations/{conversation_id}/analysis",
    response_model=AnalysisStatus,
    responses={
        200: {
            "description": "A run was already queued or running; nothing new started"
        },
        202: {"description": "A new run was queued"},
        409: {
            "description": "Already analysed, or the last run failed and retry is false"
        },
    },
)
async def start_analysis(
    conversation_id: str,
    user: ReviewerDep,
    analysis: AnalysisDep,
    background: BackgroundTasks,
    body: StartAnalysis | None = None,
):
    """Start analysing a conversation.

    A second request while a run is queued or running returns that run instead
    of starting another. A conversation that already has an audit is never
    analysed again, so earlier results cannot be replaced. After a failed run,
    starting again needs ``{"retry": true}``.
    """
    try:
        started = await analysis.start(
            user.organization_id,
            conversation_id,
            requested_by=user.user_id,
            retry=body.retry if body else False,
        )
    except ConversationNotFoundError:
        raise not_found() from None
    except AlreadyAnalysedError:
        raise HTTPException(
            status.HTTP_409_CONFLICT, "Conversation already analysed"
        ) from None
    except RetryRequiredError:
        raise HTTPException(
            status.HTTP_409_CONFLICT, "The last run failed; retry explicitly"
        ) from None
    if started.created:
        background.add_task(analysis.execute, started.run.id)
    result = await analysis_status(analysis, user, conversation_id)
    return JSONResponse(
        result.model_dump(mode="json"),
        status_code=status.HTTP_202_ACCEPTED if started.created else status.HTTP_200_OK,
    )
