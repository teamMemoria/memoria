from dataclasses import replace

import pytest
from fastapi.testclient import TestClient

from backend.core.config import Settings
from backend.data.seed_demo_profiles import load_profiles, profile_display_name
from backend.main import create_app
from backend.providers import ProviderUnavailableError, create_fixture_providers


def make_client(app_env="test", providers=None):
    app = create_app(providers=providers, settings=Settings(app_env=app_env))
    return TestClient(app)


def test_lists_every_fixture_profile_with_conversation_counts():
    response = make_client().get("/api/demo/profiles")
    assert response.status_code == 200
    profiles = {profile["id"]: profile for profile in response.json()}
    assert profiles["agent-alex-morgan"] == {
        "id": "agent-alex-morgan",
        "displayName": "Alex Morgan",
        "role": "agent",
        "conversationCount": 6,
    }
    assert profiles["manager-maya-chen"]["conversationCount"] is None


def test_each_listed_profile_signs_in_as_itself():
    client = make_client()
    for profile in client.get("/api/demo/profiles").json():
        viewer = client.get("/api/viewer", headers={"X-Dev-User": profile["id"]})
        assert viewer.status_code == 200
        assert viewer.json()["role"] == profile["role"]


def test_profiles_are_not_offered_in_production():
    assert (
        make_client(app_env="production").get("/api/demo/profiles").status_code == 404
    )


def test_unavailable_data_source_is_a_503():
    class Failing:
        async def list_profiles(self):
            raise ProviderUnavailableError

    providers = replace(create_fixture_providers(), demo_profiles=Failing())
    response = make_client(providers=providers).get("/api/demo/profiles")
    assert response.status_code == 503


def test_profiles_file_matches_the_abcd_mapping():
    profiles = load_profiles()
    assert profiles.manager_name == "Manager"
    assert len(profiles.agents) == 31
    assert sum(len(agent.conversations) for agent in profiles.agents) == 117
    names = {agent.name for agent in profiles.agents}
    assert {"Carol", "Carol Jensen", "Betty"} <= names


@pytest.mark.parametrize(
    ("identity", "name", "expected"),
    [
        ("demo-agent-02", "Alex (demo)", "Alex"),
        ("demo-abcd-carol-jensen", "Carol Jensen (demo)", "Carol Jensen"),
        ("demo-agent-99", "Alex", "Alex"),
        ("demo-agent-99", "A (demo) B", "A (demo) B"),
        ("real-agent", "Alex (demo)", "Alex (demo)"),
        ("demo-manager-01", "Demo Manager", "Manager"),
        ("demo-manager-01", "Manager", "Manager"),
        ("demo-manager-01", "Maya Chen", "Maya Chen"),
        ("real-manager", "Demo Manager", "Demo Manager"),
    ],
)
def test_profile_names_remove_only_legacy_demo_labels(identity, name, expected):
    assert profile_display_name(identity, name) == expected
    assert profile_display_name(identity, expected) == expected
