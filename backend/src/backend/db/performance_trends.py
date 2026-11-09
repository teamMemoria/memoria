from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from sqlalchemy import Select, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.models.audit import Audit, Finding, FindingCategory, FindingResult
from backend.models.conversation import Conversation, Topic


class TrendPeriod(StrEnum):
    DAY = "day"
    WEEK = "week"
    MONTH = "month"


@dataclass(frozen=True)
class DateWindow:
    start: datetime
    end: datetime

    def __post_init__(self) -> None:
        if self.start >= self.end:
            raise ValueError("date window start must be before end")


@dataclass(frozen=True)
class ResultCounts:
    passes: int
    needs_work: int
    cannot_assess: int

    @property
    def assessed(self) -> int:
        return self.passes + self.needs_work

    @property
    def pass_rate(self) -> float | None:
        if self.assessed == 0:
            return None
        return self.passes / self.assessed


@dataclass(frozen=True)
class TrendPoint:
    period_start: datetime
    category: FindingCategory
    topic_id: int | None
    topic_name: str | None
    counts: ResultCounts


@dataclass(frozen=True)
class WindowComparison:
    category: FindingCategory
    topic_id: int | None
    topic_name: str | None
    earlier: ResultCounts
    later: ResultCounts

    @property
    def pass_rate_change(self) -> float | None:
        if self.earlier.pass_rate is None or self.later.pass_rate is None:
            return None
        return self.later.pass_rate - self.earlier.pass_rate


def _count_result(result: FindingResult):
    return func.count().filter(Finding.result == result)


def _base_query(agent_id: int, window: DateWindow) -> Select:
    return (
        select()
        .select_from(Conversation)
        .join(Audit, Audit.conversation_id == Conversation.id)
        .join(Finding, Finding.audit_id == Audit.id)
        .outerjoin(Topic, Topic.id == Conversation.topic_id)
        .where(
            Conversation.agent_id == agent_id,
            Conversation.synthetic_started_at >= window.start,
            Conversation.synthetic_started_at < window.end,
        )
    )


def _counts_from_row(row) -> ResultCounts:
    return ResultCounts(
        passes=row.passes,
        needs_work=row.needs_work,
        cannot_assess=row.cannot_assess,
    )


async def get_agent_performance_trends(
    session: AsyncSession,
    *,
    agent_id: int,
    window: DateWindow,
    period: TrendPeriod = TrendPeriod.WEEK,
) -> list[TrendPoint]:
    """Return an agent's finding counts grouped chronologically by period and topic."""
    period_start = func.date_trunc(
        period.value, Conversation.synthetic_started_at
    ).label("period_start")
    statement = (
        _base_query(agent_id, window)
        .add_columns(
            period_start,
            Finding.category,
            Conversation.topic_id,
            Topic.name.label("topic_name"),
            _count_result(FindingResult.PASS).label("passes"),
            _count_result(FindingResult.NEEDS_WORK).label("needs_work"),
            _count_result(FindingResult.CANNOT_ASSESS).label("cannot_assess"),
        )
        .group_by(period_start, Finding.category, Conversation.topic_id, Topic.name)
        .order_by(
            period_start,
            Finding.category,
            Conversation.topic_id.nulls_last(),
        )
    )
    rows = (await session.execute(statement)).all()
    return [
        TrendPoint(
            period_start=row.period_start,
            category=row.category,
            topic_id=row.topic_id,
            topic_name=row.topic_name,
            counts=_counts_from_row(row),
        )
        for row in rows
    ]


async def _window_counts(
    session: AsyncSession, *, agent_id: int, window: DateWindow
) -> dict[tuple[FindingCategory, int | None, str | None], ResultCounts]:
    statement = (
        _base_query(agent_id, window)
        .add_columns(
            Finding.category,
            Conversation.topic_id,
            Topic.name.label("topic_name"),
            _count_result(FindingResult.PASS).label("passes"),
            _count_result(FindingResult.NEEDS_WORK).label("needs_work"),
            _count_result(FindingResult.CANNOT_ASSESS).label("cannot_assess"),
        )
        .group_by(Finding.category, Conversation.topic_id, Topic.name)
    )
    rows = (await session.execute(statement)).all()
    return {
        (row.category, row.topic_id, row.topic_name): _counts_from_row(row)
        for row in rows
    }


async def compare_agent_performance_windows(
    session: AsyncSession,
    *,
    agent_id: int,
    earlier: DateWindow,
    later: DateWindow,
) -> list[WindowComparison]:
    """Compare result counts for two configurable half-open date windows."""
    earlier_counts = await _window_counts(session, agent_id=agent_id, window=earlier)
    later_counts = await _window_counts(session, agent_id=agent_id, window=later)
    keys = sorted(
        earlier_counts.keys() | later_counts.keys(),
        key=lambda item: (item[0].value, item[2] or "", item[1] or -1),
    )
    empty = ResultCounts(passes=0, needs_work=0, cannot_assess=0)
    return [
        WindowComparison(
            category=category,
            topic_id=topic_id,
            topic_name=topic_name,
            earlier=earlier_counts.get(key, empty),
            later=later_counts.get(key, empty),
        )
        for key in keys
        for category, topic_id, topic_name in [key]
    ]
