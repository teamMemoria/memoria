"""store knowledge pipeline output

Pipeline drafts are stored as pending knowledge drafts, keyed by the
pipeline's own draft ID so reprocessing updates instead of duplicating. Their
cited passages, duplicate links, matches to approved entries and possible
conflicts get their own tables. Possible conflicts are kept apart from the
disputed status of approved entries, which only a reviewer sets.

Revision ID: b3d8e5f1a274
Revises: 9e6f3a1c4b27
Create Date: 2026-11-02
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "b3d8e5f1a274"
down_revision: str | Sequence[str] | None = "9e6f3a1c4b27"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "knowledge_drafts", sa.Column("source_key", sa.String(100), nullable=True)
    )
    op.add_column("knowledge_drafts", sa.Column("question", sa.Text(), nullable=True))
    op.add_column(
        "knowledge_drafts", sa.Column("group_key", sa.String(100), nullable=True)
    )
    op.add_column(
        "knowledge_drafts", sa.Column("duplicate_of_id", sa.Integer(), nullable=True)
    )
    op.add_column(
        "knowledge_drafts",
        sa.Column("duplicate_similarity", sa.Numeric(5, 4), nullable=True),
    )
    op.add_column(
        "knowledge_drafts",
        sa.Column("ml_verification", sa.String(30), nullable=True),
    )
    op.add_column(
        "knowledge_drafts",
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_unique_constraint(
        "uq_knowledge_drafts_source_key",
        "knowledge_drafts",
        ["organization_id", "source_key"],
    )
    op.create_foreign_key(
        "fk_knowledge_drafts_duplicate_of",
        "knowledge_drafts",
        "knowledge_drafts",
        ["organization_id", "duplicate_of_id"],
        ["organization_id", "id"],
    )
    op.create_index(
        "ix_knowledge_drafts_group_key",
        "knowledge_drafts",
        ["organization_id", "group_key"],
    )

    op.create_table(
        "knowledge_draft_passages",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("organization_id", sa.Integer(), nullable=False),
        sa.Column("draft_id", sa.Integer(), nullable=False),
        sa.Column("conversation_id", sa.Integer(), nullable=False),
        sa.Column("role", sa.String(20), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("turn_number", sa.Integer(), nullable=False),
        sa.Column("speaker", sa.String(20), nullable=False),
        sa.Column("quote", sa.Text(), nullable=False),
        sa.Column("span_start", sa.Integer(), nullable=False),
        sa.Column("span_end", sa.Integer(), nullable=False),
        sa.Column("source_key", sa.String(200), nullable=False),
        sa.Column("source_version", sa.String(100), nullable=False),
        sa.CheckConstraint(
            "role IN ('question', 'answer', 'condition')",
            name="ck_knowledge_draft_passage_role",
        ),
        sa.CheckConstraint(
            "span_start >= 0 AND span_end > span_start",
            name="ck_knowledge_draft_passage_span",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id", "draft_id"],
            ["knowledge_drafts.organization_id", "knowledge_drafts.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id", "conversation_id"],
            ["conversations.organization_id", "conversations.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("draft_id", "role", "position"),
    )

    op.create_table(
        "knowledge_draft_entry_matches",
        sa.Column("organization_id", sa.Integer(), nullable=False),
        sa.Column("draft_id", sa.Integer(), nullable=False),
        sa.Column("entry_id", sa.Integer(), nullable=False),
        sa.Column("kind", sa.String(30), nullable=False),
        sa.Column("similarity", sa.Numeric(5, 4), nullable=False),
        sa.ForeignKeyConstraint(
            ["organization_id", "draft_id"],
            ["knowledge_drafts.organization_id", "knowledge_drafts.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id", "entry_id"],
            ["knowledge_entries.organization_id", "knowledge_entries.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("organization_id", "draft_id", "entry_id"),
    )

    op.create_table(
        "knowledge_conflicts",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("organization_id", sa.Integer(), nullable=False),
        sa.Column("source_key", sa.String(100), nullable=False),
        sa.Column("kind", sa.String(30), nullable=False),
        sa.Column("status", sa.String(30), nullable=False),
        sa.Column("explanation", sa.Text(), nullable=False),
        sa.Column("draft_id", sa.Integer(), nullable=False),
        sa.Column("other_draft_id", sa.Integer(), nullable=True),
        sa.Column("other_entry_id", sa.Integer(), nullable=True),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "status IN ('possible_conflict', 'unresolved')",
            name="ck_knowledge_conflict_status",
        ),
        sa.CheckConstraint(
            "(other_draft_id IS NULL) <> (other_entry_id IS NULL)",
            name="ck_knowledge_conflict_one_other_side",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"], ["organizations.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["organization_id", "draft_id"],
            ["knowledge_drafts.organization_id", "knowledge_drafts.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id", "other_draft_id"],
            ["knowledge_drafts.organization_id", "knowledge_drafts.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id", "other_entry_id"],
            ["knowledge_entries.organization_id", "knowledge_entries.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("organization_id", "source_key"),
    )


def downgrade() -> None:
    op.drop_table("knowledge_conflicts")
    op.drop_table("knowledge_draft_entry_matches")
    op.drop_table("knowledge_draft_passages")
    op.drop_index("ix_knowledge_drafts_group_key", table_name="knowledge_drafts")
    op.drop_constraint(
        "fk_knowledge_drafts_duplicate_of", "knowledge_drafts", type_="foreignkey"
    )
    op.drop_constraint(
        "uq_knowledge_drafts_source_key", "knowledge_drafts", type_="unique"
    )
    for column in (
        "updated_at",
        "ml_verification",
        "duplicate_similarity",
        "duplicate_of_id",
        "group_key",
        "question",
        "source_key",
    ):
        op.drop_column("knowledge_drafts", column)
