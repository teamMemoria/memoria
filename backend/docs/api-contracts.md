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

## Proposed routes

These are implemented in #72–#74. The agent is always the authenticated requester (#71),
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
