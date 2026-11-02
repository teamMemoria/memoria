from datetime import datetime
from enum import StrEnum
from typing import TYPE_CHECKING

from sqlalchemy import (
    Column,
    DateTime,
    ForeignKey,
    String,
    Table,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.core.database import Base
from backend.models.columns import str_enum
from backend.models.conversation import Agent, Conversation, Turn
from backend.models.knowledge import KnowledgeEntry

if TYPE_CHECKING:
    from backend.models.evaluation import EvaluationFormVersion


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


class ManagerReviewOutcome(StrEnum):
    CONFIRMED = "confirmed"
    CORRECTED = "corrected"
    DISMISSED = "dismissed"
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
    evaluation_form_version_id: Mapped[int] = mapped_column(
        ForeignKey("evaluation_form_versions.id", ondelete="RESTRICT"), index=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    # The report's plain-language summary, when the analysis produced one.
    summary: Mapped[str | None] = mapped_column(Text)

    conversation: Mapped[Conversation] = relationship()
    evaluation_form_version: Mapped["EvaluationFormVersion"] = relationship()
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
    # What the agent could do differently; only needs-work findings have one.
    suggestion: Mapped[str | None] = mapped_column(Text)
    # The approved entry this finding was checked against, if any.
    knowledge_entry_id: Mapped[int | None] = mapped_column(
        ForeignKey("knowledge_entries.id", ondelete="SET NULL"), index=True
    )

    audit: Mapped[Audit] = relationship(back_populates="findings")
    evidence: Mapped[list[Turn]] = relationship(
        secondary=finding_evidence, order_by=Turn.line_number
    )
    knowledge_entry: Mapped[KnowledgeEntry | None] = relationship()
    feedback_flag: Mapped["FeedbackFlag | None"] = relationship(
        back_populates="finding", cascade="all, delete-orphan", uselist=False
    )


class FeedbackFlag(Base):
    """An Agent's request for a Manager to review an automated finding."""

    __tablename__ = "feedback_flags"

    id: Mapped[int] = mapped_column(primary_key=True)
    finding_id: Mapped[int] = mapped_column(
        ForeignKey("findings.id", ondelete="CASCADE"), unique=True
    )
    agent_id: Mapped[int] = mapped_column(ForeignKey("agents.id"), index=True)
    reason: Mapped[str] = mapped_column(Text)
    agent_context: Mapped[str | None] = mapped_column(Text)
    flagged_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    finding: Mapped[Finding] = relationship(back_populates="feedback_flag")
    agent: Mapped[Agent] = relationship()
    manager_review: Mapped["ManagerReview | None"] = relationship(
        back_populates="feedback_flag", cascade="all, delete-orphan", uselist=False
    )


class ManagerReview(Base):
    """A Manager's decision on a flag, separate from the automated finding."""

    __tablename__ = "manager_reviews"

    id: Mapped[int] = mapped_column(primary_key=True)
    feedback_flag_id: Mapped[int] = mapped_column(
        ForeignKey("feedback_flags.id", ondelete="CASCADE"), unique=True
    )
    outcome: Mapped[ManagerReviewOutcome] = mapped_column(
        str_enum(ManagerReviewOutcome, "manager_review_outcome")
    )
    reviewer: Mapped[str] = mapped_column(String(200))
    reason: Mapped[str] = mapped_column(Text)
    feedback: Mapped[str] = mapped_column(Text)
    reviewed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    feedback_flag: Mapped[FeedbackFlag] = relationship(back_populates="manager_review")
