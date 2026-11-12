from dataclasses import dataclass, replace

import httpx
import pytest
from sqlalchemy import select
from sqlalchemy.exc import OperationalError

from backend.core.auth import Permission
from backend.core.config import Settings
from backend.main import create_app
from backend.models import OrganizationMembership, User, UserRole
from backend.providers import (
    FixtureIdentityProvider,
    Providers,
    create_fixture_providers,
)
from backend.providers.database import create_database_providers
from backend.providers.fixture_data import KNOWLEDGE
from tests.database_seed import (
    ALEX,
    HARBOR,
    MAYA,
    NORTHWIND,
    RILEY,
    SAM,
    UNLINKED,
    seed,
    sessions_for,
)

# --- the same behaviour from both providers -----------------------------------------


@dataclass
class Backend:
    providers: Providers
    own_conversation: str
    other_agents_conversation: str
    other_organizations_conversation: str
    hidden_entry: str


async def fixture_backend(session) -> Backend:
    return Backend(
        providers=create_fixture_providers(),
        own_conversation="C1042",
        other_agents_conversation="C2001",
        other_organizations_conversation="C3001",
        hidden_entry=next(
            entry["id"]
            for entry in KNOWLEDGE[NORTHWIND]
            if entry["status"] != "approved"
        ),
    )


async def database_backend(session) -> Backend:
    data = await seed(session)
    return Backend(
        providers=create_database_providers(sessions_for(session)),
        own_conversation=data.id(data.assessed),
        other_agents_conversation=data.id(data.sam_call),
        other_organizations_conversation=data.id(data.harbor_call),
        hidden_entry=data.id(data.disputed_entry),
    )


@pytest.fixture(
    params=[fixture_backend, database_backend], ids=["fixtures", "database"]
)
async def backend(request, session) -> Backend:
    return await request.param(session)


async def test_agent_lists_only_their_own_conversations_newest_first(backend):
    conversations = await backend.providers.conversations.list_for_agent(
        NORTHWIND, ALEX
    )
    assert conversations
    assert {conversation.agent_id for conversation in conversations} == {ALEX}
    dated = [conversation.date for conversation in conversations if conversation.date]
    assert dated == sorted(dated, reverse=True)


async def test_agent_sees_nothing_in_another_organization(backend):
    assert await backend.providers.conversations.list_for_agent(HARBOR, ALEX) == []


async def test_call_detail_is_scoped_to_the_owner(backend):
    calls = backend.providers.calls
    own = await calls.get_for_agent(NORTHWIND, ALEX, backend.own_conversation)
    assert own is not None and own.agent_id == ALEX
    assert (
        await calls.get_for_agent(NORTHWIND, ALEX, backend.other_agents_conversation)
        is None
    )
    assert (
        await calls.get_for_agent(
            NORTHWIND, ALEX, backend.other_organizations_conversation
        )
        is None
    )
    assert await calls.get_for_agent(HARBOR, ALEX, backend.own_conversation) is None
    assert await calls.get_for_agent(NORTHWIND, ALEX, "999999") is None
    assert await calls.get_for_agent(NORTHWIND, ALEX, "not-an-id") is None


async def test_ready_calls_have_one_result_per_criterion(backend):
    call = await backend.providers.calls.get_for_agent(
        NORTHWIND, ALEX, backend.own_conversation
    )
    assert call.status == "ready"
    assert sorted(criterion.id for criterion in call.criteria) == sorted(
        ["procedure", "answer-support", "completeness", "communication-style"]
    )


async def test_knowledge_list_and_detail_follow_one_rule(backend):
    knowledge = backend.providers.knowledge
    entries = await knowledge.list_for_agent(NORTHWIND, ALEX)
    assert entries
    assert all(entry.readable_by(ALEX) for entry in entries)
    for entry in entries:
        assert await knowledge.get_for_agent(NORTHWIND, ALEX, entry.id) == entry
    assert await knowledge.get_for_agent(NORTHWIND, ALEX, backend.hidden_entry) is None
    assert await knowledge.list_for_agent(HARBOR, ALEX) == []
    assert await knowledge.list_for_agent(NORTHWIND, MAYA) == []


async def test_viewer_comes_from_the_requesters_own_record(backend):
    viewers = backend.providers.viewers
    assert (await viewers.get_viewer(NORTHWIND, ALEX)).role == "agent"
    assert (await viewers.get_viewer(NORTHWIND, MAYA)).role == "manager"
    assert await viewers.get_viewer(HARBOR, ALEX) is None
    assert await viewers.get_viewer(NORTHWIND, "nobody") is None


async def test_identities_resolve_organization_and_permissions(backend):
    identities = backend.providers.identities
    alex = await identities.resolve(ALEX)
    assert alex.organization_id == NORTHWIND
    assert alex.has(Permission.CONVERSATIONS_READ_OWN)
    assert not alex.has(Permission.FEEDBACK_REVIEW)
    maya = await identities.resolve(MAYA)
    assert maya.has(Permission.FEEDBACK_REVIEW)
    assert not maya.has(Permission.CONVERSATIONS_READ_OWN)
    assert (await identities.resolve(RILEY)).organization_id == HARBOR
    assert await identities.resolve(ALEX, HARBOR) is None
    assert await identities.resolve("nobody") is None


