from datetime import datetime
from enum import StrEnum

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    Column,
    DateTime,
    ForeignKey,
    Index,
    String,
    Table,
    Text,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.core.database import Base
from backend.models.columns import str_enum
from backend.models.conversation import Conversation, Topic

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
    Column(
        "draft_id",
        ForeignKey("knowledge_drafts.id", ondelete="CASCADE"),
        primary_key=True,
    ),
    Column(
        "conversation_id",
        ForeignKey("conversations.id", ondelete="CASCADE"),
        primary_key=True,
    ),
)


class KnowledgeDraft(Base):
    """A candidate answer waiting on review. Never used for scoring."""

    __tablename__ = "knowledge_drafts"
    __table_args__ = (hnsw_index("knowledge_drafts"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    topic_id: Mapped[int] = mapped_column(ForeignKey("topics.id"), index=True)
    answer_text: Mapped[str] = mapped_column(Text)
    embedding: Mapped[list[float] | None] = mapped_column(Vector(EMBEDDING_DIM))
    status: Mapped[DraftStatus] = mapped_column(
        str_enum(DraftStatus, "draft_status"), default=DraftStatus.PENDING
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    topic: Mapped[Topic] = relationship()
    supporting_conversations: Mapped[list[Conversation]] = relationship(
        secondary=knowledge_draft_conversations
    )
    reviews: Mapped[list["KnowledgeReview"]] = relationship(
        back_populates="draft", order_by="KnowledgeReview.reviewed_at"
    )


class KnowledgeReview(Base):
    """A reviewer's decision on a draft."""

    __tablename__ = "knowledge_reviews"

    id: Mapped[int] = mapped_column(primary_key=True)
    draft_id: Mapped[int] = mapped_column(ForeignKey("knowledge_drafts.id"), index=True)
    action: Mapped[ReviewAction] = mapped_column(
        str_enum(ReviewAction, "review_action")
    )
    reviewer: Mapped[str] = mapped_column(String(200))
    reviewed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    note: Mapped[str | None] = mapped_column(Text)

    draft: Mapped[KnowledgeDraft] = relationship(back_populates="reviews")


class KnowledgeEntry(Base):
    """An approved baseline answer. The only knowledge used for scoring."""

    __tablename__ = "knowledge_entries"
    __table_args__ = (hnsw_index("knowledge_entries"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    topic_id: Mapped[int] = mapped_column(ForeignKey("topics.id"), index=True)
    answer_text: Mapped[str] = mapped_column(Text)
    embedding: Mapped[list[float] | None] = mapped_column(Vector(EMBEDDING_DIM))
    status: Mapped[EntryStatus] = mapped_column(
        str_enum(EntryStatus, "entry_status"), default=EntryStatus.APPROVED
    )
    support_count: Mapped[int] = mapped_column(default=0, server_default="0")
    last_confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # Required, so every entry traces back to a recorded reviewer and timestamp.
    approved_review_id: Mapped[int] = mapped_column(
        ForeignKey("knowledge_reviews.id"), unique=True
    )

    topic: Mapped[Topic] = relationship()
    approved_review: Mapped[KnowledgeReview] = relationship()
