# Query plans on synthetic scratch data

Postgres 17/pgvector; 200 agents, 100 topics, 20,000 conversations,
20,000 audits, 80,000 findings, 5,000 knowledge entries (1,536 dimensions).
Audits include a 500-byte synthetic summary, representing stored report text.
Default planner settings; ANALYZE run after seeding; no scan types disabled.

Data is rolled back when this report exits. Timings are illustrative.

## Recent agent audits

```text
Limit  (cost=0.57..175.14 rows=20 width=12) (actual time=0.044..0.923 rows=20 loops=1)
  Buffers: shared hit=24 read=58 written=58
  ->  Nested Loop  (cost=0.57..873.41 rows=100 width=12) (actual time=0.043..0.920 rows=20 loops=1)
        Buffers: shared hit=24 read=58 written=58
        ->  Index Scan Backward using ix_conversations_org_agent_started on conversations c  (cost=0.29..174.91 rows=100 width=12) (actual time=0.030..0.283 rows=20 loops=1)
              Index Cond: ((organization_id = '3'::smallint) AND (agent_id = '201'::smallint) AND (synthetic_started_at >= '2026-01-01 00:00:00+00'::timestamp with time zone))
              Buffers: shared read=22 written=22
        ->  Index Scan using audits_conversation_id_key on audits a  (cost=0.29..6.98 rows=1 width=8) (actual time=0.031..0.031 rows=1 loops=20)
              Index Cond: (conversation_id = c.id)
              Buffers: shared hit=24 read=36 written=36
Planning:
  Buffers: shared hit=174 read=303 dirtied=65 written=303
Planning Time: 2.412 ms
Execution Time: 0.933 ms
```

## Knowledge by topic and status

```text
Limit  (cost=60.49..60.51 rows=10 width=25) (actual time=0.024..0.024 rows=10 loops=1)
  Buffers: shared hit=35
  ->  Sort  (cost=60.49..60.57 rows=33 width=25) (actual time=0.024..0.024 rows=10 loops=1)
        Sort Key: id
        Sort Method: top-N heapsort  Memory: 25kB
        Buffers: shared hit=35
        ->  Index Scan using ix_knowledge_entries_org_topic_status on knowledge_entries  (cost=0.28..59.77 rows=33 width=25) (actual time=0.003..0.017 rows=33 loops=1)
              Index Cond: ((organization_id = '3'::smallint) AND (topic_id = '101'::smallint) AND ((status)::text = 'approved'::text))
              Buffers: shared hit=35
Planning:
  Buffers: shared hit=69 read=7 written=7
Planning Time: 0.159 ms
Execution Time: 0.028 ms
```

## Weekly category progress

```text
GroupAggregate  (cost=1004.30..1018.30 rows=400 width=44) (actual time=1.729..1.764 rows=28 loops=1)
  Group Key: (date_trunc('week'::text, c.synthetic_started_at, 'UTC'::text)), f.category
  Buffers: shared hit=866 read=236 written=236
  ->  Sort  (cost=1004.30..1005.30 rows=400 width=30) (actual time=1.719..1.728 rows=400 loops=1)
        Sort Key: (date_trunc('week'::text, c.synthetic_started_at, 'UTC'::text)), f.category
        Sort Method: quicksort  Memory: 44kB
        Buffers: shared hit=866 read=236 written=236
        ->  Nested Loop  (cost=0.99..987.01 rows=400 width=30) (actual time=0.068..1.673 rows=400 loops=1)
              Buffers: shared hit=866 read=236 written=236
              ->  Nested Loop  (cost=0.57..873.66 rows=100 width=12) (actual time=0.018..0.937 rows=100 loops=1)
                    Buffers: shared hit=234 read=168 written=168
                    ->  Index Scan using ix_conversations_org_agent_started on conversations c  (cost=0.29..175.16 rows=100 width=12) (actual time=0.012..0.378 rows=100 loops=1)
                          Index Cond: ((organization_id = '3'::smallint) AND (agent_id = '201'::smallint) AND (synthetic_started_at >= '2026-01-01 00:00:00+00'::timestamp with time zone) AND (synthetic_started_at < '2026-03-01 00:00:00+00'::timestamp with time zone))
                          Buffers: shared hit=23 read=79 written=79
                    ->  Index Scan using audits_conversation_id_key on audits a  (cost=0.29..6.98 rows=1 width=8) (actual time=0.005..0.005 rows=1 loops=100)
                          Index Cond: (conversation_id = c.id)
                          Buffers: shared hit=211 read=89 written=89
              ->  Index Scan using findings_audit_id_category_key on findings f  (cost=0.42..1.08 rows=4 width=26) (actual time=0.004..0.006 rows=4 loops=100)
                    Index Cond: (audit_id = a.id)
                    Buffers: shared hit=632 read=68 written=68
Planning:
  Buffers: shared hit=349 read=220 dirtied=76 written=220
Planning Time: 2.115 ms
Execution Time: 1.776 ms
```