# --- database mapping ----------------------------------------------------------------


@pytest.fixture
async def data(session):
    return await seed(session)


@pytest.fixture
def providers(session):
    return create_database_providers(sessions_for(session))


async def test_stored_results_use_the_frontend_names(providers, data):
    call = await providers.calls.get_for_agent(NORTHWIND, ALEX, data.id(data.assessed))
    results = {criterion.id: criterion.result for criterion in call.criteria}
    assert results == {
        "procedure": "needs-review",
        "answer-support": "meets-criteria",
        "completeness": "cannot-assess",
        "communication-style": "meets-criteria",
    }
    [finding] = call.findings
    assert finding.id == data.id(data.procedure_finding)
    assert finding.criterion_id == "procedure"
    procedure = next(c for c in call.criteria if c.id == "procedure")
    assert procedure.finding_id == finding.id


async def test_evidence_keeps_original_turn_numbers_and_labels_system_actions(
    providers, data
):
    call = await providers.calls.get_for_agent(NORTHWIND, ALEX, data.id(data.assessed))
    assert [turn.number for turn in call.transcript.turns] == [1, 2, 4, 5, 7]
    assert [turn.speaker for turn in call.transcript.turns] == [
        "Customer",
        "Agent",
        "Customer",
        "System action",
        "Agent",
    ]
    # Recorded action 5 is included and distinguished from an Agent claim.
    assert call.findings[0].evidence_turn_numbers == [2, 5, 7]


async def test_reference_is_the_version_the_call_was_assessed_against(providers, data):
    call = await providers.calls.get_for_agent(NORTHWIND, ALEX, data.id(data.assessed))
    [reference] = call.references
    assert reference.id == data.id(data.stale_entry)
    assert reference.status == "stale"
    assert reference.version == f"review-{data.stale_entry.approved_review_id}"
    assert reference.available_to_agent_ids == [ALEX]
    assert call.findings[0].reference_id == reference.id


async def test_list_statuses_follow_audits_flags_and_reviews(providers, data):
    conversations = {
        conversation.id: conversation
        for conversation in await providers.conversations.list_for_agent(
            NORTHWIND, ALEX
        )
    }
    assert set(conversations) == {
        data.id(data.assessed),
        data.id(data.processing),
        data.id(data.undated),
        data.id(data.reviewed),
    }
    processing = conversations[data.id(data.processing)]
    assert (processing.automated_result, processing.review_status) == (
        "unavailable",
        None,
    )
    assessed = conversations[data.id(data.assessed)]
    assert (assessed.automated_result, assessed.review_status) == (
        "needs-review",
        "feedback-ready",
    )
    reviewed = conversations[data.id(data.reviewed)]
    assert reviewed.review_status == "review-complete"
    undated = conversations[data.id(data.undated)]
    assert (undated.date, undated.topic, undated.automated_result) == (
        None,
        "Unassigned",
        "meets-criteria",
    )


async def test_undated_conversations_are_listed_last(providers, data):
    conversations = await providers.conversations.list_for_agent(NORTHWIND, ALEX)
    assert [conversation.id for conversation in conversations] == [
        data.id(data.processing),
        data.id(data.reviewed),
        data.id(data.assessed),
        data.id(data.undated),
    ]


async def test_processing_call_has_no_assessment(providers, data):
    call = await providers.calls.get_for_agent(
        NORTHWIND, ALEX, data.id(data.processing)
    )
    assert call.status == "unavailable"
    assert (call.criteria, call.findings, call.decision) == ([], [], None)


async def test_manager_decision_sits_beside_the_automated_result(providers, data):
    call = await providers.calls.get_for_agent(NORTHWIND, ALEX, data.id(data.reviewed))
    assert call.decision.outcome == "cannot-assess"
    assert call.decision.manager_name == "Maya Chen"
    assert call.decision.decided_at == "2026-10-13T15:20:00Z"
    procedure = next(c for c in call.criteria if c.id == "procedure")
    assert procedure.result == "needs-review"


async def test_knowledge_maps_approval_details_and_leaves_unknowns_empty(
    providers, data
):
    [entry] = await providers.knowledge.list_for_agent(NORTHWIND, ALEX)
    assert entry.id == data.id(data.approved_entry)
    assert entry.paragraphs == [
        "Refunds go to the original card.",
        "They take 5 to 7 business days.",
    ]
    assert (entry.approved_at, entry.approved_by) == ("2026-09-01", "Maya Chen")
    assert entry.last_confirmed_at == "2026-10-01"
    assert (entry.effective_at, entry.owner, entry.source) == (None, None, None)


