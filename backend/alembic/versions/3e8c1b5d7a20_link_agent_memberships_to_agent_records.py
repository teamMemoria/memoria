"""link agent memberships to agent records

A signed-in agent is a User with a membership; the calls they handled point at
an Agent row from the source data. This link is how ownership checks know which
calls belong to which person. Only agent memberships can carry it, and each
agent record belongs to at most one membership in its organization.

Revision ID: 3e8c1b5d7a20
Revises: ca38f73b9d21
Create Date: 2026-11-02
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "3e8c1b5d7a20"
down_revision: str | Sequence[str] | None = "ca38f73b9d21"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "organization_memberships",
        sa.Column("agent_id", sa.Integer(), nullable=True),
    )
    op.create_foreign_key(
        "fk_organization_memberships_agent",
        "organization_memberships",
        "agents",
        ["organization_id", "agent_id"],
        ["organization_id", "id"],
    )
    op.create_unique_constraint(
        "uq_organization_memberships_agent",
        "organization_memberships",
        ["organization_id", "agent_id"],
    )
    op.create_check_constraint(
        "ck_organization_memberships_agent_link_role",
        "organization_memberships",
        "agent_id IS NULL OR role = 'agent'",
    )


def downgrade() -> None:
    op.drop_constraint(
        "ck_organization_memberships_agent_link_role",
        "organization_memberships",
        type_="check",
    )
    op.drop_constraint(
        "uq_organization_memberships_agent",
        "organization_memberships",
        type_="unique",
    )
    op.drop_constraint(
        "fk_organization_memberships_agent",
        "organization_memberships",
        type_="foreignkey",
    )
    op.drop_column("organization_memberships", "agent_id")
