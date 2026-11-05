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
To run locally:

```bash
MEMORIA_APP_ENV=development .venv/bin/uvicorn backend.main:app --reload
curl -H "X-Dev-User: agent-alex-morgan" localhost:8000/api/viewer
```

`feedback:review` (Managers) and `knowledge:approve` (Knowledge Approvers) are deliberately separate.
Routes protect themselves with `Depends(require_permission(Permission.X))`, and agent-owned records
are checked with `can_read_agent_record(user, organization_id, agent_id)`.

## Proposed routes

`/api/viewer` (#71), `/api/agent/conversations` (#72) and `/api/agent/conversations/{conversationId}` (#73) are implemented; knowledge comes in #74. The agent is always the authenticated requester (#71),
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
  measured against (fixture `C1047`).
- **`decision`** is the Manager's decision, kept beside the automated `criteria`, never merged into them.

| Status | Body | When |
|---|---|---|
| `200` | `CallReview` | Success, in any of the states above |
| `401` | `{"detail": "Missing identity"}` | No identity |
| `403` | `{"detail": "Not permitted"}` | A Manager or Knowledge Approver without `conversations:read-own` |
| `404` | `{"detail": "Conversation not found"}` | Unknown call, call record unavailable, or another agent's or organization's call |
| `503` | `{"detail": "Data source unavailable"}` | The call provider is down |

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

## Providers

Routes read data through the interfaces in `backend/src/backend/providers/base.py`
(`ViewerProvider`, `ConversationProvider`, `CallReviewProvider`, `KnowledgeProvider`).
Every method takes an `organization_id` and returns `None` for records that are missing
or not visible to that agent. The app starts with the fixture providers; #75 adds
PostgreSQL implementations of the same interfaces. Tests can pass their own `Providers`
to `create_app()`.

## Gaps in the current frontend types

Documented here rather than filled with invented data. Each needs agreement with the frontend team.

1. **No organization or permissions on `Viewer`.** `role` is only `agent | manager`; there is no
   Knowledge Approver. #71 keeps organization and permissions in the server-side user context;
   the frontend may need a `permissions` field later.
2. **No organization ID on any response.** Organization scoping happens on the server only.
3. **`KnowledgeEntry.availableToAgentIds` exposes every assigned agent's ID** to any agent who can
   read the entry. #74 should decide whether to trim this to the requester or drop it from responses.
4. **No technical-failure state.** `CallReview.status` is only `ready | processing` and
   `AutomatedResult` has no `failed`. #76 requires failures to stay distinct from `cannot-assess`,
   so a new value will be needed.
5. **Preformatted strings.** `duration` and `TranscriptTurn.time` are display strings like `4:32`
   with no defined format for calls over an hour.
6. **Date formats are implicit.** `Conversation.date` and knowledge dates are `YYYY-MM-DD`;
   `decision.decidedAt` is an ISO 8601 timestamp. No timezone is stated for date-only values.
7. **One decision per call.** `CallReview.decision` holds a single Manager decision, with no history
   and no link to which finding was reviewed.
8. **A listed conversation can have no call record.** The list has no way to mark that the detail
   is unavailable; the detail route returns `404` (fixture `C1046`).
