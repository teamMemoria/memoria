from typing import Annotated

from fastapi import APIRouter, Depends

from backend.api.auth import require_permission
from backend.api.dependencies import ProvidersDep
from backend.core.auth import CurrentUser, Permission
from backend.schemas import Conversation

router = APIRouter(prefix="/api/agent")

AgentDep = Annotated[
    CurrentUser, Depends(require_permission(Permission.CONVERSATIONS_READ_OWN))
]


@router.get("/conversations", response_model=list[Conversation])
async def list_conversations(
    user: AgentDep, providers: ProvidersDep
) -> list[Conversation]:
    """The requester's own conversations, newest first. An agent with none gets []."""
    conversations = await providers.conversations.list_for_agent(
        user.organization_id, user.user_id
    )
    # The provider is already scoped, but never let a record for someone else slip through.
    return [
        conversation
        for conversation in conversations
        if conversation.agent_id == user.user_id
    ]
