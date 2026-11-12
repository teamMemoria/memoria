from typing import Literal

from backend.schemas.base import ApiModel

# Matches ViewerRole in frontend/src/types/viewer.ts.
ViewerRole = Literal["agent", "manager"]


class Viewer(ApiModel):
    id: str
    display_name: str
    role: ViewerRole


class DemoProfile(ApiModel):
    """A profile offered on the demo entry screen. Matches DemoProfile in frontend/src/types/viewer.ts."""

    id: str
    display_name: str
    role: ViewerRole
    # Conversations already imported for an Agent; null for Managers.
    conversation_count: int | None = None
