"""Synthetic workload shared by query-plan tests and the scratch-only report."""

from sqlalchemy import text


def seed_query_plan_fixture(conn):
    org = conn.execute(
        text(
            "INSERT INTO organizations (slug, name) VALUES ('index-benchmark', 'Synthetic index benchmark') RETURNING id"
        )
    ).scalar_one()
    conn.execute(
        text(
            "INSERT INTO agents (organization_id, external_id) "
            "SELECT :org, 'benchmark-' || n FROM generate_series(1, 200) n"
        ),
        {"org": org},
    )
    conn.execute(
        text(
            "INSERT INTO topics (organization_id, source_dataset, name) "
            "SELECT :org, 'synthetic', 'Topic ' || n FROM generate_series(1, 100) n"
        ),
        {"org": org},
    )
    agents = conn.execute(
        text("SELECT array_agg(id ORDER BY id) FROM agents WHERE organization_id=:org"),
        {"org": org},
    ).scalar_one()
    topics = conn.execute(
        text("SELECT array_agg(id ORDER BY id) FROM topics WHERE organization_id=:org"),
        {"org": org},
    ).scalar_one()
    conn.execute(
        text("""
        INSERT INTO conversations (organization_id, source_dataset, original_id,
            channel, agent_id, topic_id, synthetic_started_at, conversation_date)
        SELECT :org, 'synthetic', 'benchmark-' || n, 'voice',
            (CAST(:agents AS integer[]))[1 + (n % 200)],
            (CAST(:topics AS integer[]))[1 + (n % 100)],
            TIMESTAMPTZ '2026-01-01 00:00:00+00' + (n % 56) * INTERVAL '1 day' + n * INTERVAL '1 second',
            DATE '2026-01-01' + (n % 56)
        FROM generate_series(1, 20000) n
    """),
        {"org": org, "agents": agents, "topics": topics},
    )
    version = conn.execute(
        text("SELECT id FROM evaluation_form_versions LIMIT 1")
    ).scalar_one()
    conn.execute(
        text("""
        INSERT INTO audits (organization_id, conversation_id, evaluation_form_version_id, summary)
        SELECT :org, id, :version, repeat('Synthetic audit summary. ', 20) FROM conversations WHERE organization_id=:org
    """),
        {"org": org, "version": version},
    )
    conn.execute(
        text("""
        INSERT INTO findings (organization_id, audit_id, category, result, feedback)
        SELECT :org, a.id, category,
            CASE a.id % 3 WHEN 0 THEN 'cannot_assess' WHEN 1 THEN 'pass' ELSE 'needs_work' END,
            'Synthetic benchmark feedback'
        FROM audits a CROSS JOIN unnest(ARRAY['procedure','answer_support','completeness','communication']) category
        WHERE a.organization_id=:org
    """),
        {"org": org},
    )
    user = conn.execute(
        text(
            "INSERT INTO users (external_id, display_name) VALUES ('index-benchmark-manager', 'Synthetic Manager') RETURNING id"
        )
    ).scalar_one()
    member = conn.execute(
        text(
            "INSERT INTO organization_memberships (organization_id, user_id, role) VALUES (:org, :user, 'manager') RETURNING id"
        ),
        {"org": org, "user": user},
    ).scalar_one()
    conn.execute(
        text("""
        INSERT INTO knowledge_drafts (organization_id, topic_id, answer_text, status)
        SELECT :org, (CAST(:topics AS integer[]))[1 + n % 100], 'Synthetic answer ' || n, 'approved'
        FROM generate_series(1, 5000) n
    """),
        {"org": org, "topics": topics},
    )
    conn.execute(
        text("""
        INSERT INTO knowledge_reviews (organization_id, draft_id, action, reviewer_membership_id)
        SELECT :org, id, 'approved', :member FROM knowledge_drafts WHERE organization_id=:org
    """),
        {"org": org, "member": member},
    )
    conn.execute(
        text("""
        INSERT INTO knowledge_entries (organization_id, topic_id, answer_text, status, approved_review_id, embedding)
        SELECT :org, d.topic_id, d.answer_text,
            CASE d.id % 3 WHEN 0 THEN 'disputed' ELSE 'approved' END, r.id,
            (ARRAY[(1 + d.id % 101)::real, (1 + d.id % 37)::real] || array_fill(0.01::real, ARRAY[1534]))::vector
        FROM knowledge_drafts d JOIN knowledge_reviews r ON r.draft_id=d.id
        WHERE d.organization_id=:org
    """),
        {"org": org},
    )
    conn.execute(
        text("ANALYZE conversations, audits, findings, knowledge_entries, topics")
    )
    return {
        "org": org,
        "agent": agents[0],
        "topic": topics[0],
        "vector": "[1,1," + ",".join(["0.01"] * 1534) + "]",
    }


