from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request, status
from fastapi.responses import JSONResponse

from backend.entities.assessments import (
    AlreadyAnalysedError,
    ConversationNotFoundError,
    RetryRequiredError,
)
from backend.entities.identity import CurrentUser, Permission
from backend.frameworks.http.auth import require_permission
from backend.frameworks.http.demo_scorecards import require_saved_calls
from backend.interface_adapters.presenters.assessments import iso_timestamp
from backend.schemas.analysis import AnalysisRunView, AnalysisStatus, StartAnalysis
from backend.use_cases.assessment_runs import (
    AssessmentRunsInputBoundary,
    RunOutput,
    RunStatusOutput,
)

router = APIRouter(prefix="/api/manager")

ReviewerDep = Annotated[
    CurrentUser, Depends(require_permission(Permission.FEEDBACK_REVIEW))
]


def get_analysis(request: Request) -> AssessmentRunsInputBoundary:
    return request.app.state.assessment_runs


AnalysisDep = Annotated[AssessmentRunsInputBoundary, Depends(get_analysis)]


def run_view(run: RunOutput) -> AnalysisRunView:
    return AnalysisRunView(
        id=str(run.id),
        attempt=run.attempt,
        status=run.status,
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
    analysis: AssessmentRunsInputBoundary, user: CurrentUser, conversation_id: str
) -> AnalysisStatus:
    try:
        result = await analysis.status(user.organization_id, conversation_id)
    except ConversationNotFoundError:
        raise not_found() from None
    return status_view(result)


def status_view(result: RunStatusOutput) -> AnalysisStatus:
    return AnalysisStatus(
        conversation_id=result.conversation_id,
        status=result.status,
        runs=[run_view(run) for run in result.runs],
    )


@router.get(
    "/conversations/{conversation_id}/analysis",
    response_model=AnalysisStatus,
    dependencies=[Depends(require_saved_calls)],
)
async def get_analysis_status(
    conversation_id: str, user: ReviewerDep, analysis: AnalysisDep
) -> AnalysisStatus:
    """Every analysis attempt for a conversation in the requester's organization."""
    return await analysis_status(analysis, user, conversation_id)


@router.post(
    "/conversations/{conversation_id}/analysis",
    response_model=AnalysisStatus,
    dependencies=[Depends(require_saved_calls)],
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
        started, snapshot = await analysis.start(
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
    result = status_view(snapshot)
    return JSONResponse(
        result.model_dump(mode="json"),
        status_code=status.HTTP_202_ACCEPTED if started.created else status.HTTP_200_OK,
    )
