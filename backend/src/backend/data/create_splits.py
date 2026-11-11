"""Create deterministic development and evaluation conversation manifests."""

import argparse
import asyncio
import itertools
import json
import math
import random
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.db.session import async_session_factory
from backend.models import Agent, Conversation, Topic

DEFAULT_DEVELOPMENT_RATIO = 0.7
DEFAULT_SEED = 43
DEFAULT_OUTPUT_DIR = Path(__file__).resolve().parents[3] / "splits"
HVB_DATASET = "HarperValleyBank"


@dataclass(frozen=True, order=True)
class ConversationRecord:
    conversation_id: str
    dataset: str
    topic: str
    agent_id: str


@dataclass(frozen=True)
class SplitResult:
    development: tuple[ConversationRecord, ...]
    evaluation: tuple[ConversationRecord, ...]


def _validate_records(
    records: list[ConversationRecord], development_ratio: float
) -> None:
    if not 0 < development_ratio < 1:
        raise ValueError("development_ratio must be between 0 and 1")
    if not records:
        raise ValueError("At least one conversation is required")

    seen = set()
    for record in records:
        for field in ("conversation_id", "dataset", "topic"):
            value = getattr(record, field)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(
                    f"Conversation {record.conversation_id!r} has no {field}"
                )
        if record.conversation_id in seen:
            raise ValueError(f"Duplicate conversation ID: {record.conversation_id}")
        seen.add(record.conversation_id)
        if record.dataset == HVB_DATASET and not record.agent_id.strip():
            raise ValueError(
                f"HVB conversation {record.conversation_id!r} has no identified Agent"
            )


def _hvb_split(
    records: list[ConversationRecord], evaluation_ratio: float, seed: int
) -> tuple[list[ConversationRecord], list[ConversationRecord]]:
    by_agent = defaultdict(list)
    for record in records:
        by_agent[record.agent_id].append(record)
    if len(by_agent) < 2:
        raise ValueError("HVB splitting requires at least two identified Agents")

    evaluation_agent_count = round(len(by_agent) * evaluation_ratio)
    evaluation_agent_count = max(1, min(len(by_agent) - 1, evaluation_agent_count))

    agents = sorted(by_agent)
    random.Random(f"{seed}:HVB:agents").shuffle(agents)
    topic_totals = Counter(record.topic for record in records)
    target_total = len(records) * evaluation_ratio

    def score(candidate: tuple[str, ...]) -> tuple[int, float, float]:
        candidate_records = [
            record for agent in candidate for record in by_agent[agent]
        ]
        topic_counts = Counter(record.topic for record in candidate_records)
        missing_coverage = sum(
            topic_counts[topic] == 0 or topic_counts[topic] == total
            for topic, total in topic_totals.items()
        )
        topic_difference = sum(
            abs(topic_counts[topic] - total * evaluation_ratio)
            for topic, total in topic_totals.items()
        )
        return (
            missing_coverage,
            abs(len(candidate_records) - target_total),
            topic_difference,
        )

    candidates = itertools.combinations(agents, evaluation_agent_count)
    evaluation_agents = set(min(candidates, key=score))
    development, evaluation = [], []
    for agent, agent_records in by_agent.items():
        destination = evaluation if agent in evaluation_agents else development
        destination.extend(agent_records)
    return development, evaluation


def _topic_allocations(
    topic_sizes: dict[str, int], evaluation_ratio: float, seed: int, dataset: str
) -> dict[str, int]:
    target = round(sum(topic_sizes.values()) * evaluation_ratio)
    allocations = {}
    remainders = {}
    for topic, size in topic_sizes.items():
        raw = size * evaluation_ratio
        allocations[topic] = math.floor(raw)
        remainders[topic] = raw - math.floor(raw)
        if size > 1:
            allocations[topic] = max(1, min(size - 1, allocations[topic]))

    tie_order = sorted(topic_sizes)
    random.Random(f"{seed}:{dataset}:allocation").shuffle(tie_order)
    rank = {topic: index for index, topic in enumerate(tie_order)}

    while sum(allocations.values()) < target:
        choices = [
            topic
            for topic, size in topic_sizes.items()
            if allocations[topic] < size - (1 if size > 1 else 0)
        ]
        if not choices:
            raise ValueError(f"Cannot create requested {dataset} evaluation split")
        topic = min(choices, key=lambda item: (-remainders[item], rank[item]))
        allocations[topic] += 1

    while sum(allocations.values()) > target:
        choices = [
            topic
            for topic, size in topic_sizes.items()
            if allocations[topic] > (1 if size > 1 else 0)
        ]
        if not choices:
            raise ValueError(
                f"Cannot preserve {dataset} topic coverage at the requested ratio"
            )
        topic = min(choices, key=lambda item: (remainders[item], rank[item]))
        allocations[topic] -= 1
    return allocations


