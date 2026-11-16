import copy
from dataclasses import replace

import pytest
from fastapi.testclient import TestClient

from backend.core.config import Settings
from backend.main import create_app
from backend.providers import ProviderUnavailableError, create_fixture_providers
from backend.providers.fixture_data import CONVERSATIONS, NORTHWIND
from backend.schemas import Conversation

URL = "/api/agent/conversations"
ALEX = "agent-alex-morgan"
SAM = "agent-sam-rivera"
RILEY = "agent-riley-chen"


def make_client(conversations=None):
    providers = create_fixture_providers()
    if conversations is not None:
        providers = replace(providers, conversations=conversations)
    return TestClient(
        create_app(providers=providers, settings=Settings(app_env="test"))
    )


def get(user_id, client=None):
    return (client or make_client()).get(URL, headers={"X-Dev-User": user_id})


def test_agent_gets_own_conversations_newest_first():
    response = get(ALEX)
    assert response.status_code == 200
    assert [c["id"] for c in response.json()] == [
        "C1045",
        "C1044",
        "C1043",
        "C1042",
        "C1047",
        "C1046",
    ]
    assert {c["agentId"] for c in response.json()} == {ALEX}


def test_response_matches_frontend_conversation_shape():
    expected = next(c for c in CONVERSATIONS[NORTHWIND] if c["id"] == "C1042")
    c1042 = next(c for c in get(ALEX).json() if c["id"] == "C1042")
    assert c1042 == {**expected, "overallScoring": None, "sourceId": None}
    assert set(c1042) == {
        "id",
        "sourceId",
        "topic",
        "agentId",
        "agentName",
        "date",
        "automatedResult",
        "reviewStatus",
        "overallScoring",
    }


def test_agents_in_the_same_organization_see_only_their_own():
    assert [c["id"] for c in get(SAM).json()] == ["C2001"]
    assert "C2001" not in [c["id"] for c in get(ALEX).json()]


def test_agents_in_another_organization_see_only_theirs():
    assert [c["id"] for c in get(RILEY).json()] == ["C3001"]


def test_processing_and_review_status_stay_separate():
    by_id = {c["id"]: c for c in get(ALEX).json()}
    assert by_id["C1045"]["automatedResult"] == "processing"
    assert by_id["C1045"]["reviewStatus"] is None
    assert by_id["C1043"]["automatedResult"] == "meets-criteria"
    assert by_id["C1043"]["reviewStatus"] == "review-complete"
    assert by_id["C1042"]["automatedResult"] == "needs-review"
    assert by_id["C1042"]["reviewStatus"] == "feedback-ready"


class _Empty:
    async def list_for_agent(self, organization_id, agent_id):
        return []


class _Broken:
    async def list_for_agent(self, organization_id, agent_id):
        raise ProviderUnavailableError


class _Spy:
    def __init__(self):
        self.calls = []

    async def list_for_agent(self, organization_id, agent_id):
        self.calls.append((organization_id, agent_id))
        return []


class _Leaky:
    """A buggy provider that returns another agent's conversation."""

    async def list_for_agent(self, organization_id, agent_id):
        rows = copy.deepcopy(CONVERSATIONS[NORTHWIND])
        return [Conversation.model_validate(row) for row in rows]


def test_empty_result_is_an_empty_list():
    response = get(ALEX, make_client(_Empty()))
    assert response.status_code == 200
    assert response.json() == []


def test_provider_failure_is_503_not_empty():
    response = get(ALEX, make_client(_Broken()))
    assert response.status_code == 503
    assert response.json() == {"detail": "Data source unavailable"}


def test_provider_is_asked_for_the_requesters_organization_and_id():
    spy = _Spy()
    get(RILEY, make_client(spy))
    assert spy.calls == [("org-harbor", RILEY)]


def test_client_supplied_ids_are_ignored():
    spy = _Spy()
    make_client(spy).get(
        f"{URL}?agentId={SAM}&organizationId=org-harbor",
        headers={
            "X-Dev-User": ALEX,
            "X-Agent-Id": SAM,
            "X-Organization-Id": "org-harbor",
        },
    )
    assert spy.calls == [("org-northwind", ALEX)]


def test_records_for_other_agents_are_never_returned():
    response = get(ALEX, make_client(_Leaky()))
    assert {c["agentId"] for c in response.json()} == {ALEX}


def test_missing_identity_is_rejected():
    assert make_client().get(URL).status_code == 401


@pytest.mark.parametrize("user_id", ["manager-maya-chen", "approver-devon-park"])
def test_users_without_agent_permission_are_forbidden(user_id):
    assert get(user_id).status_code == 403
