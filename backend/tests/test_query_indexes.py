from sqlalchemy import inspect, text

from tests.query_plan_fixture import explain_query_plans, seed_query_plan_fixture


async def test_every_foreign_key_has_a_leading_index_in_migrated_schema(session):
    def check(sync_session):
        inspector = inspect(sync_session.connection())
        for table in inspector.get_table_names():
            indexes = [tuple(inspector.get_pk_constraint(table)["constrained_columns"])]
            indexes += [
                tuple(value["column_names"])
                for value in inspector.get_unique_constraints(table)
            ]
            indexes += [
                tuple(value["column_names"])
                for value in inspector.get_indexes(table)
                if not value.get("dialect_options", {}).get("postgresql_where")
            ]
            for foreign_key in inspector.get_foreign_keys(table):
                columns = tuple(foreign_key["constrained_columns"])
                assert any(index[: len(columns)] == columns for index in indexes), (
                    table,
                    columns,
                )

    await session.run_sync(check)


async def test_vector_indexes_keep_hnsw_cosine_operator_class(session):
    rows = (
        await session.execute(
            text(
                "SELECT tablename, indexdef FROM pg_indexes WHERE indexname IN "
                "('ix_knowledge_entries_embedding_hnsw', 'ix_knowledge_drafts_embedding_hnsw')"
            )
        )
    ).all()
    assert {row.tablename for row in rows} == {"knowledge_entries", "knowledge_drafts"}
    assert all(
        "USING hnsw" in row.indexdef and "vector_cosine_ops" in row.indexdef
        for row in rows
    )


def nodes(plan):
    yield plan
    for child in plan.get("Plans", []):
        yield from nodes(child)


async def test_main_query_plans_use_indexes_without_forcing_planner(session):
    def check(sync_session):
        conn = sync_session.connection()
        parameters = seed_query_plan_fixture(conn)
        plans = explain_query_plans(conn, parameters, json=True)
        large_tables = {"conversations", "audits", "findings", "knowledge_entries"}
        for name, output in plans.items():
            all_nodes = list(nodes(output["Plan"]))
            assert any("Index" in node["Node Type"] for node in all_nodes), (
                name,
                output,
            )
            assert not any(
                node["Node Type"] == "Seq Scan"
                and node.get("Relation Name") in large_tables
                for node in all_nodes
            ), (name, output)
        vector_nodes = list(nodes(plans["Vector cosine similarity"]["Plan"]))
        assert any(
            node.get("Index Name") == "ix_knowledge_entries_embedding_hnsw"
            for node in vector_nodes
        )

    await session.run_sync(check)
