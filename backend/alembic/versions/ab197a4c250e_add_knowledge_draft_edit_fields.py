"""Separate Manager draft labels and questions from imported source fields."""

import sqlalchemy as sa

from alembic import op

revision = "ab197a4c250e"
down_revision = "5b92ee84d4b6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("knowledge_drafts", sa.Column("title", sa.String(140)))
    op.add_column("knowledge_drafts", sa.Column("edited_question", sa.String(600)))


def downgrade() -> None:
    op.drop_column("knowledge_drafts", "edited_question")
    op.drop_column("knowledge_drafts", "title")
