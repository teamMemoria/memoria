import os
import subprocess
import sys
from pathlib import Path

import psycopg

ADMIN_URL = os.getenv(
    "TEST_ADMIN_URL", "postgresql://app:app@localhost:5432/callassist"
)
MIGRATION_DB = "callassist_organization_migration_test"
MIGRATION_URL = ADMIN_URL.rsplit("/", 1)[0] + f"/{MIGRATION_DB}"
ALEMBIC_URL = MIGRATION_URL.replace("postgresql://", "postgresql+psycopg://", 1)
SOURCE_DIR = Path(__file__).resolve().parents[1] / "src"


def alembic_env() -> dict[str, str]:
    return {
        **os.environ,
        "DATABASE_URL": ALEMBIC_URL,
        "PYTHONPATH": str(SOURCE_DIR),
    }


def run_alembic(revision: str) -> None:
    subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", revision],
        env=alembic_env(),
        check=True,
        capture_output=True,
    )


def test_populated_database_is_backfilled_without_losing_reviewer_names():
    with psycopg.connect(ADMIN_URL, autocommit=True) as conn:
        conn.execute(f"DROP DATABASE IF EXISTS {MIGRATION_DB} WITH (FORCE)")
        conn.execute(f"CREATE DATABASE {MIGRATION_DB}")

    try:
        with psycopg.connect(MIGRATION_URL, autocommit=True) as conn:
            conn.execute("CREATE EXTENSION IF NOT EXISTS vector")
        run_alembic("4024e756007c")

        with psycopg.connect(MIGRATION_URL, autocommit=True) as conn:
            agent_id = conn.execute(
                "INSERT INTO agents (external_id) VALUES ('legacy-agent') RETURNING id"
            ).fetchone()[0]
            topic_id = conn.execute(
                """
                INSERT INTO topics (source_dataset, name)
                VALUES ('HarperValleyBank', 'Card replacement')
                RETURNING id
                """
            ).fetchone()[0]
            conversation_id = conn.execute(
                """
                INSERT INTO conversations (
                    source_dataset, original_id, channel, agent_id, topic_id,
                    curated_id
                )
                VALUES (
                    'HarperValleyBank', 'legacy-call', 'voice', %s, %s,
                    'HVB-LEGACY'
                )
                RETURNING id
                """,
                (agent_id, topic_id),
            ).fetchone()[0]
            draft_id = conn.execute(
                """
                INSERT INTO knowledge_drafts (topic_id, answer_text, status)
                VALUES (%s, 'Legacy answer', 'pending')
                RETURNING id
                """,
                (topic_id,),
            ).fetchone()[0]
            conn.execute(
                """
                INSERT INTO knowledge_draft_conversations (draft_id, conversation_id)
                VALUES (%s, %s)
                """,
                (draft_id, conversation_id),
            )
            review_id = conn.execute(
                """
                INSERT INTO knowledge_reviews (draft_id, action, reviewer)
                VALUES (%s, 'approved', 'Legacy Manager')
                RETURNING id
                """,
                (draft_id,),
            ).fetchone()[0]
            entry_id = conn.execute(
                """
                INSERT INTO knowledge_entries (
                    topic_id, answer_text, status, approved_review_id
                )
                VALUES (%s, 'Legacy answer', 'approved', %s)
                RETURNING id
                """,
                (topic_id, review_id),
            ).fetchone()[0]
            audit_id = conn.execute(
                "INSERT INTO audits (conversation_id) VALUES (%s) RETURNING id",
                (conversation_id,),
            ).fetchone()[0]
            conn.execute(
                """
                INSERT INTO findings (
                    audit_id, category, result, feedback, knowledge_entry_id
                )
                VALUES (%s, 'answer_support', 'pass', 'Supported', %s)
                """,
                (audit_id, entry_id),
            )

        run_alembic("head")

        with psycopg.connect(MIGRATION_URL) as conn:
            default_org_id = conn.execute(
                "SELECT id FROM organizations WHERE slug = 'default'"
            ).fetchone()[0]
            for table in (
                "agents",
                "topics",
                "conversations",
                "knowledge_drafts",
                "knowledge_draft_conversations",
                "knowledge_reviews",
                "knowledge_entries",
                "audits",
                "findings",
            ):
                assert conn.execute(
                    f"SELECT DISTINCT organization_id FROM {table}"
                ).fetchall() == [(default_org_id,)]

            assert conn.execute(
                """
                SELECT u.display_name, om.role
                FROM knowledge_reviews AS kr
                JOIN organization_memberships AS om
                  ON om.id = kr.reviewer_membership_id
                JOIN users AS u ON u.id = om.user_id
                """
            ).fetchall() == [("Legacy Manager", "manager")]

        subprocess.run(
            [sys.executable, "-m", "alembic", "downgrade", "-1"],
            env=alembic_env(),
            check=True,
            capture_output=True,
        )
        with psycopg.connect(MIGRATION_URL) as conn:
            assert conn.execute(
                "SELECT reviewer FROM knowledge_reviews"
            ).fetchall() == [("Legacy Manager",)]
        run_alembic("head")
    finally:
        with psycopg.connect(ADMIN_URL, autocommit=True) as conn:
            conn.execute(f"DROP DATABASE IF EXISTS {MIGRATION_DB} WITH (FORCE)")
