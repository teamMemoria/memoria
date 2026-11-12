from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status

from backend.api.auth import get_settings
from backend.api.dependencies import ProvidersDep
from backend.core.config import Settings
from backend.schemas import DemoProfile

router = APIRouter(prefix="/api/demo")


@router.get("/profiles", response_model=list[DemoProfile])
async def list_demo_profiles(
    settings: Annotated[Settings, Depends(get_settings)], providers: ProvidersDep
) -> list[DemoProfile]:
    # Picking a profile is how the demo signs in, so the list needs no identity.
    # It only exists where X-Dev-User is accepted; elsewhere it is a 404.
    if not settings.dev_identity_enabled or providers.demo_profiles is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Not Found")
    return await providers.demo_profiles.list_profiles()