def benchmark_queries():
    joins = """
        FROM conversations c
        JOIN audits a ON a.conversation_id=c.id
        JOIN findings f ON f.audit_id=a.id
        WHERE c.organization_id=:org AND c.agent_id=:agent
          AND c.synthetic_started_at >= TIMESTAMPTZ '2026-01-01'
          AND c.synthetic_started_at < TIMESTAMPTZ '2026-03-01'
    """
    counts = """
        count(*) FILTER (WHERE f.result='pass') AS passes,
        count(*) FILTER (WHERE f.result='needs_work') AS needs_work,
        count(*) FILTER (WHERE f.result='cannot_assess') AS cannot_assess
    """
    return {
        "Recent agent audits": """
            SELECT a.id, c.synthetic_started_at FROM conversations c
            JOIN audits a ON a.conversation_id=c.id
            WHERE c.organization_id=:org AND c.agent_id=:agent
              AND c.synthetic_started_at >= TIMESTAMPTZ '2026-01-01'
            ORDER BY c.synthetic_started_at DESC LIMIT 20
        """,
        "Knowledge by topic and status": """
            SELECT id, answer_text FROM knowledge_entries
            WHERE organization_id=:org AND topic_id=:topic AND status='approved'
            ORDER BY id LIMIT 10
        """,
        "Weekly category progress": "SELECT date_trunc('week', c.synthetic_started_at, 'UTC'), f.category, "
        + counts
        + joins
        + " GROUP BY 1, 2 ORDER BY 1, 2",
        "Weekly overall progress": "SELECT date_trunc('week', c.synthetic_started_at, 'UTC'), "
        + counts
        + joins
        + " GROUP BY 1 ORDER BY 1",
        "Vector cosine similarity": """
            SELECT id FROM knowledge_entries
            WHERE organization_id=:org AND status='approved'
            ORDER BY embedding <=> CAST(:vector AS vector) LIMIT 5
        """,
    }


def explain_query_plans(conn, parameters, *, json=False):
    prefix = (
        "EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) "
        if json
        else "EXPLAIN (ANALYZE, BUFFERS) "
    )
    result = {}
    for name, query in benchmark_queries().items():
        rows = conn.execute(text(prefix + query), parameters)
        result[name] = (
            rows.scalar_one()[0] if json else "\n".join(row[0] for row in rows)
        )
    return result


def main():
    from sqlalchemy import create_engine, make_url

    from backend.core.config import get_settings

    url = make_url(get_settings().database_url)
    if not url.database or not url.database.endswith("_index_benchmark"):
        raise SystemExit(
            "Use a disposable database named *_index_benchmark; refusing other databases"
        )
    engine = create_engine(url)
    try:
        with engine.connect() as conn:
            parameters = seed_query_plan_fixture(conn)
            print("# Query plans on synthetic scratch data\n")
            print("Postgres 17/pgvector; 200 agents, 100 topics, 20,000 conversations,")
            print(
                "20,000 audits, 80,000 findings, 5,000 knowledge entries (1,536 dimensions)."
            )
            print(
                "Audits include a 500-byte synthetic summary, representing stored report text."
            )
            print(
                "Default planner settings; ANALYZE run after seeding; no scan types disabled.\n"
            )
            print(
                "Data is rolled back when this report exits. Timings are illustrative.\n"
            )
            for name, plan in explain_query_plans(conn, parameters).items():
                plan = plan.replace(
                    parameters["vector"], "<1536-dimensional vector; literal elided>"
                )
                print(f"## {name}\n\n```text\n{plan}\n```\n")
            conn.rollback()
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()
