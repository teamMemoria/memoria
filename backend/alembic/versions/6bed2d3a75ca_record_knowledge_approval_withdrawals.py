"""Record knowledge approval withdrawals without deleting published versions."""

from alembic import op

revision = "6bed2d3a75ca"
down_revision = "ab197a4c250e"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_constraint("entry_status", "knowledge_entries", type_="check")
    op.create_check_constraint(
        "entry_status",
        "knowledge_entries",
        "status IN ('approved', 'disputed', 'stale', 'withdrawn')",
    )
    op.drop_constraint("review_action", "knowledge_reviews", type_="check")
    op.create_check_constraint(
        "review_action",
        "knowledge_reviews",
        "action IN ('approved', 'edited', 'rejected', 'unapproved')",
    )


def downgrade() -> None:
    op.drop_constraint("review_action", "knowledge_reviews", type_="check")
    op.create_check_constraint(
        "review_action",
        "knowledge_reviews",
        "action IN ('approved', 'edited', 'rejected')",
    )
    op.drop_constraint("entry_status", "knowledge_entries", type_="check")
    op.create_check_constraint(
        "entry_status",
        "knowledge_entries",
        "status IN ('approved', 'disputed', 'stale')",
    )
