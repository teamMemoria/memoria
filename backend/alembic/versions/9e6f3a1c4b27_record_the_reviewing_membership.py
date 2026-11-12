"""record the reviewing membership

This branch first added manager_reviews.reviewer_membership_id here. The
organizations migration on main (b7e2f4a91c3d) now creates that column, NOT
NULL and scoped to the organization, and drops the reviewer name. Nothing is
left to change, so this revision is kept only so later revisions still chain.

Revision ID: 9e6f3a1c4b27
Revises: 7c4a2e9b1d58
Create Date: 2026-11-02
"""

from collections.abc import Sequence

revision: str = "9e6f3a1c4b27"
down_revision: str | Sequence[str] | None = "7c4a2e9b1d58"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
