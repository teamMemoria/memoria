# Knowledge pipeline (ML)

Post-call text only. Finished ABCD conversations go in; **unapproved** drafts
and findings come out, for an authorized person to review. The pipeline has no
API, database, job queue or UI. The backend owns those, and it also owns IDs,
access, storage, statuses and every human decision. Everything here runs on
local JSON files, with no backend and none of Nick's code.

Code lives in `src/backend/services/knowledge/`.

| Stage | Issue | Entry point | Status |
|---|---|---|---|
| Extract knowledge drafts | #16 | `extract_drafts` | done |
| Group drafts and find duplicates | #17 | `group_drafts` | done |
| Find possible knowledge conflicts | #18 | `find_conflicts` | done |
| Check drafts against approved sources | #19 | `check_drafts` | this PR |

## Running it

```bash
cd backend
uv sync
uv run pytest tests/knowledge                      # offline, about 2 s
uv run python -m backend.services.knowledge extract data/abcd/conversations --company acme --out /tmp/drafts.json
uv run python -m backend.services.knowledge group /tmp/drafts.json --company acme --out /tmp/groups.json
uv run python -m backend.services.knowledge conflicts /tmp/drafts.json --company acme --groups /tmp/groups.json --out /tmp/conflicts.json
uv run python -m backend.services.knowledge verify /tmp/drafts.json --company acme --references data/references/abcd-guidelines.snapshot.json --conflicts /tmp/conflicts.json --groups /tmp/groups.json --as-of 2026-10-22
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
  Rewritten wording stays unverifiable: checking its source quotes does not
  establish that a paraphrase means the same thing. Truncated replies are errors.
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

## #17: Group drafts and find duplicates

```python
from backend.services.knowledge import group_drafts, GroupingConfig

result = group_drafts(drafts, company_id="acme", existing_entries=entries, config=GroupingConfig())
result["groups"]  # one entry per group, singletons included
```

**Input.** Drafts from #16, for one company. Optionally, existing knowledge
entries supplied by the backend, in the form `{entry_id, company_id, scope:
{flow, subflow}, question, answer, conditions, status, version}`. A draft
from another company is rejected with `invalid_input`. An entry from another
company is ignored. Knowledge bases never mix.

**What groups.** Drafts are only compared within one scope: company plus
ABCD subflow (`scope_level="flow"` widens this to the flow). A draft joins a
group when its similarity to the group's members is at least
`group_threshold` **and** its conditions are compatible with every member's.
Conditions are compatible unless one of these holds:

- the membership levels named are disjoint (gold vs guest);
- only one of the two depends on membership at all;
- the same unit has different values (7 days vs 30 days).

Incompatible drafts stay apart even with identical wording. #18 is where they
get compared. Similarity is TF-IDF cosine over question and answer, plus a
sentence-by-sentence alignment of the answers, so filler around the part that
matters doesn't hide a match. A handful of domain synonyms ("promotional",
"coupon" → "promo") and quantity tokens ("one week" = "7 days") are applied.
Clustering visits drafts in `draft_id` order, so the result doesn't depend on
input order.

**What comes out, per group.**

- `member_draft_ids`, plus `representative`. The representative is the most
  central member, **unchanged** and still `status: "draft"`, with its own
  passages. Text is never blended across drafts.
- `distinct_conversation_count` and `source_keys`. These count distinct
  source conversations, not drafts or turns. The same draft submitted twice
  is kept once and reported in `duplicate_input_drafts`. The same ABCD
  conversation read from the curated and the raw file counts once.
  Reprocessing never raises a count.
- `duplicates`. These are pairs that are exact, or above
  `duplicate_threshold` with identical conditions. Paraphrases share a group
  without being duplicates.
- `existing_matches`. Existing entries in the same scope, with their status
  and version, marked `equivalent`, `related` or `different_conditions`.
- `meets_source_threshold`. True once `min_distinct_conversations` distinct
  conversations back the group. **This is not verification**, and neither is
  a similarity score or a match with an approved entry.

ML only returns groups, counts and matches. The backend stores them and
updates queue statuses and counts.

**Tests.** `tests/knowledge/test_grouping.py`. The labelled cases in
`labels/grouping.json` (first pass, `human_reviewed: false`) cover exact
duplicates, paraphrases, similar but different questions, conditional answers
that must not merge, different scopes, and two real ABCD sets. Other tests
cover repeat processing, input-order independence, cross-company input and
existing-entry matches. `group_threshold` (0.25) was chosen on these labels, so
treat them as a regression check. #20's held-out cases are where it gets a
fair score.

### Still to agree (#17)

- `group_threshold` 0.25, `duplicate_threshold` 0.8,
  `existing_match_threshold` 0.45.
- `min_distinct_conversations` 3 (the README's guess). It only sets
  `meets_source_threshold`, a queue hint. Whether drafts below it should be
  created at all is undecided, and it is **not an approval rule** either way.
- Whether one person calling three times counts once. Today the count is of
  conversations. Counting distinct customers needs a customer id, which ABCD
  doesn't provide.

### Known limits

- Lexical similarity misses paraphrases that share few words. The model
  extractor's normalised wording helps. Embeddings (pgvector is already in
  the stack) are the obvious next step and fit behind `similarity()`.
- Condition compatibility reads membership levels and quantities only. A
  condition such as "with a receipt" vs "without a receipt" isn't caught here.
  #18 compares claims more closely.

## #18: Find possible knowledge conflicts

```python
from backend.services.knowledge import find_conflicts

