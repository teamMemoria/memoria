from datetime import date

import pytest

from backend.entities.progress import (
    MAX_PERIODS,
    DateRange,
    Period,
    ProgressPeriod,
    periods_in,
)


def test_weeks_start_on_monday_and_partial_weeks_are_clipped():
    # Wednesday 7 October to Tuesday 20 October 2026.
    periods = periods_in(DateRange(date(2026, 10, 7), date(2026, 10, 20)), "week")
    assert periods == [
        Period(date(2026, 10, 5), date(2026, 10, 7), date(2026, 10, 11)),
        Period(date(2026, 10, 12), date(2026, 10, 12), date(2026, 10, 18)),
        Period(date(2026, 10, 19), date(2026, 10, 19), date(2026, 10, 20)),
    ]


def test_months_roll_over_the_year():
    periods = periods_in(
        DateRange(date(2026, 11, 15), date(2027, 2, 3)), ProgressPeriod.MONTH
    )
    assert [(p.bucket, p.first, p.last) for p in periods] == [
        (date(2026, 11, 1), date(2026, 11, 15), date(2026, 11, 30)),
        (date(2026, 12, 1), date(2026, 12, 1), date(2026, 12, 31)),
        (date(2027, 1, 1), date(2027, 1, 1), date(2027, 1, 31)),
        (date(2027, 2, 1), date(2027, 2, 1), date(2027, 2, 3)),
    ]


def test_one_day_is_one_period():
    day = date(2026, 10, 7)
    assert periods_in(DateRange(day, day), ProgressPeriod.DAY) == [
        Period(day, day, day)
    ]
    assert periods_in(DateRange(day, day), ProgressPeriod.WEEK) == [
        Period(date(2026, 10, 5), day, day)
    ]


def test_the_end_cannot_be_before_the_start():
    with pytest.raises(ValueError, match="end date"):
        DateRange(date(2026, 10, 8), date(2026, 10, 7))


def test_too_many_periods_are_refused():
    first = date(2026, 1, 1)
    year = DateRange(first, date(2026, 12, 31))
    assert len(periods_in(year, ProgressPeriod.DAY)) == 365
    with pytest.raises(ValueError, match=str(MAX_PERIODS)):
        periods_in(DateRange(first, date(2027, 12, 31)), ProgressPeriod.DAY)
