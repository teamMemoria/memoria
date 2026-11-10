from typing import Annotated

import pytest
from fastapi import Depends
from fastapi.testclient import TestClient

from backend.api.auth import require_permission
from backend.core.auth import (
    DEV_IDENTITIES,
    CurrentUser,
    Permission,
    can_read_agent_record,
)
from backend.core.config import Settings
from backend.main import create_app
from backend.providers import ProviderUnavailableError, create_fixture_providers

ALEX = "agent-alex-morgan"
SAM = "agent-sam-rivera"
MAYA = "manager-maya-chen"
DEVON = "approver-devon-park"
RILEY = "agent-riley-chen"


def make_client(app_env="test", providers=None):
    app = create_app(providers=providers, settings=Settings(app_env=app_env))

    # A route per permission, so the checks can be exercised over HTTP.
    for permission in Permission:

        def route(
            user: Annotated[CurrentUser, Depends(require_permission(permission))],
        ):
            return {"userId": user.user_id}

        app.get(f"/test/{permission.value}")(route)

    return TestClient(app)


def as_user(user_id):
    return {"X-Dev-User": user_id}


# --- identity -----------------------------------------------------------------


def test_missing_identity_is_rejected():
    response = make_client().get("/api/viewer")
    assert response.status_code == 401
    assert response.json() == {"detail": "Missing identity"}


def test_unknown_identity_is_rejected():
    response = make_client().get("/api/viewer", headers=as_user("agent-nobody"))
    assert response.status_code == 401


@pytest.mark.parametrize("app_env", ["development", "test"])
def test_dev_identity_works_in_development_and_test(app_env):
    response = make_client(app_env).get("/api/viewer", headers=as_user(ALEX))
    assert response.status_code == 200


def test_dev_identity_is_disabled_in_production():
    response = make_client("production").get("/api/viewer", headers=as_user(ALEX))
    assert response.status_code == 401
    assert response.json() == {"detail": "Authentication is not configured"}


def test_settings_default_to_production(monkeypatch):
    monkeypatch.delenv("MEMORIA_APP_ENV", raising=False)
    assert Settings().app_env == "production"
    assert not Settings().dev_identity_enabled


def test_settings_read_environment(monkeypatch):
    monkeypatch.setenv("MEMORIA_APP_ENV", "development")
    assert Settings().dev_identity_enabled


# --- viewer -------------------------------------------------------------------


@pytest.mark.parametrize(
    ("user_id", "expected"),
    [
        (ALEX, {"id": ALEX, "displayName": "Alex Morgan", "role": "agent"}),
        (MAYA, {"id": MAYA, "displayName": "Maya Chen", "role": "manager"}),
        (DEVON, {"id": DEVON, "displayName": "Devon Park", "role": "manager"}),
        (RILEY, {"id": RILEY, "displayName": "Riley Chen", "role": "agent"}),
    ],
)
def test_viewer_matches_frontend_shape(user_id, expected):
    response = make_client().get("/api/viewer", headers=as_user(user_id))
    assert response.json() == expected


def test_client_supplied_agent_id_cannot_change_the_requester():
    response = make_client().get(
        f"/api/viewer?agentId={SAM}&userId={SAM}",
        headers={**as_user(ALEX), "X-Agent-Id": SAM, "X-Organization-Id": "org-harbor"},
    )
    assert response.json()["id"] == ALEX


class _NoViewers:
    async def get_viewer(self, organization_id, user_id):
        return None


class _BrokenViewers:
    async def get_viewer(self, organization_id, user_id):
        raise ProviderUnavailableError


def _with_viewers(viewers):
    fixtures = create_fixture_providers()
    return type(fixtures)(
        viewers, fixtures.conversations, fixtures.calls, fixtures.knowledge
    )


def test_viewer_without_profile_is_not_found():
    response = make_client(providers=_with_viewers(_NoViewers())).get(
        "/api/viewer", headers=as_user(ALEX)
    )
    assert response.status_code == 404


def test_provider_failure_is_503_not_empty():
    response = make_client(providers=_with_viewers(_BrokenViewers())).get(
        "/api/viewer", headers=as_user(ALEX)
    )
    assert response.status_code == 503
    assert response.json() == {"detail": "Data source unavailable"}


# --- permissions ----------------------------------------------------------------

ALLOWED = {
    ALEX: {Permission.CONVERSATIONS_READ_OWN, Permission.KNOWLEDGE_READ},
    MAYA: {Permission.FEEDBACK_REVIEW, Permission.KNOWLEDGE_READ},
    DEVON: {Permission.KNOWLEDGE_APPROVE, Permission.KNOWLEDGE_READ},
}


@pytest.mark.parametrize("user_id", list(ALLOWED))
@pytest.mark.parametrize("permission", list(Permission))
def test_permission_matrix(user_id, permission):
    response = make_client().get(f"/test/{permission.value}", headers=as_user(user_id))
    if permission in ALLOWED[user_id]:
        assert response.status_code == 200
        assert response.json() == {"userId": user_id}
    else:
        assert response.status_code == 403


def test_manager_review_and_knowledge_approval_are_separate():
    manager = DEV_IDENTITIES[MAYA]
    approver = DEV_IDENTITIES[DEVON]
    assert manager.has(Permission.FEEDBACK_REVIEW) and not manager.has(
        Permission.KNOWLEDGE_APPROVE
    )
    assert approver.has(Permission.KNOWLEDGE_APPROVE) and not approver.has(
        Permission.FEEDBACK_REVIEW
    )


def test_permission_check_runs_after_identity_check():
    response = make_client().get(f"/test/{Permission.FEEDBACK_REVIEW.value}")
    assert response.status_code == 401


# --- ownership and organization ------------------------------------------------


def test_agent_can_read_own_record():
    assert can_read_agent_record(DEV_IDENTITIES[ALEX], "org-northwind", ALEX)


def test_agent_cannot_read_another_agents_record():
    assert not can_read_agent_record(DEV_IDENTITIES[ALEX], "org-northwind", SAM)


def test_agent_cannot_read_another_organizations_record():
    assert not can_read_agent_record(DEV_IDENTITIES[ALEX], "org-harbor", ALEX)


def test_record_access_needs_the_permission_not_just_the_id():
    no_permissions = CurrentUser(ALEX, "org-northwind", frozenset())
    assert not can_read_agent_record(no_permissions, "org-northwind", ALEX)


def test_current_user_cannot_be_changed():
    user = DEV_IDENTITIES[ALEX]
    with pytest.raises(AttributeError):
        user.permissions = frozenset(Permission)  # type: ignore[misc]


async def test_dev_identities_have_viewer_profiles():
    providers = create_fixture_providers()
    for user in DEV_IDENTITIES.values():
        viewer = await providers.viewers.get_viewer(user.organization_id, user.user_id)
        assert viewer is not None, user.user_id
