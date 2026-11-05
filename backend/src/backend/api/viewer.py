from fastapi import APIRouter, HTTPException, status

from backend.api.auth import CurrentUserDep
from backend.api.dependencies import ProvidersDep
from backend.schemas import Viewer

router = APIRouter(prefix="/api")


@router.get("/viewer", response_model=Viewer)
async def get_viewer(user: CurrentUserDep, providers: ProvidersDep) -> Viewer:
    # Always the requester's own profile; nothing in the request can choose another user.
    viewer = await providers.viewers.get_viewer(user.organization_id, user.user_id)
    if viewer is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Viewer not found")
    return viewer
