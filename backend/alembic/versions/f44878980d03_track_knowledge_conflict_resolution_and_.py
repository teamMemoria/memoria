"""track knowledge conflict resolution and disputed topics

Revision ID: f44878980d03
Revises: 92c6a85f041d
Create Date: 2026-11-17 23:31:15.408254

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "f44878980d03"
down_revision: str | Sequence[str] | None = "92c6a85f041d"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        "knowledge_conflicts",
        sa.Column(
            "lifecycle_status",
            sa.String(length=20),
            server_default="open",
            nullable=False,
        ),
    )
    op.add_column(
        "knowledge_conflicts",
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )
    op.add_column(
        "knowledge_conflicts",
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "topics",
        sa.Column("disputed", sa.Boolean(), server_default="false", nullable=False),
    )

    op.execute("UPDATE knowledge_conflicts SET created_at = updated_at")

    # Autogenerate does not detect new CHECK constraints on existing tables.
    op.create_check_constraint(
        "ck_knowledge_conflict_lifecycle",
        "knowledge_conflicts",
        "lifecycle_status IN ('open', 'resolved')",
    )
    op.create_check_constraint(
        "ck_knowledge_conflict_resolution",
        "knowledge_conflicts",
        "(lifecycle_status = 'resolved') = (resolved_at IS NOT NULL)",
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_constraint(
        "ck_knowledge_conflict_resolution", "knowledge_conflicts", type_="check"
    )
    op.drop_constraint(
        "ck_knowledge_conflict_lifecycle", "knowledge_conflicts", type_="check"
    )
    op.drop_column("topics", "disputed")
    op.drop_column("knowledge_conflicts", "resolved_at")
    op.drop_column("knowledge_conflicts", "created_at")
    op.drop_column("knowledge_conflicts", "lifecycle_status")
