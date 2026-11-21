"""add performance trend index

Revision ID: aa37b6c1d0e2
Revises: 4024e756007c
Create Date: 2026-11-02

"""

from collections.abc import Sequence

from alembic import op

revision: str = "aa37b6c1d0e2"
down_revision: str | Sequence[str] | None = "4024e756007c"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_index(
        "ix_conversations_agent_started_topic",
        "conversations",
        ["agent_id", "synthetic_started_at", "topic_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_conversations_agent_started_topic", table_name="conversations")
