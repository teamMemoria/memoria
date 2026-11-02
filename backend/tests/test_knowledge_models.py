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
    Organization,
    OrganizationMembership,
    ReviewAction,
    Topic,
    User,
    UserRole,
)


def one_hot(i: int) -> list[float]:
    v = [0.0] * EMBEDDING_DIM
    v[i] = 1.0
    return v


@pytest.fixture
async def organization(session):
    value = Organization(slug="northwind", name="Northwind Support")
    session.add(value)
    await session.flush()
    return value


@pytest.fixture
async def topic(session, organization):
    t = Topic(
        organization=organization,
        source_dataset="HarperValleyBank",
        name="Card replacement",
    )
    session.add(t)
    await session.flush()
    return t


@pytest.fixture
async def manager_membership(session, organization):
    membership = OrganizationMembership(
        organization=organization,
        user=User(external_id="manager-maya", display_name="Maya Chen"),
        role=UserRole.MANAGER,
    )
    session.add(membership)
    await session.flush()
    return membership


async def approve(
    session,
    draft: KnowledgeDraft,
    reviewer_membership: OrganizationMembership,
):
    review = KnowledgeReview(
        organization=draft.organization,
        draft=draft,
        action=ReviewAction.APPROVED,
        reviewer_membership=reviewer_membership,
    )
    draft.status = DraftStatus.APPROVED
    entry = KnowledgeEntry(
        organization=draft.organization,
        topic=draft.topic,
        answer_text=draft.answer_text,
        embedding=draft.embedding,
        approved_review=review,
    )
    session.add(entry)
    await session.flush()
    return entry


async def test_draft_keeps_its_supporting_conversations(session, topic):
    agent = Agent(organization=topic.organization, external_id="hvb-speaker-1")
    conversations = [
        Conversation(
            organization=topic.organization,
            source_dataset="HarperValleyBank",
            original_id=str(i),
            channel="voice",
            agent=agent,
        )
        for i in range(3)
    ]
    draft = KnowledgeDraft(
        organization=topic.organization,
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


async def test_drafts_and_entries_cannot_be_confused(
    session, topic, manager_membership
):
    session.add(
        KnowledgeDraft(
            organization=topic.organization,
            topic=topic,
            answer_text="Unapproved draft",
        )
    )
    approved_draft = KnowledgeDraft(
        organization=topic.organization, topic=topic, answer_text="Approved answer"
    )
    session.add(approved_draft)
    await approve(session, approved_draft, manager_membership)

    entries = (await session.scalars(select(KnowledgeEntry))).all()
    assert [e.answer_text for e in entries] == ["Approved answer"]

    # An entry can't be stored with a draft-only status.
    with pytest.raises(IntegrityError):
        async with session.begin_nested():
            await session.execute(
                text("UPDATE knowledge_entries SET status = 'pending' WHERE id = :id"),
                {"id": entries[0].id},
            )


async def test_every_approval_records_reviewer_and_timestamp(
    session, topic, manager_membership
):
    draft = KnowledgeDraft(
        organization=topic.organization,
        topic=topic,
        answer_text="Branch opens at 9am.",
    )
    session.add(draft)
    entry = await approve(session, draft, manager_membership)
    await session.refresh(entry.approved_review)

    assert entry.status == EntryStatus.APPROVED
    assert entry.approved_review.reviewer_membership_id == manager_membership.id
    assert isinstance(entry.approved_review.reviewed_at, datetime)


async def test_entry_without_an_approval_is_rejected(session, topic):
    session.add(
        KnowledgeEntry(
            organization=topic.organization, topic=topic, answer_text="No review"
        )
    )
    with pytest.raises(IntegrityError):
        await session.flush()


async def test_review_requires_a_reviewer(session, topic):
    draft = KnowledgeDraft(
        organization=topic.organization, topic=topic, answer_text="x"
    )
    session.add(
        KnowledgeReview(
            organization=topic.organization,
            draft=draft,
            action=ReviewAction.REJECTED,
            reviewer_membership=None,
        )
    )
    with pytest.raises(IntegrityError):
        await session.flush()


async def test_nearest_neighbour_search_returns_closest_entry(
    session, topic, manager_membership
):
    for i, answer in enumerate(["alpha", "beta", "gamma"]):
        draft = KnowledgeDraft(
            organization=topic.organization,
            topic=topic,
            answer_text=answer,
            embedding=one_hot(i),
        )
        session.add(draft)
        await approve(session, draft, manager_membership)

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
