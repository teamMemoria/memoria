"""Progress routes with a stand-in provider: roles, query checks and failures."""

from dataclasses import replace
from datetime import date

import pytest
from fastapi.testclient import TestClient

from backend.core.config import Settings
from backend.entities.progress import DateRange, ProgressPeriod
from backend.main import create_app
from backend.providers import ProviderUnavailableError, create_fixture_providers
from backend.schemas.progress import AgentProgress

ALEX = {"X-Dev-User": "agent-alex-morgan"}
MAYA = {"X-Dev-User": "manager-maya-chen"}
RANGE = {"from": "2026-10-05", "to": "2026-10-18"}


class Recording:
    """Answers for one known agent and remembers what it was asked."""

    def __init__(self):
        self.calls = []

    def progress(self, agent_id, dates, period):
        return AgentProgress(
            agent_id=agent_id,
            agent_name="Alex Morgan",
            period=period.value,
            from_=dates.first,
            to=dates.last,
            points=[],
        )

    async def for_agent(self, organization_id, user_id, dates, period):
        self.calls.append(("agent", organization_id, user_id, dates, period))
        return self.progress(user_id, dates, period)

    async def for_manager(self, organization_id, manager_id, agent_id, dates, period):
        self.calls.append(("manager", organization_id, manager_id, agent_id))
        if agent_id != "agent-alex-morgan":
            return None
        return self.progress(agent_id, dates, period)


@pytest.fixture
def provider():
    return Recording()


@pytest.fixture
def client(provider):
    providers = replace(create_fixture_providers(), progress=provider)
    app = create_app(providers=providers, settings=Settings(app_env="test"))
    return TestClient(app)


def test_an_agent_gets_their_own_progress(client, provider):
    response = client.get("/api/agent/progress", params=RANGE, headers=ALEX)
    assert response.status_code == 200
    assert response.json() == {
        "agentId": "agent-alex-morgan",
        "agentName": "Alex Morgan",
        "period": "week",
        "from": "2026-10-05",
        "to": "2026-10-18",
        "points": [],
    }
    assert provider.calls == [
        (
            "agent",
            "org-northwind",
            "agent-alex-morgan",
            DateRange(date(2026, 10, 5), date(2026, 10, 18)),
            ProgressPeriod.WEEK,
        )
    ]


def test_a_manager_gets_an_agent_in_their_organization(client, provider):
    response = client.get(
        "/api/manager/agents/agent-alex-morgan/progress",
        params={**RANGE, "period": "month"},
        headers=MAYA,
    )
    assert response.status_code == 200
    assert response.json()["period"] == "month"
    assert provider.calls == [
        ("manager", "org-northwind", "manager-maya-chen", "agent-alex-morgan")
    ]


def test_an_agent_the_manager_cannot_see_is_a_404(client):
    response = client.get(
        "/api/manager/agents/agent-riley-chen/progress", params=RANGE, headers=MAYA
    )
    assert response.status_code == 404


def test_each_role_is_kept_to_its_own_route(client, provider):
    agent_on_manager_route = client.get(
        "/api/manager/agents/agent-sam-rivera/progress", params=RANGE, headers=ALEX
    )
    manager_on_agent_route = client.get(
        "/api/agent/progress", params=RANGE, headers=MAYA
    )
    assert agent_on_manager_route.status_code == 403
    assert manager_on_agent_route.status_code == 403
    assert provider.calls == []


def test_missing_identity_is_rejected(client):
    assert client.get("/api/agent/progress", params=RANGE).status_code == 401


@pytest.mark.parametrize(
    "params",
    [
        {},
        {"from": "2026-10-05"},
        {"from": "2026-10-18", "to": "2026-10-05"},
        {"from": "2026-13-01", "to": "2026-12-31"},
        {"from": "last week", "to": "2026-10-18"},
        {**RANGE, "period": "year"},
        {"from": "2020-01-01", "to": "2026-01-01", "period": "day"},
    ],
)
def test_invalid_dates_and_periods_are_rejected(client, provider, params):
    response = client.get("/api/agent/progress", params=params, headers=ALEX)
    assert response.status_code == 422
    assert provider.calls == []


def test_progress_needs_the_database_when_running_on_fixtures():
    app = create_app(
        providers=create_fixture_providers(), settings=Settings(app_env="test")
    )
    response = TestClient(app).get("/api/agent/progress", params=RANGE, headers=ALEX)
    assert response.status_code == 503


def test_a_database_failure_is_a_503():
    class Failing:
        async def for_agent(self, *args):
            raise ProviderUnavailableError("database unavailable")

    providers = replace(create_fixture_providers(), progress=Failing())
    app = create_app(providers=providers, settings=Settings(app_env="test"))
    response = TestClient(app).get("/api/agent/progress", params=RANGE, headers=ALEX)
    assert response.status_code == 503