def _stratified_split(
    records: list[ConversationRecord], evaluation_ratio: float, seed: int
) -> tuple[list[ConversationRecord], list[ConversationRecord]]:
    by_dataset_topic = defaultdict(list)
    for record in records:
        by_dataset_topic[(record.dataset, record.topic)].append(record)

    development, evaluation = [], []
    datasets = sorted({record.dataset for record in records})
    for dataset in datasets:
        topics = {
            topic: sorted(by_dataset_topic[(dataset, topic)])
            for current_dataset, topic in by_dataset_topic
            if current_dataset == dataset
        }
        allocations = _topic_allocations(
            {topic: len(topic_records) for topic, topic_records in topics.items()},
            evaluation_ratio,
            seed,
            dataset,
        )
        for topic in sorted(topics):
            topic_records = topics[topic]
            random.Random(f"{seed}:{dataset}:{topic}").shuffle(topic_records)
            evaluation_count = allocations[topic]
            evaluation.extend(topic_records[:evaluation_count])
            development.extend(topic_records[evaluation_count:])
    return development, evaluation


def create_splits(
    records: list[ConversationRecord], *, development_ratio: float, seed: int
) -> SplitResult:
    _validate_records(records, development_ratio)
    evaluation_ratio = 1 - development_ratio

    hvb = [record for record in records if record.dataset == HVB_DATASET]
    other = [record for record in records if record.dataset != HVB_DATASET]
    development, evaluation = [], []

    if hvb:
        hvb_development, hvb_evaluation = _hvb_split(hvb, evaluation_ratio, seed)
        development.extend(hvb_development)
        evaluation.extend(hvb_evaluation)
    if other:
        other_development, other_evaluation = _stratified_split(
            other, evaluation_ratio, seed
        )
        development.extend(other_development)
        evaluation.extend(other_evaluation)

    return SplitResult(
        development=tuple(sorted(development)),
        evaluation=tuple(sorted(evaluation)),
    )


def _coverage(records: tuple[ConversationRecord, ...]) -> dict:
    datasets = {}
    for dataset in sorted({record.dataset for record in records}):
        dataset_records = [record for record in records if record.dataset == dataset]
        topic_counts = Counter(record.topic for record in dataset_records)
        datasets[dataset] = {
            "count": len(dataset_records),
            "topics": dict(sorted(topic_counts.items())),
        }
    return {"total": len(records), "datasets": datasets}


def build_manifests(
    split: SplitResult, *, development_ratio: float, seed: int
) -> dict[str, dict]:
    manifests = {}
    for partition, records in (
        ("development", split.development),
        ("evaluation", split.evaluation),
    ):
        manifests[partition] = {
            "manifest_version": 1,
            "partition": partition,
            "seed": seed,
            "development_ratio": development_ratio,
            "conversation_ids": sorted(record.conversation_id for record in records),
            "coverage": _coverage(records),
        }
    return manifests


def write_manifests(manifests: dict[str, dict], output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    for partition in sorted(manifests):
        serialized = json.dumps(manifests[partition], indent=2, sort_keys=True) + "\n"
        (output_dir / f"{partition}.json").write_text(serialized, encoding="utf-8")


def format_coverage(manifests: dict[str, dict]) -> str:
    lines = []
    for partition in ("development", "evaluation"):
        coverage = manifests[partition]["coverage"]
        lines.append(f"{partition}: {coverage['total']} conversations")
        for dataset, dataset_coverage in coverage["datasets"].items():
            lines.append(f"  {dataset}: {dataset_coverage['count']}")
            for topic, count in dataset_coverage["topics"].items():
                lines.append(f"    {topic}: {count}")
    return "\n".join(lines)


async def load_records(session: AsyncSession) -> list[ConversationRecord]:
    rows = await session.execute(
        select(
            Conversation.curated_id,
            Conversation.source_dataset,
            Topic.name,
            Agent.external_id,
        )
        .join(Agent)
        .outerjoin(Topic)
        .where(Conversation.curated_id.is_not(None))
        .order_by(Conversation.curated_id)
    )
    return [
        ConversationRecord(
            conversation_id=conversation_id,
            dataset=dataset,
            topic=topic or "",
            agent_id=agent_id,
        )
        for conversation_id, dataset, topic, agent_id in rows
    ]


async def run(development_ratio: float, seed: int, output_dir: Path) -> None:
    async with async_session_factory() as session:
        records = await load_records(session)
    split = create_splits(records, development_ratio=development_ratio, seed=seed)
    manifests = build_manifests(split, development_ratio=development_ratio, seed=seed)
    write_manifests(manifests, output_dir)
    print(format_coverage(manifests))
    print(f"Wrote manifests to {output_dir}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED)
    parser.add_argument(
        "--development-ratio", type=float, default=DEFAULT_DEVELOPMENT_RATIO
    )
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    args = parser.parse_args()
    try:
        asyncio.run(run(args.development_ratio, args.seed, args.output_dir))
    except ValueError as error:
        sys.exit(str(error))


if __name__ == "__main__":
    main()
