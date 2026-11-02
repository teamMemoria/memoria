"""merge evaluation, organization and review heads

The evaluation forms (#87), organizations and roles (#85) and feedback review
(#91) migrations each branch from an earlier revision. This revision joins
them so `alembic upgrade head` has a single target again. It changes no
schema.

Revision ID: 0a1d5e7c9b42
Revises: 84b37f614ac2, b7e2f4a91c3d, c75d2d9e41af
Create Date: 2026-11-02
"""

from collections.abc import Sequence

revision: str = "0a1d5e7c9b42"
down_revision: str | Sequence[str] | None = (
    "84b37f614ac2",
    "b7e2f4a91c3d",
    "c75d2d9e41af",
)
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
