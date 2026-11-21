"""add analysis runs

One row per attempt to analyse a conversation, so processing status and
technical failures are recorded apart from the audit they may produce. A partial
unique index allows only one queued or running attempt per conversation.
Audits gain the report summary and findings gain the suggestion text.

Revision ID: 5b2d9f4e6c13
Revises: 3e8c1b5d7a20
Create Date: 2026-11-02
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "5b2d9f4e6c13"
down_revision: str | Sequence[str] | None = "3e8c1b5d7a20"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "analysis_runs",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("organization_id", sa.Integer(), nullable=False),
        sa.Column("conversation_id", sa.Integer(), nullable=False),
        sa.Column(
            "status",
            sa.Enum(
                "queued",
                "running",
                "succeeded",
                "failed",
                name="analysis_run_status",
                native_enum=False,
                create_constraint=True,
                length=20,
            ),
            nullable=False,
        ),
        sa.Column("attempt", sa.Integer(), nullable=False),
        sa.Column("requested_by", sa.String(length=100), nullable=True),
        sa.Column("error_code", sa.String(length=50), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("transcript_version", sa.String(length=100), nullable=True),
        sa.Column("report_version", sa.String(length=100), nullable=True),
        sa.Column("audit_id", sa.Integer(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("attempt > 0", name="ck_analysis_run_attempt_positive"),
        sa.CheckConstraint(
            "(status = 'failed') = (error_code IS NOT NULL)",
            name="ck_analysis_run_failure_has_code",
        ),
        sa.CheckConstraint(
            "(status = 'succeeded') = (audit_id IS NOT NULL)",
            name="ck_analysis_run_success_has_audit",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"], ["organizations.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["organization_id", "conversation_id"],
            ["conversations.organization_id", "conversations.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(["audit_id"], ["audits.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("conversation_id", "attempt"),
    )
    op.create_index(
        op.f("ix_analysis_runs_conversation_id"),
        "analysis_runs",
        ["conversation_id"],
        unique=False,
    )
    op.create_index(
        "uq_analysis_runs_one_active_per_conversation",
        "analysis_runs",
        ["conversation_id"],
        unique=True,
        postgresql_where=sa.text("status IN ('queued', 'running')"),
    )
    op.add_column("audits", sa.Column("summary", sa.Text(), nullable=True))
    op.add_column("findings", sa.Column("suggestion", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("findings", "suggestion")
    op.drop_column("audits", "summary")
    op.drop_index(
        "uq_analysis_runs_one_active_per_conversation", table_name="analysis_runs"
    )
    op.drop_index(op.f("ix_analysis_runs_conversation_id"), table_name="analysis_runs")
    op.drop_table("analysis_runs")
