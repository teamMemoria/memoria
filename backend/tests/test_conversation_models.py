import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import selectinload

from backend.models import Agent, Conversation, Organization, Speaker, Topic, Turn


def make_conversation(agent: Agent, original_id: str = "abc123") -> Conversation:
    return Conversation(
        organization=agent.organization,
        source_dataset="HarperValleyBank",
        original_id=original_id,
        channel="voice",
        agent=agent,
    )


@pytest.fixture
def organization():
    return Organization(slug="northwind", name="Northwind Support")


async def test_conversation_with_turns_reads_back_in_order(session, organization):
    agent = Agent(organization=organization, external_id="hvb-speaker-1")
    topic = Topic(
        organization=organization,
        source_dataset="HarperValleyBank",
        name="Card replacement",
    )
    conversation = make_conversation(agent)
    conversation.topic = topic
    # Added out of order, with a gap, to check ordering uses line_number.
    conversation.turns = [
        Turn(line_number=4, speaker=Speaker.AGENT, text="Your card is on its way."),
        Turn(line_number=1, speaker=Speaker.AGENT, text="How can I help?"),
        Turn(line_number=2, speaker=Speaker.CUSTOMER, text="I lost my card."),
    ]
    session.add(conversation)
    await session.commit()
    session.expunge_all()

    loaded = await session.scalar(
        select(Conversation)
        .where(Conversation.original_id == "abc123")
        .options(selectinload(Conversation.turns))
    )

    assert [t.line_number for t in loaded.turns] == [1, 2, 4]
    assert [t.speaker for t in loaded.turns] == [
        Speaker.AGENT,
        Speaker.CUSTOMER,
        Speaker.AGENT,
    ]
    assert loaded.turns[1].text == "I lost my card."
    assert loaded.channel == "voice"
    assert loaded.conversation_date is None


async def test_line_number_is_unique_within_a_conversation(session, organization):
    conversation = make_conversation(
        Agent(organization=organization, external_id="hvb-speaker-2")
    )
    conversation.turns = [
        Turn(line_number=1, speaker=Speaker.AGENT, text="Hi"),
        Turn(line_number=1, speaker=Speaker.CUSTOMER, text="Hello"),
    ]
    session.add(conversation)
    with pytest.raises(IntegrityError):
        await session.flush()


async def test_line_numbers_are_stable_when_turns_are_added(session, organization):
    conversation = make_conversation(
        Agent(organization=organization, external_id="hvb-speaker-3")
    )
    conversation.turns = [Turn(line_number=2, speaker=Speaker.CUSTOMER, text="b")]
    session.add(conversation)
    await session.flush()
    original = conversation.turns[0]

    session.add(
        Turn(conversation=conversation, line_number=1, speaker=Speaker.AGENT, text="a")
    )
    await session.flush()
    await session.refresh(original)

    assert original.line_number == 2


async def test_source_id_is_unique_per_dataset(session, organization):
    agent = Agent(organization=organization, external_id="hvb-speaker-4")
    session.add_all([make_conversation(agent, "dup"), make_conversation(agent, "dup")])
    with pytest.raises(IntegrityError):
        await session.flush()


async def test_speaker_is_restricted_to_known_values(session, organization):
    conversation = make_conversation(
        Agent(organization=organization, external_id="hvb-speaker-5")
    )
    session.add(conversation)
    await session.flush()
    with pytest.raises(IntegrityError):
        await session.execute(
            Turn.__table__.insert().values(
                conversation_id=conversation.id,
                line_number=1,
                speaker="robot",
                text="x",
            )
        )
