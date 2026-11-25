from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status

from backend.core.config import Settings
from backend.data.demo_profiles import demo_profile_ids
from backend.frameworks.http.auth import get_settings
from backend.frameworks.http.demo_scorecards import DemoScorecardsDep
from backend.frameworks.http.dependencies import ProvidersDep
from backend.schemas import DemoProfile

router = APIRouter(prefix="/api/demo")


@router.get("/profiles", response_model=list[DemoProfile])
async def list_demo_profiles(
    settings: Annotated[Settings, Depends(get_settings)],
    providers: ProvidersDep,
    scorecards: DemoScorecardsDep,
) -> list[DemoProfile]:
    # Picking a profile is how the demo signs in, so the list needs no identity.
    # It only exists where X-Dev-User is accepted; elsewhere it is a 404.
    if not settings.demo_profile_selection_enabled or providers.demo_profiles is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Not Found")
    profiles = await providers.demo_profiles.list_profiles()
    if not settings.dev_identity_enabled:
        allowed = demo_profile_ids()
        profiles = [profile for profile in profiles if profile.id in allowed]
    return scorecards.profiles(profiles) if scorecards else profiles
