import pytest
from fastapi.testclient import TestClient

from backend.core.config import Settings
from backend.main import create_app
from backend.providers import create_fixture_providers

FRONTEND = "https://memoria-ftl.netlify.app"
OTHER = "https://other.example"


def client(origins=FRONTEND):
    app = create_app(
        providers=create_fixture_providers(),
        settings=Settings(app_env="production", cors_origins=origins),
    )
    return TestClient(app)


@pytest.mark.parametrize("method", ["GET", "POST", "PUT"])
def test_frontend_preflight_allows_used_methods_and_headers(method):
    response = client().options(
        "/api/viewer",
        headers={
            "Origin": FRONTEND,
            "Access-Control-Request-Method": method,
            "Access-Control-Request-Headers": "content-type,x-dev-user,x-organization",
        },
    )

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == FRONTEND
    assert response.headers["access-control-allow-credentials"] == "true"
    allowed_headers = response.headers["access-control-allow-headers"].lower()
    assert all(
        header in allowed_headers
        for header in ("content-type", "x-dev-user", "x-organization")
    )


def test_unlisted_origin_receives_no_cors_authorization():
    response = client().options(
        "/api/viewer",
        headers={
            "Origin": OTHER,
            "Access-Control-Request-Method": "GET",
            "Access-Control-Request-Headers": "x-dev-user",
        },
    )
    assert response.status_code == 400
    assert "access-control-allow-origin" not in response.headers


def test_cors_does_not_authenticate_a_request():
    response = client().get(
        "/api/viewer", headers={"Origin": FRONTEND, "X-Dev-User": "agent-alex-morgan"}
    )
    assert response.status_code == 401
    assert response.headers["access-control-allow-origin"] == FRONTEND


def test_origin_setting_defaults_closed_and_rejects_wildcards():
    assert Settings(cors_origins="").allowed_cors_origins == []
    assert Settings(cors_origins=f" {FRONTEND}/, {FRONTEND} ").allowed_cors_origins == [
        FRONTEND
    ]
    with pytest.raises(ValueError, match="exact HTTP"):
        assert Settings(cors_origins="*").allowed_cors_origins
    with pytest.raises(ValueError, match="exact HTTP"):
        assert Settings(cors_origins=f"{FRONTEND}/path").allowed_cors_origins
