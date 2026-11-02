from datetime import datetime
from enum import StrEnum

from sqlalchemy import (
    Column,
    DateTime,
    ForeignKey,
    Table,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.core.database import Base
from backend.models.columns import str_enum
from backend.models.conversation import Conversation, Turn
from backend.models.knowledge import KnowledgeEntry


class FindingCategory(StrEnum):
    PROCEDURE = "procedure"
    ANSWER_SUPPORT = "answer_support"
    COMPLETENESS = "completeness"
    COMMUNICATION = "communication"


class FindingResult(StrEnum):
    PASS = "pass"
    NEEDS_WORK = "needs_work"
    # Not enough in the transcript to judge. Not a failure.
    CANNOT_ASSESS = "cannot_assess"


finding_evidence = Table(
    "finding_evidence",
    Base.metadata,
    Column(
        "finding_id", ForeignKey("findings.id", ondelete="CASCADE"), primary_key=True
    ),
    Column("turn_id", ForeignKey("turns.id", ondelete="CASCADE"), primary_key=True),
)


class Audit(Base):
    """The post-call audit of one conversation."""

    __tablename__ = "audits"

    id: Mapped[int] = mapped_column(primary_key=True)
    conversation_id: Mapped[int] = mapped_column(
        ForeignKey("conversations.id", ondelete="CASCADE"), unique=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    conversation: Mapped[Conversation] = relationship()
    findings: Mapped[list["Finding"]] = relationship(
        back_populates="audit", cascade="all, delete-orphan", order_by="Finding.id"
    )


class Finding(Base):
    __tablename__ = "findings"
    __table_args__ = (UniqueConstraint("audit_id", "category"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    audit_id: Mapped[int] = mapped_column(ForeignKey("audits.id", ondelete="CASCADE"))
    category: Mapped[FindingCategory] = mapped_column(
        str_enum(FindingCategory, "finding_category")
    )
    result: Mapped[FindingResult] = mapped_column(
        str_enum(FindingResult, "finding_result")
    )
    feedback: Mapped[str] = mapped_column(Text)
    # The approved entry this finding was checked against, if any.
    knowledge_entry_id: Mapped[int | None] = mapped_column(
        ForeignKey("knowledge_entries.id", ondelete="SET NULL"), index=True
    )

    audit: Mapped[Audit] = relationship(back_populates="findings")
    evidence: Mapped[list[Turn]] = relationship(
        secondary=finding_evidence, order_by=Turn.line_number
    )
    knowledge_entry: Mapped[KnowledgeEntry | None] = relationship()
