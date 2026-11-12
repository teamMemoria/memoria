from datetime import datetime
from decimal import Decimal
from enum import StrEnum

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    CheckConstraint,
    Column,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    Numeric,
    String,
    Table,
    Text,
    UniqueConstraint,
    and_,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.core.database import Base
from backend.models.columns import str_enum
from backend.models.conversation import Conversation, Topic
from backend.models.organization import Organization, OrganizationMembership

# Placeholder until the embedding model is chosen; changing it needs a migration.
EMBEDDING_DIM = 1536


def hnsw_index(table: str) -> Index:
    return Index(
        f"ix_{table}_embedding_hnsw",
        "embedding",
        postgresql_using="hnsw",
        postgresql_ops={"embedding": "vector_cosine_ops"},
    )


class EntryStatus(StrEnum):
    APPROVED = "approved"
    DISPUTED = "disputed"
    STALE = "stale"


class DraftStatus(StrEnum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"


class ReviewAction(StrEnum):
    APPROVED = "approved"
    EDITED = "edited"
    REJECTED = "rejected"


knowledge_draft_conversations = Table(
    "knowledge_draft_conversations",
    Base.metadata,
    Column("organization_id", Integer, primary_key=True),
    Column("draft_id", Integer, primary_key=True),
    Column("conversation_id", Integer, primary_key=True),
    ForeignKeyConstraint(
        ["organization_id", "draft_id"],
        ["knowledge_drafts.organization_id", "knowledge_drafts.id"],
        ondelete="CASCADE",
    ),
    ForeignKeyConstraint(
        ["organization_id", "conversation_id"],
        ["conversations.organization_id", "conversations.id"],
        ondelete="CASCADE",
    ),
)


class KnowledgeDraft(Base):
    """A candidate answer waiting on review. Never used for scoring."""

    __tablename__ = "knowledge_drafts"
    __table_args__ = (
        hnsw_index("knowledge_drafts"),
        UniqueConstraint("organization_id", "id"),
        UniqueConstraint(
            "organization_id", "source_key", name="uq_knowledge_drafts_source_key"
        ),
        ForeignKeyConstraint(
            ["organization_id", "topic_id"],
            ["topics.organization_id", "topics.id"],
        ),
        ForeignKeyConstraint(
            ["organization_id", "duplicate_of_id"],
            ["knowledge_drafts.organization_id", "knowledge_drafts.id"],
            name="fk_knowledge_drafts_duplicate_of",
        ),
        Index("ix_knowledge_drafts_group_key", "organization_id", "group_key"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), index=True
    )
    topic_id: Mapped[int] = mapped_column(index=True)
    answer_text: Mapped[str] = mapped_column(Text)
    embedding: Mapped[list[float] | None] = mapped_column(Vector(EMBEDDING_DIM))
    status: Mapped[DraftStatus] = mapped_column(
        str_enum(DraftStatus, "draft_status"), default=DraftStatus.PENDING
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    # Set for drafts imported from the knowledge pipeline: its draft ID, so
    # importing the same output again updates the row instead of adding one.
    source_key: Mapped[str | None] = mapped_column(String(100))
    question: Mapped[str | None] = mapped_column(Text)
    # The pipeline's grouping of similar drafts, replaced on every import.
    group_key: Mapped[str | None] = mapped_column(String(100))
    duplicate_of_id: Mapped[int | None] = mapped_column()
    duplicate_similarity: Mapped[Decimal | None] = mapped_column(Numeric(5, 4))
    # The pipeline's own reading of its references. A hint for the reviewer;
    # it never approves anything or confirms an entry.
    ml_verification: Mapped[str | None] = mapped_column(String(30))
    updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    # Composite foreign keys share organization_id, so overlapping relationships
    # must tell SQLAlchemy that they coordinate writes to the same column.
    organization: Mapped[Organization] = relationship()
    topic: Mapped[Topic] = relationship(overlaps="organization")
    passages: Mapped[list["KnowledgeDraftPassage"]] = relationship(
        back_populates="draft",
        cascade="all, delete-orphan",
        order_by="(KnowledgeDraftPassage.role, KnowledgeDraftPassage.position)",
        overlaps="organization",
    )
    supporting_conversations: Mapped[list[Conversation]] = relationship(
        secondary=knowledge_draft_conversations,
        primaryjoin=lambda: and_(
            KnowledgeDraft.organization_id
            == knowledge_draft_conversations.c.organization_id,
            KnowledgeDraft.id == knowledge_draft_conversations.c.draft_id,
        ),
        secondaryjoin=lambda: and_(
            Conversation.organization_id
            == knowledge_draft_conversations.c.organization_id,
            Conversation.id == knowledge_draft_conversations.c.conversation_id,
        ),
    )
    reviews: Mapped[list["KnowledgeReview"]] = relationship(
        back_populates="draft",
        order_by="KnowledgeReview.reviewed_at",
        overlaps="organization,reviewer_membership",
    )


class KnowledgeReview(Base):
    """A reviewer's decision on a draft."""

    __tablename__ = "knowledge_reviews"

    __table_args__ = (
        UniqueConstraint("organization_id", "id"),
        ForeignKeyConstraint(
            ["organization_id", "draft_id"],
            ["knowledge_drafts.organization_id", "knowledge_drafts.id"],
        ),
        ForeignKeyConstraint(
            ["organization_id", "reviewer_membership_id"],
            [
                "organization_memberships.organization_id",
                "organization_memberships.id",
            ],
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), index=True
    )
    draft_id: Mapped[int] = mapped_column(index=True)
    action: Mapped[ReviewAction] = mapped_column(
        str_enum(ReviewAction, "review_action")
    )
    reviewer_membership_id: Mapped[int] = mapped_column(index=True)
    reviewed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    note: Mapped[str | None] = mapped_column(Text)

    organization: Mapped[Organization] = relationship(
        overlaps="draft,reviews,reviewer_membership"
    )
    reviewer_membership: Mapped[OrganizationMembership] = relationship(
        overlaps="draft,organization,reviews"
    )
    draft: Mapped[KnowledgeDraft] = relationship(
        back_populates="reviews", overlaps="organization,reviewer_membership"
    )


class KnowledgeEntry(Base):
    """An approved baseline answer. The only knowledge used for scoring."""

    __tablename__ = "knowledge_entries"
    __table_args__ = (
        hnsw_index("knowledge_entries"),
        UniqueConstraint("organization_id", "id"),
        UniqueConstraint("organization_id", "approved_review_id"),
        ForeignKeyConstraint(
            ["organization_id", "topic_id"],
            ["topics.organization_id", "topics.id"],
        ),
        ForeignKeyConstraint(
            ["organization_id", "approved_review_id"],
            ["knowledge_reviews.organization_id", "knowledge_reviews.id"],
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), index=True
    )
    topic_id: Mapped[int] = mapped_column(index=True)
    answer_text: Mapped[str] = mapped_column(Text)
    embedding: Mapped[list[float] | None] = mapped_column(Vector(EMBEDDING_DIM))
    status: Mapped[EntryStatus] = mapped_column(
        str_enum(EntryStatus, "entry_status"), default=EntryStatus.APPROVED
    )
    support_count: Mapped[int] = mapped_column(default=0, server_default="0")
    last_confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # Required, so every entry traces back to a recorded reviewer and timestamp.
    approved_review_id: Mapped[int] = mapped_column()

    organization: Mapped[Organization] = relationship()
    topic: Mapped[Topic] = relationship(overlaps="organization")
    approved_review: Mapped[KnowledgeReview] = relationship(
        overlaps="organization,topic"
    )


class KnowledgeDraftPassage(Base):
    """A passage the pipeline quoted from a conversation, with its source version."""

    __tablename__ = "knowledge_draft_passages"
    __table_args__ = (
        CheckConstraint(
            "role IN ('question', 'answer', 'condition')",
            name="ck_knowledge_draft_passage_role",
        ),
        CheckConstraint(
            "span_start >= 0 AND span_end > span_start",
            name="ck_knowledge_draft_passage_span",
        ),
        ForeignKeyConstraint(
            ["organization_id", "draft_id"],
            ["knowledge_drafts.organization_id", "knowledge_drafts.id"],
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["organization_id", "conversation_id"],
            ["conversations.organization_id", "conversations.id"],
            ondelete="CASCADE",
        ),
        UniqueConstraint("draft_id", "role", "position"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int]
    draft_id: Mapped[int]
    conversation_id: Mapped[int]
    role: Mapped[str] = mapped_column(String(20))
    position: Mapped[int]
    # Original turn number and speaker, as in the stored transcript.
    turn_number: Mapped[int]
    speaker: Mapped[str] = mapped_column(String(20))
    quote: Mapped[str] = mapped_column(Text)
    span_start: Mapped[int]
    span_end: Mapped[int]
    source_key: Mapped[str] = mapped_column(String(200))
    source_version: Mapped[str] = mapped_column(String(100))

    draft: Mapped[KnowledgeDraft] = relationship(
        back_populates="passages", overlaps="passages"
    )


class KnowledgeDraftEntryMatch(Base):
    """An approved entry the pipeline found similar to a draft."""

    __tablename__ = "knowledge_draft_entry_matches"
    __table_args__ = (
        ForeignKeyConstraint(
            ["organization_id", "draft_id"],
            ["knowledge_drafts.organization_id", "knowledge_drafts.id"],
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["organization_id", "entry_id"],
            ["knowledge_entries.organization_id", "knowledge_entries.id"],
            ondelete="CASCADE",
        ),
    )

    organization_id: Mapped[int] = mapped_column(primary_key=True)
    draft_id: Mapped[int] = mapped_column(primary_key=True)
    entry_id: Mapped[int] = mapped_column(primary_key=True)
    kind: Mapped[str] = mapped_column(String(30))
    similarity: Mapped[Decimal] = mapped_column(Numeric(5, 4))


class KnowledgeConflict(Base):
    """A possible conflict the pipeline found. Not a confirmed dispute.

    Only a reviewer marks an approved entry disputed; storing this never
    changes an entry's status or removes it from use.
    """

    __tablename__ = "knowledge_conflicts"
    __table_args__ = (
        CheckConstraint(
            "status IN ('possible_conflict', 'unresolved')",
            name="ck_knowledge_conflict_status",
        ),
        CheckConstraint(
            "(other_draft_id IS NULL) <> (other_entry_id IS NULL)",
            name="ck_knowledge_conflict_one_other_side",
        ),
        ForeignKeyConstraint(
            ["organization_id", "draft_id"],
            ["knowledge_drafts.organization_id", "knowledge_drafts.id"],
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["organization_id", "other_draft_id"],
            ["knowledge_drafts.organization_id", "knowledge_drafts.id"],
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["organization_id", "other_entry_id"],
            ["knowledge_entries.organization_id", "knowledge_entries.id"],
            ondelete="CASCADE",
        ),
        UniqueConstraint("organization_id", "source_key"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE")
    )
    # The pipeline's conflict ID.
    source_key: Mapped[str] = mapped_column(String(100))
    kind: Mapped[str] = mapped_column(String(30))
    status: Mapped[str] = mapped_column(String(30))
    explanation: Mapped[str] = mapped_column(Text)
    draft_id: Mapped[int]
    other_draft_id: Mapped[int | None]
    other_entry_id: Mapped[int | None]
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
