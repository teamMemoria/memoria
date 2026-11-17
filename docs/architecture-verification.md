# #130 local verification

## PR review corrections (November 17, 2026)

The combined `acceptance` stack was checked again after the shared-error,
review-decision and data-access boundary corrections. A disposable pgvector
container hosted the migrated test database; no application records were used.

| Check | Result |
|---|---|
| Backend pytest | **595 passed** |
| ML regression suite | **189 passed; 631 subtests passed; 3 existing skips** |
| Frontend Vitest | **161 passed across 15 files** |
| Backend Ruff lint, formatting and Python compilation | Passed |
| Frontend lint, TypeScript and production build | Passed |

The active review route now calls `RecordReviewDecision` with an injected scoped
SQL repository. The repository preserves the existing authorization, transaction
and concurrent-decision behavior. Database providers are checked against their
existing read/write ports, and simple profile formatting is outside SQL access.
The OpenAPI models and frontend views were not edited by these corrections.

The results below record the earlier pre-PR baseline and remain as historical
comparison evidence.

Worktree: `/Users/nicol/Desktop/PROJECTS/memoria-worktrees/clean-architecture`

Branch: `clean-architecture`. Base: `5664bc15d94dc65c3e3d9c36281b4005d634c83a`.
All implementation remains uncommitted and unstaged. See
[architecture](architecture.md) and [proposed PR split](architecture-pr-plan.md).

## Results

| Check | Result |
|---|---|
| Backend pytest | **591 passed** |
| Core and dependency tests with an unreachable database | **47 passed** |
| ML regression suite | **189 passed; 631 subtests passed; 3 existing skips** |
| Frontend Vitest | **157 passed across 15 files** |
| Backend/ML Ruff lint and formatting | Passed; 195 Python files formatted |
| Python compilation | Passed |
| Frontend lint, TypeScript and production build | Passed |
| Full OpenAPI JSON against combined pre-refactor baseline | Identical, **22 paths** |
| Frontend view structure | All **41 JSX view trees unchanged** |
| Frontend CSS/assets | All **32 files byte-identical** |
| Browser comparison | Eight screens retain text, geometry and layout |
| Database integration, application restart | Agent ownership/reviews and knowledge decisions persist |
| Git | Empty index, unchanged branch HEAD, `git diff --check` clean |

Before refactoring, the combined integration/design baseline had 543 backend
passes after configuring its migration test for the scratch server, 157 frontend
passes, and the same ML results. The original migration test hardcoded a different
PostgreSQL address; it now honors the scratch configuration and refuses the app
or main test database. Existing assertions were not removed or weakened.

## Isolated flow checks

All records are independently authored fixtures from `tests/database_seed.py`,
not imported conversations. The dedicated Docker container is
`memoria-clean-architecture-test`, PostgreSQL/pgvector 17 on `127.0.0.1:55461`.
The test suite uses `architecture_test`; interactive checks use a separate
`architecture_browser` database. No other server/container/database was changed.

Automated persistence test:

1. List database demo profiles; resolve Agent and Manager memberships.
2. Deny another Agent's direct conversation access with 404.
3. Save Agent context and a finding review request.
4. Save a Manager decision; retain the original automatic criteria/evidence.
5. Approve one authored knowledge draft, reject another, leave a third pending.
6. Destroy the application/engine; create a new app and new connections.
7. Verify decisions/context persist, automatic assessment is unchanged, and only
   approved knowledge is visible to the Agent.

Browser test against Vite and a separate Uvicorn process:

- Select database Agent, open assigned call and Procedure evidence.
- Submit review request; switch to Manager; open request and save a decision.
- Approve an authored draft through the reference-open and checkbox gate. Its
  `example.test` reference was intercepted in the browser with authored test
  guidance; no real approval or external authority was claimed.
- Reject a second draft with a reason; leave the third pending.
- Switch back to Agent and see the persisted Manager decision.
- Restart the backend and verify the decision and approved guidance remain.
- Confirm other-Agent access is still 404 and rejected/pending guidance is hidden.

## Design comparison

Baseline includes the published #124–128 designs on #123, before this refactor.
Compared at identical viewport size: login, Agent conversations, Procedure,
Answer support, Completeness, Communication style, Manager knowledge queue and
knowledge review.

