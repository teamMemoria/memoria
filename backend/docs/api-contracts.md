# Agent-facing API contracts

Response formats for the agent screens. Every schema mirrors a frontend type field-for-field,
so the frontend's development providers can be swapped for HTTP calls without changing the UI.

| Backend schema (`backend.schemas`) | Frontend type |
|---|---|
| `Viewer` | `Viewer` in `frontend/src/types/viewer.ts` |
| `Conversation` | `Conversation` in `frontend/src/features/conversations/conversations.ts` |
| `CallReview` | `CallReview` in `frontend/src/types/callReview.ts` |
| `KnowledgeEntry` | `KnowledgeEntry` in `frontend/src/types/knowledge.ts` |

JSON uses camelCase (`agentId`, `evidenceTurnNumbers`); Python uses snake_case. Unknown fields are rejected.

## Result values

Automated audit results are exactly `meets-criteria`, `needs-review` and `cannot-assess`.
The conversation list adds `processing` for calls that have no result yet.
Human review status (`feedback-ready`, `review-requested`, `review-complete`) is a separate field and
is always `null` while a call is processing.

## Validation rules

`CallReview` rejects a record when:

- a criterion, finding or procedure step cites a turn number that is not in the transcript
  (including any citation when the transcript is missing)
- a criterion cites a finding or reference that is not included in the response
- a `needs-review` criterion cites no evidence. Missing evidence must be `cannot-assess`, never an agent failure
- a ready call does not have exactly one result for each of the four criteria
- a processing call already has criteria, findings or a decision
- transcript turn numbers are duplicated or out of order. Gaps are allowed and kept as-is

## Identity and permissions

Every route except `/health` reads the requester from `get_current_user`
(`backend/src/backend/api/auth.py`), which returns a `CurrentUser` with a user ID,
organization ID and set of permissions.

There is no login system yet. When `MEMORIA_APP_ENV` is `development` or `test`, the requester
is one of the fixed identities in `backend/src/backend/core/auth.py`, named in the `X-Dev-User`
header:

| `X-Dev-User` | Organization | Permissions |
|---|---|---|
| `agent-alex-morgan` | `org-northwind` | `conversations:read-own`, `knowledge:read` |
| `agent-sam-rivera` | `org-northwind` | `conversations:read-own`, `knowledge:read` |
| `manager-maya-chen` | `org-northwind` | `feedback:review`, `knowledge:read` |
| `approver-devon-park` | `org-northwind` | `knowledge:approve`, `knowledge:read` |
| `agent-riley-chen` | `org-harbor` | `conversations:read-own`, `knowledge:read` |

`MEMORIA_APP_ENV` defaults to `production`, where the header is ignored and every request gets `401`.

### How an identity enters the request context

1. **Authentication** decides *who* is asking. A future login system will verify the user and hand
   the backend their user ID. Until then, in development and test only, `X-Dev-User` stands in for
   that verified ID. Nothing else in a request is treated as proof of identity.
2. **Authorization** decides *what they may do*, and always comes from the server. `get_current_user`
   passes the user ID to the identity provider (`Providers.identities`), which returns the
   `CurrentUser`:
   - With fixtures (`MEMORIA_DATA_SOURCE=fixtures`, the default) it is the matching entry in
     `DEV_IDENTITIES`.
   - With the database (`MEMORIA_DATA_SOURCE=database`) it is built from the user's stored
     `OrganizationMembership`: `organization_id` is the organization's `slug`, and permissions come
     from `permissions_for_membership` in `backend/core/auth.py`.

   | Membership | Permissions |
   |---|---|
   | role `agent` | `conversations:read-own`, `knowledge:read` |
   | `can_review_feedback` | adds `feedback:review` |
   | `can_approve_knowledge` | adds `knowledge:approve` |

   Today both capabilities belong to the `manager` role, so a stored Manager can do both. They map
   to separate permissions, so splitting the role later needs no change here.
3. **Ownership** of calls goes through `OrganizationMembership.agent_id`, the link from a person to
   the agent record (`agents` row) in the source data. An agent sees only conversations whose
   `agent_id` matches their link, in their own organization. An agent with no link sees no calls.

Choosing a role in the frontend is a display choice, not authentication: the backend never reads a
role, organization or permission from the request. A user who belongs to several organizations
picks one with the `X-Organization` header (an organization slug); it only selects among memberships
they already hold, and without it such a user gets `401`.

To run on the database:

```bash
MEMORIA_APP_ENV=development MEMORIA_DATA_SOURCE=database .venv/bin/uvicorn backend.main:app --reload
```
To run locally:

