from datetime import datetime
from enum import StrEnum
from typing import Any

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.core.database import Base
from backend.models.audit import Audit
from backend.models.columns import str_enum
from backend.models.conversation import Conversation


class AnalysisRunStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    # A technical failure. It never becomes a cannot-assess result.
    FAILED = "failed"


ACTIVE_RUN_STATUSES = (AnalysisRunStatus.QUEUED, AnalysisRunStatus.RUNNING)


class AnalysisRun(Base):
    """One attempt to analyse a conversation, kept even when it fails."""

    __tablename__ = "analysis_runs"
    __table_args__ = (
        CheckConstraint("attempt > 0", name="ck_analysis_run_attempt_positive"),
        CheckConstraint(
            "(status = 'failed') = (error_code IS NOT NULL)",
            name="ck_analysis_run_failure_has_code",
        ),
        CheckConstraint(
            "(status = 'succeeded') = (audit_id IS NOT NULL)",
            name="ck_analysis_run_success_has_audit",
        ),
        ForeignKeyConstraint(
            ["organization_id", "conversation_id"],
            ["conversations.organization_id", "conversations.id"],
            ondelete="CASCADE",
        ),
        UniqueConstraint("conversation_id", "attempt"),
        Index(
            "uq_analysis_runs_one_active_per_conversation",
            "conversation_id",
            unique=True,
            postgresql_where=text("status IN ('queued', 'running')"),
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE")
    )
    conversation_id: Mapped[int] = mapped_column(index=True)
    status: Mapped[AnalysisRunStatus] = mapped_column(
        str_enum(AnalysisRunStatus, "analysis_run_status")
    )
    attempt: Mapped[int]
    # User ID of whoever asked for the run; None for system-started runs.
    requested_by: Mapped[str | None] = mapped_column(String(100))
    error_code: Mapped[str | None] = mapped_column(String(50))
    error_message: Mapped[str | None] = mapped_column(Text)
    # The evidence and report versions the run used, for reproducing it later.
    transcript_version: Mapped[str | None] = mapped_column(String(100))
    report_version: Mapped[str | None] = mapped_column(String(100))
    assessment_report: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    audit_id: Mapped[int | None] = mapped_column(
        ForeignKey("audits.id", ondelete="RESTRICT")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    conversation: Mapped[Conversation] = relationship()
    audit: Mapped[Audit | None] = relationship()
