"""Store canonical evidence and versioned rule reports without replacing decisions."""

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

from alembic import op

revision = "92c6a85f041d"
down_revision = "b3d8e5f1a274"
branch_labels = depends_on = None


def upgrade():
    op.add_column(
        "conversations", sa.Column("canonical_evidence", JSONB, nullable=True)
    )
    op.add_column("audits", sa.Column("assessment_report", JSONB, nullable=True))
    op.add_column("analysis_runs", sa.Column("assessment_report", JSONB, nullable=True))

    op.add_column(
        "knowledge_drafts", sa.Column("verification_reference", JSONB, nullable=True)
    )
    op.add_column(
        "knowledge_reviews",
        sa.Column("verified_reference_url", sa.Text(), nullable=True),
    )


def downgrade():
    op.drop_column("knowledge_reviews", "verified_reference_url")
    op.drop_column("knowledge_drafts", "verification_reference")
    op.drop_column("analysis_runs", "assessment_report")
    op.drop_column("audits", "assessment_report")
    op.drop_column("conversations", "canonical_evidence")
