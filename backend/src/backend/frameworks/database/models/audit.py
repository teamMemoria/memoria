from datetime import datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import (
    CheckConstraint,
    Column,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    Table,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.core.database import Base
from backend.entities.results import (
    FindingCategory,
    FindingResult,
    ManagerReviewOutcome,
)
from backend.frameworks.database.models.columns import str_enum
from backend.frameworks.database.models.conversation import Agent, Conversation, Turn
from backend.frameworks.database.models.knowledge import KnowledgeEntry
from backend.frameworks.database.models.organization import (
    Organization,
    OrganizationMembership,
)

if TYPE_CHECKING:
    from backend.frameworks.database.models.evaluation import EvaluationFormVersion


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
    __table_args__ = (
        UniqueConstraint("organization_id", "id"),
        ForeignKeyConstraint(
            ["organization_id", "conversation_id"],
            ["conversations.organization_id", "conversations.id"],
            ondelete="CASCADE",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), index=True
    )
    conversation_id: Mapped[int] = mapped_column(unique=True)
    evaluation_form_version_id: Mapped[int] = mapped_column(
        ForeignKey("evaluation_form_versions.id", ondelete="RESTRICT"), index=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    # The report's plain-language summary, when the analysis produced one.
    summary: Mapped[str | None] = mapped_column(Text)
    assessment_report: Mapped[dict[str, Any] | None] = mapped_column(JSONB)

    # Composite foreign keys share organization_id across these relationships.
    organization: Mapped[Organization] = relationship(overlaps="conversation")
    conversation: Mapped[Conversation] = relationship(overlaps="organization")
    evaluation_form_version: Mapped["EvaluationFormVersion"] = relationship()
    findings: Mapped[list["Finding"]] = relationship(
        back_populates="audit",
        cascade="all, delete-orphan",
        order_by="Finding.id",
        overlaps="organization",
    )


class Finding(Base):
    __tablename__ = "findings"
    __table_args__ = (
        UniqueConstraint("audit_id", "category"),
        UniqueConstraint("organization_id", "id"),
        ForeignKeyConstraint(
            ["organization_id", "audit_id"],
            ["audits.organization_id", "audits.id"],
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["organization_id", "knowledge_entry_id"],
            ["knowledge_entries.organization_id", "knowledge_entries.id"],
            ondelete="SET NULL (knowledge_entry_id)",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), index=True
    )
    audit_id: Mapped[int] = mapped_column()
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
    knowledge_entry_id: Mapped[int | None] = mapped_column(Integer, index=True)

    organization: Mapped[Organization] = relationship(
        overlaps="audit,findings,knowledge_entry"
    )
    audit: Mapped[Audit] = relationship(
        back_populates="findings", overlaps="organization"
    )
    evidence: Mapped[list[Turn]] = relationship(
        secondary=finding_evidence, order_by=Turn.line_number
    )
    knowledge_entry: Mapped[KnowledgeEntry | None] = relationship(
        overlaps="audit,findings,organization"
    )
    feedback_flags: Mapped[list["FeedbackFlag"]] = relationship(
        back_populates="finding",
        cascade="all, delete-orphan",
        order_by="FeedbackFlag.id",
        overlaps="organization,audit",
    )

    @property
    def feedback_flag(self) -> "FeedbackFlag | None":
        """The latest request, preserving the existing call/review read contract."""
        return self.feedback_flags[-1] if self.feedback_flags else None


class FeedbackFlag(Base):
    """An Agent's request for a Manager to review an automated finding."""

    __tablename__ = "feedback_flags"
    __table_args__ = (
        CheckConstraint(
            "status IN ('open', 'resolved')", name="ck_feedback_flags_status"
        ),
        CheckConstraint(
            "(status = 'resolved') = (resolved_at IS NOT NULL)",
            name="ck_feedback_flags_resolved_at",
        ),
        Index(
            "uq_feedback_flags_open_finding",
            "finding_id",
            unique=True,
            postgresql_where=text("status = 'open'"),
        ),
        UniqueConstraint("organization_id", "id"),
        ForeignKeyConstraint(
            ["organization_id", "finding_id"],
            ["findings.organization_id", "findings.id"],
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["organization_id", "agent_id"],
            ["agents.organization_id", "agents.id"],
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), index=True
    )
    finding_id: Mapped[int] = mapped_column(index=True)
    agent_id: Mapped[int] = mapped_column(index=True)
    reason: Mapped[str] = mapped_column(Text)
    agent_context: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(
        String(20), default="open", server_default="open"
    )
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    flagged_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    organization: Mapped[Organization] = relationship(overlaps="finding,agent")
    finding: Mapped[Finding] = relationship(
        back_populates="feedback_flags", overlaps="organization,agent,feedback_flags"
    )
    agent: Mapped[Agent] = relationship(overlaps="organization,finding,feedback_flags")
    manager_review: Mapped["ManagerReview | None"] = relationship(
        back_populates="feedback_flag",
        cascade="all, delete-orphan",
        uselist=False,
        overlaps="organization",
    )


class AgentContext(Base):
    """An agent's own note on one of their calls.

    Kept apart from FeedbackFlag on purpose: saving context never requests a
    Manager review. A flag copies the context as it was when the flag was raised.
    """

    __tablename__ = "agent_contexts"
    __table_args__ = (
        CheckConstraint("length(btrim(text)) > 0", name="ck_agent_context_text"),
        ForeignKeyConstraint(
            ["organization_id", "conversation_id"],
            ["conversations.organization_id", "conversations.id"],
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["organization_id", "agent_id"],
            ["agents.organization_id", "agents.id"],
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE")
    )
    conversation_id: Mapped[int] = mapped_column(unique=True)
    agent_id: Mapped[int]
    text: Mapped[str] = mapped_column(Text)
    saved_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class ManagerReview(Base):
    """A Manager's decision on a flag, separate from the automated finding."""

    __tablename__ = "manager_reviews"
    __table_args__ = (
        ForeignKeyConstraint(
            ["organization_id", "feedback_flag_id"],
            ["feedback_flags.organization_id", "feedback_flags.id"],
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["organization_id", "reviewer_membership_id"],
            ["organization_memberships.organization_id", "organization_memberships.id"],
        ),
        CheckConstraint(
            "(outcome = 'corrected') = (reviewed_result IS NOT NULL)",
            name="ck_manager_reviews_corrected_result",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), index=True
    )
    feedback_flag_id: Mapped[int] = mapped_column(unique=True)
    outcome: Mapped[ManagerReviewOutcome] = mapped_column(
        str_enum(ManagerReviewOutcome, "manager_review_outcome")
    )
    reviewed_result: Mapped[FindingResult | None] = mapped_column(
        str_enum(FindingResult, "finding_result")
    )
    reviewer_membership_id: Mapped[int] = mapped_column(index=True)
    reason: Mapped[str] = mapped_column(Text)
    feedback: Mapped[str] = mapped_column(Text)
    reviewed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    organization: Mapped[Organization] = relationship(
        overlaps="feedback_flag,reviewer_membership"
    )
    feedback_flag: Mapped[FeedbackFlag] = relationship(
        back_populates="manager_review", overlaps="organization,reviewer_membership"
    )
    reviewer_membership: Mapped[OrganizationMembership] = relationship(
        overlaps="organization,feedback_flag,manager_review"
    )


__all__ = ["FindingCategory", "FindingResult", "ManagerReviewOutcome"]
