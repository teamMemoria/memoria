"""add organizations users and roles

Revision ID: b7e2f4a91c3d
Revises: c75d2d9e41af
Create Date: 2026-11-01 23:30:00

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "b7e2f4a91c3d"
down_revision: str | Sequence[str] | None = "c75d2d9e41af"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

DEFAULT_ORGANIZATION_SLUG = "default"


def _add_backfilled_organization_id(table_name: str) -> None:
    op.add_column(table_name, sa.Column("organization_id", sa.Integer(), nullable=True))
    op.execute(
        sa.text(
            f"""
            UPDATE {table_name}
            SET organization_id = (
                SELECT id FROM organizations WHERE slug = :slug
            )
            WHERE organization_id IS NULL
            """
        ).bindparams(slug=DEFAULT_ORGANIZATION_SLUG)
    )
    op.alter_column(table_name, "organization_id", nullable=False)


def upgrade() -> None:
    op.create_table(
        "organizations",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("slug", sa.String(length=100), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("slug"),
    )
    op.create_table(
        "users",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("external_id", sa.String(length=100), nullable=False),
        sa.Column("display_name", sa.String(length=200), nullable=False),
        sa.Column("email", sa.String(length=320), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("email"),
        sa.UniqueConstraint("external_id"),
    )
    op.create_table(
        "organization_memberships",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("organization_id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column(
            "role",
            sa.Enum(
                "agent",
                "manager",
                name="user_role",
                native_enum=False,
                create_constraint=True,
                length=20,
            ),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"], ["organizations.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("organization_id", "id"),
        sa.UniqueConstraint("organization_id", "user_id"),
    )
    op.create_index(
        op.f("ix_organization_memberships_organization_id"),
        "organization_memberships",
        ["organization_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_organization_memberships_user_id"),
        "organization_memberships",
        ["user_id"],
        unique=False,
    )
    op.execute(
        sa.text(
            """
            INSERT INTO organizations (slug, name)
            VALUES (:slug, 'Default Organization')
            """
        ).bindparams(slug=DEFAULT_ORGANIZATION_SLUG)
    )

    _add_backfilled_organization_id("agents")
    op.create_foreign_key(
        "fk_agents_organization_id",
        "agents",
        "organizations",
        ["organization_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.drop_constraint("agents_external_id_key", "agents", type_="unique")
    op.create_unique_constraint(
        "uq_agents_organization_external_id",
        "agents",
        ["organization_id", "external_id"],
    )
    op.create_unique_constraint(
        "uq_agents_organization_id", "agents", ["organization_id", "id"]
    )
    op.create_index(
        op.f("ix_agents_organization_id"), "agents", ["organization_id"], unique=False
    )

    _add_backfilled_organization_id("topics")
    op.create_foreign_key(
        "fk_topics_organization_id",
        "topics",
        "organizations",
        ["organization_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.drop_constraint("topics_source_dataset_name_key", "topics", type_="unique")
    op.create_unique_constraint(
        "uq_topics_organization_source_name",
        "topics",
        ["organization_id", "source_dataset", "name"],
    )
    op.create_unique_constraint(
        "uq_topics_organization_id", "topics", ["organization_id", "id"]
    )
    op.create_index(
        op.f("ix_topics_organization_id"), "topics", ["organization_id"], unique=False
    )

    _add_backfilled_organization_id("conversations")
    op.drop_constraint(
        "conversations_source_dataset_original_id_key",
        "conversations",
        type_="unique",
    )
    op.drop_constraint("conversations_curated_id_key", "conversations", type_="unique")
    op.drop_constraint(
        "conversations_agent_id_fkey", "conversations", type_="foreignkey"
    )
    op.drop_constraint(
        "conversations_topic_id_fkey", "conversations", type_="foreignkey"
    )
    op.create_foreign_key(
        "fk_conversations_organization_id",
        "conversations",
        "organizations",
        ["organization_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_foreign_key(
        "fk_conversations_organization_agent",
        "conversations",
        "agents",
        ["organization_id", "agent_id"],
        ["organization_id", "id"],
    )
    op.create_foreign_key(
        "fk_conversations_organization_topic",
        "conversations",
        "topics",
        ["organization_id", "topic_id"],
        ["organization_id", "id"],
    )
    op.create_unique_constraint(
        "uq_conversations_organization_source_original",
        "conversations",
        ["organization_id", "source_dataset", "original_id"],
    )
    op.create_unique_constraint(
        "uq_conversations_organization_curated_id",
        "conversations",
        ["organization_id", "curated_id"],
    )
    op.create_unique_constraint(
        "uq_conversations_organization_id",
        "conversations",
        ["organization_id", "id"],
    )
    op.create_index(
        op.f("ix_conversations_organization_id"),
        "conversations",
        ["organization_id"],
        unique=False,
    )

    _add_backfilled_organization_id("knowledge_drafts")
    op.drop_constraint(
        "knowledge_drafts_topic_id_fkey", "knowledge_drafts", type_="foreignkey"
    )
    op.create_foreign_key(
        "fk_knowledge_drafts_organization_id",
        "knowledge_drafts",
        "organizations",
        ["organization_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_foreign_key(
        "fk_knowledge_drafts_organization_topic",
        "knowledge_drafts",
        "topics",
        ["organization_id", "topic_id"],
        ["organization_id", "id"],
    )
    op.create_unique_constraint(
        "uq_knowledge_drafts_organization_id",
        "knowledge_drafts",
        ["organization_id", "id"],
    )
    op.create_index(
        op.f("ix_knowledge_drafts_organization_id"),
        "knowledge_drafts",
        ["organization_id"],
        unique=False,
    )

    _add_backfilled_organization_id("knowledge_draft_conversations")
    op.drop_constraint(
        "knowledge_draft_conversations_pkey",
        "knowledge_draft_conversations",
        type_="primary",
    )
    op.drop_constraint(
        "knowledge_draft_conversations_draft_id_fkey",
        "knowledge_draft_conversations",
        type_="foreignkey",
    )
    op.drop_constraint(
        "knowledge_draft_conversations_conversation_id_fkey",
        "knowledge_draft_conversations",
        type_="foreignkey",
    )
    op.create_primary_key(
        "knowledge_draft_conversations_pkey",
        "knowledge_draft_conversations",
        ["organization_id", "draft_id", "conversation_id"],
    )
    op.create_foreign_key(
        "fk_draft_conversations_organization_draft",
        "knowledge_draft_conversations",
        "knowledge_drafts",
        ["organization_id", "draft_id"],
        ["organization_id", "id"],
        ondelete="CASCADE",
    )
    op.create_foreign_key(
        "fk_draft_conversations_organization_conversation",
        "knowledge_draft_conversations",
        "conversations",
        ["organization_id", "conversation_id"],
        ["organization_id", "id"],
        ondelete="CASCADE",
    )

    _add_backfilled_organization_id("knowledge_reviews")
    op.add_column(
        "knowledge_reviews",
        sa.Column("reviewer_membership_id", sa.Integer(), nullable=True),
    )
    op.execute(
        """
        INSERT INTO users (external_id, display_name)
        SELECT
            'legacy-reviewer-' || row_number() OVER (ORDER BY reviewer),
            reviewer
        FROM (
            SELECT reviewer FROM knowledge_reviews
            UNION
            SELECT reviewer FROM manager_reviews
        ) AS reviewers
        """
    )
    op.execute(
        sa.text(
            """
            INSERT INTO organization_memberships (organization_id, user_id, role)
            SELECT o.id, u.id, 'manager'
            FROM organizations AS o
            CROSS JOIN users AS u
            WHERE o.slug = :slug
              AND u.external_id LIKE 'legacy-reviewer-%'
            """
        ).bindparams(slug=DEFAULT_ORGANIZATION_SLUG)
    )
    op.execute(
        sa.text(
            """
            UPDATE knowledge_reviews AS kr
            SET reviewer_membership_id = om.id
            FROM organization_memberships AS om
            JOIN users AS u ON u.id = om.user_id
            JOIN organizations AS o ON o.id = om.organization_id
            WHERE u.display_name = kr.reviewer
              AND o.slug = :slug
            """
        ).bindparams(slug=DEFAULT_ORGANIZATION_SLUG)
    )
    op.alter_column("knowledge_reviews", "reviewer_membership_id", nullable=False)
    op.drop_column("knowledge_reviews", "reviewer")
    op.drop_constraint(
        "knowledge_reviews_draft_id_fkey", "knowledge_reviews", type_="foreignkey"
    )
    op.create_foreign_key(
        "fk_knowledge_reviews_organization_id",
        "knowledge_reviews",
        "organizations",
        ["organization_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_foreign_key(
        "fk_knowledge_reviews_organization_draft",
        "knowledge_reviews",
        "knowledge_drafts",
        ["organization_id", "draft_id"],
        ["organization_id", "id"],
    )
    op.create_foreign_key(
        "fk_knowledge_reviews_organization_membership",
        "knowledge_reviews",
        "organization_memberships",
        ["organization_id", "reviewer_membership_id"],
        ["organization_id", "id"],
    )
    op.create_unique_constraint(
        "uq_knowledge_reviews_organization_id",
        "knowledge_reviews",
        ["organization_id", "id"],
    )
    op.create_index(
        op.f("ix_knowledge_reviews_organization_id"),
        "knowledge_reviews",
        ["organization_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_knowledge_reviews_reviewer_membership_id"),
        "knowledge_reviews",
        ["reviewer_membership_id"],
        unique=False,
    )

    _add_backfilled_organization_id("knowledge_entries")
    op.drop_constraint(
        "knowledge_entries_approved_review_id_key",
        "knowledge_entries",
        type_="unique",
    )
    op.drop_constraint(
        "knowledge_entries_topic_id_fkey", "knowledge_entries", type_="foreignkey"
    )
    op.drop_constraint(
        "knowledge_entries_approved_review_id_fkey",
        "knowledge_entries",
        type_="foreignkey",
    )
    op.create_foreign_key(
        "fk_knowledge_entries_organization_id",
        "knowledge_entries",
        "organizations",
        ["organization_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_foreign_key(
        "fk_knowledge_entries_organization_topic",
        "knowledge_entries",
        "topics",
        ["organization_id", "topic_id"],
        ["organization_id", "id"],
    )
    op.create_foreign_key(
        "fk_knowledge_entries_organization_review",
        "knowledge_entries",
        "knowledge_reviews",
        ["organization_id", "approved_review_id"],
        ["organization_id", "id"],
    )
    op.create_unique_constraint(
        "uq_knowledge_entries_organization_id",
        "knowledge_entries",
        ["organization_id", "id"],
    )
    op.create_unique_constraint(
        "uq_knowledge_entries_organization_review",
        "knowledge_entries",
        ["organization_id", "approved_review_id"],
    )
    op.create_index(
        op.f("ix_knowledge_entries_organization_id"),
        "knowledge_entries",
        ["organization_id"],
        unique=False,
    )

    _add_backfilled_organization_id("audits")
    op.execute(
        """
        UPDATE audits AS a
        SET organization_id = c.organization_id
        FROM conversations AS c
        WHERE a.conversation_id = c.id
        """
    )
    op.drop_constraint("audits_conversation_id_fkey", "audits", type_="foreignkey")
    op.create_foreign_key(
        "fk_audits_organization_id",
        "audits",
        "organizations",
        ["organization_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_foreign_key(
        "fk_audits_organization_conversation",
        "audits",
        "conversations",
        ["organization_id", "conversation_id"],
        ["organization_id", "id"],
        ondelete="CASCADE",
    )
    op.create_unique_constraint(
        "uq_audits_organization_id", "audits", ["organization_id", "id"]
    )
    op.create_index(
        op.f("ix_audits_organization_id"),
        "audits",
        ["organization_id"],
        unique=False,
    )

    _add_backfilled_organization_id("findings")
    op.execute(
        """
        UPDATE findings AS f
        SET organization_id = a.organization_id
        FROM audits AS a
        WHERE f.audit_id = a.id
        """
    )
    op.drop_constraint("findings_audit_id_fkey", "findings", type_="foreignkey")
    op.drop_constraint(
        "findings_knowledge_entry_id_fkey", "findings", type_="foreignkey"
    )
    op.create_foreign_key(
        "fk_findings_organization_id",
        "findings",
        "organizations",
        ["organization_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_foreign_key(
        "fk_findings_organization_audit",
        "findings",
        "audits",
        ["organization_id", "audit_id"],
        ["organization_id", "id"],
        ondelete="CASCADE",
    )
    op.execute(
        """
        ALTER TABLE findings
        ADD CONSTRAINT fk_findings_organization_knowledge_entry
        FOREIGN KEY (organization_id, knowledge_entry_id)
        REFERENCES knowledge_entries (organization_id, id)
        ON DELETE SET NULL (knowledge_entry_id)
        """
    )
    op.create_unique_constraint(
        "uq_findings_organization_id", "findings", ["organization_id", "id"]
    )
    op.create_index(
        op.f("ix_findings_organization_id"),
        "findings",
        ["organization_id"],
        unique=False,
    )

    op.add_column("feedback_flags", sa.Column("organization_id", sa.Integer()))
    op.execute(
        """
        UPDATE feedback_flags AS ff
        SET organization_id = f.organization_id
        FROM findings AS f
        WHERE ff.finding_id = f.id
        """
    )
    op.alter_column("feedback_flags", "organization_id", nullable=False)
    op.drop_constraint(
        "feedback_flags_finding_id_fkey", "feedback_flags", type_="foreignkey"
    )
    op.drop_constraint(
        "feedback_flags_agent_id_fkey", "feedback_flags", type_="foreignkey"
    )
    op.create_foreign_key(
        "fk_feedback_flags_organization_id",
        "feedback_flags",
        "organizations",
        ["organization_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_foreign_key(
        "fk_feedback_flags_organization_finding",
        "feedback_flags",
        "findings",
        ["organization_id", "finding_id"],
        ["organization_id", "id"],
        ondelete="CASCADE",
    )
    op.create_foreign_key(
        "fk_feedback_flags_organization_agent",
        "feedback_flags",
        "agents",
        ["organization_id", "agent_id"],
        ["organization_id", "id"],
    )
    op.create_unique_constraint(
        "uq_feedback_flags_organization_id", "feedback_flags", ["organization_id", "id"]
    )
    op.create_index(
        op.f("ix_feedback_flags_organization_id"), "feedback_flags", ["organization_id"]
    )

    op.add_column("manager_reviews", sa.Column("organization_id", sa.Integer()))
    op.add_column("manager_reviews", sa.Column("reviewer_membership_id", sa.Integer()))
    op.execute(
        """
        UPDATE manager_reviews AS mr
        SET organization_id = ff.organization_id
        FROM feedback_flags AS ff
        WHERE mr.feedback_flag_id = ff.id
        """
    )
    op.execute(
        """
        UPDATE manager_reviews AS mr
        SET reviewer_membership_id = om.id
        FROM organization_memberships AS om
        JOIN users AS u ON u.id = om.user_id
        WHERE mr.organization_id = om.organization_id
          AND u.display_name = mr.reviewer
        """
    )
    op.alter_column("manager_reviews", "organization_id", nullable=False)
    op.alter_column("manager_reviews", "reviewer_membership_id", nullable=False)
    op.drop_column("manager_reviews", "reviewer")
    op.drop_constraint(
        "manager_reviews_feedback_flag_id_fkey", "manager_reviews", type_="foreignkey"
    )
    op.create_foreign_key(
        "fk_manager_reviews_organization_id",
        "manager_reviews",
        "organizations",
        ["organization_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_foreign_key(
        "fk_manager_reviews_organization_flag",
        "manager_reviews",
        "feedback_flags",
        ["organization_id", "feedback_flag_id"],
        ["organization_id", "id"],
        ondelete="CASCADE",
    )
    op.create_foreign_key(
        "fk_manager_reviews_organization_membership",
        "manager_reviews",
        "organization_memberships",
        ["organization_id", "reviewer_membership_id"],
        ["organization_id", "id"],
    )
    op.create_index(
        op.f("ix_manager_reviews_organization_id"),
        "manager_reviews",
        ["organization_id"],
    )
    op.create_index(
        op.f("ix_manager_reviews_reviewer_membership_id"),
        "manager_reviews",
        ["reviewer_membership_id"],
    )


def downgrade() -> None:
    op.drop_index(
        op.f("ix_manager_reviews_reviewer_membership_id"), table_name="manager_reviews"
    )
    op.drop_index(
        op.f("ix_manager_reviews_organization_id"), table_name="manager_reviews"
    )
    op.drop_constraint(
        "fk_manager_reviews_organization_membership",
        "manager_reviews",
        type_="foreignkey",
    )
    op.drop_constraint(
        "fk_manager_reviews_organization_flag", "manager_reviews", type_="foreignkey"
    )
    op.drop_constraint(
        "fk_manager_reviews_organization_id", "manager_reviews", type_="foreignkey"
    )
    op.add_column("manager_reviews", sa.Column("reviewer", sa.String(length=200)))
    op.execute(
        """
        UPDATE manager_reviews AS mr
        SET reviewer = u.display_name
        FROM organization_memberships AS om
        JOIN users AS u ON u.id = om.user_id
        WHERE mr.reviewer_membership_id = om.id
        """
    )
    op.alter_column("manager_reviews", "reviewer", nullable=False)
    op.drop_column("manager_reviews", "reviewer_membership_id")
    op.drop_column("manager_reviews", "organization_id")
    op.create_foreign_key(
        None,
        "manager_reviews",
        "feedback_flags",
        ["feedback_flag_id"],
        ["id"],
        ondelete="CASCADE",
    )

    op.drop_index(
        op.f("ix_feedback_flags_organization_id"), table_name="feedback_flags"
    )
    op.drop_constraint(
        "uq_feedback_flags_organization_id", "feedback_flags", type_="unique"
    )
    op.drop_constraint(
        "fk_feedback_flags_organization_agent", "feedback_flags", type_="foreignkey"
    )
    op.drop_constraint(
        "fk_feedback_flags_organization_finding", "feedback_flags", type_="foreignkey"
    )
    op.drop_constraint(
        "fk_feedback_flags_organization_id", "feedback_flags", type_="foreignkey"
    )
    op.drop_column("feedback_flags", "organization_id")
    op.create_foreign_key(
        None, "feedback_flags", "findings", ["finding_id"], ["id"], ondelete="CASCADE"
    )
    op.create_foreign_key(None, "feedback_flags", "agents", ["agent_id"], ["id"])

    op.drop_index(op.f("ix_findings_organization_id"), table_name="findings")
    op.drop_constraint("uq_findings_organization_id", "findings", type_="unique")
    op.drop_constraint(
        "fk_findings_organization_knowledge_entry",
        "findings",
        type_="foreignkey",
    )
    op.drop_constraint("fk_findings_organization_audit", "findings", type_="foreignkey")
    op.drop_constraint("fk_findings_organization_id", "findings", type_="foreignkey")
    op.create_foreign_key(
        None,
        "findings",
        "knowledge_entries",
        ["knowledge_entry_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_foreign_key(
        None,
        "findings",
        "audits",
        ["audit_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.drop_column("findings", "organization_id")

    op.drop_index(op.f("ix_audits_organization_id"), table_name="audits")
    op.drop_constraint("uq_audits_organization_id", "audits", type_="unique")
    op.drop_constraint(
        "fk_audits_organization_conversation", "audits", type_="foreignkey"
    )
    op.drop_constraint("fk_audits_organization_id", "audits", type_="foreignkey")
    op.create_foreign_key(
        None,
        "audits",
        "conversations",
        ["conversation_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.drop_column("audits", "organization_id")

    op.drop_index(
        op.f("ix_knowledge_entries_organization_id"), table_name="knowledge_entries"
    )
    op.drop_constraint(
        "uq_knowledge_entries_organization_review", "knowledge_entries", type_="unique"
    )
    op.drop_constraint(
        "uq_knowledge_entries_organization_id", "knowledge_entries", type_="unique"
    )
    op.drop_constraint(
        "fk_knowledge_entries_organization_review",
        "knowledge_entries",
        type_="foreignkey",
    )
    op.drop_constraint(
        "fk_knowledge_entries_organization_topic",
        "knowledge_entries",
        type_="foreignkey",
    )
    op.drop_constraint(
        "fk_knowledge_entries_organization_id", "knowledge_entries", type_="foreignkey"
    )
    op.create_foreign_key(
        None, "knowledge_entries", "knowledge_reviews", ["approved_review_id"], ["id"]
    )
    op.create_foreign_key(None, "knowledge_entries", "topics", ["topic_id"], ["id"])
    op.create_unique_constraint(None, "knowledge_entries", ["approved_review_id"])
    op.drop_column("knowledge_entries", "organization_id")

    op.drop_index(
        op.f("ix_knowledge_reviews_reviewer_membership_id"),
        table_name="knowledge_reviews",
    )
    op.drop_index(
        op.f("ix_knowledge_reviews_organization_id"), table_name="knowledge_reviews"
    )
    op.drop_constraint(
        "uq_knowledge_reviews_organization_id", "knowledge_reviews", type_="unique"
    )
    op.drop_constraint(
        "fk_knowledge_reviews_organization_membership",
        "knowledge_reviews",
        type_="foreignkey",
    )
    op.drop_constraint(
        "fk_knowledge_reviews_organization_draft",
        "knowledge_reviews",
        type_="foreignkey",
    )
    op.drop_constraint(
        "fk_knowledge_reviews_organization_id", "knowledge_reviews", type_="foreignkey"
    )
    op.add_column(
        "knowledge_reviews", sa.Column("reviewer", sa.String(length=200), nullable=True)
    )
    op.execute(
        """
        UPDATE knowledge_reviews AS kr
        SET reviewer = u.display_name
        FROM organization_memberships AS om
        JOIN users AS u ON u.id = om.user_id
        WHERE kr.reviewer_membership_id = om.id
        """
    )
    op.alter_column("knowledge_reviews", "reviewer", nullable=False)
    op.drop_column("knowledge_reviews", "reviewer_membership_id")
    op.drop_column("knowledge_reviews", "organization_id")
    op.create_foreign_key(
        None, "knowledge_reviews", "knowledge_drafts", ["draft_id"], ["id"]
    )

    op.drop_constraint(
        "fk_draft_conversations_organization_conversation",
        "knowledge_draft_conversations",
        type_="foreignkey",
    )
    op.drop_constraint(
        "fk_draft_conversations_organization_draft",
        "knowledge_draft_conversations",
        type_="foreignkey",
    )
    op.drop_constraint(
        "knowledge_draft_conversations_pkey",
        "knowledge_draft_conversations",
        type_="primary",
    )
    op.create_primary_key(
        None, "knowledge_draft_conversations", ["draft_id", "conversation_id"]
    )
    op.create_foreign_key(
        None,
        "knowledge_draft_conversations",
        "knowledge_drafts",
        ["draft_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_foreign_key(
        None,
        "knowledge_draft_conversations",
        "conversations",
        ["conversation_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.drop_column("knowledge_draft_conversations", "organization_id")

    op.drop_index(
        op.f("ix_knowledge_drafts_organization_id"), table_name="knowledge_drafts"
    )
    op.drop_constraint(
        "uq_knowledge_drafts_organization_id", "knowledge_drafts", type_="unique"
    )
    op.drop_constraint(
        "fk_knowledge_drafts_organization_topic", "knowledge_drafts", type_="foreignkey"
    )
    op.drop_constraint(
        "fk_knowledge_drafts_organization_id", "knowledge_drafts", type_="foreignkey"
    )
    op.create_foreign_key(None, "knowledge_drafts", "topics", ["topic_id"], ["id"])
    op.drop_column("knowledge_drafts", "organization_id")

    op.drop_index(op.f("ix_conversations_organization_id"), table_name="conversations")
    op.drop_constraint(
        "uq_conversations_organization_id", "conversations", type_="unique"
    )
    op.drop_constraint(
        "uq_conversations_organization_source_original", "conversations", type_="unique"
    )
    op.drop_constraint(
        "uq_conversations_organization_curated_id", "conversations", type_="unique"
    )
    op.drop_constraint(
        "fk_conversations_organization_topic", "conversations", type_="foreignkey"
    )
    op.drop_constraint(
        "fk_conversations_organization_agent", "conversations", type_="foreignkey"
    )
    op.drop_constraint(
        "fk_conversations_organization_id", "conversations", type_="foreignkey"
    )
    op.create_foreign_key(None, "conversations", "agents", ["agent_id"], ["id"])
    op.create_foreign_key(None, "conversations", "topics", ["topic_id"], ["id"])
    op.create_unique_constraint(
        None, "conversations", ["source_dataset", "original_id"]
    )
    # This can fail if multiple organizations now share a curated source ID.
    op.create_unique_constraint(None, "conversations", ["curated_id"])
    op.drop_column("conversations", "organization_id")

    op.drop_index(op.f("ix_topics_organization_id"), table_name="topics")
    op.drop_constraint("uq_topics_organization_id", "topics", type_="unique")
    op.drop_constraint("uq_topics_organization_source_name", "topics", type_="unique")
    op.drop_constraint("fk_topics_organization_id", "topics", type_="foreignkey")
    op.create_unique_constraint(None, "topics", ["source_dataset", "name"])
    op.drop_column("topics", "organization_id")

    op.drop_index(op.f("ix_agents_organization_id"), table_name="agents")
    op.drop_constraint("uq_agents_organization_id", "agents", type_="unique")
    op.drop_constraint("uq_agents_organization_external_id", "agents", type_="unique")
    op.drop_constraint("fk_agents_organization_id", "agents", type_="foreignkey")
    # This can fail if multiple organizations now share an agent external ID.
    op.create_unique_constraint(None, "agents", ["external_id"])
    op.drop_column("agents", "organization_id")

    op.drop_index(
        op.f("ix_organization_memberships_user_id"),
        table_name="organization_memberships",
    )
    op.drop_index(
        op.f("ix_organization_memberships_organization_id"),
        table_name="organization_memberships",
    )
    op.drop_table("organization_memberships")
    op.drop_table("users")
    op.drop_table("organizations")
