from datetime import date
from typing import Literal

from pydantic import Field

from backend.schemas.base import ApiModel
from backend.schemas.call_review import CriterionId


class ResultCounts(ApiModel):
    """How many findings had each result."""

    meets_criteria: int
    needs_review: int
    cannot_assess: int


class CriterionProgress(ApiModel):
    id: CriterionId
    title: str
    counts: ResultCounts


class ProgressPoint(ApiModel):
    """One day, week or month of an agent's results.

    ``start`` and ``end`` are inclusive and clipped to the requested range.
    ``has_results`` is false when nothing in the period could be scored (no
    calls, or only unassessed or cannot-assess findings). Such a period is a
    gap in the data, not a poor result.
    """

    start: date
    end: date
    call_count: int
    has_results: bool
    overall: ResultCounts
    criteria: list[CriterionProgress]


class AgentProgress(ApiModel):
    agent_id: str
    agent_name: str
    period: Literal["day", "week", "month"]
    from_: date = Field(alias="from")
    to: date
    points: list[ProgressPoint]