Five screenshots were pixel-identical. The other three had 64, 65 and 1,119
changed pixels respectively (at most about 0.052% of the image); inspection found
rasterization differences rather than text or geometry changes. All JSX view
structures and all CSS/assets match. Existing design quirks were preserved,
not redesigned as part of architecture work.

Local screenshots and comparison data are under ignored
`ml/output/architecture/`. They contain authored fixtures only. The snapshot used
for comparison is `/tmp/memoria-architecture-baseline-20261116`; it excludes
credentials, raw data, result history and dependency directories from the source
checkout. Local dependencies were installed separately for verification.

## Reproduce the checks

Use a disposable PostgreSQL/pgvector server. The suite recreates its designated
test database, and rejects using the app database as that target.

```sh
# From backend/, with DATABASE_URL pointing to a separate empty scratch app DB
# and TEST_DATABASE_URL pointing to the disposable test DB:
uv sync --frozen
uv run pytest -q --tb=short
uv run ruff check src tests ../ml
uv run ruff format --check src tests ../ml
uv run python -m compileall -q src ../ml

# From the repository root:
backend/.venv/bin/python -m pytest ml -q -rs --tb=short

# From frontend/:
npm ci
npm test
npm run lint
npm run build
```

The new `.github/workflows/ci.yml` runs these equivalents with a disposable
PostgreSQL/pgvector service. Hosted CI has not been run: nothing was pushed.

## Size

Physical lines, including comments and blanks, compared with the combined
integration/design baseline. Moves are counted once at their new location;
compatibility modules are included. CSS, data, docs and generated results are
excluded from production code counts.

| Area | Before | After | Change |
|---|---:|---:|---:|
| Backend production Python | 10,201 | 11,342 | +1,141 |
| ML production Python | 4,142 | 4,175 | +33 |
| Frontend production TS/TSX | 9,649 | 9,724 | +75 |
| Backend tests | 8,715 | 9,490 | +775 |

The additional production lines are primarily explicit contracts, compatibility
exports, dependency wiring and separated functions. No new runtime dependency
was introduced. Most of the large Git diff is movement plus the existing design
PR dependencies; it is not newly invented functionality.

## Limits and deferred work

- Three existing ML skips remain: new language cases await human judgment;
  pinned local evaluation metadata is unavailable; pinned ABCD source files are
  absent in this isolated checkout. No held-out data was loaded. Automated
  regression success does not establish new semantic accuracy.
- Existing warnings remain: Starlette/httpx deprecation; a legacy ML test helper
  returns a value; frontend bundle exceeds Vite's 500 kB advisory threshold.
  Checks were not disabled to hide them.
- No assessment was recomputed and no paid/model call was made. Engine and
  extraction integrations remain optional. This verifies architecture and
  preserved behavior, not scoring coverage or model quality.
- Existing runtime/CLI compatibility paths remain. Their eventual removal is
  a separate cleanup, not a prerequisite to inward business dependencies.
- GitHub CI, deployment and browser/device combinations beyond the local
  Playwright comparison were not exercised. No remote state was changed.

The temporary preview servers and the dedicated test container were stopped
after verification. Screenshots, authored scratch database contents and local
reports remain available; the user's existing development services were left
untouched.

## Follow-up corrections and independently tested PR slices

The review gaps are fixed: pure Manager decision validation, neutral review
outputs, used run-management input/data-access boundaries and stronger guards
for relative imports and file/clock calls. No source checks or approvals were
weakened. Duplicate scoring validation was consolidated without changing rules.

All 15 cumulative local snapshots passed their assigned checks. Each snapshot
was checked for lint, formatting, compilation, unchanged OpenAPI, patch
applicability and an empty Git index. Backend slices ran the full backend suite;
frontend slices ran the full frontend tests and production build. Baseline,
ML and acceptance slices also ran the ML suite. Final acceptance includes the
persistent Agent/Manager and knowledge decision tests after application restart.

The final slice's source matches the combined worktree. The unchanged view/asset
comparison was rerun. Fresh GitHub CI and deployment remain untested because
nothing was published. The previously captured browser screenshots remain
applicable to the unchanged JSX/CSS; this follow-up verified flows through the
full API persistence tests rather than rerunning the earlier interactive browser
session.

Machine-readable results and full logs are in the sibling
`clean-architecture-slices/verification.json` and `logs/`. The local branch names,
file ownership and incremental patches are in its `manifest.json` and `patches/`.
Existing design dependencies are kept in patch 00, separate from the #130 deltas.
