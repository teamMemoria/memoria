# Assessment and knowledge integration

The integration foundation builds on the scoring engine and merged main `634e719`
(backend PRs #93, #94, #104, #105, #106 and login #121). Screen registrations
are installed independently by the four assessment PRs. Missing registrations
retain the generic assessment/evidence route. Original worktrees and local history
are preserved. Knowledge candidate generation and natural narration arrive in
their respective sibling PRs; the notes below also describe the complete local demo.

## Connected flows

The four assessment designs read the Agent/Manager endpoints. The backend stores
validated rule reports and exposes scores, coverage, point ledgers, canonical
citations, request dispositions and source/rule versions. System actions retain
original positions and are labelled separately from Agent claims. Unknown dates,
audio, exhaustive claim counts and timed action measurements remain unavailable.

Percentages measure **assessed points**. Unresolved checks neither lose points nor
receive full marks. Overall remains unscored without all required categories and
eligible weights. Existing Agent context, review requests and Manager decisions
persist separately; a human decision never rewrites the automatic score.

Knowledge queue/detail use `/api/manager/knowledge/drafts`. Approve/reject writes
require the correct permission, organization and content version. Approval also
requires the stored authoritative reference; conflicts/duplicates block it.
Rejection requires a reason. Imports and decisions serialize per organization.
The saved approval records its reference. Drafts never reach Agent knowledge or
scoring; imports never approve, renew verification or replace a decided draft.

## Local data

The isolated database `integration_117_20261111` on port 55440 contains the 117
frozen ABCD training conversations and exact v13 reports assessed on **2026-11-09**.
Import revalidates evidence, scoring versions, citations and eligibility for that
historical date. The bounded demo approval was not renewed. Screens show the date.

Supported numeric categories: Procedure 11, Completeness 7, Communication style
75, Answer support 3. Eighty conversations have at least one score; none has all
four or an overall. Available percentages are 100% of assessed points, not full
performance grades. Unresolved checks remain visible for all 117.

One existing prepared return-policy draft was checked against canonical training
conversation 1891 and imported. Its Agent quotations are examples, not policy
authority. It stays pending without an authoritative verification reference.
The prepared import remains intact. With `MEMORIA_KNOWLEDGE_ENGINE=rules`, the
existing Manager-only `POST /api/manager/knowledge/imports` now generates pending
candidates from canonical evidence in the frozen training cohort. The generator
reuses the request links and exact-citation checks; database writes reuse the
existing importer. It does not treat agent answers as policy authority.
A run over all 117 produced five additional candidates; repeating it created none.
All six stored drafts remain pending. No frontend redesign or new controls were
needed: the existing queue and source dialogs show the stored candidates.
Generation returns a per-conversation record, including failures, missing input
and no supported candidate. Grouping, conflicts and verification remain separate.

Recognition changes are versioned v15/v8. Saved November 9 scores are retained;
new runs do not inherit their approval or renew the review date. See the current
recognition review under `ml/output/coverage-generation-20261111/`.

`integration_actions_20261111` is a separate database of authored test fixtures.
Browser approval/rejection and review writes run there, never against ABCD data.
Human annotations and corpus knowledge approvals remain unset.

Scripts, mappings, verification and screenshots: ignored
`ml/output/backend-integration/`. Source exports and older databases remain in
place. No held-out data is needed.

## Local execution

From the root, using the installed Python environment:

```sh
DATABASE_URL=postgresql+psycopg://app:app@127.0.0.1:55440/integration_117_20261111 \
MEMORIA_APP_ENV=development MEMORIA_DATA_SOURCE=database PYTHONPATH=backend/src:. \
python -m uvicorn backend.main:app --host 127.0.0.1 --port 8020
```

From frontend/, set `VITE_API_BASE_URL=/`, `VITE_DEMO_BACKEND=true` and
`MEMORIA_API_TARGET=http://127.0.0.1:8022`, then `npm run dev`. The combined preview
is running at http://127.0.0.1:5328. Select a database profile on the entry screen;
use the avatar or sidebar profile menu to switch. No fixed development user is used.
Production never sends development identity headers;
production sign-in remains a separate dependency. HTTP errors never fall back to
fictional fixtures.

`MEMORIA_ANALYSIS_ENGINE=rules` opts into rule analysis. Current eligibility still
applies; it will not renew expired approval to reproduce historical scores.
Finished audits are never overwritten. Historical import preserves the saved date.

## Verification and review boundaries

Run backend tests from backend/ with TEST_DATABASE_URL and TEST_ADMIN_URL pointing
to the isolated server: the suite recreates scratch databases. Run frontend tests,
lint and build (including TypeScript) from frontend/. Run ML tests from the root.

Checks include report validation, partial failures, ownership, stale responses,
source versions, quotation spans, request changes, reference selection, approval
reset and persistence. Chrome/WebKit check both roles, history, dialogs and mobile.

Shared backend/schema/HTTP changes precede feature PRs (#4 design follow-up, #46,
#47, #48). Knowledge design/mutations are a separate review unit. The current app
registers all four screens; carry each registration with its feature when splitting
and build every intermediate branch. Nothing has been split or committed yet.


## Login integration after PR #121

PR #121 merged as `634e719` including head `fb4eecc`. This integration is now based
on that main commit. Local changes were backed up before reconciling the incoming
entry screen, profile controls and dropdowns. The richer four assessment screens
and persistent knowledge approve/reject endpoints remain in place. No application
commit was created.

The existing database has 31 Agent profiles plus a Manager, with the earlier
`demo-abcd-*` identifiers. The incoming seed catalogue uses `demo-agent-*` IDs;
it must not be rerun over this database to create duplicate personas. The entry
point reads actual database profiles. Their names and all 117 source assignments
match the catalogue without reseeding or changing ownership.

Original ABCD IDs are exposed independently of audit availability and displayed
in both conversation lists and assessment details. Missing stored assessments are
explicitly unavailable and never feedback-ready; absent dates/durations remain
absent. Partial rule reports keep their existing category processing-error details.

Read-only verification compared all 117 assessments against their saved reports,
including every category's score, coverage, limitation and check citations. Tests
for review requests, Manager decisions, knowledge approval/rejection and persistence
use the separate authored database `login_actions_20261112_v2` (port 8023, UI 5329),
not corpus decisions. Scripts and screenshots are in `ml/output/login-integration/`.
