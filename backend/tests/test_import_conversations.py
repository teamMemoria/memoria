import json

import pytest
from sqlalchemy import func, select

from backend.data.import_conversations import (
    dataset_counts,
    import_conversations,
    load_directory,
)
from backend.models import (
    Agent,
    Conversation,
    ConversationMetric,
    Organization,
    Speaker,
    Topic,
    Turn,
)

HVB = {
    "id": "HVB-0001",
    "source": {"dataset": "HarperValleyBank", "original_id": "hvb-a"},
    "modifications": [],
    "channel": "voice",
    "agent_id": "hvb-speaker-1",
    "customer_record": {"customer_name": "Test Person"},
    "turns": [
        {
            "n": 1,
            "speaker": "agent",
            "text": "how can i help",
            "asr_text": "how can i help",
            "start_ms": 10,
            "duration_ms": 90,
        },
        {
            "n": 3,
            "speaker": "customer",
            "text": "i lost my card",
            "asr_text": "i lost my cart",
            "start_ms": 120,
            "duration_ms": 180,
        },
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
    "source_fields": {
        "flow": "account_access",
        "subflow": "reset_2fa",
        "actions_taken": ["pull-up-account"],
    },
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
    await session.refresh(hvb, ["agent", "turns", "metrics"])
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
    assert hvb.metrics.turn_count == 2
    assert hvb.metrics.call_elapsed_ms == 290
    assert hvb.metrics.agent_speaking_ms == 90
    assert hvb.metrics.customer_speaking_ms == 180
    assert hvb.metrics.asr_word_error_rate == pytest.approx(1 / 8)

    abcd = await session.scalar(
        select(Conversation).where(Conversation.curated_id == "ABCD-0001")
    )
    await session.refresh(abcd, ["agent", "turns", "metrics"])
    assert abcd.agent.external_id == "abcd-unknown-agent"
    assert abcd.turns[1].speaker == Speaker.SYSTEM_ACTION
    assert abcd.metrics.system_action_count == 1
    assert abcd.metrics.documented_action_count == 1
    assert abcd.metrics.call_elapsed_ms is None

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


async def test_reimport_recomputes_metrics_without_duplicating_them(
    session, data_dir, tmp_path, organization
):
    await import_conversations(session, load_directory(data_dir), organization.id)
    changed = {
        **HVB,
        "turns": [{"n": 1, "speaker": "agent", "text": "hi there"}],
    }
    (tmp_path / "HVB-0001.json").write_text(json.dumps(changed))

    await import_conversations(session, load_directory(data_dir), organization.id)
    session.expire_all()
    convo = await session.scalar(
        select(Conversation).where(Conversation.curated_id == "HVB-0001")
    )
    await session.refresh(convo, ["metrics"])

    assert convo.metrics.turn_count == 1
    assert convo.metrics.agent_word_count == 2
    assert convo.metrics.customer_word_count == 0
    assert convo.metrics.agent_text_share == 1
    assert convo.metrics.call_elapsed_ms is None


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
    assert (
        await session.scalar(select(func.count(ConversationMetric.conversation_id)))
        == 4
    )


def test_missing_required_key_names_the_file(tmp_path):
    (tmp_path / "BAD-0001.json").write_text(json.dumps({"id": "BAD-0001"}))
    with pytest.raises(ValueError, match="BAD-0001.json"):
        load_directory(tmp_path)


def test_empty_directory_is_an_error(tmp_path):
    with pytest.raises(ValueError, match="No .json files"):
        load_directory(tmp_path)