```bash
MEMORIA_APP_ENV=development .venv/bin/uvicorn backend.main:app --reload
curl -H "X-Dev-User: agent-alex-morgan" localhost:8000/api/viewer
```

`feedback:review` (Managers) and `knowledge:approve` (Knowledge Approvers) are deliberately separate.
Routes protect themselves with `Depends(require_permission(Permission.X))`, and agent-owned records
are checked with `can_read_agent_record(user, organization_id, agent_id)`.

## Proposed routes

All five are implemented: `/api/viewer` (#71), conversations (#72), call detail (#73) and knowledge (#74). The agent is always the authenticated requester (#71),
never an ID taken from the URL or query string.

| Method and path | Response | Frontend interface |
|---|---|---|
| `GET /api/viewer` | `Viewer` | `ViewerApi.getViewer` |
| `GET /api/agent/conversations` | `Conversation[]` (newest first) | `ConversationsApi.listForAgent` |
| `GET /api/agent/conversations/{conversationId}` | `CallReview` | `CallApi.getCallForAgent` |
| `GET /api/agent/knowledge` | `KnowledgeEntry[]` | `ApprovedKnowledgeApi.listForAgent` |
| `GET /api/agent/knowledge/{entryId}` | `KnowledgeEntry` | `ApprovedKnowledgeApi.getForAgent` |

### Errors

Error bodies use FastAPI's default shape: `{"detail": "..."}`.

| Status | When |
|---|---|
| `401` | No identity on the request |
| `403` | Identity lacks the permission for this route |
| `404` | Record does not exist **or** is not visible to the requester (same response, so existence is not leaked) |
| `503` | The provider raised `ProviderUnavailableError` |

An empty list is a `200` with `[]`, not an error.

### `GET /api/agent/conversations`

Requires `conversations:read-own`. Returns only the requester's conversations in their own
organization, newest first. `automatedResult` and `reviewStatus` are independent fields:
a processing call has `automatedResult: "processing"` and `reviewStatus: null`.

| Status | Body | When |
|---|---|---|
| `200` | `Conversation[]` | Success, including `[]` when the agent has no conversations |
| `401` | `{"detail": "Missing identity"}` | No identity |
| `403` | `{"detail": "Not permitted"}` | A Manager or Knowledge Approver without `conversations:read-own` |
| `503` | `{"detail": "Data source unavailable"}` | The conversation provider is down |

### `GET /api/agent/conversations/{conversationId}`

Requires `conversations:read-own`. Returns the `CallReview` for one of the requester's own calls.

- **Ready:** four criteria (one per category), findings with suggestions, transcript turns and references.
- **Processing:** `status: "processing"` with empty `criteria` and `findings` and no `decision`.
- **Missing transcript:** `transcript: null`; criteria are `cannot-assess` with no evidence.
- **Partial transcript:** `transcript.complete: false` with an `unavailableReason`; criteria that
  depend on the missing part are `cannot-assess`.
- **Turn numbers** are the originals, gaps included, and every evidence number points at a turn in
  this call's transcript.
- **References** are the versions the call was assessed against. A reference that has since become
  stale is still returned, with its `status` and `version` unchanged, so the agent sees what they were
  measured against (fixture `C1047`). As with the knowledge routes, `availableToAgentIds` is
  trimmed to `[requesterId]`.
- **`decision`** is the Manager's decision, kept beside the automated `criteria`, never merged into them.

| Status | Body | When |
|---|---|---|
| `200` | `CallReview` | Success, in any of the states above |
| `401` | `{"detail": "Missing identity"}` | No identity |
| `403` | `{"detail": "Not permitted"}` | A Manager or Knowledge Approver without `conversations:read-own` |
| `404` | `{"detail": "Conversation not found"}` | Unknown call, call record unavailable, or another agent's or organization's call |
| `503` | `{"detail": "Data source unavailable"}` | The call provider is down |

### `GET /api/agent/knowledge` and `GET /api/agent/knowledge/{entryId}`

Requires `knowledge:read`. Returns approved entries assigned to the requester in their own
organization, with content, source, version, approval information and dates. Draft, rejected,
disputed and stale entries are never returned. The detail route applies exactly the same rule
as the list, so a direct request cannot open an entry the list hides.

Unknown dates (`approvedAt`, `effectiveAt`, `lastConfirmedAt`) and an unknown `approvedBy`,
`owner` or `source` stay `null`.

`availableToAgentIds` is trimmed to `[requesterId]`, so an agent never learns who else an entry is
assigned to. The frontend's `canReadKnowledge` check still passes.

| Status | Body | When |
|---|---|---|
| `200` | `KnowledgeEntry[]` / `KnowledgeEntry` | Success, including `[]` when nothing is assigned (for example a Manager) |
| `401` | `{"detail": "Missing identity"}` | No identity |
| `404` | `{"detail": "Knowledge entry not found"}` | Missing, not approved, assigned to someone else, or in another organization |
| `503` | `{"detail": "Data source unavailable"}` | The knowledge provider is down |

### Examples

`GET /api/agent/conversations`

```json
[
  {
    "id": "C1045",
    "topic": "Order status",
    "agentId": "agent-alex-morgan",
    "agentName": "Alex Morgan",
    "date": "2026-10-14",
    "automatedResult": "processing",
    "reviewStatus": null
  },
  {
    "id": "C1042",
    "topic": "Refund request",
    "agentId": "agent-alex-morgan",
    "agentName": "Alex Morgan",
    "date": "2026-10-08",
    "automatedResult": "needs-review",
    "reviewStatus": "feedback-ready"
  }
]
```

`GET /api/agent/conversations/C1042` (trimmed)

```json
{
  "id": "C1042",
  "agentId": "agent-alex-morgan",
  "status": "ready",
  "criteria": [
    {
      "id": "procedure",
      "title": "Procedure",
      "result": "needs-review",
      "explanation": "The refund was offered at turn 8. Purchase verification followed at turn 13. ...",
      "evidenceTurnNumbers": [8, 13],
      "findingId": "procedure-order",
      "referenceId": "RP-01"
    }
  ],
  "transcript": {
    "complete": true,
    "turns": [{ "number": 8, "speaker": "Agent", "text": "I can offer you a refund.", "time": "2:02" }],
    "unavailableReason": null
  },
  "references": [{ "id": "RP-01", "version": "v1", "status": "approved" }],
  "decision": null
}
```

`GET /api/agent/conversations/C1044`: transcript unavailable

```json
{
  "id": "C1044",
  "status": "ready",
  "criteria": [
    { "id": "procedure", "result": "cannot-assess", "evidenceTurnNumbers": [], "findingId": null, "referenceId": null }
  ],
  "transcript": null
}
```

The full records are in `backend/src/backend/providers/fixture_data.py`.

## Post-call analysis

`backend/src/backend/services/analysis.py` runs the post-call feedback report and saves its result
as the conversation's audit. Each attempt is an `analysis_runs` row, so processing status and
technical failures are recorded apart from any audit.

| Method and path | Permission | Response |
|---|---|---|
| `GET /api/manager/conversations/{conversationId}/analysis` | `feedback:review` | `AnalysisStatus`: the latest status (`not-started`, `queued`, `running`, `succeeded`, `failed`) and every run, newest first |
| `POST /api/manager/conversations/{conversationId}/analysis` | `feedback:review` | `202` with a new queued run, or `200` with the run already queued or running |

Body for `POST`: optional `{"retry": true}`.

| Status | When |
|---|---|
| `404` | The conversation does not exist or is in another organization |
| `409` `Conversation already analysed` | It has an audit. Audits are never replaced, so earlier results cannot be lost |
| `409` `The last run failed; retry explicitly` | The latest run failed and `retry` was not `true` |

### The adapter

The run calls an `AnalysisAdapter` with an `AnalysisRequest`, following the input and output of
`run_feedback_report` in `ml/report.py`:

- `conversation`: `{id, transcript_version, events}`. Each event has the original turn number as
  `turn_id`, `kind` (`message` or `action`), `speaker` and `text`. `transcript_version` is a SHA-256
  of the events, so a report can be matched to exactly this evidence.
- `references`: the organization's approved entries for the conversation's topic (all approved
  entries if it has none), each with `id`, `section_id`, `version`, `title` and `text`.
- `criteria`: the active evaluation form version's criteria, with `evaluation_form_version` stored
  on the audit.

The report is accepted only if `parse_report` finds `processing_status: "complete"`, the same
`conversation_id` and `transcript_version`, all four categories completed, and every citation
pointing at a supplied turn (with a matching quote) or a supplied reference version. A
`needs-review` finding must cite at least one turn. Anything else fails the run with an error code
(`report-<code>`, `invalid-citation`, `missing-evidence`, `evidence-mismatch`, `invalid-report`,
`analysis-error`, `analysis-unavailable`, `no-evaluation-form`, `no-transcript`) and saves nothing.
A failure is never stored as `cannot-assess`; the agent keeps seeing `processing`.

The audit model has one finding per category. When a report has several findings in one category,
their explanations, suggestions and evidence turns are combined, and the first cited reference is
linked.

No adapter is configured by default, so runs fail with `analysis-unavailable` until one is passed to
`create_app(analysis=AnalysisService(sessions, adapter))`. `run_feedback_report` currently accepts
only prepared ABCD evidence, so connecting it needs an adapter that prepares stored conversations
the same way.

Runs execute as background tasks in the API process. If the process stops mid-run, that run stays
`running` and blocks new runs for the conversation; clearing such runs needs a worker with a
timeout, which is not built yet.

## Providers

Routes read data through the interfaces in `backend/src/backend/providers/base.py`
(`ViewerProvider`, `ConversationProvider`, `CallReviewProvider`, `KnowledgeProvider`).
Every method takes an `organization_id` and returns `None` for records that are missing
or not visible to that agent. `MEMORIA_DATA_SOURCE` picks the fixture providers or the
PostgreSQL ones in `backend/src/backend/providers/database.py`; tests can pass their own
`Providers` to `create_app()`. `tests/test_database_providers.py` runs the same checks against
both, so they cannot drift apart.

### Database mapping

| Stored | API |
|---|---|
| `Conversation.id` | `id` (as a string) |
| `FindingResult` `pass` / `needs_work` / `cannot_assess` | `meets-criteria` / `needs-review` / `cannot-assess` |
| `FindingCategory` `procedure` / `answer_support` / `completeness` / `communication` | `procedure` / `answer-support` / `completeness` / `communication-style` |
| `ManagerReviewOutcome` `cannot_assess` | `cannot-assess` (others unchanged) |
| `Turn.line_number` | `TranscriptTurn.number` and every evidence number, gaps kept |
| `Finding.knowledge_entry` | a `references` entry; each approval creates a new entry row, so `version` is `review-<approving review id>` |
| No audit yet | `status: "processing"`, `automatedResult: "processing"` |
| Flags with no Manager review / all reviewed / none | `review-requested` / `review-complete` / `feedback-ready` |

Rules the mapping applies, each covered by a test:

- System-action turns are not part of the frontend transcript, so they are left out of
  `transcript` and of evidence numbers.
- A category with no stored finding is `cannot-assess` with the explanation
  "No result was stored for this criterion."
- A stored `needs_work` finding whose evidence is not in the transcript is shown as `cannot-assess`,
  never as a failure without evidence.
- A conversation without a topic shows `Unassigned`.
- Approved guidance is assigned to every agent in the organization; Managers are assigned none.
- Fields the database does not store stay empty: `duration`, `TranscriptTurn.time`,
  `KnowledgeEntry.effectiveAt`, `owner`, `source` and `steps`. A conversation with no source date has
  `date: null` and is listed after the dated ones.

## Gaps in the current frontend types

Documented here rather than filled with invented data. Each needs agreement with the frontend team.

1. **No organization or permissions on `Viewer`.** `role` is only `agent | manager`; there is no
   Knowledge Approver. #71 keeps organization and permissions in the server-side user context;
   the frontend may need a `permissions` field later.
2. **No organization ID on any response.** Organization scoping happens on the server only.
3. **`KnowledgeEntry.availableToAgentIds` exposes every assigned agent's ID.** Resolved on the server:
   the knowledge routes and `CallReview.references` trim it to `[requesterId]`. The field could be
   dropped from the frontend type entirely once the frontend stops relying on it.
4. **No technical-failure state.** `CallReview.status` is only `ready | processing` and
   `AutomatedResult` has no `failed`. A failed analysis run therefore still shows as `processing`
   to the agent; the failure and its error code are visible to Managers in the analysis status
   route. A `failed` value would let the frontend show it.
5. **Preformatted strings.** `duration` and `TranscriptTurn.time` are display strings like `4:32`
   with no defined format for calls over an hour.
6. **Dates and durations can be unknown.** Source datasets do not always record a call date or length, so
   `Conversation.date`, `CallReview.date` and `CallReview.duration` are nullable rather than guessed.
   The frontend types still say `string`; `getAgentConversations` sorts with `localeCompare`, which
   needs a null check before it reads database records.
7. **Date formats are implicit.** `Conversation.date` and knowledge dates are `YYYY-MM-DD`;
   `decision.decidedAt` is an ISO 8601 timestamp. No timezone is stated for date-only values.
8. **One decision per call.** `CallReview.decision` holds a single Manager decision, with no history
   and no link to which finding was reviewed.
9. **A listed conversation can have no call record.** The list has no way to mark that the detail
   is unavailable; the detail route returns `404` (fixture `C1046`).
