"""add feedback flags and manager reviews

Revision ID: c75d2d9e41af
Revises: aa37b6c1d0e2
Create Date: 2026-11-02
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "c75d2d9e41af"
down_revision: str | Sequence[str] | None = "aa37b6c1d0e2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "feedback_flags",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("finding_id", sa.Integer(), nullable=False),
        sa.Column("agent_id", sa.Integer(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("agent_context", sa.Text(), nullable=True),
        sa.Column(
            "flagged_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["agent_id"], ["agents.id"]),
        sa.ForeignKeyConstraint(["finding_id"], ["findings.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("finding_id"),
    )
    op.create_index(
        op.f("ix_feedback_flags_agent_id"),
        "feedback_flags",
        ["agent_id"],
        unique=False,
    )
    op.create_table(
        "manager_reviews",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("feedback_flag_id", sa.Integer(), nullable=False),
        sa.Column(
            "outcome",
            sa.Enum(
                "confirmed",
                "corrected",
                "dismissed",
                "cannot_assess",
                name="manager_review_outcome",
                native_enum=False,
                create_constraint=True,
                length=20,
            ),
            nullable=False,
        ),
        sa.Column(
            "reviewed_result",
            sa.Enum(
                "pass",
                "needs_work",
                "cannot_assess",
                name="finding_result",
                native_enum=False,
                create_constraint=True,
                length=20,
            ),
            nullable=True,
        ),
        sa.Column("reviewer", sa.String(length=200), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("feedback", sa.Text(), nullable=False),
        sa.Column(
            "reviewed_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["feedback_flag_id"], ["feedback_flags.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint(
            "(outcome = 'corrected') = (reviewed_result IS NOT NULL)",
            name="ck_manager_reviews_corrected_result",
        ),
        sa.UniqueConstraint("feedback_flag_id"),
    )


def downgrade() -> None:
    op.drop_table("manager_reviews")
    op.drop_index(op.f("ix_feedback_flags_agent_id"), table_name="feedback_flags")
    op.drop_table("feedback_flags")
