from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status

from backend.entities.identity import CurrentUser, Permission
from backend.frameworks.http.auth import require_permission
from backend.frameworks.http.demo_scorecards import (
    DemoScorecardsDep,
    require_saved_calls,
)
from backend.frameworks.http.dependencies import ProvidersDep
from backend.interface_adapters.presenters.reviews import present_decision
from backend.providers import (
    ConflictError,
    Providers,
    ProviderUnavailableError,
    RecordNotFoundError,
    ReviewProvider,
)
from backend.schemas import ManagerDecision
from backend.schemas.reviews import (
    DecisionInput,
    FindingReviewDetail,
    QueueStatus,
    TeamConversation,
)
from backend.use_cases.record_review_decision import RecordReviewDecision

router = APIRouter(prefix="/api/manager")

ReviewerDep = Annotated[
    CurrentUser, Depends(require_permission(Permission.FEEDBACK_REVIEW))
]


def review_provider(providers: Providers) -> ReviewProvider:
    # The review queue needs the database; the fixtures have no Manager data.
    if providers.reviews is None:
        raise ProviderUnavailableError("no review provider configured")
    return providers.reviews


@router.get("/conversations", response_model=list[TeamConversation])
async def list_team_conversations(
    user: ReviewerDep,
    providers: ProvidersDep,
    scorecards: DemoScorecardsDep,
    status_filter: Annotated[QueueStatus, Query(alias="status")] = "all",
    q: Annotated[str, Query(max_length=200)] = "",
) -> list[TeamConversation]:
    """Conversations in the requester's organization, with any review request.

    ``status`` filters like the frontend's status menu (``processing`` matches
    the automated result, the others the review status); ``q`` searches the
    call ID, topic, agent name, request reason and finding title.
    """
    try:
        rows = await review_provider(providers).list_for_manager(
            user.organization_id,
            user.user_id,
            "all" if scorecards else status_filter,
            "" if scorecards else q,
        )
    except RecordNotFoundError:
        return []
    return scorecards.conversations(rows) if scorecards else rows


@router.get("/conversations/{conversation_id}", response_model=FindingReviewDetail)
async def get_team_call(
    conversation_id: str,
    user: ReviewerDep,
    providers: ProvidersDep,
    scorecards: DemoScorecardsDep,
) -> FindingReviewDetail:
    """The call, its findings with evidence, the agent's context and any decision."""
    try:
        detail = await review_provider(providers).get_for_manager(
            user.organization_id, user.user_id, conversation_id
        )
    except RecordNotFoundError:
        detail = None
    if detail is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Conversation not found")
    if scorecards:
        return FindingReviewDetail(call=scorecards.call(detail.call), can_decide=False)
    return detail


@router.post(
    "/conversations/{conversation_id}/findings/{finding_id}/decision",
    response_model=ManagerDecision,
    dependencies=[Depends(require_saved_calls)],
    status_code=status.HTTP_201_CREATED,
    responses={
        200: {"description": "The same decision was already recorded"},
        409: {"description": "A different decision was already recorded"},
    },
)
async def decide(
    conversation_id: str,
    finding_id: str,
    body: DecisionInput,
    user: ReviewerDep,
    providers: ProvidersDep,
    response: Response,
) -> ManagerDecision:
    """Record a decision on an agent's review request.

    The decision is stored beside the automated finding, which is never changed.
    A request is decided once: sending the same decision again returns it with
    200, and a different one is a 409.
    """
    try:
        async with review_provider(providers).decision_repository(
            user.organization_id, user.user_id, conversation_id, finding_id
        ) as repository:
            result, created = await RecordReviewDecision().execute(
                body.to_decision(), repository
            )
    except RecordNotFoundError as error:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(error)) from None
    except ConflictError as error:
        raise HTTPException(status.HTTP_409_CONFLICT, str(error)) from None
    if not created:
        response.status_code = status.HTTP_200_OK
    return present_decision(result)
