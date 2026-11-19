"""The reporting periods an agent's progress is split into."""

from dataclasses import dataclass
from datetime import date, timedelta
from enum import StrEnum


class ProgressPeriod(StrEnum):
    DAY = "day"
    WEEK = "week"
    MONTH = "month"


# Enough for a year of days; anything longer is a mistake in the request.
MAX_PERIODS = 366


@dataclass(frozen=True)
class DateRange:
    """Calendar dates, both inclusive."""

    first: date
    last: date

    def __post_init__(self) -> None:
        if self.last < self.first:
            raise ValueError("the end date must not be before the start date")


@dataclass(frozen=True)
class Period:
    # Start of the calendar day, Monday-based week or month, as PostgreSQL's
    # date_trunc gives it. Query results are matched to periods on this.
    bucket: date
    # The part of the period inside the requested range. The first and last
    # periods can be partial; they only count calls inside the range.
    first: date
    last: date


def bucket_start(day: date, period: ProgressPeriod) -> date:
    if period == ProgressPeriod.DAY:
        return day
    if period == ProgressPeriod.WEEK:
        return day - timedelta(days=day.weekday())
    return day.replace(day=1)


def next_bucket(start: date, period: ProgressPeriod) -> date:
    if period == ProgressPeriod.DAY:
        return start + timedelta(days=1)
    if period == ProgressPeriod.WEEK:
        return start + timedelta(days=7)
    # Day 28 exists in every month, and four days later is always next month.
    return (start.replace(day=28) + timedelta(days=4)).replace(day=1)


def periods_in(dates: DateRange, period: ProgressPeriod) -> list[Period]:
    """Every period that overlaps the range, in order, including empty ones."""
    periods = []
    start = bucket_start(dates.first, period)
    while start <= dates.last:
        end = next_bucket(start, period)
        periods.append(
            Period(
                bucket=start,
                first=max(start, dates.first),
                last=min(end - timedelta(days=1), dates.last),
            )
        )
        if len(periods) > MAX_PERIODS:
            raise ValueError(f"the range covers more than {MAX_PERIODS} periods")
        start = end
    return periods
