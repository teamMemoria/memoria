"""Pick conversations for the hand-scored evaluation set and write a template.

Usage (from backend/, after import-conversations and assign-topics):

    uv run select-eval-set [--per-dataset 14] [--seed 31] [--out evaluation/scoring_template.csv]

Picks the same number of conversations from each dataset, covering every
topic and every agent first, then spreading the rest across the least-used
topics. The same seed always picks the same conversations. The scoring
columns are left empty for people to fill in.
"""

import argparse
import asyncio
import csv
import random
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy import func, select

from backend.db.session import async_session_factory
from backend.models import Agent, Conversation, FindingCategory, Topic, Turn

DEFAULT_OUT = Path("evaluation/scoring_template.csv")
DEFAULT_PER_DATASET = 14
DEFAULT_SEED = 31
SCORERS = ("scorer1", "scorer2")


@dataclass(frozen=True)
class Candidate:
    curated_id: str
    source_dataset: str
    topic: str
    agent: str
    turns: int


def select_balanced(
    candidates: list[Candidate], count: int, rng: random.Random
) -> list[Candidate]:
    """Pick `count` candidates from one dataset, covering topics and agents first."""
    pool = sorted(candidates, key=lambda c: c.curated_id)
    rng.shuffle(pool)
    picked: list[Candidate] = []
    topics, agents = Counter(), Counter()

    def gain(c: Candidate) -> tuple[int, int, int]:
        new = (c.topic not in topics) + (c.agent not in agents)
        return (new, -topics[c.topic], -agents[c.agent])

    while len(picked) < min(count, len(pool)):
        # max() keeps the first of equal candidates, so ties follow the shuffle.
        best = max((c for c in pool if c not in picked), key=gain)
        picked.append(best)
        topics[best.topic] += 1
        agents[best.agent] += 1
    return sorted(picked, key=lambda c: c.curated_id)


def template_columns() -> list[str]:
    columns = ["curated_id", "source_dataset", "topic", "agent", "turns", *SCORERS]
    for category in FindingCategory:
        columns += [f"{category.value}_{scorer}" for scorer in SCORERS]
    columns += [f"{scorer}_notes" for scorer in SCORERS]
    columns.append("disagreement_notes")
    return columns


def write_template(selection: list[Candidate], out: Path) -> None:
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=template_columns())
        writer.writeheader()
        for c in selection:
            writer.writerow(
                {
                    "curated_id": c.curated_id,
                    "source_dataset": c.source_dataset,
                    "topic": c.topic,
                    "agent": c.agent,
                    "turns": c.turns,
                }
            )


async def load_candidates() -> list[Candidate]:
    async with async_session_factory() as session:
        rows = await session.execute(
            select(
                Conversation.curated_id,
                Conversation.source_dataset,
                Topic.name,
                Agent.external_id,
                func.count(Turn.id),
            )
            .join(Topic)
            .join(Agent)
            .join(Turn)
            .where(Conversation.curated_id.is_not(None))
            .group_by(Conversation.id, Topic.name, Agent.external_id)
        )
        return [Candidate(*row) for row in rows]


def select_eval_set(
    candidates: list[Candidate], per_dataset: int, seed: int
) -> list[Candidate]:
    selection = []
    for dataset in sorted({c.source_dataset for c in candidates}):
        # Seeded per dataset, so one dataset's pool doesn't change the other's picks.
        rng = random.Random(f"{seed}:{dataset}")
        pool = [c for c in candidates if c.source_dataset == dataset]
        selection += select_balanced(pool, per_dataset, rng)
    return selection


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--per-dataset", type=int, default=DEFAULT_PER_DATASET)
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    args = parser.parse_args()

    candidates = asyncio.run(load_candidates())
    selection = select_eval_set(candidates, args.per_dataset, args.seed)
    write_template(selection, args.out)

    print(f"Wrote {len(selection)} conversations to {args.out}")
    for dataset in sorted({c.source_dataset for c in selection}):
        picked = [c for c in selection if c.source_dataset == dataset]
        pool = [c for c in candidates if c.source_dataset == dataset]
        print(
            f"{dataset}: {len(picked)} picked, "
            f"{len({c.topic for c in picked})}/{len({c.topic for c in pool})} topics, "
            f"{len({c.agent for c in picked})}/{len({c.agent for c in pool})} agents"
        )
        for topic, n in sorted(Counter(c.topic for c in picked).items()):
            print(f"  {topic:<30}{n:>3}")


if __name__ == "__main__":
    main()
