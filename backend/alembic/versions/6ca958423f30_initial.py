"""initial

Revision ID: 6ca958423f30
Revises: 
Create Date: 2026-10-21 16:07:17.149163

"""
from collections.abc import Sequence

# revision identifiers, used by Alembic.
revision: str = '6ca958423f30'
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""


def downgrade() -> None:
    """Downgrade schema."""