result = find_conflicts(drafts, company_id="acme", existing_entries=entries, groups=groups)
result["possible_conflicts"]     # status "possible_conflict" or "unresolved"
result["explained_differences"]  # looked contradictory, explained by conditions or an exception
```

**What is compared.** Each answer passage of a draft is one claim, and so is
each sentence of an existing entry. Two drafts are compared when they share a
company and scope and their questions overlap. A draft is compared with every
existing entry in its scope. Group membership doesn't limit this: incompatible
drafts were deliberately put in different groups by #17, and they still need
to be compared. One conversation read twice is not compared with itself.
Pairs of existing entries are not compared.

**What counts as a possible conflict.** Two claims about the same thing (at
least two shared subject words), where one of these holds:

- **eligibility:** one claim allows a membership level that the other
  excludes. "Guests can always get a replacement code" against "Guests cannot
  get a replacement promo code". Or, from a real ABCD pair, "I could only
  issue a replacement promo code to one of our existing members" against a
  guest's chat where "A promo code has been created". A recorded action takes
  the membership level of its own conversation.
- **value:** the same unit with different figures under the same conditions,
  such as 7 days against 30 days.
- **polarity:** "X" against "not X", where the negation applies to something
  the other claim asserts. "You will not be charged" doesn't contradict "I
  cancelled the order".

**What doesn't.** These are separated out:

- **Different wording.** 7 days and "one week" agree.
- **Different conditions.** Members can but guests cannot, or different
  figures for different levels. These go to `explained_differences` so the
  condition difference stays visible.
- **An exception.** "Bronze cannot return final-sale items" is the "unless the
  item was on final sale" of the other claim.
- **Different scope or company.** These are never compared.
- **Missing evidence.** If only one side states a figure or condition, nothing
  is reported.

**Uncertain cases stay `unresolved`.** That covers hedged wording ("I think",
"usually", "might"), time-bound statements ("this year", a date) that may
differ by date rather than by policy, and polarity with only partial overlap.

**Each finding has** both exact passages, with their draft id or entry id,
source key or entry version, `reference_status` (`unverified draft`, or the
entry's own status such as `approved`), the conditions of each side, the
compared conditions (levels allowed and excluded, quantities, negation,
exceptions), a one-line explanation, the uncertainty reasons, and the group id
of each side when `groups` is passed.

**ML only reports.** It never marks an entry disputed, removes it from use,
replaces it or rewrites an earlier audit. A test checks that inputs are
unchanged and that no such field appears. Authorized people and backend rules
decide all of that. This module doesn't use Nick's audit code or reports.

**Tests.** `tests/knowledge/test_conflicts.py`. The labelled pairs in
`labels/conflicts.json` (first pass, `human_reviewed: false`) cover
contradictions, paraphrases, exceptions, different scopes, different
conditions, uncertain cases and agreements, which check for false alarms.
Across all 100 ABCD records, the only possible conflict reported is the real
one (ABCD-0041 against ABCD-0046).

### Still to agree (#18)

- **How to show unresolved conflicts.** Today they are a separate status,
  each with its own `uncertainty` list. The backend could queue them with
  possible conflicts or keep a separate list.
- **Which condition differences must stay visible.** Today every explained
  difference is returned. Trimming the list is a display choice.

### Known limits

- Claims are compared with rules: membership levels, numbers with units,
  negation scope and exception clauses. A contradiction expressed in other
  terms is missed, for example "in store only" against "by mail". A model
  comparator could sit behind `_compare` with the same output shape.

## #19: Check drafts against approved sources

```python
from pathlib import Path
from backend.services.knowledge import check_drafts, load_reference_snapshot