async def test_agent_without_a_linked_record_has_no_calls(providers, data):
    assert await providers.conversations.list_for_agent(NORTHWIND, UNLINKED) == []


async def test_a_user_in_two_organizations_must_choose_one(providers, data, session):
    user = await session.scalar(select(User).where(User.external_id == SAM))
    session.add(
        OrganizationMembership(
            organization_id=data.harbor.id, user=user, role=UserRole.MANAGER
        )
    )
    await session.commit()
    assert await providers.identities.resolve(SAM) is None
    assert (await providers.identities.resolve(SAM, HARBOR)).has(
        Permission.FEEDBACK_REVIEW
    )
    assert (await providers.identities.resolve(SAM, NORTHWIND)).has(
        Permission.CONVERSATIONS_READ_OWN
    )


# --- the API on the database ------------------------------------------------------


def client_for(providers):
    app = create_app(providers=providers, settings=Settings(app_env="test"))
    return httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    )


async def test_read_apis_work_with_stored_records(providers, data):
    async with client_for(providers) as client:
        headers = {"X-Dev-User": ALEX}
        listed = await client.get("/api/agent/conversations", headers=headers)
        assert listed.status_code == 200
        assert len(listed.json()) == 4
        detail = await client.get(
            f"/api/agent/conversations/{data.id(data.assessed)}", headers=headers
        )
        assert detail.status_code == 200
        assert detail.json()["references"][0]["availableToAgentIds"] == [ALEX]
        knowledge = await client.get("/api/agent/knowledge", headers=headers)
        assert [entry["id"] for entry in knowledge.json()] == [
            data.id(data.approved_entry)
        ]
        viewer = await client.get("/api/viewer", headers=headers)
        assert viewer.json() == {
            "id": ALEX,
            "displayName": "Alex Morgan",
            "role": "agent",
        }


async def test_other_agents_calls_are_not_found(providers, data):
    async with client_for(providers) as client:
        for conversation in (data.sam_call, data.harbor_call):
            response = await client.get(
                f"/api/agent/conversations/{data.id(conversation)}",
                headers={"X-Dev-User": ALEX},
            )
            assert response.status_code == 404


async def test_permissions_come_from_the_stored_membership(providers, data):
    async with client_for(providers) as client:
        manager = await client.get(
            "/api/agent/conversations", headers={"X-Dev-User": MAYA}
        )
        assert manager.status_code == 403
        unknown = await client.get(
            "/api/agent/conversations", headers={"X-Dev-User": "agent-nobody"}
        )
        assert unknown.status_code == 401


async def test_database_failure_is_503_not_empty():
    class Broken:
        async def __aenter__(self):
            raise OperationalError("SELECT 1", {}, ConnectionError("refused"))

        async def __aexit__(self, *exc):
            return False

    # Identities still resolve, so the 503 comes from the conversation provider.
    providers = replace(
        create_database_providers(lambda: Broken()),
        identities=FixtureIdentityProvider(),
    )
    async with client_for(providers) as client:
        response = await client.get(
            "/api/agent/conversations", headers={"X-Dev-User": ALEX}
        )
    assert response.status_code == 503
    assert response.json() == {"detail": "Data source unavailable"}


async def test_an_identity_lookup_failure_is_503_not_401():
    class Broken:
        async def __aenter__(self):
            raise OperationalError("SELECT 1", {}, ConnectionError("refused"))

        async def __aexit__(self, *exc):
            return False

    async with client_for(create_database_providers(lambda: Broken())) as client:
        response = await client.get("/api/viewer", headers={"X-Dev-User": ALEX})
    assert response.status_code == 503


@pytest.mark.parametrize("conversation_id", ["2147483648", "99999999999", "0"])
async def test_ids_outside_the_key_range_are_not_found(
    providers, data, conversation_id
):
    async with client_for(providers) as client:
        response = await client.get(
            f"/api/agent/conversations/{conversation_id}",
            headers={"X-Dev-User": ALEX},
        )
    assert response.status_code == 404


def test_settings_choose_the_data_source(monkeypatch):
    monkeypatch.setenv("MEMORIA_DATA_SOURCE", "database")
    assert Settings().data_source == "database"
    monkeypatch.delenv("MEMORIA_DATA_SOURCE")
    assert Settings().data_source == "fixtures"


async def test_original_abcd_id_is_visible_even_without_an_assessment(
    providers, data, session
):
    data.processing.source_dataset = "ABCD"
    data.processing.original_id = "source-example"
    session.add(data.processing)
    await session.commit()
    call = await providers.calls.get_for_agent(
        NORTHWIND, ALEX, data.id(data.processing)
    )
    assert call.source_id == "source-example"
    assert call.status == "unavailable"
    assert call.criteria == []
    rows = await providers.conversations.list_for_agent(NORTHWIND, ALEX)
    row = next(row for row in rows if row.id == call.id)
    assert row.source_id == call.source_id
    assert row.review_status is None
    assert row.overall_scoring is None
