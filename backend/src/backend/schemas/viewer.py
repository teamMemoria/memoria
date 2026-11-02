from typing import Literal

from backend.schemas.base import ApiModel

# Matches ViewerRole in frontend/src/types/viewer.ts.
ViewerRole = Literal["agent", "manager"]


class Viewer(ApiModel):
    id: str
    display_name: str
    role: ViewerRole
