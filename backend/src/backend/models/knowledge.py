from datetime import datetime
from enum import StrEnum

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    Column,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
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
        ForeignKeyConstraint(
            ["organization_id", "topic_id"],
            ["topics.organization_id", "topics.id"],
        ),
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

    # Composite foreign keys share organization_id, so overlapping relationships
    # must tell SQLAlchemy that they coordinate writes to the same column.
    organization: Mapped[Organization] = relationship()
    topic: Mapped[Topic] = relationship(overlaps="organization")
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
