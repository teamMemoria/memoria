from datetime import datetime

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError

from backend.models import (
    EMBEDDING_DIM,
    Agent,
    Conversation,
    DraftStatus,
    EntryStatus,
    KnowledgeDraft,
    KnowledgeEntry,
    KnowledgeReview,
    ReviewAction,
    Topic,
)


def one_hot(i: int) -> list[float]:
    v = [0.0] * EMBEDDING_DIM
    v[i] = 1.0
    return v


@pytest.fixture
async def topic(session):
    t = Topic(source_dataset="HarperValleyBank", name="Card replacement")
    session.add(t)
    await session.flush()
    return t


async def approve(
    session, draft: KnowledgeDraft, reviewer: str = "manager@example.com"
):
    review = KnowledgeReview(
        draft=draft, action=ReviewAction.APPROVED, reviewer=reviewer
    )
    draft.status = DraftStatus.APPROVED
    entry = KnowledgeEntry(
        topic=draft.topic,
        answer_text=draft.answer_text,
        embedding=draft.embedding,
        approved_review=review,
    )
    session.add(entry)
    await session.flush()
    return entry


async def test_draft_keeps_its_supporting_conversations(session, topic):
    agent = Agent(external_id="hvb-speaker-1")
    conversations = [
        Conversation(
            source_dataset="HarperValleyBank",
            original_id=str(i),
            channel="voice",
            agent=agent,
        )
        for i in range(3)
    ]
    draft = KnowledgeDraft(
        topic=topic,
        answer_text="New cards arrive in 5 to 7 business days.",
        supporting_conversations=conversations,
    )
    session.add(draft)
    await session.flush()

    assert draft.status == DraftStatus.PENDING
    rows = await session.execute(
        text(
            "SELECT conversation_id FROM knowledge_draft_conversations WHERE draft_id = :d"
        ),
        {"d": draft.id},
    )
    assert sorted(r[0] for r in rows) == sorted(c.id for c in conversations)


async def test_drafts_and_entries_cannot_be_confused(session, topic):
    session.add(KnowledgeDraft(topic=topic, answer_text="Unapproved draft"))
    approved_draft = KnowledgeDraft(topic=topic, answer_text="Approved answer")
    session.add(approved_draft)
    await approve(session, approved_draft)

    entries = (await session.scalars(select(KnowledgeEntry))).all()
    assert [e.answer_text for e in entries] == ["Approved answer"]

    # An entry can't be stored with a draft-only status.
    with pytest.raises(IntegrityError):
        async with session.begin_nested():
            await session.execute(
                text("UPDATE knowledge_entries SET status = 'pending' WHERE id = :id"),
                {"id": entries[0].id},
            )


async def test_every_approval_records_reviewer_and_timestamp(session, topic):
    draft = KnowledgeDraft(topic=topic, answer_text="Branch opens at 9am.")
    session.add(draft)
    entry = await approve(session, draft, reviewer="alex")
    await session.refresh(entry.approved_review)

    assert entry.status == EntryStatus.APPROVED
    assert entry.approved_review.reviewer == "alex"
    assert isinstance(entry.approved_review.reviewed_at, datetime)


async def test_entry_without_an_approval_is_rejected(session, topic):
    session.add(KnowledgeEntry(topic=topic, answer_text="No review"))
    with pytest.raises(IntegrityError):
        await session.flush()


async def test_review_requires_a_reviewer(session, topic):
    draft = KnowledgeDraft(topic=topic, answer_text="x")
    session.add(
        KnowledgeReview(draft=draft, action=ReviewAction.REJECTED, reviewer=None)
    )
    with pytest.raises(IntegrityError):
        await session.flush()


async def test_nearest_neighbour_search_returns_closest_entry(session, topic):
    for i, answer in enumerate(["alpha", "beta", "gamma"]):
        draft = KnowledgeDraft(topic=topic, answer_text=answer, embedding=one_hot(i))
        session.add(draft)
        await approve(session, draft)

    query = [0.0] * EMBEDDING_DIM
    query[1], query[2] = 0.9, 0.1

    nearest = (
        await session.scalars(
            select(KnowledgeEntry)
            .order_by(KnowledgeEntry.embedding.cosine_distance(query))
            .limit(2)
        )
    ).all()
    assert [e.answer_text for e in nearest] == ["beta", "gamma"]
