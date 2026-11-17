"""Turn loaded identity values into the existing public response shapes."""

from backend.data.demo_profiles import profile_display_name
from backend.schemas import DemoProfile, Viewer


def demo_profile(user_id: str, name: str, is_agent: bool, count: int) -> DemoProfile:
    return DemoProfile(
        id=user_id,
        display_name=profile_display_name(user_id, name),
        role="agent" if is_agent else "manager",
        conversation_count=count if is_agent else None,
    )


def viewer(user_id: str, name: str, is_agent: bool) -> Viewer:
    return Viewer(
        id=user_id,
        display_name=profile_display_name(user_id, name),
        role="agent" if is_agent else "manager",
    )
