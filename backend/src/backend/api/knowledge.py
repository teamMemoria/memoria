from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status

from backend.api.auth import require_permission
from backend.api.dependencies import ProvidersDep
from backend.core.auth import CurrentUser, Permission
from backend.schemas import KnowledgeEntry

router = APIRouter(prefix="/api/agent")

KnowledgeReaderDep = Annotated[
    CurrentUser, Depends(require_permission(Permission.KNOWLEDGE_READ))
]


def for_requester(entry: KnowledgeEntry, user: CurrentUser) -> KnowledgeEntry:
    """Hide which other agents an entry is assigned to.

    The frontend only checks whether the list includes the viewer, so returning
    just the requester's own ID keeps it working without exposing anyone else.
    """
    return entry.model_copy(update={"available_to_agent_ids": [user.user_id]})


@router.get("/knowledge", response_model=list[KnowledgeEntry])
async def list_knowledge(
    user: KnowledgeReaderDep, providers: ProvidersDep
) -> list[KnowledgeEntry]:
    """Approved guidance assigned to the requester. Draft, rejected, disputed and stale entries never appear."""
    entries = await providers.knowledge.list_for_agent(
        user.organization_id, user.user_id
    )
    return [
        for_requester(entry, user)
        for entry in entries
        if entry.readable_by(user.user_id)
    ]


@router.get("/knowledge/{entry_id}", response_model=KnowledgeEntry)
async def get_knowledge(
    entry_id: str, user: KnowledgeReaderDep, providers: ProvidersDep
) -> KnowledgeEntry:
    # Same rule as the list, and the same 404 whether the entry is missing,
    # not approved, not assigned to the requester or in another organization.
    entry = await providers.knowledge.get_for_agent(
        user.organization_id, user.user_id, entry_id
    )
    if entry is None or not entry.readable_by(user.user_id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Knowledge entry not found")
    return for_requester(entry, user)
