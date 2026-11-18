from dataclasses import dataclass
from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status

from backend.entities.progress import DateRange, ProgressPeriod, periods_in
from backend.frameworks.http.conversations import AgentDep
from backend.frameworks.http.dependencies import ProvidersDep
from backend.frameworks.http.reviews import ReviewerDep
from backend.providers import ProgressProvider, Providers, ProviderUnavailableError
from backend.schemas.progress import AgentProgress

router = APIRouter()


@dataclass(frozen=True)
class ProgressQuery:
    dates: DateRange
    period: ProgressPeriod


def progress_query(
    start: Annotated[date, Query(alias="from")],
    end: Annotated[date, Query(alias="to")],
    period: ProgressPeriod = ProgressPeriod.WEEK,
) -> ProgressQuery:
    """``from`` and ``to`` are inclusive dates; ``period`` is day, week or month."""
    try:
        dates = DateRange(start, end)
        # Rejects ranges with too many periods before anything is queried.
        periods_in(dates, period)
    except ValueError as error:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(error)) from None
    return ProgressQuery(dates, period)


ProgressQueryDep = Annotated[ProgressQuery, Depends(progress_query)]


def progress_provider(providers: Providers) -> ProgressProvider:
    # Progress needs the database; the fixtures have no dated results.
    if providers.progress is None:
        raise ProviderUnavailableError("no progress provider configured")
    return providers.progress


@router.get("/api/agent/progress", response_model=AgentProgress)
async def own_progress(
    query: ProgressQueryDep, user: AgentDep, providers: ProvidersDep
) -> AgentProgress:
    """The requester's own results over time, one point per period.

    There is no agent ID to choose: an agent can only ever see their own.
    """
    progress = await progress_provider(providers).for_agent(
        user.organization_id, user.user_id, query.dates, query.period
    )
    if progress is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Agent not found")
    return progress


@router.get("/api/manager/agents/{agent_id}/progress", response_model=AgentProgress)
async def agent_progress(
    agent_id: str, query: ProgressQueryDep, user: ReviewerDep, providers: ProvidersDep
) -> AgentProgress:
    """Any agent's results over time, inside the Manager's own organization.

    ``agent_id`` is the ``agentId`` shown in the review queue. Unknown agents
    and other organizations' agents get the same 404.
    """
    progress = await progress_provider(providers).for_manager(
        user.organization_id, user.user_id, agent_id, query.dates, query.period
    )
    if progress is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Agent not found")
    return progress
