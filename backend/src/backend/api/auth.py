from typing import Annotated

from fastapi import Depends, Header, HTTPException, Request, status

from backend.api.dependencies import ProvidersDep
from backend.core.auth import CurrentUser, Permission
from backend.core.config import Settings


def get_settings(request: Request) -> Settings:
    return request.app.state.settings


async def get_current_user(
    settings: Annotated[Settings, Depends(get_settings)],
    providers: ProvidersDep,
    x_dev_user: Annotated[str | None, Header()] = None,
    x_organization: Annotated[str | None, Header()] = None,
) -> CurrentUser:
    """Identify the requester.

    There is no login system yet. In development and test mode the X-Dev-User
    header stands in for the user ID a login system would have verified. In any
    other mode every request is rejected, so the header can never be used in
    production.

    The header only names who is asking. Their organization and permissions
    always come from the identity provider (the stored membership in database
    mode), never from the request, so a client cannot pick its own role.
    X-Organization only chooses between organizations the user already belongs to.
    """
    if not settings.dev_identity_enabled:
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED, "Authentication is not configured"
        )
    if x_dev_user is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Missing identity")

    user = await providers.identities.resolve(x_dev_user, x_organization)
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
