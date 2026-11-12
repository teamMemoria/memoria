import pytest
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from backend.data.import_conversations import (
    import_conversations,
    load_directory,
    placeholder_agent_id,
)
from backend.data.seed_demo_profiles import (
    DemoAgent,
    DemoProfiles,
    load_profiles,
    seed_demo_profiles,
)
from backend.models import (
    Agent,
    Conversation,
    Organization,
    OrganizationMembership,
    User,
    UserRole,
)
from backend.providers.database import create_database_providers
from tests.database_seed import sessions_for

PROFILES = DemoProfiles(
    dataset="ABCD",
    split="train",
    manager_id="demo-manager-01",
    manager_name="Manager",
    agents=(
        DemoAgent("demo-agent-01", "Alex", ("1891", "5496")),
        DemoAgent("demo-agent-02", "Amy", ("8215",)),
    ),
)


@pytest.fixture
async def organization(session):
    return await session.scalar(
        select(Organization).where(Organization.slug == "default")
    )


async def add_conversation(session, organization, agent, dataset, original_id):
    conversation = Conversation(
        organization_id=organization.id,
        source_dataset=dataset,
        original_id=original_id,
        channel="chat",
        agent_id=agent.id,
    )
    session.add(conversation)
    await session.flush()
    return conversation


@pytest.fixture
async def unassigned(session, organization):
    agent = Agent(
        organization_id=organization.id, external_id=placeholder_agent_id("ABCD")
    )
    session.add(agent)
    await session.flush()
    return agent


async def test_links_only_the_listed_conversations(session, organization, unassigned):
    listed = await add_conversation(session, organization, unassigned, "ABCD", "1891")
    unlisted = await add_conversation(session, organization, unassigned, "ABCD", "9999")
    other_dataset = await add_conversation(
        session, organization, unassigned, "HarperValleyBank", "5496"
    )

    result = await seed_demo_profiles(session, organization.id, PROFILES)

    alex = await session.scalar(
        select(Agent).where(Agent.external_id == "demo-agent-01")
    )
    assert alex.name == "Alex"
    assert listed.agent_id == alex.id
    assert unlisted.agent_id == unassigned.id
    assert other_dataset.agent_id == unassigned.id
    assert result.linked_conversations == 1
    assert result.missing_conversations == 2


async def test_creates_users_with_the_right_memberships(session, organization):
    await seed_demo_profiles(session, organization.id, PROFILES)

    memberships = {
        m.user.external_id: m
        for m in await session.scalars(
            select(OrganizationMembership)
            .join(User)
            .where(User.external_id.startswith("demo-"))
            .options(
                selectinload(OrganizationMembership.user),
                selectinload(OrganizationMembership.agent),
            )
        )
    }
    assert memberships["demo-agent-01"].role is UserRole.AGENT
    assert memberships["demo-agent-01"].agent.external_id == "demo-agent-01"
    assert memberships["demo-manager-01"].role is UserRole.MANAGER
    assert memberships["demo-manager-01"].agent_id is None


async def test_running_twice_changes_nothing(session, organization, unassigned):
    await add_conversation(session, organization, unassigned, "ABCD", "1891")
    first = await seed_demo_profiles(session, organization.id, PROFILES)
    second = await seed_demo_profiles(session, organization.id, PROFILES)

    assert first == second
    users = await session.scalars(
        select(User).where(User.external_id.startswith("demo-"))
    )
    assert len(list(users)) == 3


async def test_does_not_take_a_conversation_from_a_known_agent(session, organization):
    known = Agent(organization_id=organization.id, external_id="abcd-speaker-7")
    session.add(known)
    await session.flush()
    conversation = await add_conversation(session, organization, known, "ABCD", "1891")

    await seed_demo_profiles(session, organization.id, PROFILES)

    assert conversation.agent_id == known.id


async def test_profiles_and_their_conversations_are_listed(
    session, organization, unassigned
):
    await add_conversation(session, organization, unassigned, "ABCD", "1891")
    await add_conversation(session, organization, unassigned, "ABCD", "5496")
    await seed_demo_profiles(session, organization.id, PROFILES)
    providers = create_database_providers(sessions_for(session))

    profiles = {p.id: p for p in await providers.demo_profiles.list_profiles()}
    assert profiles["demo-agent-01"].conversation_count == 2
    assert profiles["demo-agent-02"].conversation_count == 0
    assert profiles["demo-manager-01"].role == "manager"
    assert profiles["demo-manager-01"].conversation_count is None

    alex = await providers.identities.resolve("demo-agent-01")
    listed = await providers.conversations.list_for_agent(
        alex.organization_id, alex.user_id
    )
    assert len(listed) == 2
    amy = await providers.identities.resolve("demo-agent-02")
    assert (
        await providers.conversations.list_for_agent(amy.organization_id, amy.user_id)
        == []
    )


async def test_import_assigns_listed_abcd_conversations_to_their_profile(
    session, organization, tmp_path
):
    (tmp_path / "ABCD-0001.json").write_text(
        '{"id": "ABCD-0001", "source": {"dataset": "ABCD", "original_id": "8434"},'
        ' "channel": "chat", "turns": [{"n": 1, "speaker": "agent", "text": "Hi"}],'
        ' "source_fields": {}}'
    )
    adam = next(a for a in load_profiles().agents if "8434" in a.conversations)

    await import_conversations(session, load_directory(tmp_path), organization.id)

    conversation = await session.scalar(
        select(Conversation).where(Conversation.original_id == "8434")
    )
    await session.refresh(conversation, ["agent"])
    assert conversation.agent.external_id == adam.id
