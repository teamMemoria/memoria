"""Give every conversation a generated start time, so there is a timeline.

Usage (from backend/, after import-conversations):

    uv run assign-synthetic-dates [--start 2026-01-05] [--weeks 8] [--seed 2026]

Each agent's conversations are spread across the window during business hours
(weekdays, 09:00-17:00 UTC) and kept in curated-ID order, so a later file is
always a later call. The source date column is never touched. The same seed
always gives the same times.
"""

import argparse
import asyncio
import random
from collections import defaultdict
from datetime import UTC, date, datetime, time, timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.database import SessionLocal
from backend.models import Agent, Conversation

DEFAULT_START = date(2026, 1, 5)  # a Monday
DEFAULT_WEEKS = 8
DEFAULT_SEED = 2026
DAY_START = time(9)
WORKDAY_SECONDS = 8 * 3600


def business_days(start: date, weeks: int) -> list[date]:
    days = (start + timedelta(days=i) for i in range(weeks * 7))
    return [d for d in days if d.weekday() < 5]


def synthetic_times(
    agent_key: str, count: int, start: date, weeks: int, seed: int
) -> list[datetime]:
    """Return `count` distinct, increasing business-hours times for one agent."""
    days = business_days(start, weeks)
    slots = len(days) * WORKDAY_SECONDS
    if count > slots:
        raise ValueError(f"{count} conversations don't fit in {weeks} weeks")
    # Seeded per agent, so adding or removing one agent doesn't move the others.
    rng = random.Random(f"{seed}:{agent_key}")
    times = []
    for offset in sorted(rng.sample(range(slots), count)):
        day, second = divmod(offset, WORKDAY_SECONDS)
        times.append(
            datetime.combine(days[day], DAY_START, tzinfo=UTC)
            + timedelta(seconds=second)
        )
    return times


async def assign_synthetic_dates(
    session: AsyncSession, start: date, weeks: int, seed: int
) -> None:
    rows = await session.execute(
        select(Conversation, Agent.external_id)
        .join(Agent)
        .order_by(Conversation.curated_id, Conversation.id)
    )
    by_agent: dict[str, list[Conversation]] = defaultdict(list)
    for conversation, agent_key in rows:
        by_agent[agent_key].append(conversation)

    for agent_key, conversations in by_agent.items():
        times = synthetic_times(agent_key, len(conversations), start, weeks, seed)
        for conversation, started_at in zip(conversations, times, strict=True):
            conversation.synthetic_started_at = started_at
    await session.flush()


async def run(start: date, weeks: int, seed: int) -> None:
    async with SessionLocal() as session:
        async with session.begin():
            await assign_synthetic_dates(session, start, weeks, seed)
        rows = await session.execute(
            select(
                Agent.external_id,
                func.count(Conversation.id),
                func.min(Conversation.synthetic_started_at),
                func.max(Conversation.synthetic_started_at),
            )
            .join(Conversation)
            .group_by(Agent.external_id)
            .order_by(Agent.external_id)
        )

    end = start + timedelta(weeks=weeks)
    print(f"Synthetic window {start} to {end} (seed {seed})")
    print(f"{'agent':<22}{'calls':>6}  first             last")
    for agent_key, n, first, last in rows:
        print(f"{agent_key:<22}{n:>6}  {first:%Y-%m-%d %H:%M}  {last:%Y-%m-%d %H:%M}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--start", type=date.fromisoformat, default=DEFAULT_START)
    parser.add_argument("--weeks", type=int, default=DEFAULT_WEEKS)
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED)
    args = parser.parse_args()
    asyncio.run(run(args.start, args.weeks, args.seed))


if __name__ == "__main__":
    main()
