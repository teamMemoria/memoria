"""index tenant foreign keys and common query filters

Revision ID: 5b92ee84d4b6
Revises: 92c6a85f041d
Create Date: 2026-11-17 23:42:00.934164

"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "5b92ee84d4b6"
down_revision: str | Sequence[str] | None = "92c6a85f041d"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_index(
        "ix_agent_contexts_org_agent",
        "agent_contexts",
        ["organization_id", "agent_id"],
        unique=False,
    )
    op.create_index(
        "ix_agent_contexts_org_conversation",
        "agent_contexts",
        ["organization_id", "conversation_id"],
        unique=False,
    )
    op.create_index(
        "ix_analysis_runs_audit", "analysis_runs", ["audit_id"], unique=False
    )
    op.create_index(
        "ix_analysis_runs_org_conversation",
        "analysis_runs",
        ["organization_id", "conversation_id"],
        unique=False,
    )
    op.create_index(
        "ix_audits_org_conversation",
        "audits",
        ["organization_id", "conversation_id"],
        unique=False,
    )
    op.create_index(
        "ix_conversations_conversation_date",
        "conversations",
        ["conversation_date"],
        unique=False,
    )
    op.create_index(
        "ix_conversations_org_agent_started",
        "conversations",
        ["organization_id", "agent_id", "synthetic_started_at"],
        unique=False,
    )
    op.create_index(
        "ix_conversations_org_topic",
        "conversations",
        ["organization_id", "topic_id"],
        unique=False,
    )
    op.create_index(
        "ix_conversations_synthetic_started_at",
        "conversations",
        ["synthetic_started_at"],
        unique=False,
    )
    op.create_index(
        "ix_feedback_flags_org_agent",
        "feedback_flags",
        ["organization_id", "agent_id"],
        unique=False,
    )
    op.create_index(
        "ix_feedback_flags_org_finding",
        "feedback_flags",
        ["organization_id", "finding_id"],
        unique=False,
    )
    op.create_index(
        "ix_finding_evidence_turn", "finding_evidence", ["turn_id"], unique=False
    )
    op.create_index(
        "ix_findings_org_audit",
        "findings",
        ["organization_id", "audit_id"],
        unique=False,
    )
    op.create_index(
        "ix_findings_org_knowledge",
        "findings",
        ["organization_id", "knowledge_entry_id"],
        unique=False,
    )
    op.create_index(
        "ix_knowledge_conflicts_org_draft",
        "knowledge_conflicts",
        ["organization_id", "draft_id"],
        unique=False,
    )
    op.create_index(
        "ix_knowledge_conflicts_org_other_draft",
        "knowledge_conflicts",
        ["organization_id", "other_draft_id"],
        unique=False,
    )
    op.create_index(
        "ix_knowledge_conflicts_org_other_entry",
        "knowledge_conflicts",
        ["organization_id", "other_entry_id"],
        unique=False,
    )
    op.create_index(
        "ix_knowledge_draft_conversations_org_conversation",
        "knowledge_draft_conversations",
        ["organization_id", "conversation_id"],
        unique=False,
    )
    op.create_index(
        "ix_knowledge_draft_entry_matches_org_entry",
        "knowledge_draft_entry_matches",
        ["organization_id", "entry_id"],
        unique=False,
    )
    op.create_index(
        "ix_knowledge_draft_passages_org_conversation",
        "knowledge_draft_passages",
        ["organization_id", "conversation_id"],
        unique=False,
    )
    op.create_index(
        "ix_knowledge_draft_passages_org_draft",
        "knowledge_draft_passages",
        ["organization_id", "draft_id"],
        unique=False,
    )
    op.create_index(
        "ix_knowledge_drafts_org_duplicate",
        "knowledge_drafts",
        ["organization_id", "duplicate_of_id"],
        unique=False,
    )
    op.create_index(
        "ix_knowledge_drafts_org_status",
        "knowledge_drafts",
        ["organization_id", "status"],
        unique=False,
    )
    op.create_index(
        "ix_knowledge_drafts_org_topic_status",
        "knowledge_drafts",
        ["organization_id", "topic_id", "status"],
        unique=False,
    )
    op.create_index(
        "ix_knowledge_entries_org_status",
        "knowledge_entries",
        ["organization_id", "status"],
        unique=False,
    )
    op.create_index(
        "ix_knowledge_entries_org_topic_status",
        "knowledge_entries",
        ["organization_id", "topic_id", "status"],
        unique=False,
    )
    op.create_index(
        "ix_knowledge_reviews_org_draft",
        "knowledge_reviews",
        ["organization_id", "draft_id"],
        unique=False,
    )
    op.create_index(
        "ix_knowledge_reviews_org_reviewer",
        "knowledge_reviews",
        ["organization_id", "reviewer_membership_id"],
        unique=False,
    )
    op.create_index(
        "ix_manager_reviews_org_flag",
        "manager_reviews",
        ["organization_id", "feedback_flag_id"],
        unique=False,
    )
    op.create_index(
        "ix_manager_reviews_org_reviewer",
        "manager_reviews",
        ["organization_id", "reviewer_membership_id"],
        unique=False,
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index("ix_manager_reviews_org_reviewer", table_name="manager_reviews")
    op.drop_index("ix_manager_reviews_org_flag", table_name="manager_reviews")
    op.drop_index("ix_knowledge_reviews_org_reviewer", table_name="knowledge_reviews")
    op.drop_index("ix_knowledge_reviews_org_draft", table_name="knowledge_reviews")
    op.drop_index(
        "ix_knowledge_entries_org_topic_status", table_name="knowledge_entries"
    )
    op.drop_index("ix_knowledge_entries_org_status", table_name="knowledge_entries")
    op.drop_index("ix_knowledge_drafts_org_topic_status", table_name="knowledge_drafts")
    op.drop_index("ix_knowledge_drafts_org_status", table_name="knowledge_drafts")
    op.drop_index("ix_knowledge_drafts_org_duplicate", table_name="knowledge_drafts")
    op.drop_index(
        "ix_knowledge_draft_passages_org_draft", table_name="knowledge_draft_passages"
    )
    op.drop_index(
        "ix_knowledge_draft_passages_org_conversation",
        table_name="knowledge_draft_passages",
    )
    op.drop_index(
        "ix_knowledge_draft_entry_matches_org_entry",
        table_name="knowledge_draft_entry_matches",
    )
    op.drop_index(
        "ix_knowledge_draft_conversations_org_conversation",
        table_name="knowledge_draft_conversations",
    )
    op.drop_index(
        "ix_knowledge_conflicts_org_other_entry", table_name="knowledge_conflicts"
    )
    op.drop_index(
        "ix_knowledge_conflicts_org_other_draft", table_name="knowledge_conflicts"
    )
    op.drop_index("ix_knowledge_conflicts_org_draft", table_name="knowledge_conflicts")
    op.drop_index("ix_findings_org_knowledge", table_name="findings")
    op.drop_index("ix_findings_org_audit", table_name="findings")
    op.drop_index("ix_finding_evidence_turn", table_name="finding_evidence")
    op.drop_index("ix_feedback_flags_org_finding", table_name="feedback_flags")
    op.drop_index("ix_feedback_flags_org_agent", table_name="feedback_flags")
    op.drop_index("ix_conversations_synthetic_started_at", table_name="conversations")
    op.drop_index("ix_conversations_org_topic", table_name="conversations")
    op.drop_index("ix_conversations_org_agent_started", table_name="conversations")
    op.drop_index("ix_conversations_conversation_date", table_name="conversations")
    op.drop_index("ix_audits_org_conversation", table_name="audits")
    op.drop_index("ix_analysis_runs_org_conversation", table_name="analysis_runs")
    op.drop_index("ix_analysis_runs_audit", table_name="analysis_runs")
    op.drop_index("ix_agent_contexts_org_conversation", table_name="agent_contexts")
    op.drop_index("ix_agent_contexts_org_agent", table_name="agent_contexts")
