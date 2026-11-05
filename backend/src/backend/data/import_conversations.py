"""Import curated conversations from the docs repo into the database.

Usage (from backend/):

    uv run import-conversations ../../uoft-ftli-2026-genesys-docs/curated/conversations

Safe to re-run: conversations are matched on (source dataset, original ID) and
turns on (conversation, line number), so existing rows are updated in place
and keep their IDs. Topics assigned later are left alone.
"""

import argparse
import asyncio
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sqlalchemy import delete, func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from backend.db.session import async_session_factory
from backend.models import Agent, Conversation, Turn

REQUIRED_KEYS = ("id", "source", "channel", "turns", "source_fields")


def placeholder_agent_id(dataset: str) -> str:
    """Agent used for datasets with no agent identity (e.g. ABCD)."""
    return f"{dataset.lower()}-unknown-agent"


@dataclass
class CuratedConversation:
    curated_id: str
    source_dataset: str
    original_id: str
    channel: str
    agent_external_id: str
    source_fields: dict[str, Any]
    customer_record: dict[str, Any] | None
    turns: list[dict[str, Any]]


def parse_file(path: Path) -> CuratedConversation:
    data = json.loads(path.read_text(encoding="utf-8"))
    missing = [k for k in REQUIRED_KEYS if k not in data]
    if missing:
        raise ValueError(f"{path.name}: missing keys {missing}")
    dataset = data["source"]["dataset"]
    return CuratedConversation(
        curated_id=data["id"],
        source_dataset=dataset,
        original_id=str(data["source"]["original_id"]),
        channel=data["channel"],
        agent_external_id=data.get("agent_id") or placeholder_agent_id(dataset),
        source_fields=data["source_fields"],
        customer_record=data.get("customer_record"),
        turns=[
            {"line_number": t["n"], "speaker": t["speaker"], "text": t["text"]}
            for t in data["turns"]
        ],
    )


def load_directory(path: Path) -> list[CuratedConversation]:
    files = sorted(path.glob("*.json"))
    if not files:
        raise ValueError(f"No .json files found in {path}")
    return [parse_file(f) for f in files]


async def upsert_agent(session: AsyncSession, external_id: str) -> int:
    stmt = insert(Agent).values(external_id=external_id)
    stmt = stmt.on_conflict_do_update(
        index_elements=[Agent.external_id],
        set_={"external_id": stmt.excluded.external_id},
    ).returning(Agent.id)
    return await session.scalar(stmt)


async def upsert_conversation(
    session: AsyncSession, convo: CuratedConversation, agent_id: int
) -> None:
    stmt = insert(Conversation).values(
        source_dataset=convo.source_dataset,
        original_id=convo.original_id,
        curated_id=convo.curated_id,
        channel=convo.channel,
        agent_id=agent_id,
        source_fields=convo.source_fields,
        customer_record=convo.customer_record,
    )
    # Only import-owned columns are updated, so topic_id and dates set by
    # later steps survive a re-import.
    updated = ("curated_id", "channel", "agent_id", "source_fields", "customer_record")
    stmt = stmt.on_conflict_do_update(
        index_elements=[Conversation.source_dataset, Conversation.original_id],
        set_={col: stmt.excluded[col] for col in updated},
    ).returning(Conversation.id)
    conversation_id = await session.scalar(stmt)

    turns = insert(Turn).values(
        [{"conversation_id": conversation_id, **t} for t in convo.turns]
    )
    await session.execute(
        turns.on_conflict_do_update(
            index_elements=[Turn.conversation_id, Turn.line_number],
            set_={"speaker": turns.excluded.speaker, "text": turns.excluded.text},
        )
    )
    await session.execute(
        delete(Turn).where(
            Turn.conversation_id == conversation_id,
            Turn.line_number.not_in([t["line_number"] for t in convo.turns]),
        )
    )


async def import_conversations(
    session: AsyncSession, conversations: list[CuratedConversation]
) -> None:
    agent_ids: dict[str, int] = {}
    for convo in conversations:
        key = convo.agent_external_id
        if key not in agent_ids:
            agent_ids[key] = await upsert_agent(session, key)
        await upsert_conversation(session, convo, agent_ids[key])


async def dataset_counts(session: AsyncSession) -> dict[str, tuple[int, int, int]]:
    """Per dataset: (conversations, turns, distinct agents)."""
    rows = await session.execute(
        select(
            Conversation.source_dataset,
            func.count(func.distinct(Conversation.id)),
            func.count(Turn.id),
            func.count(func.distinct(Conversation.agent_id)),
        )
        .outerjoin(Turn)
        .group_by(Conversation.source_dataset)
        .order_by(Conversation.source_dataset)
    )
    return {dataset: (c, t, a) for dataset, c, t, a in rows}


async def run(path: Path) -> None:
    conversations = load_directory(path)
    async with async_session_factory() as session:
        async with session.begin():
            await import_conversations(session, conversations)
        counts = await dataset_counts(session)

    print(f"Imported {len(conversations)} files from {path}")
    print(f"{'dataset':<20}{'conversations':>15}{'turns':>10}{'agents':>10}")
    for dataset, (c, t, a) in counts.items():
        print(f"{dataset:<20}{c:>15}{t:>10}{a:>10}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "path", type=Path, help="the curated/conversations directory of the docs repo"
    )
    args = parser.parse_args()
    if not args.path.is_dir():
        sys.exit(f"Not a directory: {args.path}")
    asyncio.run(run(args.path))


if __name__ == "__main__":
    main()
