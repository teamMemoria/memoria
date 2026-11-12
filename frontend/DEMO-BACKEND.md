# PR #121: database-backed dashboard entry

This branch runs with **one backend built from this checkout**. It does not need
any uncommitted assessment/knowledge backend or model service.

## Start the demo

Use the existing PostgreSQL setup and `DATABASE_URL` described in
[`../backend/README.md`](../backend/README.md). From `backend`, apply this branch's
migrations and seed profiles. Seeding is repeatable: it links only explicitly
mapped, already imported conversations, without taking them from known owners.
It does not import conversations, generate assessments or approve anything.

```sh
uv run alembic upgrade head
uv run seed-demo-profiles
MEMORIA_APP_ENV=development MEMORIA_DATA_SOURCE=database \
  uv run uvicorn backend.main:app --host 127.0.0.1 --port 8000
```

In another terminal, from `frontend`:

```sh
npm ci
VITE_DEMO_BACKEND=true MEMORIA_API_TARGET=http://127.0.0.1:8000 npm run dev
```

All `/api` requests use that single backend. `VITE_API_BASE_URL` is an optional
path prefix for a configured reverse proxy. The backend URL defaults to
`http://localhost:8000`. There is no separate profile-service target.

The current local preview uses frontend port 54121 and this branch's backend on
54122, reading the existing demo database. The other integration backend is not
involved. No existing database records were altered by browser verification.

## Scope and behavior

- Figma-aligned login, accessible role cards/dropdown, responsive layout, one
  full logo animation ending on the M, and a still logo for reduced motion.
- The 31 Agent profiles and Manager come from the database. IDs stay stable;
  display names omit the legacy `(demo)` suffix. Profile selection is remembered
  when storage is available; blocked storage still permits the current visit.
- Every workspace request uses the selected, server-validated viewer. The backend
  enforces organization, ownership and role permissions; profile switches discard
  the old workspace and stale responses. HTTP failures never fall back to fixtures.
- Agents see their assigned, already imported conversations. Managers see their
  existing team queue. Missing timestamps/durations are labelled, not invented.
- Existing category results, explanations, cited turns, approved references and
  transcripts are readable using the current backend contract. Review requests,
  context and Manager feedback decisions use existing endpoints and permissions.
- Knowledge lists and drafts are readable. This backend has no approve/reject
  endpoints, so those controls are unavailable. Server decision permissions stay
  separate from this transport capability. Existing decisions remain visible.
- Percentage scoring, extended evidence contracts, assessment generation and new
  knowledge decision endpoints are separate work. This PR does not implement them.

This is a local school demo. The development identity header is sent only in
Vite development mode, and accepted only by a backend explicitly configured for
development/test. Production authentication remains outside this ticket; a
production build does not enable the demo login.

## Verification

```sh
# frontend
npm test
npm run lint
npm run build

# backend: TEST_DATABASE_URL MUST name a disposable database, never app data.
# The test fixture drops/recreates that test database before running migrations.
TEST_DATABASE_URL='<scratch PostgreSQL URL>' uv run pytest \
  tests/test_seed_demo_profiles.py tests/test_demo_profiles_api.py \
  tests/test_database_providers.py tests/test_auth.py \
  tests/test_calls_api.py tests/test_conversations_api.py \
  tests/test_manager_reviews.py tests/test_knowledge_api.py \
  tests/test_organization_permissions.py tests/test_membership_agent_link.py -q
```

Coverage includes safe/idempotent seeding, both roles, missing profiles, failed
requests, refresh, profile switching, stale responses, ownership, context/review
persistence, separate Manager decisions, and unavailable knowledge writes.
Browser verification uses GETs against the existing data. Write tests run only
in the disposable database; no real approvals or review decisions are created.
