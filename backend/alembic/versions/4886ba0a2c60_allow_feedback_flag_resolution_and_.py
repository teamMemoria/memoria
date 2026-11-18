"""allow feedback flag resolution and repeat requests

Revision ID: 4886ba0a2c60
Revises: 92c6a85f041d
Create Date: 2026-11-17 23:25:51.866296

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "4886ba0a2c60"
down_revision: str | Sequence[str] | None = "92c6a85f041d"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        "feedback_flags",
        sa.Column(
            "status", sa.String(length=20), server_default="open", nullable=False
        ),
    )
    op.add_column(
        "feedback_flags",
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
    )
    # Reviewed flags must leave the open queue before enforcing the new rule.
    op.execute("""
        UPDATE feedback_flags f SET status = 'resolved', resolved_at = r.reviewed_at
        FROM manager_reviews r WHERE r.feedback_flag_id = f.id
    """)
    op.create_check_constraint(
        "ck_feedback_flags_status", "feedback_flags", "status IN ('open', 'resolved')"
    )
    op.create_check_constraint(
        "ck_feedback_flags_resolved_at",
        "feedback_flags",
        "(status = 'resolved') = (resolved_at IS NOT NULL)",
    )
    # Enforce resolution for every writer, including direct SQL and data imports.
    op.execute("""
        CREATE FUNCTION resolve_reviewed_feedback_flag() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
            UPDATE feedback_flags SET status = 'resolved', resolved_at = NEW.reviewed_at
            WHERE id = NEW.feedback_flag_id;
            RETURN NEW;
        END;
        $$
    """)
    op.execute("""
        CREATE TRIGGER resolve_feedback_flag AFTER INSERT ON manager_reviews
        FOR EACH ROW EXECUTE FUNCTION resolve_reviewed_feedback_flag()
    """)
    op.drop_constraint(
        op.f("feedback_flags_finding_id_key"), "feedback_flags", type_="unique"
    )
    op.create_index(
        op.f("ix_feedback_flags_finding_id"),
        "feedback_flags",
        ["finding_id"],
        unique=False,
    )
    op.create_index(
        "uq_feedback_flags_open_finding",
        "feedback_flags",
        ["finding_id"],
        unique=True,
        postgresql_where=sa.text("status = 'open'"),
    )


def downgrade() -> None:
    """Restore the old schema, refusing to discard repeat-request history."""
    # Restoring the old unique constraint fails transactionally if repeat flags
    # exist. An operator must archive that history before downgrading; never
    # silently delete flags or their decisions.
    op.execute("DROP TRIGGER resolve_feedback_flag ON manager_reviews")
    op.execute("DROP FUNCTION resolve_reviewed_feedback_flag()")
    op.drop_constraint("ck_feedback_flags_resolved_at", "feedback_flags", type_="check")
    op.drop_constraint("ck_feedback_flags_status", "feedback_flags", type_="check")
    op.drop_index(
        "uq_feedback_flags_open_finding",
        table_name="feedback_flags",
        postgresql_where=sa.text("status = 'open'"),
    )
    op.drop_index(op.f("ix_feedback_flags_finding_id"), table_name="feedback_flags")
    op.create_unique_constraint(
        op.f("feedback_flags_finding_id_key"),
        "feedback_flags",
        ["finding_id"],
        postgresql_nulls_not_distinct=False,
    )
    op.drop_column("feedback_flags", "resolved_at")
    op.drop_column("feedback_flags", "status")
