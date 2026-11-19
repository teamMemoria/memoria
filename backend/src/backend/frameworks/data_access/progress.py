"""An agent's results over time, for the agent themself or a Manager.

Counts come from ``backend.db.performance_trends`` and are grouped into UTC
calendar periods by the conversation's ``synthetic_started_at``. Conversations
without that time are left out. Agents only see the agent record linked to
their own membership; Managers see any agent in their own organization.
"""

from collections import defaultdict
from datetime import UTC, date, datetime, time, timedelta

from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from backend.db.performance_trends import (
    DateWindow,
    TrendPeriod,
    get_agent_performance_trends,
)
from backend.entities.identity import Permission
from backend.entities.progress import DateRange, ProgressPeriod, periods_in
from backend.frameworks.data_access.database import (
    AgentIdentity,
    SessionFactory,
    agent_identity,
    current_user_for,
    load_membership,
    unavailable_on_database_error,
)
from backend.frameworks.data_access.reviews import agent_identities
from backend.frameworks.database.models import Conversation, UserRole
from backend.interface_adapters.presenters.progress import present_progress
from backend.schemas.progress import AgentProgress


def utc_midnight(day: date) -> datetime:
    return datetime.combine(day, time.min, tzinfo=UTC)


def utc_day(value: datetime) -> date:
    return value.astimezone(UTC).date()


async def load_progress(
    session: AsyncSession,
    organization_id: int,
    agent_key: int | None,
    agent: AgentIdentity,
    dates: DateRange,
    period: ProgressPeriod,
) -> AgentProgress:
    periods = periods_in(dates, period)
    findings = defaultdict(dict)
    calls = {}
    # An agent membership without a linked agent record has no calls yet.
    if agent_key is not None:
        # date_trunc follows the session time zone; periods are UTC calendar periods.
        await session.execute(text("SET LOCAL TIME ZONE 'UTC'"))
        window = DateWindow(
            utc_midnight(dates.first), utc_midnight(dates.last + timedelta(days=1))
        )
        points = await get_agent_performance_trends(
            session, agent_id=agent_key, window=window, period=TrendPeriod(period)
        )
        # The query splits each period by topic; progress adds the topics together.
        for point in points:
            by_category = findings[utc_day(point.period_start)]
            passes, needs_work, cannot_assess = by_category.get(
                point.category, (0, 0, 0)
            )
            by_category[point.category] = (
                passes + point.counts.passes,
                needs_work + point.counts.needs_work,
                cannot_assess + point.counts.cannot_assess,
            )

        # Grouped by the label, so PostgreSQL sees one expression, not two copies
        # with separate parameters.
        bucket = func.date_trunc(period.value, Conversation.synthetic_started_at).label(
            "period_start"
        )
        rows = await session.execute(
            select(bucket, func.count())
            .where(
                Conversation.organization_id == organization_id,
                Conversation.agent_id == agent_key,
                Conversation.synthetic_started_at >= window.start,
                Conversation.synthetic_started_at < window.end,
            )
            .group_by(bucket)
        )
        calls = {utc_day(started): count for started, count in rows}
    return present_progress(agent, dates, period, periods, findings, calls)


class DatabaseProgressProvider:
    def __init__(self, sessions: SessionFactory):
        self._sessions = sessions

    @unavailable_on_database_error
    async def for_agent(self, organization_id, user_id, dates, period):
        async with self._sessions() as session:
            membership = await load_membership(session, organization_id, user_id)
            if membership is None or membership.role is not UserRole.AGENT:
                return None
            return await load_progress(
                session,
                membership.organization_id,
                membership.agent_id,
                agent_identity(membership),
                dates,
                period,
            )

    @unavailable_on_database_error
    async def for_manager(self, organization_id, manager_id, agent_id, dates, period):
        async with self._sessions() as session:
            membership = await load_membership(session, organization_id, manager_id)
            # Routes check the permission first; this keeps the provider safe on its own.
            if membership is None or not current_user_for(membership).has(
                Permission.FEEDBACK_REVIEW
            ):
                return None
            # agent_id is the agent ID the review queue shows: the linked
            # person's ID, else the agent record's source ID.
            agents = await agent_identities(session, membership.organization_id)
            match = next(
                (
                    (key, identity)
                    for key, identity in agents.items()
                    if identity.id == agent_id
                ),
                None,
            )
            if match is None:
                return None
            key, identity = match
            return await load_progress(
                session, membership.organization_id, key, identity, dates, period
            )
