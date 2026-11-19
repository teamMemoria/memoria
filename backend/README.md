# Backend

## Railway deployment (issue #157)

Create a Railway service from `teamMemoria/memoria` with **Root Directory**
`/` and **Dockerfile Path** `/backend/Dockerfile` (or set the service variable
`RAILWAY_DOCKERFILE_PATH=/backend/Dockerfile`). The repository root must be the
build context because the backend imports code from the sibling `ml/` directory.
The Dockerfile copies that directory into the image. It uses Python
3.13 and installs the production dependencies from `uv.lock` with
`uv sync --locked --no-dev`; no dashboard build or start command is needed.
The image runs `./start.sh`, which applies Alembic migrations and starts
`backend.main:app` on `0.0.0.0:${PORT:-8000}` without reload.

Set the Railway service variable `DATABASE_URL` to the hosted PostgreSQL
connection string using the `postgresql+psycopg://` driver. Derek's database
must have the `vector` extension enabled before the first deploy. Do not put
the connection string in Git or deployment notes. Set the Railway healthcheck
path to `/health` and generate a public HTTPS domain. `/ready` checks database
connectivity separately. Keep one backend replica while migrations run in the
startup script; with multiple replicas, move migrations to a one-time deploy
step first.

Merge the reviewed deployment changes into `main`, then deploy that `main`
commit. In Railway, check the build log for the Dockerfile and locked dependency
install, then the startup log for successful
Alembic migration and Uvicorn binding. Confirm `GET https://<backend-domain>/health`
returns HTTP 200 and `{"status":"ok"}`. Restart or redeploy the service and
repeat the check. Record the deployed Git commit and public backend URL in the
issue once verified, and give Rayaan the URL for the frontend API setting.

Deployment record (fill after the hosted checks):

| Item | Value |
| --- | --- |
| Railway service | Pending |
| Backend URL | Pending |
| Deployed Git commit and branch | Pending |
| Build and startup logs checked | Pending |
| `/health` after deploy and restart | Pending |

## Validate and profile conversations

From the `backend` directory, run the validator against the supplied curated
conversation directory:

```bash
uv run profile-conversations /path/to/uoft-ftli-2026-genesys-docs/curated/conversations
```

The command validates every JSON file before printing a deterministic profile.
Validation errors are written to stderr with the filename and field, and the
command exits with status 1 without printing a partial profile.

The current 200-file corpus is pinned at commit
`c39d2e0610417256bf05811b774d400deea7456f` of
`marcomarchesanogenesys/uoft-ftli-2026-genesys-docs`. Keep those real
conversation files in the source repository; do not copy them into Memoria.

## Tests

Tests run against a separate `callassist_test` database that is dropped, recreated
and migrated at the start of each run, so they never touch your local data. With
the database running:

    uv run pytest

## Importing the curated conversations

`uv run setup-demo` runs all four steps below in order (import, topics, dates,
demo profiles). It is also what `docker compose up` runs; see "Running it
locally" in the top-level README. The steps can still be run one at a time:

The conversation data lives in the
[uoft-ftli-2026-genesys-docs](https://github.com/marcomarchesanogenesys/uoft-ftli-2026-genesys-docs)
repo, not here. Clone it next to this repo, then from `backend/` with the database
migrated:

    uv run import-conversations ../../uoft-ftli-2026-genesys-docs/curated/conversations

It is safe to run again; existing conversations and turns are updated in place.
Don't copy the dataset files into this repo.

Then give every conversation a topic. The label-to-topic mapping is in
`src/backend/data/topic_mapping.toml`; edit it and re-run to change topics:

    uv run assign-topics

Finally, spread the conversations over an 8-week timeline. These times are
generated (fixed seed, so always the same) and stored in
`synthetic_started_at`, separate from any real source date:

    uv run assign-synthetic-dates

Then create the demo profiles offered on the entry screen: 31 Agents from the
ABCD training conversations and one Manager, listed in
`src/backend/data/demo_profiles.toml`. Each Agent is linked to the imported
conversations listed for it; nothing is assessed, reviewed or approved:

    uv run seed-demo-profiles

To use them from the frontend, start the backend with
`MEMORIA_APP_ENV=development` and the frontend with `npm run dev`. Runtime
requests use the database; fixture providers are injected only by tests.

See [the dashboard entry guide](../frontend/DEMO-BACKEND.md) for the single-backend
setup, supported assessment views and current read-only knowledge limitation.

Each data command accepts `--organization <slug>` and defaults to the
migration-created `default` organization.

## Conversation metrics

Importing a conversation creates or updates its one `conversation_metrics` row.
All values are derived from the source record; re-importing recalculates them.

- All channels: `turn_count`, agent/customer word counts, and agent/customer
  text shares (fractions from 0 to 1).
- HarperValleyBank voice: `call_elapsed_ms`, agent/customer speaking time in
  milliseconds, `average_turn_duration_ms`, `asr_word_error_rate` (word errors
  divided by reference words), and `asr_compared_turn_count`.
- ABCD chat: `system_action_count` (system-action turns) and
  `documented_action_count` (entries in `source_fields.actions_taken`).

Channel-specific fields are `NULL` when unsupported or unavailable. Voice
timing requires complete timing data for all agent and customer turns.

## Evaluation set

`evaluation/` holds the scoring rubric and the score sheet for the
evaluation set. The scores in the sheet so far are AI-generated, not human
(see `evaluation/README.md`). The conversations in the sheet were picked by
`select-eval-set`. To check the selection again without touching the sheet,
write it somewhere else:

    uv run select-eval-set --out evaluation/new_selection.csv

`select-eval-set` won't replace an existing file, so it can't wipe recorded
scores. Pass `--overwrite` only when you mean to start the sheet again.

## Provenance manifests

Generated artifacts store their provenance in a JSON sidecar beside the
artifact. The sidecar name is `<artifact filename>.provenance.json`; for
example, `evaluation.csv` uses `evaluation.csv.provenance.json`. Call
`write_manifest(artifact_path, manifest)` from `backend.data.provenance` to
apply this convention and write deterministic JSON.

## Agent progress scores

`backend.db.performance_trends` provides
`get_agent_weekly_category_scores(session, organization_id=..., agent_id=..., window=...)`
and `get_agent_overall_trend` with the same arguments. Both use the conversations'
synthetic timestamps and a `DateWindow(start, end)` with timezone-aware bounds.
The window includes start and excludes end, including only in-range calls in
partial first/last weeks. Weeks begin Monday at 00:00 UTC, independently of the
Postgres session's timezone.

Each `WeeklyScore` includes counts and `average_score`: pass = 1, needs work = 0,
with `cannot_assess` excluded from the denominator. Category scores combine all
topics for that category. Overall scores count all assessed findings directly,
so they weight each assessed finding equally rather than averaging category or
topic percentages. Scores range from 0 to 1.

Every week intersecting the window is returned, with all categories for the
category query. Weeks with no calls and buckets containing only `cannot_assess`
findings return `None` for the average, allowing a graph to show a gap instead
of a failure. Queries require both the agent and organization IDs; no other
agent's findings contribute. Existing topic-level trend/comparison queries
remain available.

## Database index verification

Tenant-scoped foreign-key indexes, conversation date indexes, and knowledge
status/topic indexes are declared in
`src/backend/frameworks/database/models/indexes.py` and created by Alembic.
Existing primary/unique indexes and HNSW cosine indexes are retained.

The full suite verifies foreign-key index coverage in the migrated schema and
runs unforced `EXPLAIN ANALYZE` plans on synthetic conversations/audits/knowledge.
See [the captured query plans](docs/query-plans.md) for data sizes, timings,
planner limitations, and the scratch-only reproduction command.
