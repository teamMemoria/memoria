"""add conversation metrics

Revision ID: ca38f73b9d21
Revises: 84b37f614ac2
Create Date: 2026-11-02 12:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "ca38f73b9d21"
down_revision: str | Sequence[str] | None = "84b37f614ac2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "conversation_metrics",
        sa.Column("conversation_id", sa.Integer(), nullable=False),
        sa.Column("turn_count", sa.Integer(), nullable=False),
        sa.Column("agent_word_count", sa.Integer(), nullable=False),
        sa.Column("customer_word_count", sa.Integer(), nullable=False),
        sa.Column("agent_text_share", sa.Float(), nullable=True),
        sa.Column("customer_text_share", sa.Float(), nullable=True),
        sa.Column("call_elapsed_ms", sa.Integer(), nullable=True),
        sa.Column("agent_speaking_ms", sa.Integer(), nullable=True),
        sa.Column("customer_speaking_ms", sa.Integer(), nullable=True),
        sa.Column("average_turn_duration_ms", sa.Float(), nullable=True),
        sa.Column("asr_word_error_rate", sa.Float(), nullable=True),
        sa.Column("asr_compared_turn_count", sa.Integer(), nullable=True),
        sa.Column("system_action_count", sa.Integer(), nullable=True),
        sa.Column("documented_action_count", sa.Integer(), nullable=True),
        sa.CheckConstraint("agent_text_share BETWEEN 0 AND 1"),
        sa.CheckConstraint("agent_word_count >= 0"),
        sa.CheckConstraint("agent_speaking_ms >= 0"),
        sa.CheckConstraint("asr_compared_turn_count >= 0"),
        sa.CheckConstraint("asr_word_error_rate >= 0"),
        sa.CheckConstraint("average_turn_duration_ms >= 0"),
        sa.CheckConstraint("call_elapsed_ms >= 0"),
        sa.CheckConstraint("customer_text_share BETWEEN 0 AND 1"),
        sa.CheckConstraint("customer_word_count >= 0"),
        sa.CheckConstraint("customer_speaking_ms >= 0"),
        sa.CheckConstraint("documented_action_count >= 0"),
        sa.CheckConstraint("system_action_count >= 0"),
        sa.CheckConstraint("turn_count >= 0"),
        sa.ForeignKeyConstraint(
            ["conversation_id"], ["conversations.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("conversation_id"),
    )


def downgrade() -> None:
    op.drop_table("conversation_metrics")
