"""Create the demo profiles offered on the entry screen.

Usage (from backend/, after import-conversations):

    uv run seed-demo-profiles [--organization default]

Reads backend/data/demo_profiles.toml. For each Agent profile it creates an
agent record, links the imported ABCD conversations listed for it, and adds a
user with an agent membership. It also adds one demo Manager.

Safe to re-run: profiles are matched on their permanent IDs and updated in
place. Only conversations listed for a profile are linked, and only if they
are still unassigned; nothing is imported, assessed, reviewed or approved.
"""

import argparse
import asyncio
import sys
from dataclasses import dataclass

from sqlalchemy import func, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from backend.data.demo_profiles import DemoProfiles, load_profiles, profile_display_name
from backend.data.import_conversations import placeholder_agent_id
from backend.db.session import async_session_factory
from backend.models import (
    Agent,
    Conversation,
    Organization,
    OrganizationMembership,
    User,
    UserRole,
)


@dataclass(frozen=True)
class SeedResult:
    agents: int
    managers: int
    linked_conversations: int
    # Listed for a profile but not imported yet; they are linked on a later run.
    missing_conversations: int


async def upsert_user(session: AsyncSession, external_id: str, name: str) -> int:
    stmt = insert(User).values(external_id=external_id, display_name=name)
    stmt = stmt.on_conflict_do_update(
        index_elements=[User.external_id],
        set_={"display_name": stmt.excluded.display_name},
    ).returning(User.id)
    return await session.scalar(stmt)


async def upsert_membership(
    session: AsyncSession,
    organization_id: int,
    user_id: int,
    role: UserRole,
    agent_id: int | None = None,
) -> None:
    stmt = insert(OrganizationMembership).values(
        organization_id=organization_id, user_id=user_id, role=role, agent_id=agent_id
    )
    await session.execute(
        stmt.on_conflict_do_update(
            index_elements=[
                OrganizationMembership.organization_id,
                OrganizationMembership.user_id,
            ],
            set_={"role": stmt.excluded.role, "agent_id": stmt.excluded.agent_id},
        )
    )


async def upsert_named_agent(
    session: AsyncSession, organization_id: int, external_id: str, name: str
) -> int:
    stmt = insert(Agent).values(
        organization_id=organization_id, external_id=external_id, name=name
    )
    stmt = stmt.on_conflict_do_update(
        index_elements=[Agent.organization_id, Agent.external_id],
        set_={"name": stmt.excluded.name},
    ).returning(Agent.id)
    return await session.scalar(stmt)


async def seed_demo_profiles(
    session: AsyncSession, organization_id: int, profiles: DemoProfiles
) -> SeedResult:
    # Conversations without a known agent were imported under this placeholder.
    unassigned = await session.scalar(
        select(Agent.id).where(
            Agent.organization_id == organization_id,
            Agent.external_id == placeholder_agent_id(profiles.dataset),
        )
    )

    linked = 0
    for profile in profiles.agents:
        name = profile_display_name(profile.id, profile.name)
        agent_id = await upsert_named_agent(session, organization_id, profile.id, name)
        if unassigned is not None:
            await session.execute(
                update(Conversation)
                .where(
                    Conversation.organization_id == organization_id,
                    Conversation.source_dataset == profiles.dataset,
                    Conversation.original_id.in_(profile.conversations),
                    Conversation.agent_id == unassigned,
                )
                .values(agent_id=agent_id)
            )
        linked += await session.scalar(
            select(func.count())
            .select_from(Conversation)
            .where(
                Conversation.organization_id == organization_id,
                Conversation.agent_id == agent_id,
            )
        )
        user_id = await upsert_user(session, profile.id, name)
        await upsert_membership(
            session, organization_id, user_id, UserRole.AGENT, agent_id
        )

    manager_id = await upsert_user(
        session,
        profiles.manager_id,
        profile_display_name(profiles.manager_id, profiles.manager_name),
    )
    await upsert_membership(session, organization_id, manager_id, UserRole.MANAGER)

    listed = sum(len(profile.conversations) for profile in profiles.agents)
    return SeedResult(
        agents=len(profiles.agents),
        managers=1,
        linked_conversations=linked,
        missing_conversations=listed - linked,
    )


async def run(organization_slug: str) -> None:
    profiles = load_profiles()
    async with async_session_factory() as session, session.begin():
        organization_id = await session.scalar(
            select(Organization.id).where(Organization.slug == organization_slug)
        )
        if organization_id is None:
            sys.exit(f"Unknown organization: {organization_slug}")
        result = await seed_demo_profiles(session, organization_id, profiles)

    print(f"Demo profiles: {result.agents} agents, {result.managers} manager")
    print(f"Linked {result.linked_conversations} imported conversations")
    if result.missing_conversations:
        print(f"{result.missing_conversations} listed conversations are not imported")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--organization",
        default="default",
        help="organization slug to add the profiles to (default: default)",
    )
    args = parser.parse_args()
    asyncio.run(run(args.organization))


if __name__ == "__main__":
    main()
