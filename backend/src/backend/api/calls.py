from fastapi import APIRouter, HTTPException, status

from backend.api.conversations import AgentDep
from backend.api.dependencies import ProvidersDep
from backend.core.auth import can_read_agent_record
from backend.schemas import CallReview

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
    return call
