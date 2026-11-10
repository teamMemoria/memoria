from typing import Annotated

from fastapi import Depends, Header, HTTPException, Request, status

from backend.core.auth import DEV_IDENTITIES, CurrentUser, Permission
from backend.core.config import Settings


def get_settings(request: Request) -> Settings:
    return request.app.state.settings


def get_current_user(
    settings: Annotated[Settings, Depends(get_settings)],
    x_dev_user: Annotated[str | None, Header()] = None,
) -> CurrentUser:
    """Identify the requester.

    There is no login system yet. In development and test mode the requester is
    one of the fixed DEV_IDENTITIES, named in the X-Dev-User header. In any other
    mode every request is rejected, so the header can never be used in production.
    """
    if not settings.dev_identity_enabled:
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED, "Authentication is not configured"
        )
    if x_dev_user is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Missing identity")

    user = DEV_IDENTITIES.get(x_dev_user)
    if user is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Unknown identity")
    return user


CurrentUserDep = Annotated[CurrentUser, Depends(get_current_user)]


def require_permission(permission: Permission):
    """Route dependency that returns the current user, or rejects them with 403."""

    def check(user: CurrentUserDep) -> CurrentUser:
        if not user.has(permission):
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Not permitted")
        return user

    return check
