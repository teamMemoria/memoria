"""Exercise the lifecycle backfill against populated pre-change tables."""

import os
import subprocess
import sys

import psycopg
from psycopg import sql
from sqlalchemy import make_url

from tests.conftest import ADMIN_URL, BACKEND_DIR, TEST_DATABASE_URL


def test_existing_review_is_backfilled_and_migration_round_trips():
    url = make_url(TEST_DATABASE_URL).set(drivername="postgresql")
    name = url.database + "_flag_migration"
    direct_url = url.set(database=name).render_as_string(hide_password=False)
    env = {
        **os.environ,
        "DATABASE_URL": url.set(
            drivername="postgresql+psycopg", database=name
        ).render_as_string(hide_password=False),
    }

    def migrate(command, revision):
        subprocess.run(
            [sys.executable, "-m", "alembic", command, revision],
            cwd=BACKEND_DIR,
            env=env,
            check=True,
            capture_output=True,
        )

    with psycopg.connect(ADMIN_URL, autocommit=True) as admin:
        admin.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(name)))
    try:
        with psycopg.connect(direct_url, autocommit=True) as conn:
            conn.execute("CREATE EXTENSION vector")
        migrate("upgrade", "92c6a85f041d")
        with psycopg.connect(direct_url) as conn:
            org = conn.execute(
                "SELECT id FROM organizations WHERE slug = 'default'"
            ).fetchone()[0]
            agent = conn.execute(
                "INSERT INTO agents (organization_id, external_id) VALUES (%s, 'legacy') RETURNING id",
                (org,),
            ).fetchone()[0]
            call = conn.execute(
                "INSERT INTO conversations (organization_id, source_dataset, original_id, channel, agent_id) "
                "VALUES (%s, 'test', 'legacy', 'voice', %s) RETURNING id",
                (org, agent),
            ).fetchone()[0]
            version = conn.execute(
                "SELECT id FROM evaluation_form_versions LIMIT 1"
            ).fetchone()[0]
            audit = conn.execute(
                "INSERT INTO audits (organization_id, conversation_id, evaluation_form_version_id) "
                "VALUES (%s, %s, %s) RETURNING id",
                (org, call, version),
            ).fetchone()[0]
            finding = conn.execute(
                "INSERT INTO findings (organization_id, audit_id, category, result, feedback) "
                "VALUES (%s, %s, 'procedure', 'needs_work', 'Check') RETURNING id",
                (org, audit),
            ).fetchone()[0]
            flag = conn.execute(
                "INSERT INTO feedback_flags (organization_id, finding_id, agent_id, reason) "
                "VALUES (%s, %s, %s, 'Review') RETURNING id",
                (org, finding, agent),
            ).fetchone()[0]
            user = conn.execute(
                "INSERT INTO users (external_id, display_name) VALUES ('legacy-manager', 'Manager') RETURNING id"
            ).fetchone()[0]
            member = conn.execute(
                "INSERT INTO organization_memberships (organization_id, user_id, role) "
                "VALUES (%s, %s, 'manager') RETURNING id",
                (org, user),
            ).fetchone()[0]
            conn.execute(
                "INSERT INTO manager_reviews (organization_id, feedback_flag_id, reviewer_membership_id, outcome, reason, feedback) "
                "VALUES (%s, %s, %s, 'confirmed', 'Checked', 'Follow guidance')",
                (org, flag, member),
            )
        for command, revision in [
            ("upgrade", "head"),
            ("downgrade", "-1"),
            ("upgrade", "head"),
        ]:
            migrate(command, revision)
        with psycopg.connect(direct_url) as conn:
            row = conn.execute(
                "SELECT f.status, f.resolved_at, r.reviewed_at, r.reviewer_membership_id "
                "FROM feedback_flags f JOIN manager_reviews r ON r.feedback_flag_id = f.id"
            ).fetchone()
            assert row[0] == "resolved" and row[1] == row[2]
            assert row[3] == member
    finally:
        with psycopg.connect(ADMIN_URL, autocommit=True) as admin:
            admin.execute(
                sql.SQL("DROP DATABASE {} WITH (FORCE)").format(sql.Identifier(name))
            )
