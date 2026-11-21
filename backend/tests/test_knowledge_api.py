from dataclasses import replace

import pytest
from fastapi.testclient import TestClient

from backend.core.config import Settings
from backend.main import create_app
from backend.providers import ProviderUnavailableError, create_fixture_providers
from backend.providers.fixture_data import KNOWLEDGE, NORTHWIND
from backend.schemas import KnowledgeEntry

URL = "/api/agent/knowledge"
ALEX = "agent-alex-morgan"
SAM = "agent-sam-rivera"
RILEY = "agent-riley-chen"
MAYA = "manager-maya-chen"


def make_client(knowledge=None):
    providers = create_fixture_providers()
    if knowledge is not None:
        providers = replace(providers, knowledge=knowledge)
    return TestClient(
        create_app(providers=providers, settings=Settings(app_env="test"))
    )


def get(path="", user_id=ALEX, client=None):
    return (client or make_client()).get(
        f"{URL}{path}", headers={"X-Dev-User": user_id}
    )


def raw_entry(entry_id):
    return next(entry for entry in KNOWLEDGE[NORTHWIND] if entry["id"] == entry_id)


# --- listing ----------------------------------------------------------------------


@pytest.mark.parametrize(
    ("user_id", "expected"),
    [(ALEX, ["RP-01", "KB-02"]), (SAM, ["RP-01", "KB-07"]), (RILEY, ["KB-90"])],
)
def test_agents_list_only_their_approved_entries(user_id, expected):
    response = get(user_id=user_id)
    assert response.status_code == 200
    assert [entry["id"] for entry in response.json()] == expected
    assert {entry["status"] for entry in response.json()} == {"approved"}


def test_user_with_no_assigned_entries_gets_an_empty_list():
    response = get(user_id=MAYA)
    assert response.status_code == 200
    assert response.json() == []


# --- detail -----------------------------------------------------------------------


@pytest.mark.parametrize("entry_id", ["RP-01", "KB-02"])
def test_agents_can_open_entries_from_their_list(entry_id):
    response = get(f"/{entry_id}")
    assert response.status_code == 200
    assert response.json()["id"] == entry_id


def test_detail_matches_frontend_shape_with_source_and_version():
    entry = get("/RP-01").json()
    assert entry == {**raw_entry("RP-01"), "availableToAgentIds": [ALEX]}
    assert entry["version"] == "v1"
    assert entry["source"] == {
        "title": "Refund handling procedure RP-01 v1",
        "url": None,
    }
    assert entry["approvedAt"] == "2026-10-01"
    assert [step["number"] for step in entry["steps"]] == [1, 2, 3, 4]


def test_unknown_dates_stay_unknown():
    entry = get("/KB-02").json()
    for field in [
        "approvedAt",
        "approvedBy",
        "effectiveAt",
        "lastConfirmedAt",
        "owner",
        "source",
    ]:
        assert entry[field] is None, field


@pytest.mark.parametrize(
    "entry_id",
    [
        "KB-03",  # draft
        "KB-04",  # disputed
        "KB-05",  # stale
        "KB-06",  # rejected
        "KB-07",  # approved, but assigned to Sam only
        "KB-90",  # another organization
        "KB-404",  # does not exist
    ],
)
def test_direct_requests_cannot_reach_entries_hidden_from_the_list(entry_id):
    response = get(f"/{entry_id}")
    assert response.status_code == 404
    assert response.json() == {"detail": "Knowledge entry not found"}


@pytest.mark.parametrize("status", ["draft", "disputed", "stale", "rejected"])
def test_every_non_approved_status_is_excluded(status):
    """Even a provider that returns the entry cannot get it past the route."""
    entry = KnowledgeEntry.model_validate({**raw_entry("RP-01"), "status": status})
    client = make_client(_Returns([entry]))
    assert get(user_id=ALEX, client=client).json() == []
    assert get("/RP-01", user_id=ALEX, client=client).status_code == 404


def test_other_agents_ids_are_not_exposed():
    entries = get(user_id=SAM).json()
    rp01 = next(entry for entry in entries if entry["id"] == "RP-01")
    assert rp01["availableToAgentIds"] == [SAM]
    assert get("/RP-01", user_id=SAM).json()["availableToAgentIds"] == [SAM]


def test_entry_assigned_to_someone_else_is_excluded_even_if_the_provider_leaks_it():
    entry = KnowledgeEntry.model_validate(raw_entry("KB-07"))  # Sam only
    client = make_client(_Returns([entry]))
    assert get(user_id=ALEX, client=client).json() == []
    assert get("/KB-07", user_id=ALEX, client=client).status_code == 404


# --- access and failures ----------------------------------------------------------


def test_missing_identity_is_rejected():
    assert make_client().get(URL).status_code == 401
    assert make_client().get(f"{URL}/RP-01").status_code == 401


@pytest.mark.parametrize("path", ["", "/RP-01"])
def test_provider_failure_is_503(path):
    response = get(path, client=make_client(_Broken()))
    assert response.status_code == 503


class _Returns:
    """A provider that returns the given entries without applying any rules."""

    def __init__(self, entries):
        self.entries = entries

    async def list_for_agent(self, organization_id, agent_id):
        return list(self.entries)

    async def get_for_agent(self, organization_id, agent_id, entry_id):
        return next((entry for entry in self.entries if entry.id == entry_id), None)


class _Broken:
    async def list_for_agent(self, organization_id, agent_id):
        raise ProviderUnavailableError

    async def get_for_agent(self, organization_id, agent_id, entry_id):
        raise ProviderUnavailableError
