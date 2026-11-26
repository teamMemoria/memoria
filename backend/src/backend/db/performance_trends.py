from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from sqlalchemy import Select, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.frameworks.database.models.audit import (
    Audit,
    Finding,
    FindingCategory,
    FindingResult,
)
from backend.frameworks.database.models.conversation import Conversation, Topic


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
