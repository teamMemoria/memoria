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

Copy the example env file. The real `.env` is ignored by git, so put your keys there and never commit it.

```
cp .env.example .env
```

On Windows PowerShell use `Copy-Item .env.example .env` instead.

Start the database:

```
docker compose up -d
```

Start the backend. Run this from inside the `backend` folder:

```
uv sync
uv run uvicorn backend.main:app --reload
```

It runs on http://localhost:8000. Try http://localhost:8000/health, you should get `{"status":"ok"}`. FastAPI also gives you a page for poking at the endpoints at http://localhost:8000/docs.

Start the frontend in a second terminal, from inside the `frontend` folder:

```
npm install
npm run dev
```

It runs on http://localhost:5173.

## Where things are

```
backend/     FastAPI app, code lives in src/backend
frontend/    React + TypeScript + Vite
docker-compose.yml   Postgres with the pgvector extension
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

Start Postgres (with pgvector):

    docker compose up -d

Check that pgvector is enabled:

    docker compose exec db psql -U app -d callassist -c "\dx"
