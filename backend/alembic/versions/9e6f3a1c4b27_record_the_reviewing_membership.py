"""record the reviewing membership

Manager reviews already store the reviewer's name for display. This adds the
membership that made the decision, so a decision can be traced to an account
even if the display name changes.

Revision ID: 9e6f3a1c4b27
Revises: 7c4a2e9b1d58
Create Date: 2026-11-02
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "9e6f3a1c4b27"
down_revision: str | Sequence[str] | None = "7c4a2e9b1d58"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "manager_reviews",
        sa.Column("reviewer_membership_id", sa.Integer(), nullable=True),
    )
    op.create_foreign_key(
        "fk_manager_reviews_reviewer_membership",
        "manager_reviews",
        "organization_memberships",
        ["reviewer_membership_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_constraint(
        "fk_manager_reviews_reviewer_membership", "manager_reviews", type_="foreignkey"
    )
    op.drop_column("manager_reviews", "reviewer_membership_id")
