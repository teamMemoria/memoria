import pytest
from sqlalchemy.exc import IntegrityError

from backend.core.auth import Permission, permissions_for_membership
from backend.models import Agent, Organization, OrganizationMembership, User, UserRole


def member(org, external_id, role, agent=None):
    membership = OrganizationMembership(
        organization=org,
        user=User(external_id=external_id, display_name=external_id),
        role=role,
    )
    if agent is not None:
        membership.agent = agent
    return membership


async def test_an_agent_membership_links_to_one_agent_record(session):
    org = Organization(slug="northwind", name="Northwind")
    agent = Agent(organization=org, external_id="speaker-1")
    membership = member(org, "agent-alex", UserRole.AGENT, agent)
    session.add(membership)
    await session.flush()
    assert membership.agent_id == agent.id


async def test_two_people_cannot_share_an_agent_record(session):
    org = Organization(slug="northwind", name="Northwind")
    agent = Agent(organization=org, external_id="speaker-1")
    session.add_all(
        [
            member(org, "agent-alex", UserRole.AGENT, agent),
            member(org, "agent-sam", UserRole.AGENT, agent),
        ]
    )
    with pytest.raises(IntegrityError):
        await session.flush()


async def test_only_agent_memberships_can_own_calls(session):
    org = Organization(slug="northwind", name="Northwind")
    agent = Agent(organization=org, external_id="speaker-1")
    session.add(member(org, "manager-maya", UserRole.MANAGER, agent))
    with pytest.raises(IntegrityError):
        await session.flush()


async def test_an_agent_record_from_another_organization_cannot_be_linked(session):
    northwind = Organization(slug="northwind", name="Northwind")
    harbor = Organization(slug="harbor", name="Harbor")
    session.add_all([northwind, harbor])
    harbor_agent = Agent(organization=harbor, external_id="speaker-1")
    session.add(harbor_agent)
    await session.flush()
    membership = member(northwind, "agent-alex", UserRole.AGENT)
    membership.agent_id = harbor_agent.id
    session.add(membership)
    with pytest.raises(IntegrityError):
        await session.flush()


def test_membership_capabilities_map_to_separate_permissions():
    agent = permissions_for_membership(
        is_agent=True, can_review_feedback=False, can_approve_knowledge=False
    )
    assert agent == {Permission.CONVERSATIONS_READ_OWN, Permission.KNOWLEDGE_READ}
    reviewer = permissions_for_membership(
        is_agent=False, can_review_feedback=True, can_approve_knowledge=False
    )
    assert reviewer == {Permission.FEEDBACK_REVIEW, Permission.KNOWLEDGE_READ}
    approver = permissions_for_membership(
        is_agent=False, can_review_feedback=False, can_approve_knowledge=True
    )
    assert approver == {Permission.KNOWLEDGE_APPROVE, Permission.KNOWLEDGE_READ}
