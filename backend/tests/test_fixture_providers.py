import pytest
from fastapi.testclient import TestClient

from backend.api.dependencies import get_providers
from backend.main import create_app
from backend.providers import create_fixture_providers
from backend.providers.fixture_data import ALEX, HARBOR, NORTHWIND, RILEY, SAM
from backend.providers.fixtures import load_fixture_data


@pytest.fixture
def providers():
    return create_fixture_providers()


def test_all_fixtures_validate():
    data = load_fixture_data()
    assert (
        data.calls[NORTHWIND]
        and data.conversations[NORTHWIND]
        and data.knowledge[NORTHWIND]
    )


def test_listed_conversations_agree_with_call_records():
    data = load_fixture_data()
    for org, conversations in data.conversations.items():
        calls = {call.id: call for call in data.calls.get(org, [])}
        for conversation in conversations:
            call = calls.get(conversation.id)
            if call is None:
                continue  # an unavailable record (C1046) is allowed
            assert call.agent_id == conversation.agent_id
            assert (call.status == "processing") == (
                conversation.automated_result == "processing"
            )


async def test_viewer_is_scoped_to_organization(providers):
    viewer = await providers.viewers.get_viewer(NORTHWIND, ALEX)
    assert viewer.model_dump() == {
        "id": ALEX,
        "displayName": "Alex Morgan",
        "role": "agent",
    }
    assert await providers.viewers.get_viewer(HARBOR, ALEX) is None


async def test_conversations_are_scoped_and_newest_first(providers):
    conversations = await providers.conversations.list_for_agent(NORTHWIND, ALEX)
    assert [c.id for c in conversations] == [
        "C1045",
        "C1044",
        "C1043",
        "C1042",
        "C1046",
    ]
    assert await providers.conversations.list_for_agent(HARBOR, ALEX) == []
    assert [
        c.id for c in await providers.conversations.list_for_agent(HARBOR, RILEY)
    ] == ["C3001"]


async def test_call_covers_each_state(providers):
    ready = await providers.calls.get_for_agent(NORTHWIND, ALEX, "C1042")
    gaps = await providers.calls.get_for_agent(NORTHWIND, ALEX, "C1043")
    no_transcript = await providers.calls.get_for_agent(NORTHWIND, ALEX, "C1044")
    processing = await providers.calls.get_for_agent(NORTHWIND, ALEX, "C1045")

    assert ready.status == "ready" and ready.decision is None
    assert [t.number for t in gaps.transcript.turns] == [1, 2, 5, 6, 9, 10, 11]
    assert gaps.decision.outcome == "confirmed"
    assert no_transcript.transcript is None
    assert {c.result for c in no_transcript.criteria} == {"cannot-assess"}
    assert processing.status == "processing" and processing.criteria == []


async def test_call_is_none_when_unavailable_or_not_owned(providers):
    assert await providers.calls.get_for_agent(NORTHWIND, ALEX, "C1046") is None
    assert await providers.calls.get_for_agent(NORTHWIND, ALEX, "C2001") is None
    assert await providers.calls.get_for_agent(NORTHWIND, SAM, "C1042") is None
    assert await providers.calls.get_for_agent(HARBOR, ALEX, "C1042") is None


async def test_knowledge_lists_only_approved_and_assigned(providers):
    entries = await providers.knowledge.list_for_agent(NORTHWIND, ALEX)
    assert [e.id for e in entries] == ["RP-01", "KB-02"]


@pytest.mark.parametrize(
    "entry_id", ["KB-03", "KB-04", "KB-05", "KB-06", "KB-07", "KB-90", "missing"]
)
async def test_knowledge_detail_hides_what_the_list_hides(providers, entry_id):
    assert await providers.knowledge.get_for_agent(NORTHWIND, ALEX, entry_id) is None


async def test_returned_records_are_copies(providers):
    call = await providers.calls.get_for_agent(NORTHWIND, ALEX, "C1042")
    call.criteria.clear()
    again = await providers.calls.get_for_agent(NORTHWIND, ALEX, "C1042")
    assert len(again.criteria) == 4


def test_app_runs_on_fixture_providers():
    app = create_app()
    with TestClient(app) as client:
        assert client.get("/health").json() == {"status": "ok"}
    assert app.dependency_overrides.get(get_providers) is None
    assert app.state.providers.calls is not None
