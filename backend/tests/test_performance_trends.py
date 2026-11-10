from datetime import UTC, datetime

import pytest
from sqlalchemy import inspect

from backend.db.performance_trends import (
    DateWindow,
    TrendPeriod,
    compare_agent_performance_windows,
    get_agent_performance_trends,
)
from backend.models.audit import Audit, Finding, FindingCategory, FindingResult
from backend.models.conversation import Agent, Conversation, Topic


def utc(year: int, month: int, day: int) -> datetime:
    return datetime(year, month, day, tzinfo=UTC)


async def add_audited_conversation(
    session,
    *,
    agent: Agent,
    topic: Topic | None,
    original_id: str,
    started_at: datetime,
    results: dict[FindingCategory, FindingResult],
    evaluation_version,
) -> None:
    conversation = Conversation(
        source_dataset="test",
        original_id=original_id,
        channel="voice",
        conversation_date=None,
        synthetic_started_at=started_at,
        agent=agent,
        topic=topic,
        curated_id=None,
        source_fields={},
        customer_record=None,
    )
    audit = Audit(conversation=conversation, evaluation_form_version=evaluation_version)
    audit.findings = [
        Finding(category=category, result=result, feedback="test")
        for category, result in results.items()
    ]
    session.add(audit)
    await session.flush()


@pytest.mark.asyncio
async def test_trends_group_results_by_week_category_and_topic_in_order(
    session, default_evaluation_version
):
    agent = Agent(external_id="agent-37", name="Agent 37")
    other_agent = Agent(external_id="agent-other", name="Other")
    billing = Topic(source_dataset="test", name="Billing", description=None)
    account = Topic(source_dataset="test", name="Account", description=None)

    await add_audited_conversation(
        session,
        agent=agent,
        topic=billing,
        original_id="week-1-a",
        started_at=utc(2026, 1, 6),
        results={
            FindingCategory.PROCEDURE: FindingResult.NEEDS_WORK,
            FindingCategory.COMPLETENESS: FindingResult.CANNOT_ASSESS,
        },
        evaluation_version=default_evaluation_version,
    )
    await add_audited_conversation(
        session,
        agent=agent,
        topic=billing,
        original_id="week-1-b",
        started_at=utc(2026, 1, 8),
        results={FindingCategory.PROCEDURE: FindingResult.PASS},
        evaluation_version=default_evaluation_version,
    )
    await add_audited_conversation(
        session,
        agent=agent,
        topic=account,
        original_id="week-2",
        started_at=utc(2026, 1, 13),
        results={FindingCategory.PROCEDURE: FindingResult.PASS},
        evaluation_version=default_evaluation_version,
    )
    await add_audited_conversation(
        session,
        agent=other_agent,
        topic=billing,
        original_id="other-agent",
        started_at=utc(2026, 1, 7),
        results={FindingCategory.PROCEDURE: FindingResult.NEEDS_WORK},
        evaluation_version=default_evaluation_version,
    )

    trends = await get_agent_performance_trends(
        session,
        agent_id=agent.id,
        window=DateWindow(utc(2026, 1, 1), utc(2026, 2, 1)),
        period=TrendPeriod.WEEK,
    )

    assert [point.period_start for point in trends] == [
        utc(2026, 1, 5),
        utc(2026, 1, 5),
        utc(2026, 1, 12),
    ]
    completeness, first_week, second_week = trends
    assert completeness.category is FindingCategory.COMPLETENESS
    assert completeness.counts.cannot_assess == 1
    assert completeness.counts.assessed == 0
    assert completeness.counts.pass_rate is None
    assert first_week.topic_name == "Billing"
    assert first_week.counts.passes == 1
    assert first_week.counts.needs_work == 1
    assert first_week.counts.pass_rate == 0.5
    assert second_week.topic_name == "Account"
    assert second_week.counts.passes == 1


@pytest.mark.asyncio
async def test_comparison_uses_half_open_windows_and_excludes_cannot_assess(
    session, default_evaluation_version
):
    agent = Agent(external_id="compare-agent", name=None)
    topic = Topic(source_dataset="test", name="Support", description=None)
    for original_id, started_at, result in [
        ("early-pass", utc(2026, 2, 1), FindingResult.PASS),
        ("early-na", utc(2026, 2, 8), FindingResult.CANNOT_ASSESS),
        ("late-pass", utc(2026, 2, 15), FindingResult.PASS),
        ("late-pass-2", utc(2026, 2, 22), FindingResult.PASS),
    ]:
        await add_audited_conversation(
            session,
            agent=agent,
            topic=topic,
            original_id=original_id,
            started_at=started_at,
            results={FindingCategory.ANSWER_SUPPORT: result},
            evaluation_version=default_evaluation_version,
        )

    comparison = await compare_agent_performance_windows(
        session,
        agent_id=agent.id,
        earlier=DateWindow(utc(2026, 2, 1), utc(2026, 2, 15)),
        later=DateWindow(utc(2026, 2, 15), utc(2026, 3, 1)),
    )

    assert len(comparison) == 1
    result = comparison[0]
    assert result.earlier.passes == 1
    assert result.earlier.cannot_assess == 1
    assert result.earlier.pass_rate == 1.0
    assert result.later.passes == 2
    assert result.later.cannot_assess == 0
    assert result.pass_rate_change == 0.0


def test_date_window_rejects_empty_or_reversed_ranges():
    with pytest.raises(ValueError, match="start must be before end"):
        DateWindow(utc(2026, 1, 2), utc(2026, 1, 2))


@pytest.mark.asyncio
async def test_performance_trend_index_exists(session):
    def index_names(sync_session):
        return {
            index["name"]
            for index in inspect(sync_session.connection()).get_indexes("conversations")
        }

    names = await session.run_sync(index_names)
    assert "ix_conversations_agent_started_topic" in names
