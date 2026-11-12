from fastapi import APIRouter, HTTPException, Response, status

from backend.api.conversations import AgentDep
from backend.api.dependencies import ProvidersDep
from backend.api.knowledge import for_requester
from backend.core.auth import can_read_agent_record
from backend.providers import (
    FeedbackProvider,
    Providers,
    ProviderUnavailableError,
    RecordNotFoundError,
)
from backend.schemas import AgentContext, CallReview, ReviewRequest
from backend.schemas.feedback import RequestReviewInput, SaveContextInput

router = APIRouter(prefix="/api/agent")


@router.get("/conversations/{conversation_id}", response_model=CallReview)
async def get_call(
    conversation_id: str, user: AgentDep, providers: ProvidersDep
) -> CallReview:
    """The call overview and audit evidence for one of the requester's conversations.

    Unknown calls, other agents' calls and other organizations' calls all get the
    same 404, so a response never reveals that someone else's call exists.
    """
    call = await providers.calls.get_for_agent(
        user.organization_id, user.user_id, conversation_id
    )
    # The provider is already scoped; the ownership check guards against a provider bug.
    if call is None or not can_read_agent_record(
        user, user.organization_id, call.agent_id
    ):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Conversation not found")
    # References follow the same rule as the knowledge routes: no other agents' IDs.
    return call.model_copy(
        update={
            "references": [
                for_requester(reference, user) for reference in call.references
            ]
        }
    )


def feedback_provider(providers: Providers) -> FeedbackProvider:
    # Saving needs the database; the fixtures are read-only.
    if providers.feedback is None:
        raise ProviderUnavailableError("no feedback provider configured")
    return providers.feedback


@router.put("/conversations/{conversation_id}/context", response_model=AgentContext)
async def save_context(
    conversation_id: str,
    body: SaveContextInput,
    user: AgentDep,
    providers: ProvidersDep,
) -> AgentContext:
    """Save the requester's note on one of their calls.

    This only stores the note. It never asks a Manager for a review; that is
    a separate request below.
    """
    try:
        return await feedback_provider(providers).save_context(
            user.organization_id, user.user_id, conversation_id, body.text
        )
    except RecordNotFoundError as error:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(error)) from None


@router.post(
    "/conversations/{conversation_id}/review-requests",
    response_model=ReviewRequest,
    status_code=status.HTTP_201_CREATED,
    responses={200: {"description": "The finding already had a review request"}},
)
async def request_review(
    conversation_id: str,
    body: RequestReviewInput,
    user: AgentDep,
    providers: ProvidersDep,
    response: Response,
) -> ReviewRequest:
    """Ask a Manager to review one finding on the requester's call.

    A finding has one review request at most: asking again returns the
    existing request with 200 and changes nothing. The automated finding
    itself is never changed.
    """
    try:
        review_request, created = await feedback_provider(providers).request_review(
            user.organization_id,
            user.user_id,
            conversation_id,
            body.finding_id,
            body.reason,
        )
    except RecordNotFoundError as error:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(error)) from None
    if not created:
        response.status_code = status.HTTP_200_OK
    return review_request