references = load_reference_snapshot(Path("data/references/abcd-guidelines.snapshot.json"), "acme")
result = check_drafts(drafts, "acme", references, conflicts=conflicts, groups=groups, as_of="2026-10-22")
```

**References.** These are local, reviewable snapshots of ABCD's guidelines
(`data/references/`, built by `scripts/build_reference_snapshot.py`, with no
dependency on Nick's retrieval code). Every passage is word for word and
carries its own approval and eligibility. **The committed snapshot is entirely
`unreviewed`, so it verifies nothing until a person reviews it.** See
`data/references/README.md`. A reference can support or contradict a claim
only when all of these hold:

- it is an `authoritative_reference` (never another draft, a repeated agent
  answer or a knowledge entry);
- it belongs to the same company and applies to the draft's subflow;
- `approval.status` is `approved`;
- `eligibility.status` is `eligible`, and it isn't past `valid_until`. An
  expiry date with no `as_of` date counts as not current.

Every other reference in scope is listed in `ignored_references` with the
reason.

**Claims.** Each answer passage is one claim. A claim is checked against each
usable passage, and against each guideline action read together with its
sub-points, because a rule is often split across them ("Ask for 3 out of 4
items below" plus the list). The claim then gets one of these statuses:

- `contradicted`: the reference excludes a membership level the claim
  includes (a guest given a new code), gives a different figure for the same
  thing (2 of 3 details against 3 out of 4), or says the opposite.
- `supported`: at least 60 % of the claim's subject words appear in one
  passage, and any figure in the claim is the same figure in the passage.
- `partially_supported`: between 35 % and 60 %, or a figure the reference
  doesn't confirm.
- `unverifiable`: no usable passage comes close.

Each claim lists `citations` (reference id, version, snapshot, quote, approval,
eligibility, guideline, support score), `contradicted_by` (with the reason) and
`missing_conditions`. A missing condition is a membership level or limit that
the matching reference attaches to what the agent said, which the draft
leaves out. These stay unresolved and become requirements.
Explicit condition clauses are compared literally, not by general language understanding.
Conditions in a heading and its sub-points are checked together; warnings quote
the original section that states the condition.

**Per draft:**

- `verification_status`: `supported` only when every claim is supported.
- `ml_recommendation`: `supported_by_references`, `needs_more_evidence`,
  `contradicted_by_references` or `cannot_be_verified`. A supported draft with
  a missing condition or an open possible conflict from #18 is downgraded to
  `needs_more_evidence`. Missing verification never gives a supported
  recommendation.
- `decision: null`.
- `requirements_remaining`. This always ends with a human verification step.
  Having permission to approve is not the same as having checked the
  evidence.
- `possible_conflicts`, taken from #18.
- `supporting_conversations`, taken from #17's groups. These are labelled as
  repetition, not verification.

**ML cannot** approve or reject, replace entries, renew verification dates or
make a draft available for audit use. Tests check that the inputs, including
every reference's approval and eligibility, are unchanged after a call, and
that no decision field is set. The backend checks knowledge permission,
completed verification and current reference versions before it saves an
approval.

**Tests.** `tests/knowledge/test_verification.py`. The labelled drafts in
`labels/verification.json` (first pass, `human_reviewed: false`) cover
supported, partly supported, contradicted, conditional and unverifiable
drafts. They run against an in-memory copy of the snapshot that the test
approves. Other tests cover unreviewed, rejected, stale, expired, disputed,
out-of-scope and other-company references, references that aren't
authoritative, missing conditions, carried conflicts, and the rule that every
supported claim across the ABCD corpus cites an approved authoritative
passage.

### Still to agree (#19)

- **Who approves verification sources**, and where that is recorded (in
  this file or in the backend).
- **Whether every claim needs support.** `VerificationConfig(require_every_claim=True)`
  is the default. Small talk that slipped into an answer ("Thank you for
  contacting us") then keeps a draft at `partially_supported`. That is
  deliberately strict.
- **How to approve and credit adapted ABCD guidelines.** Passages are kept
  verbatim with their source commit and SHA-256. An adapted version should be
  a new snapshot with its own version.

### Known limits

- Support is lexical. A claim that paraphrases a guideline in very different
  words comes out `partially_supported` or `unverifiable`, never wrongly
  `supported`. The error is on the safe side, but it does create reviewer
  work.
- "Or" conditions in guidelines (within 90 days *or* with a receipt *or* in
  original packaging) are read as separate limits. A draft that states only
  one alternative is flagged as missing the others.
