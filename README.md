# Memoria

A tool for support agents that suggests answers while a customer is on the call, and then learns from the finished call so the suggestions get better over time.

This is early. Right now the repo is just the scaffold: a React frontend, a FastAPI backend and a Postgres database with pgvector. None of the actual features are built yet.

## What it's supposed to do

During a call, the app listens for what the customer needs, searches that company's knowledge base, and shows the agent a few relevant answers and next steps. The agent can thumbs up or thumbs down each suggestion, which changes how much we trust that entry.

After a call, the transcript is cleaned of personal details and we pull out general facts from it. New facts are compared against what we already have. If a fact is new it waits as pending until a few different calls back it up (we're guessing three, not decided). Each entry keeps the calls it came from, how many calls support it, and the date it was last seen.

Every company has its own knowledge base and they must never mix.

## What you need installed

- Git
- Node 20.19 or newer
- Python 3.13 or newer
- uv (https://docs.astral.sh/uv/)
- Docker Desktop

## Running it locally

One command starts the database, loads the demo data and starts the backend. You need Docker Desktop
running, and the conversation data cloned next to this repo:

```
git clone https://github.com/marcomarchesanogenesys/uoft-ftli-2026-genesys-docs.git ../uoft-ftli-2026-genesys-docs
```

Then, from the repo root:

```
docker compose up --build
```

This:

1. starts PostgreSQL with pgvector (`db`)
2. runs the migrations and `setup-demo` (`setup`): it imports the conversations, assigns topics and
   dates, and creates the demo profiles, then exits
3. starts the backend in development mode on http://localhost:8000 (`backend`)

The backend is ready when http://localhost:8000/ready returns `{"status":"ready"}`. The endpoints are
listed at http://localhost:8000/docs.

Run it again whenever you like: every step updates the same rows, so you get the same data, not
duplicates. Data is kept between runs; `docker compose down -v` deletes it so the next run starts
fresh. If the docs repo is somewhere else, point at its conversations first:
`MEMORIA_CONVERSATIONS_DIR=/path/to/uoft-ftli-2026-genesys-docs/curated/conversations docker compose up --build`.

Then start the frontend in a second terminal, from inside the `frontend` folder. It sends `/api` to the
backend on port 8000:

```
npm install
VITE_DEMO_BACKEND=true npm run dev
```

It runs on http://localhost:5173. Pick a demo profile to sign in.

Development mode accepts the `X-Dev-User` header and lists the demo profiles. Never run it this way in
production.

### Running the backend without Docker

Copy the example env file. The real `.env` is ignored by git, so put your keys there and never commit it.

```
cp .env.example .env
```

On Windows PowerShell use `Copy-Item .env.example .env` instead.

Start only the database, then the backend from inside the `backend` folder:

```
docker compose up -d db
cd backend
uv sync
uv run alembic upgrade head
uv run setup-demo
MEMORIA_APP_ENV=development uv run uvicorn backend.main:app --reload
```

`setup-demo` loads the same demo data as above; it looks for the docs repo next to this one, or takes
its `curated/conversations` path as an argument. Without `MEMORIA_APP_ENV=development` the backend
runs in production mode and rejects every request, because there is no login yet.

## Where things are

```
backend/     FastAPI app, code lives in src/backend
frontend/    React + TypeScript + Vite
docker-compose.yml   Postgres with pgvector, the demo data setup and the backend
```

Inside `backend/src/backend` there are folders for api routes, core (config), models (database tables) and services (the RAG and extraction logic). They're mostly empty for now.

## Database

Postgres 17 with pgvector, running in Docker. Migrations will use Alembic, which is initialised in `backend/alembic` but has no migrations yet. To check the vector extension is there:

```
docker compose exec db psql -U app -d callassist -c "CREATE EXTENSION IF NOT EXISTS vector;"
```

The login in `docker-compose.yml` is for local development only.

## Not decided yet

- Which speech-to-text provider to use for live calls
- Whether a fact needs manager approval after it hits the call threshold, or gets promoted automatically
- Whether the threshold counts calls or distinct customers

## A note on data

This will eventually handle real call transcripts, so keep the repo private and don't commit any real call data. Use made-up examples for tests.
## Database setup

Start only Postgres (with pgvector). Plain `docker compose up` also starts the backend:

    docker compose up -d db

Check that pgvector is enabled:

    docker compose exec db psql -U app -d callassist -c "\dx"

## Migrations

From the `backend/` folder, with the database running:

    uv run alembic upgrade head

After changing models, create a new migration:

    uv run alembic revision --autogenerate -m "describe the change"

## Database checks and deployment startup

The `Checks / backend` GitHub Actions job runs on every pull request and on
pushes to `main`, using a disposable Postgres 17 service with pgvector. After
`uv sync --frozen`, it enables the vector extension, requires exactly one
Alembic head, runs upgrade → downgrade one revision → upgrade plus
`alembic check`, then runs the full backend tests and plain `uv run ruff check`
(including migration files). Broken migrations and multiple heads fail the PR
check. Existing ML and frontend checks still run.

For deployment from this source repository, use `./backend/start.sh` as the
hosting dashboard's start command (or `./start.sh` if the service root is
`backend/`). Install dependencies during the build with `uv sync --frozen` in
`backend/`. Set `DATABASE_URL` through hosting secrets and enable pgvector first.
The start script runs `uv run alembic upgrade head` before launching Uvicorn;
a failed migration exits without starting the app. It listens on the hosting
platform's `PORT`, defaulting to 8000. For multiple replicas, run migrations once
as a release/pre-deploy step before starting replicas, to avoid concurrent DDL.
No production database is provisioned by this change.

For the production database users (admin for migrations, `memoria_app` for the
running backend), Railway variables, and manual backup and restore steps, see
[docs/deployment.md](docs/deployment.md).

## Knowledge health defaults

The application settings in `backend/src/backend/core/config.py` read these
values from environment variables (or your untracked `backend/.env`):

| Setting | Default | Change with |
| --- | --- | --- |
| Draft threshold X (calls needed before creating a draft) | 10 | `KNOWLEDGE_DRAFT_THRESHOLD` |
| Conflict threshold | ceil(X / 2), so 5 | `KNOWLEDGE_CONFLICT_THRESHOLD_OVERRIDE` for an independent override |
| Recent supporting-call window | 30 days | `KNOWLEDGE_RECENT_CALL_DAYS` |
| Stale approved-entry window | 60 days | `KNOWLEDGE_STALE_ENTRY_DAYS` |

Changing X changes the conflict threshold unless the override is set. All four
settings must be positive integers. No earlier draft threshold setting existed;
X is defined once in `Settings` for reuse by draft creation. These database
queries do not themselves generate drafts or infer contradictions from text.

`frameworks/data_access/knowledge_health.py` reports stored draft/baseline
conflicts with enough distinct supporting calls in the inclusive recent window
and approved entries last confirmed before the stale cutoff. A never-confirmed
entry ages from its approval date; an entry exactly at the cutoff is not stale.
Calls use synthetic timestamps where present, otherwise their source date;
future and undated calls do not count. Every query requires an organization ID.

Pipeline suspected-conflict names stay unchanged. `knowledge_conflicts` adds
`lifecycle_status` (`open`/`resolved`), creation and resolution timestamps so
reviewer resolution remains separate from pipeline hints. An authorized manager
can call `mark_topic_disputed` to pause a topic's use as an accuracy reference,
and `resolve_knowledge_conflict` to preserve conflict history and resume
scoring after the last open conflict is resolved. Imports retain resolved
conflicts and conflicts on disputed topics. These are database operations;
commit the surrounding session to persist them.
