"""Explicit tenant/FK query indexes, registered after all model tables exist.

Keep these declarations in metadata so Alembic autogenerate detects drift.
Existing PK/unique indexes and the HNSW indexes are reused, not recreated.
"""

from sqlalchemy import Index, MetaData

# (table, name suffix, leading columns). Composite tenant indexes also cover
# organization_id alone; do not add a redundant organization-only index.
QUERY_INDEXES = (
    (
        "conversations",
        "org_agent_started",
        ("organization_id", "agent_id", "synthetic_started_at"),
    ),
    ("conversations", "org_topic", ("organization_id", "topic_id")),
    ("conversations", "conversation_date", ("conversation_date",)),
    ("conversations", "synthetic_started_at", ("synthetic_started_at",)),
    ("knowledge_drafts", "org_duplicate", ("organization_id", "duplicate_of_id")),
    ("knowledge_drafts", "org_topic_status", ("organization_id", "topic_id", "status")),
    ("knowledge_drafts", "org_status", ("organization_id", "status")),
    ("agent_contexts", "org_agent", ("organization_id", "agent_id")),
    ("agent_contexts", "org_conversation", ("organization_id", "conversation_id")),
    ("audits", "org_conversation", ("organization_id", "conversation_id")),
    (
        "knowledge_draft_conversations",
        "org_conversation",
        ("organization_id", "conversation_id"),
    ),
    (
        "knowledge_draft_passages",
        "org_conversation",
        ("organization_id", "conversation_id"),
    ),
    ("knowledge_draft_passages", "org_draft", ("organization_id", "draft_id")),
    ("knowledge_reviews", "org_draft", ("organization_id", "draft_id")),
    (
        "knowledge_reviews",
        "org_reviewer",
        ("organization_id", "reviewer_membership_id"),
    ),
    ("analysis_runs", "audit", ("audit_id",)),
    ("analysis_runs", "org_conversation", ("organization_id", "conversation_id")),
    (
        "knowledge_entries",
        "org_topic_status",
        ("organization_id", "topic_id", "status"),
    ),
    ("knowledge_entries", "org_status", ("organization_id", "status")),
    ("findings", "org_audit", ("organization_id", "audit_id")),
    ("findings", "org_knowledge", ("organization_id", "knowledge_entry_id")),
    ("knowledge_conflicts", "org_draft", ("organization_id", "draft_id")),
    ("knowledge_conflicts", "org_other_draft", ("organization_id", "other_draft_id")),
    ("knowledge_conflicts", "org_other_entry", ("organization_id", "other_entry_id")),
    ("knowledge_draft_entry_matches", "org_entry", ("organization_id", "entry_id")),
    ("feedback_flags", "org_agent", ("organization_id", "agent_id")),
    ("feedback_flags", "org_finding", ("organization_id", "finding_id")),
    ("finding_evidence", "turn", ("turn_id",)),
    ("manager_reviews", "org_flag", ("organization_id", "feedback_flag_id")),
    ("manager_reviews", "org_reviewer", ("organization_id", "reviewer_membership_id")),
)


def add_query_indexes(metadata: MetaData) -> None:
    for table_name, suffix, columns in QUERY_INDEXES:
        table = metadata.tables[table_name]
        name = f"ix_{table_name}_{suffix}"
        if not any(index.name == name for index in table.indexes):
            Index(name, *(table.c[column] for column in columns))
