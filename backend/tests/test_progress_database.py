"""Agent progress read from PostgreSQL through the API.

Seeded calls get synthetic start times in October 2026: Alex has two assessed
calls in the week of 5 October, none the week after, and one call that is still
processing in the week of 19 October. Sam and Harbor's agent have calls in the
first week too, which must never be counted for Alex.
"""

from datetime import UTC, date, datetime

import httpx
import pytest
from sqlalchemy import update
from sqlalchemy.exc import OperationalError

from backend.core.config import Settings
from backend.entities.progress import DateRange, ProgressPeriod
from backend.frameworks.data_access.progress import DatabaseProgressProvider
from backend.main import create_app
from backend.models import Conversation
from backend.providers import ProviderUnavailableError
from backend.providers.database import create_database_providers
from tests.database_seed import (
    ALEX,
    HARBOR,
    MAYA,
    NORTHWIND,
    RILEY,
    SAM,
    UNLINKED,
    seed,
    sessions_for,
)

WEEKS = {"from": "2026-10-05", "to": "2026-10-25"}


def october(day: int) -> datetime:
    return datetime(2026, 10, day, 12, 0, tzinfo=UTC)


def counts(meets: int, needs: int, cannot: int) -> dict:
    return {"meetsCriteria": meets, "needsReview": needs, "cannotAssess": cannot}


NOTHING = counts(0, 0, 0)


@pytest.fixture
async def data(session):
    result = await seed(session)
    for conversation, started in [
        (result.assessed, october(6)),
        (result.reviewed, october(8)),
        (result.processing, october(20)),
        (result.sam_call, october(7)),
        (result.harbor_call, october(7)),
    ]:
        await session.execute(
            update(Conversation)
            .where(Conversation.id == conversation.id)
            .values(synthetic_started_at=started)
        )
    await session.commit()
    session.expunge_all()
    return result


def client_for(session):
    app = create_app(
        providers=create_database_providers(sessions_for(session)),
        settings=Settings(app_env="test"),
    )
    return httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    )


async def get(session, path, user, **params):
    async with client_for(session) as client:
        return await client.get(path, params=params, headers={"X-Dev-User": user})


async def test_an_agent_sees_their_own_weeks_including_empty_ones(session, data):
    response = await get(session, "/api/agent/progress", ALEX, **WEEKS)
    assert response.status_code == 200
    progress = response.json()
    assert progress["agentId"] == ALEX
    assert progress["agentName"] == "Alex Morgan"
    assert (progress["period"], progress["from"], progress["to"]) == (
        "week",
        "2026-10-05",
        "2026-10-25",
    )

    first, empty, processing = progress["points"]
    assert (first["start"], first["end"]) == ("2026-10-05", "2026-10-11")
    assert first["callCount"] == 2
    assert first["hasResults"] is True
    # Both calls: procedure needs work twice; the first call's completeness
    # could not be assessed; everything else passed.
    assert first["overall"] == counts(5, 2, 1)
    assert [(c["id"], c["counts"]) for c in first["criteria"]] == [
        ("procedure", counts(0, 2, 0)),
        ("answer-support", counts(2, 0, 0)),
        ("completeness", counts(1, 0, 1)),
        ("communication-style", counts(2, 0, 0)),
    ]

    # A week without calls is marked as such, never as a poor result.
    assert (empty["start"], empty["callCount"], empty["hasResults"]) == (
        "2026-10-12",
        0,
        False,
    )
    assert empty["overall"] == NOTHING
    # A call that is not assessed yet counts as a call, but has no results.
    assert (processing["callCount"], processing["hasResults"]) == (1, False)


async def test_other_agents_calls_are_their_own(session, data):
    response = await get(session, "/api/agent/progress", SAM, **WEEKS)
    first = response.json()["points"][0]
    assert response.json()["agentId"] == SAM
    assert (first["callCount"], first["hasResults"]) == (1, True)


async def test_a_manager_sees_the_same_progress_as_the_agent(session, data):
    own = await get(session, "/api/agent/progress", ALEX, **WEEKS)
    managed = await get(session, f"/api/manager/agents/{ALEX}/progress", MAYA, **WEEKS)
    assert managed.status_code == 200
    assert managed.json() == own.json()


@pytest.mark.parametrize("agent_id", [RILEY, "speaker-11", "no-such-agent"])
async def test_agents_outside_the_managers_organization_are_not_found(
    session, data, agent_id
):
    # speaker-11 is Harbor's agent record; Alex's record is shown by Alex's own ID.
    response = await get(
        session, f"/api/manager/agents/{agent_id}/progress", MAYA, **WEEKS
    )
    assert response.status_code == 404


async def test_the_provider_keeps_managers_to_their_organization(session, data):
    provider = DatabaseProgressProvider(sessions_for(session))
    dates = DateRange(date(2026, 10, 5), date(2026, 10, 25))
    assert (
        await provider.for_manager(
            HARBOR, "manager-harbor", ALEX, dates, ProgressPeriod.WEEK
        )
        is None
    )
    # An agent asking through the Manager method gets nothing either.
    assert (
        await provider.for_manager(NORTHWIND, SAM, ALEX, dates, ProgressPeriod.WEEK)
        is None
    )


async def test_agents_cannot_use_the_manager_route(session, data):
    response = await get(session, f"/api/manager/agents/{SAM}/progress", ALEX, **WEEKS)
    assert response.status_code == 403


async def test_an_agent_with_no_calls_gets_empty_periods(session, data):
    response = await get(session, "/api/agent/progress", UNLINKED, **WEEKS)
    assert response.status_code == 200
    points = response.json()["points"]
    assert len(points) == 3
    assert all(not point["hasResults"] and point["callCount"] == 0 for point in points)


async def test_partial_periods_only_count_calls_in_the_range(session, data):
    response = await get(
        session,
        "/api/agent/progress",
        ALEX,
        **{"from": "2026-10-07", "to": "2026-10-25"},
    )
    first = response.json()["points"][0]
    # The 6 October call is before the range; only the 8 October call is counted.
    assert first["start"] == "2026-10-07"
    assert first["callCount"] == 1
    assert first["overall"] == counts(3, 1, 0)


async def test_months_add_up_every_call_in_the_month(session, data):
    response = await get(
        session,
        "/api/agent/progress",
        ALEX,
        **{"from": "2026-10-01", "to": "2026-10-31", "period": "month"},
    )
    [october_point] = response.json()["points"]
    assert (october_point["start"], october_point["end"]) == (
        "2026-10-01",
        "2026-10-31",
    )
    assert october_point["callCount"] == 3
    assert october_point["overall"] == counts(5, 2, 1)


async def test_a_database_failure_is_a_503():
    class Broken:
        async def __aenter__(self):
            raise OperationalError("SELECT", {}, ConnectionError("refused"))

        async def __aexit__(self, *exc):
            return False

    provider = DatabaseProgressProvider(Broken)
    with pytest.raises(ProviderUnavailableError):
        await provider.for_agent(
            NORTHWIND,
            ALEX,
            DateRange(date(2026, 10, 5), date(2026, 10, 25)),
            ProgressPeriod.WEEK,
        )
