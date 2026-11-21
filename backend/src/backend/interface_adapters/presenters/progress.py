"""Turn counted results into the agent progress response."""

from collections.abc import Mapping
from datetime import date

from backend.entities.progress import DateRange, Period, ProgressPeriod
from backend.entities.results import (
    CRITERION_FOR_CATEGORY,
    CRITERION_TITLES,
    FindingCategory,
)
from backend.interface_adapters.presenters.assessments import AgentIdentity
from backend.schemas.progress import (
    AgentProgress,
    CriterionProgress,
    ProgressPoint,
    ResultCounts,
)

# (pass, needs work, cannot assess) finding counts.
Counts = tuple[int, int, int]
NO_FINDINGS: Counts = (0, 0, 0)


def result_counts(counts: Counts) -> ResultCounts:
    passes, needs_work, cannot_assess = counts
    return ResultCounts(
        meets_criteria=passes, needs_review=needs_work, cannot_assess=cannot_assess
    )


def progress_point(
    period: Period, by_category: Mapping[FindingCategory, Counts], call_count: int
) -> ProgressPoint:
    counts = [by_category.get(category, NO_FINDINGS) for category in FindingCategory]
    overall = (
        sum(item[0] for item in counts),
        sum(item[1] for item in counts),
        sum(item[2] for item in counts),
    )
    return ProgressPoint(
        start=period.first,
        end=period.last,
        call_count=call_count,
        # Only pass and needs-work findings are scored; cannot-assess is not a failure.
        has_results=overall[0] + overall[1] > 0,
        overall=result_counts(overall),
        criteria=[
            CriterionProgress(
                id=CRITERION_FOR_CATEGORY[category],
                title=CRITERION_TITLES[CRITERION_FOR_CATEGORY[category]],
                counts=result_counts(category_counts),
            )
            for category, category_counts in zip(FindingCategory, counts, strict=True)
        ],
    )


def present_progress(
    agent: AgentIdentity,
    dates: DateRange,
    period: ProgressPeriod,
    periods: list[Period],
    findings: Mapping[date, Mapping[FindingCategory, Counts]],
    calls: Mapping[date, int],
) -> AgentProgress:
    """One point per period, in order. Periods with nothing stored still appear."""
    return AgentProgress(
        agent_id=agent.id,
        agent_name=agent.name,
        period=period.value,
        from_=dates.first,
        to=dates.last,
        points=[
            progress_point(
                item, findings.get(item.bucket, {}), calls.get(item.bucket, 0)
            )
            for item in periods
        ],
    )
