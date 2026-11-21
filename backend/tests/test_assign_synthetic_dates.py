from datetime import date, time, timedelta

import pytest
from sqlalchemy import select, text

from backend.data.assign_synthetic_dates import (
    DEFAULT_START,
    assign_synthetic_dates,
    synthetic_times,
)
from backend.models import Agent, Conversation, Organization

START = DEFAULT_START
WEEKS = 8


def test_times_are_increasing_distinct_business_hours_in_window():
    times = synthetic_times("agent-a", 100, START, WEEKS, seed=1)

    assert times == sorted(times)
    assert len(set(times)) == 100
    for t in times:
        assert START <= t.date() < START + timedelta(weeks=WEEKS)
        assert t.weekday() < 5
        assert time(9) <= t.time() < time(17)


def test_same_seed_gives_same_times_and_different_seed_does_not():
    assert synthetic_times("a", 10, START, WEEKS, 1) == synthetic_times(
        "a", 10, START, WEEKS, 1
    )
    assert synthetic_times("a", 10, START, WEEKS, 1) != synthetic_times(
        "a", 10, START, WEEKS, 2
    )


def test_each_agent_is_seeded_independently():
    # Agents get different times from the same seed, and one agent's times
    # don't depend on how many conversations another agent has.
    assert synthetic_times("a", 5, START, WEEKS, 1) != synthetic_times(
        "b", 5, START, WEEKS, 1
    )
    synthetic_times("b", 50, START, WEEKS, 1)
    assert synthetic_times("a", 5, START, WEEKS, 1) == synthetic_times(
        "a", 5, START, WEEKS, 1
    )


def test_too_many_conversations_for_window_is_an_error():
    with pytest.raises(ValueError):
        synthetic_times("a", 10, date(2026, 1, 10), weeks=0, seed=1)


@pytest.fixture
async def organization(session):
    org = Organization(slug="synthetic-date-tests", name="Synthetic Date Tests")
    session.add(org)
    await session.flush()
    return org


@pytest.fixture
async def conversations(session, organization):
    agents = [
        Agent(organization=organization, external_id="hvb-speaker-1"),
        Agent(organization=organization, external_id="abcd-unknown-agent"),
    ]
    rows = []
    for i in range(12):
        rows.append(
            Conversation(
                organization=organization,
                source_dataset="HarperValleyBank" if i % 2 else "ABCD",
                original_id=str(i),
                # Inserted out of curated order on purpose.
                curated_id=f"C-{11 - i:04d}",
                channel="voice",
                agent=agents[i % 2],
                conversation_date=date(2020, 1, 1) if i == 0 else None,
            )
        )
    session.add_all(rows)
    await session.flush()
    return rows


async def started_times(session, organization_id):
    rows = await session.execute(
        select(
            Agent.external_id,
            Conversation.curated_id,
            Conversation.synthetic_started_at,
        )
        .join(Agent)
        .where(Conversation.organization_id == organization_id)
        .order_by(Agent.external_id, Conversation.curated_id)
    )
    return rows.all()


async def test_every_conversation_gets_a_date_in_agent_order(
    session, organization, conversations
):
    await assign_synthetic_dates(session, organization.id, START, WEEKS, seed=1)

    rows = await started_times(session, organization.id)
    assert all(t is not None for _, _, t in rows)
    for agent in ("hvb-speaker-1", "abcd-unknown-agent"):
        times = [t for a, _, t in rows if a == agent]
        assert len(times) == 6
        assert times == sorted(times) and len(set(times)) == 6


async def test_source_dates_are_left_alone(session, organization, conversations):
    await assign_synthetic_dates(session, organization.id, START, WEEKS, seed=1)
    await session.refresh(conversations[0])
    assert conversations[0].conversation_date == date(2020, 1, 1)
    assert conversations[1].conversation_date is None


async def test_rerun_with_same_seed_is_identical(session, organization, conversations):
    await assign_synthetic_dates(session, organization.id, START, WEEKS, seed=1)
    first = await started_times(session, organization.id)
    await assign_synthetic_dates(session, organization.id, START, WEEKS, seed=1)
    assert await started_times(session, organization.id) == first


async def test_only_selected_organization_gets_dates(
    session, organization, conversations
):
    other = Organization(slug="other-org", name="Other Organization")
    other_conversation = Conversation(
        organization=other,
        source_dataset="ABCD",
        original_id="other-call",
        curated_id="OTHER-0001",
        channel="chat",
        agent=Agent(organization=other, external_id="other-agent"),
    )
    session.add(other_conversation)
    await session.flush()

    await assign_synthetic_dates(session, organization.id, START, WEEKS, seed=1)

    await session.refresh(other_conversation)
    assert other_conversation.synthetic_started_at is None


async def test_column_is_marked_as_generated(session):
    comment = await session.scalar(
        text(
            "SELECT col_description(attrelid, attnum) FROM pg_attribute "
            "WHERE attrelid = 'conversations'::regclass "
            "AND attname = 'synthetic_started_at'"
        )
    )
    assert comment.startswith("Generated")
