# Memoria

**Post-conversation coaching for customer-service teams.**

Memoria helps support agents understand how they handled a completed customer conversation and where they can improve. It connects quality assessments to transcript evidence and company knowledge, giving agents and managers a concrete starting point for coaching.

**[Open the hosted demo](https://memoria-ftl.netlify.app)**

## The problem

Customer-service teams handle large numbers of conversations, but reviewing each one manually takes time. Agents need specific, actionable feedback, and managers need to understand the evidence behind an assessment. Company guidance can also become fragmented or outdated as recurring questions and policies change.

Memoria brings conversation review and knowledge management into one workspace. It assesses completed conversations across four categories:

| Category | Focus |
| --- | --- |
| Procedure | Whether the agent followed applicable steps and actions |
| Answer support | Whether the agent’s answers are supported by available guidance |
| Completeness | Whether the customer’s request was adequately addressed |
| Communication style | How clearly and appropriately the agent communicated |

Assessments show supporting evidence and evidence coverage. Missing evidence can produce **Cannot assess**, rather than treating uncertainty as proof of poor performance.

## What you can do

- Browse assigned conversations as an Agent or team conversations as a Manager.
- Open a conversation’s assessment and inspect category results, checks, and cited transcript turns.
- Consult the Agent knowledge base.
- Review knowledge drafts, inspect their sources, and approve, reject, edit, or unapprove entries where permitted.
- Explore an optional pilot that extracts recurring company facts from past conversations.

## User guide

### Agent: review a conversation before your next shift

You are a support agent who wants to identify one practical improvement from a recent interaction.

1. Open the demo and choose an **Agent** profile.
2. Select a conversation from your conversation list.
3. Open one of the four assessment categories.
4. Inspect the checks and linked transcript evidence to understand the result.
5. Check evidence coverage alongside the score. An unavailable assessment means the system lacks a usable result.
6. Open the **Knowledge Base** to review published guidance relevant to your work.

### Manager: review team conversations and guidance

1. Choose the **Manager** profile.
2. Open a team conversation and inspect its assessment and evidence.
3. Open **Knowledge drafts** to browse pending, approved, flagged, or rejected entries.
4. Select an entry and inspect its content, source conversations, and any verification reference.
5. Use the available controls to edit, approve, reject, or unapprove it. Rejection requires a reason.

When the Layer 2 pilot is enabled, **Generate pilot drafts** extracts recurring facts. Eligible consensus candidates can be approved automatically; conflicts and other drafts remain available for review.

**The hosted profile picker is public demo access. Anyone with the link can choose a listed profile, including Manager. It is not an authentication system.**

## System architecture

| Part | Technology | Hosting |
| --- | --- | --- |
| Web interface | React, TypeScript, Vite | Netlify |
| HTTP API | Python, FastAPI, Uvicorn | Railway |
| Persistence | PostgreSQL 17 with pgvector | Railway |
| Database access and migrations | SQLAlchemy, psycopg, Alembic | Backend service |
| Assessment and knowledge processing | Python modules in `ml/` and backend adapters | Configured backend or local processing |

```text
Browser
   │ HTTPS
   ▼
React frontend — Netlify
   │ HTTPS / JSON
   ▼
FastAPI backend — Railway
   ├── Conversation, assessment, and knowledge use cases
   ├── Configured scoring and knowledge-processing adapters
   └── PostgreSQL + pgvector
```

The frontend reads assessments and submits supported actions through the API. The backend enforces organization, role, and conversation-access rules. Assessment processing validates evidence and stores results for later viewing.

The demo can also serve archived scorecards. Those are prepared assessment inputs, rather than a fresh model evaluation each time someone opens a conversation.

## Code architecture

The repository separates frontend, backend, and assessment processing. Within the backend, business rules and use cases are separated from HTTP and database details.

```text
frontend/
  src/
    app/                   Routing and dependency composition
    features/              Conversation, assessment, and knowledge screens
    components/            Shared interface components
    lib/                   HTTP adapters and shared browser utilities
    types/                 TypeScript contracts

backend/
  src/backend/
    entities/              Business rules and domain values
    use_cases/             Application workflows and their boundaries
    interface_adapters/    Controllers, presenters, and adapter contracts
    frameworks/
      http/                FastAPI routes and HTTP integration
      data_access/         Persistence adapters and transactions
      database/            SQLAlchemy models and session management
    data/                  Import, seed, and evaluation commands
    schemas/               API request and response schemas
    main.py                Application composition root
  alembic/                 Database migrations
  tests/                   Unit, integration, and architecture checks

ml/                        Assessment rules, templates, evidence, and evaluation
docs/                      Architecture documentation
docker-compose.yml         Local database, demo setup, and API
netlify.toml               Frontend hosting configuration
```

Core dependencies point toward business rules and use cases. External adapters implement the required boundaries, and `main.py` supplies concrete implementations. Frontend features separate interaction controllers and presentation calculations from React views where applicable.

Python modules and functions use `snake_case`; classes use `PascalCase`. React components use `PascalCase`, hooks use the `use` prefix, and feature directories use descriptive names such as `assessment-procedure`.

See the [architecture guide](docs/architecture.md) for dependency diagrams and boundary details.

## Run locally

### Prerequisites

- Git
- Docker Desktop with Docker Compose
- Node.js 22 and npm
- Access to the course conversation-data repository

Python 3.13+ and [uv](https://docs.astral.sh/uv/) are needed if you run the backend or its tests outside Docker.

### 1. Clone the application and data

```sh
git clone https://github.com/teamMemoria/memoria.git
git clone https://github.com/marcomarchesanogenesys/uoft-ftli-2026-genesys-docs.git
cd memoria
```

Keep the repositories beside each other. The application reads conversations from:

```text
../uoft-ftli-2026-genesys-docs/curated/conversations
```

### 2. Start the database and backend

With Docker Desktop running:

```sh
docker compose up --build
```

Compose starts PostgreSQL, applies migrations, imports the demo conversations, assigns topics and synthetic dates, seeds profiles and policy drafts, and starts the API.

- [API readiness](http://localhost:8000/ready): returns `{"status":"ready"}`
- [Interactive API documentation](http://localhost:8000/docs)

Initial setup loads data and pending policies; it does not generate all conversation assessments.

### 3. Start the frontend

In another terminal:

```sh
cd memoria/frontend
npm ci
```

On macOS or Linux:

```sh
MEMORIA_API_TARGET=http://127.0.0.1:8000 npm run dev
```

On Windows PowerShell:

```powershell
$env:MEMORIA_API_TARGET = "http://127.0.0.1:8000"
npm run dev
```

Open [localhost:5173](http://localhost:5173) and choose a demo profile.

To use a different conversation-data location, set `MEMORIA_CONVERSATIONS_DIR` before starting Compose. Stop the services with `docker compose down`; the database volume is retained.

For native backend setup, data commands, and migrations, see the [backend guide](backend/README.md). For archived assessment simulation and narration setup, see the [frontend guide](frontend/README.md).

### Troubleshooting

| Symptom | Check |
| --- | --- |
| Setup cannot find conversations | Confirm the data repository exists and `curated/conversations` contains JSON files. |
| Frontend cannot load profiles | Check API readiness and explicitly set `MEMORIA_API_TARGET` to port 8000. |
| Conversation has no assessment | Importing demo data does not run scoring. Use the configured pilot or documented archived-demo setup. |
| Database connection fails | Confirm Docker is running and port 5432 is available. |

## Hosting

Netlify builds `frontend/` with `npm run build`, publishes `dist/`, and redirects application routes to `index.html`.

Railway builds the backend using repository root `/` and Dockerfile `/backend/Dockerfile`. Set `DATABASE_URL` through the hosting environment. The startup script applies migrations before launching Uvicorn.

For the public school demo:

| Service | Setting |
| --- | --- |
| Netlify | `VITE_API_BASE_URL` = backend HTTPS origin, without `/api` |
| Netlify | `VITE_DEMO_LOGIN=true` |
| Railway | `MEMORIA_PUBLIC_DEMO=true` |
| Railway | `MEMORIA_CORS_ORIGINS` = exact frontend origin |

Frontend environment variables are embedded at build time, so changing them requires a rebuild. Additional pilot and archived-scorecard configuration is described in the [hosted access guide](backend/docs/deployed-frontend-access.md) and [frontend guide](frontend/README.md).

## Development checks

With the local PostgreSQL service running:

```sh
cd backend
uv sync --frozen
uv run ruff check
uv run ruff check ../ml
uv run pytest
uv run python -m pytest ../ml -q
```

Backend database tests recreate a separate disposable test database. Use local development credentials and a dedicated test database.

From `frontend/`:

```sh
npm ci
npm run lint
npm test
npm run build
```

GitHub Actions also checks formatting, migration consistency, schema drift, backend and ML tests, and the frontend build.

## Data and prototype limitations

The curated course corpus contains HarperValleyBank voice conversations and ABCD support chats. Source conversations remain in the separate data repository. Generated dates are stored separately from original timestamps.

Layer 1 supplies authored generic policies. The optional Layer 2 pilot identifies recurring company facts, currently emphasizing values such as prices and durations. In the pilot, facts supported by at least 10 calls and 70% agreement can be published automatically, subject to conflict and review-state checks. Agreement does not independently establish correctness; repeated mistakes can produce incorrect guidance.

Archived assessments and generated narration are demonstration artifacts. Narration does not represent the original customer-call recording. Existing AI-generated evaluation labels do not establish independently measured assessment accuracy.

Agent performance comparisons over time remain planned work.

## Team

Memoria is built by five teammates with overlapping contributions:

| Teammate | Brief bio |
| --- | --- |
| [Daniel Wang](https://github.com/DanisLol) | Contributes organization and permission rules, knowledge-approval persistence, backend deployment, and hosted frontend API access. |
| [Derek Sun](https://github.com/dereksun00) | Contributes database design, migrations, conversation ingestion, knowledge lifecycle support, query optimization, and database deployment. |
| [Nicolas Cantanhede](https://github.com/nickcantanhede) | Contributes assessment scoring and evidence integration, application architecture, persistent workflow integration, and frontend review experiences. |
| [Rayaan Wasay Iftikhar](https://github.com/rayaanw) | Contributes frontend workflows, knowledge-review interfaces, progress API integration, and frontend deployment. |
| [Ritvik Aggarwal](https://github.com/ritvikagg) | Contributes knowledge extraction, Layer 2 inference and evaluation, draft persistence, and pilot integration. |