## Weekly overall progress

```text
Sort  (cost=998.59..998.84 rows=100 width=32) (actual time=0.388..0.389 rows=7 loops=1)
  Sort Key: (date_trunc('week'::text, c.synthetic_started_at, 'UTC'::text))
  Sort Method: quicksort  Memory: 25kB
  Buffers: shared hit=1102
  ->  HashAggregate  (cost=994.01..995.26 rows=100 width=32) (actual time=0.386..0.387 rows=7 loops=1)
        Group Key: date_trunc('week'::text, c.synthetic_started_at, 'UTC'::text)
        Batches: 1  Memory Usage: 24kB
        Buffers: shared hit=1102
        ->  Nested Loop  (cost=0.99..987.01 rows=400 width=18) (actual time=0.010..0.352 rows=400 loops=1)
              Buffers: shared hit=1102
              ->  Nested Loop  (cost=0.57..873.66 rows=100 width=12) (actual time=0.006..0.116 rows=100 loops=1)
                    Buffers: shared hit=402
                    ->  Index Scan using ix_conversations_org_agent_started on conversations c  (cost=0.29..175.16 rows=100 width=12) (actual time=0.004..0.031 rows=100 loops=1)
                          Index Cond: ((organization_id = '3'::smallint) AND (agent_id = '201'::smallint) AND (synthetic_started_at >= '2026-01-01 00:00:00+00'::timestamp with time zone) AND (synthetic_started_at < '2026-03-01 00:00:00+00'::timestamp with time zone))
                          Buffers: shared hit=102
                    ->  Index Scan using audits_conversation_id_key on audits a  (cost=0.29..6.98 rows=1 width=8) (actual time=0.001..0.001 rows=1 loops=100)
                          Index Cond: (conversation_id = c.id)
                          Buffers: shared hit=300
              ->  Index Scan using findings_audit_id_category_key on findings f  (cost=0.42..1.08 rows=4 width=14) (actual time=0.001..0.001 rows=4 loops=100)
                    Index Cond: (audit_id = a.id)
                    Buffers: shared hit=700
Planning:
  Buffers: shared hit=295 read=92 dirtied=26 written=92
Planning Time: 0.929 ms
Execution Time: 0.402 ms
```

## Vector cosine similarity

```text
Limit  (cost=137.82..187.59 rows=5 width=12) (actual time=0.302..0.315 rows=5 loops=1)
  Buffers: shared hit=433
  ->  Index Scan using ix_knowledge_entries_embedding_hnsw on knowledge_entries  (cost=137.82..33312.83 rows=3333 width=12) (actual time=0.302..0.314 rows=5 loops=1)
        Order By: (embedding <=> '<1536-dimensional vector; literal elided>'::vector)
        Filter: ((organization_id = '3'::smallint) AND ((status)::text = 'approved'::text))
        Rows Removed by Filter: 2
        Buffers: shared hit=433
Planning:
  Buffers: shared hit=17 read=1 written=1
Planning Time: 0.048 ms
Execution Time: 0.323 ms
```


The query definitions and synthetic seed are in `tests/query_plan_fixture.py`.
From `backend/`, point `DATABASE_URL` at a disposable migrated database whose
name ends in `_index_benchmark` and run:

```sh
uv run python -m tests.query_plan_fixture
```

The command refuses other database names and rolls back its synthetic rows.
Plans use the default PostgreSQL planner, with no scan types disabled. The
progress SELECTs use the same conversation → audit → finding joins, date bounds,
UTC grouping and result counts as the category/overall queries in #102. Existing
foreign-key/unique indexes are reused where the planner prefers them.

These measurements establish index use on this workload, not production latency
or a guarantee that every dataset will choose the same plan. With very narrow
audits lacking report text, an initial fixture correctly chose an audit scan;
using stored-summary-sized rows made indexed lookup cheaper. Small tables and
broad queries can reasonably use sequential scans. HNSW is approximate nearest
neighbor search; selective topic filtering may favor the topic/status B-tree
instead of HNSW.
