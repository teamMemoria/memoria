import json

import pytest
from sqlalchemy import func, select

from backend.data.import_conversations import (
    dataset_counts,
    import_conversations,
    load_directory,
)
from backend.models import Agent, Conversation, Organization, Speaker, Topic, Turn

HVB = {
    "id": "HVB-0001",
    "source": {"dataset": "HarperValleyBank", "original_id": "hvb-a"},
    "modifications": [],
    "channel": "voice",
    "agent_id": "hvb-speaker-1",
    "customer_record": {"customer_name": "Test Person"},
    "turns": [
        {"n": 1, "speaker": "agent", "text": "how can i help", "start_ms": 10},
        {"n": 3, "speaker": "customer", "text": "i lost my card"},
    ],
    "source_fields": {"task_assigned": ["replace card"]},
}

ABCD = {
    "id": "ABCD-0001",
    "source": {"dataset": "ABCD", "original_id": "123"},
    "modifications": [],
    "channel": "chat",
    "customer_record": {"customer_name": "sample user", "phone": "(000) 000-0000"},
    "turns": [
        {"n": 1, "speaker": "agent", "text": "Hello"},
        {"n": 2, "speaker": "system_action", "text": "Account has been pulled up."},
    ],
    "source_fields": {"flow": "account_access", "subflow": "reset_2fa"},
}


@pytest.fixture
def data_dir(tmp_path):
    for record in (HVB, ABCD):
        (tmp_path / f"{record['id']}.json").write_text(json.dumps(record))
    return tmp_path


async def snapshot(session):
    rows = await session.execute(
        select(
            Conversation.id,
            Conversation.curated_id,
            Turn.id,
            Turn.line_number,
            Turn.speaker,
            Turn.text,
        )
        .join(Turn)
        .order_by(Turn.id)
    )
    return rows.all()


@pytest.fixture
async def organization(session):
    org = Organization(slug="import-tests", name="Import Tests")
    session.add(org)
    await session.flush()
    return org


async def test_imports_conversations_turns_and_agents(session, data_dir, organization):
    await import_conversations(session, load_directory(data_dir), organization.id)

    hvb = await session.scalar(
        select(Conversation).where(Conversation.curated_id == "HVB-0001")
    )
    await session.refresh(hvb, ["agent", "turns"])
    assert hvb.source_dataset == "HarperValleyBank"
    assert hvb.original_id == "hvb-a"
    assert hvb.channel == "voice"
    assert hvb.agent.external_id == "hvb-speaker-1"
    assert hvb.source_fields == {"task_assigned": ["replace card"]}
    assert hvb.customer_record == {"customer_name": "Test Person"}
    assert hvb.organization_id == organization.id
    assert [(t.line_number, t.speaker) for t in hvb.turns] == [
        (1, Speaker.AGENT),
        (3, Speaker.CUSTOMER),
    ]

    abcd = await session.scalar(
        select(Conversation).where(Conversation.curated_id == "ABCD-0001")
    )
    await session.refresh(abcd, ["agent", "turns"])
    assert abcd.agent.external_id == "abcd-unknown-agent"
    assert abcd.turns[1].speaker == Speaker.SYSTEM_ACTION

    assert await dataset_counts(session, organization.id) == {
        "ABCD": (1, 2, 1),
        "HarperValleyBank": (1, 2, 1),
    }


async def test_running_twice_gives_the_same_result(session, data_dir, organization):
    conversations = load_directory(data_dir)
    await import_conversations(session, conversations, organization.id)
    first = await snapshot(session)

    await import_conversations(session, conversations, organization.id)

    assert await snapshot(session) == first
    assert await session.scalar(select(func.count(Agent.id))) == 2


async def test_reimport_keeps_assigned_topic_and_applies_source_changes(
    session, data_dir, tmp_path, organization
):
    await import_conversations(session, load_directory(data_dir), organization.id)
    convo = await session.scalar(
        select(Conversation).where(Conversation.curated_id == "HVB-0001")
    )
    convo.topic = Topic(
        organization=organization,
        source_dataset="HarperValleyBank",
        name="Card replacement",
    )
    await session.flush()

    changed = {**HVB, "turns": [{"n": 1, "speaker": "agent", "text": "hi there"}]}
    (tmp_path / "HVB-0001.json").write_text(json.dumps(changed))
    await import_conversations(session, load_directory(data_dir), organization.id)

    session.expire_all()
    convo = await session.scalar(
        select(Conversation).where(Conversation.curated_id == "HVB-0001")
    )
    await session.refresh(convo, ["topic", "turns"])
    assert convo.topic.name == "Card replacement"
    assert [(t.line_number, t.text) for t in convo.turns] == [(1, "hi there")]


async def test_same_source_ids_are_isolated_by_organization(session, data_dir):
    northwind = Organization(slug="northwind", name="Northwind")
    harbor = Organization(slug="harbor", name="Harbor")
    session.add_all([northwind, harbor])
    await session.flush()

    conversations = load_directory(data_dir)
    await import_conversations(session, conversations, northwind.id)
    await import_conversations(session, conversations, harbor.id)

    assert await session.scalar(select(func.count(Conversation.id))) == 4
    assert await session.scalar(select(func.count(Agent.id))) == 4


def test_missing_required_key_names_the_file(tmp_path):
    (tmp_path / "BAD-0001.json").write_text(json.dumps({"id": "BAD-0001"}))
    with pytest.raises(ValueError, match="BAD-0001.json"):
        load_directory(tmp_path)


def test_empty_directory_is_an_error(tmp_path):
    with pytest.raises(ValueError, match="No .json files"):
        load_directory(tmp_path)
