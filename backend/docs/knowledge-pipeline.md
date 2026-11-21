# Knowledge pipeline (ML)

Post-call text only. Finished ABCD conversations go in; **unapproved** drafts
and findings come out, for an authorized person to review. The pipeline has no
API, database, job queue or UI. The backend owns those, and it also owns IDs,
access, storage, statuses and every human decision. Everything here runs on
local JSON files, with no backend and none of Nick's code.

Code lives in `src/backend/services/knowledge/`.

| Stage | Issue | Entry point | Status |
|---|---|---|---|
| Extract knowledge drafts | #16 | `extract_drafts` | this PR |

## Running it

```bash
cd backend
uv sync
uv run pytest tests/knowledge                      # offline, about 2 s
uv run python -m backend.services.knowledge extract data/abcd/conversations --company acme --out /tmp/drafts.json
uv run python scripts/knowledge_examples.py        # rewrite examples/knowledge/ after a deliberate change
```

## #16: Extract knowledge drafts

```python
from backend.services.knowledge import extract_drafts

result = extract_drafts(record, company_id="acme")   # record: one ABCD JSON object
result.status          # "ok" or "error"
result.drafts          # list of drafts (may be empty when status is "ok")
result.no_draft_reason # set whenever drafts is empty and status is "ok"
result.errors          # set whenever status is "error"
```

**Input.** One ABCD conversation, in either shape:

- the curated shape (`id`, `source`, `turns`, `source_fields`, ...), as in
  `data/abcd/conversations/`;
- the raw ABCD v1.1 shape (`convo_id`, `scenario`, `original`, `delexed`).

Both are read straight from JSON (`abcd.py`). The reader keeps the source and
its version (`source.version`, `source.dataset_version`), the turns in order
with stable IDs (`ABCD-0041#t21`), the recorded agent actions paired with
their system turns, and evidence coverage (turns kept versus turns in the
source, and how many actions lined up with a turn). `source_key`
(`ABCD:<original id>`) is the same whether a conversation was read from the
curated file or from the raw dump, so it is never counted twice.

**Output.** Each draft has:

- `question` and `answer`, each with `*_passages`. A passage is the
  conversation ID, turn ID, speaker, character span and the exact quoted text.
  `check_draft_citations(draft, conversation)` re-reads the conversation and
  confirms every quote is the text at its span.
- `conditions`. These are the parts the answer depends on: membership levels,
  time limits, exceptions and requirements. Each one cites its passage and its
  basis: `agent_statement`, `customer_statement` or `recorded_action`.
- `procedure`. The agent's recorded actions, in order.
- `source`, `scope` (company, flow, subflow), `topic`, `evidence_coverage`,
  `privacy.redactions` (counts by type) and `extractor`.
- `status: "draft"`, `trusted: false`, `audit_eligible: false` and
  `verification.status: "not_verified"`, always. The pipeline has no way to
  approve a draft. Observing an answer does not verify it.

See `examples/knowledge/extraction/` for fixed inputs and the exact outputs.

**Errors are never empty successes.** Bad JSON shapes, missing fields,
out-of-order turns and unknown speakers return `invalid_input`. Over 400
turns, over 4,000 characters in one turn, or over 120,000 characters in total
returns `oversized_input`. A model that fails, times out or replies with
something other than JSON returns `model_failure`, and a reply in the wrong
shape returns `model_output_invalid`. In every error case `drafts` is empty
and `status` is `"error"`. A conversation with nothing reusable is the other
case: it returns `status: "ok"`, no drafts, and a `no_draft_reason`
(`no_reusable_answer`, `no_customer_request` or `topic_not_selected`).

**Personal data** (`privacy.py`) is removed before anything else reads the
text. Values are replaced with typed placeholders (`[CUSTOMER_NAME]`,
`[EMAIL]`, `[PHONE]`, `[ADDRESS]`, `[ORDER_ID]`, `[ACCOUNT_DETAIL]`, `[CODE]`,
`[CARD_NUMBER]`, `[DATE]`, ...). Nothing is invented in their place, and
membership levels, prices, time limits and policy wording are kept. Two
sources are used: the conversation's own customer record (including names the
customer misspells) and patterns for anything the record doesn't list. A
sentence that only hands one customer their own details ("Your new password is
[ACCOUNT_DETAIL]") is never treated as an answer.

**Two extractors.**

- `RuleExtractor` (the default) is deterministic and needs no model. The
  question is the customer's request. The answer is the agent's substantive
  sentences (greetings, filler, identity requests and account-specific
  sentences are skipped), plus recorded outcome actions such as
  `promo-code` or `offer-refund`. Everything is quoted verbatim, so it cannot
  generalise beyond what was said.
- `ModelExtractor(client)` asks a model to choose the question, answer and
  condition turns, and to word them. It then checks the reply. Any of these
  rejects that draft, and the rejection is reported in `rejected_drafts`: a
  turn ID that does not exist, a question that does not cite a customer turn,
  a figure or membership level missing from the cited turns, a negation
  missing from them, under 60 % of content words supported by them, or any
  personal detail. The model only ever sees redacted text.
  `OpenAICompatibleClient` works with any `/chat/completions` server,
  including a local Ollama. Set `LLM_BASE_URL`, `LLM_MODEL` and
  `LLM_API_KEY`. The provider is still undecided (see the top-level README).

**Tests.** `tests/knowledge/test_abcd.py`, `test_privacy.py` and
`test_extraction.py` use the ABCD records plus made-up conversations in
`tests/knowledge/conversations/`. The labelled cases in
`tests/knowledge/labels/extraction.json` cover faithful and useful extraction,
conditions, personal-data removal, and conversations that should produce no
draft. **These labels are a first pass and still need a second person's
review** (`human_reviewed: false`, see the file). The rule extractor currently
gets all 24 draft/no-draft decisions right, and finds 22 of 22 required answer
phrases and 18 of 18 required condition phrases. Some labels were written
after looking at its output, though, so treat these as a regression check and
not an unbiased score. Issue #20 adds a held-out set. The test floors are 95 %,
90 % and 80 %. Every ABCD draft cites exactly and leaks no record value.

### Still to agree (#16)

- **Starting topics.** `ExtractionConfig(topics=...)` takes flows or
  `flow/subflow` pairs. Default: all ten ABCD flows. Proposed first:
  `storewide_query` and `single_item_query` (general policy and product
  answers), then `purchase_dispute`.
- **Personal-data rules.** What counts as personal is set by the placeholder
  types above. Open question: should a city on its own be removed? It is
  removed today, to be safe.
- **What makes an answer worth reusing.** `min_answer_words` (5),
  `max_placeholder_share` (0.34) and `allow_action_only_answers` (on) are the
  knobs. An action-only answer ("A promo code has been created.") keeps the
  draft visible when the agent said little. This matters: a wrong action, such
  as a guest given a new code, should still reach review.

### Known limits

- The rule extractor finds one request and one answer per conversation. It
  doesn't split a chat that covers two separate questions.
- It recognises conditions from wording (if / only / within / membership
  levels ...). Unusual phrasings are missed, and a sentence can be tagged as a
  condition when it is really just an answer sentence that contains "if".
- Redaction is pattern based. It is tested on all 100 ABCD records and on
  made-up edge cases, but real transcripts will need a broader test set before
  any real data is used.
