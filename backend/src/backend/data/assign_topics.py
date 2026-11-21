"""Assign each imported conversation a topic from its dataset task labels.

Usage (from backend/, after import-conversations):

    uv run assign-topics [--mapping path/to/topic_mapping.toml] \
        [--organization default]

The mapping lives in topic_mapping.toml next to this file. If any conversation
has a label the mapping doesn't cover, nothing is written.
"""

import argparse
import asyncio
import sys
import tomllib
from collections import Counter
from pathlib import Path
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from backend.db.session import async_session_factory
from backend.models import Conversation, Organization, Topic

DEFAULT_MAPPING = Path(__file__).with_name("topic_mapping.toml")

Mapping = dict[str, Any]


class UnmappedLabelError(ValueError):
    pass


def load_mapping(path: Path = DEFAULT_MAPPING) -> Mapping:
    with path.open("rb") as f:
        return tomllib.load(f)


def topic_for(dataset: str, source_fields: dict[str, Any], mapping: Mapping) -> str:
    """Return the topic name for one conversation's source fields."""
    if dataset == "HarperValleyBank":
        tasks = set(source_fields.get("task_assigned") or [])
        if len(tasks) != 1:
            raise UnmappedLabelError(f"expected one task_assigned, got {sorted(tasks)}")
        task = tasks.pop()
        try:
            return mapping[dataset]["task_assigned"][task]
        except KeyError:
            raise UnmappedLabelError(f"no topic for task_assigned {task!r}") from None

    if dataset == "ABCD":
        flow, subflow = source_fields.get("flow"), source_fields.get("subflow")
        rules = mapping.get(dataset, {})
        override = rules.get("subflow", {}).get(f"{flow}/{subflow}")
        if override:
            return override
        try:
            return rules["flow"][flow]
        except KeyError:
            raise UnmappedLabelError(f"no topic for flow {flow!r}") from None

    raise UnmappedLabelError(f"no topic rules for dataset {dataset!r}")


async def assign_topics(
    session: AsyncSession, mapping: Mapping, organization_id: int
) -> None:
    conversations = (
        await session.scalars(
            select(Conversation).where(Conversation.organization_id == organization_id)
        )
    ).all()

    names: dict[int, tuple[str, str]] = {}
    errors = []
    for c in conversations:
        try:
            names[c.id] = (
                c.source_dataset,
                topic_for(c.source_dataset, c.source_fields, mapping),
            )
        except UnmappedLabelError as e:
            errors.append(f"{c.curated_id or c.id}: {e}")
    if errors:
        raise UnmappedLabelError("\n".join(errors))

    topic_ids: dict[tuple[str, str], int] = {}
    for dataset, name in sorted(set(names.values())):
        stmt = insert(Topic).values(
            organization_id=organization_id, source_dataset=dataset, name=name
        )
        stmt = stmt.on_conflict_do_update(
            index_elements=[Topic.organization_id, Topic.source_dataset, Topic.name],
            set_={"name": stmt.excluded.name},
        ).returning(Topic.id)
        topic_ids[(dataset, name)] = await session.scalar(stmt)

    for c in conversations:
        c.topic_id = topic_ids[names[c.id]]
    await session.flush()


async def topic_counts(
    session: AsyncSession, organization_id: int
) -> Counter[tuple[str, str | None]]:
    rows = await session.execute(
        select(Conversation.source_dataset, Topic.name, func.count())
        .outerjoin(Topic)
        .where(Conversation.organization_id == organization_id)
        .group_by(Conversation.source_dataset, Topic.name)
    )
    return Counter({(dataset, name): n for dataset, name, n in rows})


async def run(mapping_path: Path, organization_slug: str) -> None:
    mapping = load_mapping(mapping_path)
    async with async_session_factory() as session:
        try:
            async with session.begin():
                organization_id = await session.scalar(
                    select(Organization.id).where(
                        Organization.slug == organization_slug
                    )
                )
                if organization_id is None:
                    sys.exit(f"Unknown organization: {organization_slug}")
                await assign_topics(session, mapping, organization_id)
        except UnmappedLabelError as e:
            sys.exit(f"Unmapped labels, nothing was written:\n{e}")
        counts = await topic_counts(session, organization_id)

    for dataset in sorted({d for d, _ in counts}):
        rows = sorted(
            ((name, n) for (d, name), n in counts.items() if d == dataset),
            key=lambda r: (-r[1], r[0] or ""),
        )
        print(f"{dataset} ({sum(n for _, n in rows)} conversations)")
        for name, n in rows:
            print(f"  {name or '(no topic)':<30}{n:>5}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--mapping", type=Path, default=DEFAULT_MAPPING)
    parser.add_argument(
        "--organization",
        default="default",
        help="organization slug to update (default: default)",
    )
    args = parser.parse_args()
    asyncio.run(run(args.mapping, args.organization))


if __name__ == "__main__":
    main()
