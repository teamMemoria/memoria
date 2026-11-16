# Deterministic percentage assessments

This is a local, rule-based experiment. It does not call an LLM, Jev, OpenAI
Decisions, Ollama, Groq or another model API. Rules recognize declared wording
and recorded action forms; they do not understand every sentence.

## Frozen training cohort

`rule_cohort.json` freezes 117 unique training conversation IDs, original training
positions, 31 dialogue aliases and the source commit/checksum. Every alias was
checked against an explicit agent self-introduction. These are demo personas,
not verified people or proof that one person handled all chats under an alias.
The existing 15 remain the development subset. No dev/test conversation content
is needed for this experiment or its constructed tests.

Five varied conversations were selected **before rule-engine verdicts**: 8434
(site performance), 835 (account address), 8097 (refund update), 223 (size return)
and 9359 (subscription policy). Their human reviewer, date and judgements remain
unset. Selection is not a result label and is never an evaluator input.

Sixteen records have inconsistent optional `delexed` turn annotations. Their
warnings remain in the manifest. Preparation uses only the original messages
and actions plus personal/order fields for masking; research annotations,
scenario intent, flow/subflow, targets and candidates are not audit input.
Original turn positions are preserved. Unrecognized or malformed actions remain
visible evidence, not invented successful actions or proved agent failures.

## Workflow inventory and decision tables

Inventory uses customer wording and recorded actions, never dataset answer
labels. The initial observable-purpose inventory found 45 candidate workflows
across all 10 public guideline families. These tables preserve their complete
pinned guideline sections and applicable conditions. A pattern hit is only a
purpose candidate; quotation, negation, changed requests and ambiguity must be
resolved before choosing applicable requirements.

| Guideline family | Candidate workflows documented |
| --- | --- |
| Product Defect | initiate-refund, update-refund, refund-status, return-due-to-color, return-due-to-size |
| Order Issue | status-payment-method, status-quantity, manage-upgrade, manage-downgrade, manage-cancel |
| Account Access | recover-username, recover-password, reset-two-factor-auth |
| Troubleshoot Site | invalid-credit-card, cart-not-updating, search-not-working, website-too-slow |
| Manage Account | status-service-added, status-service-removed, status-shipping-question, manage-change-address |
| Purchase Dispute | bad-price-competitor, bad-price-yesterday, out-of-stock-general, promo-code-invalid, promo-code-out-of-date, mistimed-billing-already-returned, mistimed-billing-never-bought |
| Shipping Issue | shipping-status, manage-shipping, missing-item, shipping-cost |
| Subscription Inquiry | status-due-amount, status-due-date, manage-pay-bill, manage-extension, manage-dispute-bill |
| Single-Item Query | boots-faq, shirt-faq, jeans-faq, jacket-faq |
| Storewide Query | pricing-faq, membership-faq, timing-faq, policy-faq |

The inventory recognizes a candidate in 116/117 records; 21 have multiple
candidates. This is **not** 116 correct classifications or a measure of accuracy.
Conversation 5496 contains incomplete copied-task wording, inconsistent jeans/
jacket context, and an unrelated food request. Its possible product-question
purposes and unsupported content stay unresolved; no special-case verdict or
forced workflow is assigned. These observations are inventory metadata only.

Six initial recognition gaps were inspected. General equivalents now include
rejected/rejecting, reversed “cost of shipping”, plural sizes, “search doesn't
work”, and a product subject followed by a materials/care question. These have
constructed positive and counterexample tests. They do not justify interpreting
arbitrary paraphrases, quoted requests or unrelated intervening turns.

Of 492 recorded actions, the inventory lexicon matches 269 forms recording an
action, 161 forms recording only a started operation, and leaves 62 unresolved.
The unresolved set includes 34 ambiguous “looking for solutions” messages and
28 blank/malformed payloads, unsupported status values, or malformed refund
amounts. A recognized action form does not establish correct policy compliance.

Each workflow uses shared one-point check definitions, relevant source sections
and action forms. The tables record 105 explicit field prerequisites and four
explicit field-order relationships. “Full name or Account ID” is one alternative
check, not two mandatory checks. Identity rules asking for three of four/seven
details retain that threshold as an unresolved condition until a tested rule
supports it. Source list position never creates a mandatory order. Unparsed
conditions, exceptions and relationships remain unresolved rather than passing.

The shared categories are:

- **Procedure:** required actions, supported prerequisites, explicit order and
  applicable conditional details. Lookup is not identity; started validation is
  not successful validation. Volunteered information can satisfy a detail.
- **Completeness:** each distinct request's contextual disposition, requested
  elements and required next-step details. A linked promise or refusal can
  address a request without completing it. Changes and withdrawals retain prior
  history and can follow answers or promises.
- **Communication style:** defined instruction clarity, relevant acknowledgement
  and explicit respectful/disrespectful wording. No inferred emotion, intent,
  vocal tone, satisfaction or penalties for dialect alone.
- **Answer support:** distinct factual assertions, their values/units and material
  conditions against eligible guidance or recorded evidence. A shared keyword,
  FAQ selection or the agent's own claim is not independent factual support.

## Approval and provenance

The user explicitly approved seven bounded ABCD sections, the four authored
Memoria criteria, the point policy and two supported weight profiles for the
local demo on 2026-11-09. Their unchanged content versions and the authorization
are preserved in the local approval snapshot. Verification is conservatively
limited to that assessment date; this does not establish production suitability
or an ongoing review interval. The 38 blocked sections, new derived candidates
and human case judgements remain unapproved. The
existing refund references and their controlled-experiment interpretation limits
are unchanged. New policy is not authorized simply because an old reference was
approved. Unsupported simulated instructions (including invented/default outcomes)
remain flagged and blocked. Do not approve a whole source section to bypass a
specific unsafe sentence: correct and version it before human review.

Memoria request/wording criteria use genuine local provenance at
`ml/rule_tables.json`, not ABCD attribution. Every section has a content-derived
version. Scoring approval binds the complete policy table and current reference
review state; profiles have separate content-derived versions. Approving or
changing a reference invalidates the previous policy fingerprint. No new
conversation renews verification or approval.

Copied ABCD guidance retains the pinned commit
`6b8700ce67c6b37b062dd7a60abc76d7ef832a97` and guideline SHA-256
`9264557941df24fe075138a632a2345172971573124a354ccb2ceee2a12e4c2a`.
The complete required ASAPP MIT notice is retained below and in `abcd.py`.

## Points, coverage and weights

Each approved atomic check is worth one point. Direct support earns one; a
directly evidenced breach earns zero with one justified deduction. Unresolved
checks earn nothing and deduct nothing. Proven inapplicability is excluded with
its evidence. Partial credit is declared subchecks, never a guessed fraction.
Equivalent repeated requests, claims or evidence cannot manufacture points.

For each category:

- **E** = earned points; **A** = assessed maximum (including evidenced breaches).
- **P** = applicable plus unresolved potentially applicable maximum.
- Score = `100 * E / A`; evidence coverage = `100 * A / P`.
- Zero assessed points means **Not scored**, never 0% or automatic full marks.
- Unknown applicability or missing authority is visible separately; it must not
  be represented as an invented full denominator.

For example, 18/20 assessed points with 100 potentially applicable points means
90% with 20% evidence coverage. This is not a complete performance assessment.
Scores use unrounded values internally. With approved equal weights,
90%, 90%, 92%, 92% gives 91% overall.

Overall requires all four category scores and one applicable, approved profile.
No missing category's weight is redistributed. Ordinary support proposes
30/30/20/20; account-access changes propose 40/20/10/30 (Procedure, Completeness,
Style, Answer support). Fraud is explicitly disabled future scope; a keyword
cannot establish suspected fraud. Criticality must come from approved rule
metadata and remains visible regardless of the overall percentage.

## Verification and limits

Constructed tests validate rule mechanics, reference versions, canonical quotes,
context handling, score arithmetic, approval gates and known counterexamples.
They do not establish semantic accuracy across these 117 conversations. Report
processing failures, per-workflow/per-metric evidence coverage and observed
semantic errors separately. Mechanical citation validity only proves that a
quotation exists at its cited source; humans still check whether it supports the
judgement. The five selected spot-checks and shared approval package are pending.

Expanded evidence and failures belong under ignored `ml/output/`; raw sources
remain local. Masking is lexical and requires a privacy spot-check before
sharing. Do not expose incidental source names or financial strings because
record preparation happened to succeed.

Complete workflow coverage means documented applicable checks, supported patterns
and tested limitations for every represented purpose. It never means every
sentence was understood. All 117 records must remain in processing, including
ambiguous and malformed examples; do not replace difficult cases.

The 2,900-added-line estimate was a stretch guide. Preserving 45 full provenance-
bound guideline sections, rule conditions and 117 source/alias mappings exceeds
that guide in manifest/table data alone. Production functions, tests, data and
documentation must be reported separately; formatting is not compressed to hide
the data size.

## Execution and implementation boundaries

`prepare_cohort(training, source, manifest)` accepts the parsed official training
list, its verified source pin and the frozen manifest. It keeps only original
messages/actions and approved masking fields before calling shared preparation.
Its result contains `evidence`, isolated `errors`, and optional annotation
`warnings`. `run_cohort` accepts those parsed values and an optional checkpoint;
only its outer execution loop reads the timing clock. No rule reads files or
uses the execution clock to infer performance.

```python
from ml.rule_batch import prepare_cohort, run_cohort, cohort_summary

prepared = prepare_cohort(training, source, manifest)
development = run_cohort(
    prepared["evidence"], manifest, references, rubric, tables,
    as_of="2026-11-09", development=True,
    preparation_errors=prepared["errors"],
)
complete = run_cohort(
    prepared["evidence"], manifest, references, rubric, tables,
    as_of="2026-11-09", checkpoint=development,
    preparation_errors=prepared["errors"],
)
summary = cohort_summary(complete)
```

The caller loads/saves JSON under ignored `ml/output/`; pass a saved checkpoint
back to resume. Changed evidence, policies, approvals, dates or rule versions
invalidate cached records and retain old attempts in history. Do not parse or
use held-out content to supply `training`. This API does not download datasets
or assert that a caller-supplied checksum was verified against raw bytes.

Preparation uses opt-in masking v5 for grouped financial identifiers. The legacy
v4 default and refund benchmark remain unchanged. Both versions validate against
their own transcript hashes; results cannot be relabelled across versions. v5
fixes the two observed grouped-number gaps, but privacy review is still required
for incidental names, misspellings and unlabelled personal information.

For backend integration, `import_prepared` requires an existing same-organization
agent and canonical evidence. It stores full evidence separately from display
turns, including system actions. `MEMORIA_ANALYSIS_ENGINE=rules` selects the
local adapter. Successful full reports are stored with Audits and AnalysisRuns;
technical partial results stay on retryable AnalysisRuns. Existing Manager
decisions remain separate and are never rewritten by a score.

The inherited backend permits one successful Audit per conversation. It does
not yet refresh saved audits after policy approvals or rule changes. Local batch
checkpoints invalidate correctly, but a versioned backend re-analysis lifecycle
is separate follow-up work. Verification used separate disposable databases for
successive rule versions, preserving earlier audits and decisions.

The optional frontend proxy connects the existing UI without a profile picker:

```sh
# From frontend/, with the local backend already running:
MEMORIA_BACKEND_URL=http://127.0.0.1:8765 \
VITE_API_BASE_URL=/ VITE_DEV_USER=demo-abcd-adam npm run dev
```

Use the separately seeded `demo-abcd-manager` development identity for Manager
checks. These development headers are disabled by the existing production
safeguards. Production authentication is not added here. The chosen backend base
has no knowledge-draft mutation provider; that route remains explicitly
unavailable in backend mode, rather than mixing real ownership with fixture data.

Numeric claim checks currently require the complete assertion frame, units and
conditions to match one eligible source statement. A different value in that
same frame can support a deduction; a changed unit, missing condition, quotation
or unrecognised correction remains unresolved. These inseparable assertions are
one check. Partial credit comes from independent checks such as individually
specified prerequisites, not additional points for matching words in a false
claim. Short-answer withdrawal checks require the same operation, object and
recipient as the preceding question and the existing request. Supported request
paraphrases and numerically equivalent repeated claims are deduplicated.

## Local verification, 2026-11-09

- All 117 records prepared and processed with rule version
  `observable-rule-checks-v5`, request-link version `contextual-request-links-v3`
  and masking v5. A second run revalidated and reused all 117 checkpoints.
- The stricter evaluation context establishes one purpose candidate for 90
  records, multiple candidates for 19, and no candidate for eight. All 45
  inventoried workflows remain represented among candidates. These counts differ
  from the broad inventory because quotes/negation/context are filtered.
- 3,925 candidate checks were produced; per-metric/workflow denominators are
  in the local final summary. Counts are not accuracy scores.
- Every new policy remains unapproved, so the real reports correctly have no
  authoritative numeric scores. Tests exercise approved scoring using isolated,
  authored in-memory fixtures only. No human acceptance or semantic error rate
  is claimed for these 117 cases.
- An isolated database stores 117 successful final reports and 31 demo aliases.
  Earlier database runs and checkpoint histories remain preserved separately.
- Chrome/WebKit verified actual database cards, ledgers, canonical action links,
  Back/Forward, Agent ownership and the Manager's 117-conversation queue.
- Existing sidebar limitation retained: with reduced motion and a keyboard-open
  sidebar, dismissing it through a workspace pointerdown can move the click
  target before pointerup. Verification used Escape before those pointer clicks;
  the sidebar implementation was not changed by this work.

Pending human work is one policy/guidance/weight approval package, privacy review,
and the five preselected evidence/point spot-checks. Shared approvals and
judgements must remain unset until that review actually happens.

## Review corrections, 2026-11-09

Rule version `observable-rule-checks-v7` and request links
`contextual-request-links-v4` supersede the local v5 results above. Explicit
withdrawals now match the operation and stated object, recipient and values;
unrecognised qualifiers remain unresolved. Withdrawing an email to a manager
does not cancel an email promised to the customer.

All 45 pinned ABCD texts and source locations are unchanged. Thirty-eight
unsafe, contradictory or incomplete snapshots now have explicit safety blocks
and interpretation restrictions, including invented balances, ambiguous Oracle
responses and FAQ navigation without answer content. Approval metadata alone
cannot make these eligible. Seven snapshots remain bounded review candidates,
not fully validated workflows; conditional branches can still be unresolved.

Generic Answer support compares only `answer_statements` selected in each
workflow, with exact quotes and matching reference versions. There is no fallback
to raw instructions. The four selections contain three distinct proposed facts:
Gold members' unlimited returns, standard shipping at $8, and Gold members'
subscription extensions. They do not establish a particular customer's tier,
paid amount or successful transaction. Generic answer citations contain the exact
selected passage, and independent report validation enforces that selection.

All approvals remain pending. New local runs preserve earlier outputs; the
existing database reports are not automatically replaced. The local approval
review sheet distinguishes selected facts, bounded guidance and blocked source
material. Broader recognition coverage and saved-audit refresh remain separate.

## Approved demo results, 2026-11-09

The final local run uses `observable-rule-checks-v9`,
`contextual-request-links-v5` and the same frozen 117 masked training records.
The original approval and pre-correction outputs remain preserved. Rebinding
records the explicitly authorized recognition corrections; no guideline text,
criterion meaning, point allocation, profile or selected factual passage changed.
New derived guidance is kept outside the live catalogue and cannot earn points.

Recognition now compares complete sentence clauses without dropping decimal
values, conditions, quoted speech or corrections. Every retained claim gets its
own check; repeated equivalents cannot add points. Explicit courtesy and
field-request equivalents are recognized without inferring emotion or policy
appropriateness. A product question can inherit an explicit customer product
subject only through a finite question form, with both source turns cited;
negation, a competing product or an unsupported subject blocks that link.

The request linker supports finite cost, duration, due-date and product-property
questions. A named answer must match its subject and attribute. A short answer
binds only to the immediately preceding single supported question. Answering
establishes addressing, never factual correctness or transaction completion.

All 117 completed with no technical failures; repeating the run revalidated and
reused all 117 checkpoints. Numeric scores exist for Procedure in 11 records,
Completeness in one, Communication style in 74, and Answer support in one.
Seventy-six records have at least one score; none has all four and an overall.
The observed resolved checks all earn their point, so available percentages are
100% **of assessed checks**, not full performance grades. Coverage and unresolved
checks must accompany every displayed percentage; unknown coverage stays unknown.

The two smallest metric examples are a linked hood-detachability question/answer
(Completeness, 1/8 checks assessed) and the selected Gold-member return statement
(Answer support, 1/5). The former is not proof the hood is detachable; the latter
is not proof a particular return or refund succeeded.

The pinned guidelines contain no actual answer text for eight FAQ families.
Product details, prices, care instructions, membership benefits, hours and policy
answers need additional approved sources. Navigation instructions, answer IDs,
research labels and the agent's own answers cannot supply those facts. Other
blocked sections contain contradictory boundaries, undefined Oracle Booleans,
fictional balances or unsafe identity/payment instructions. The separate
38-candidate review pack preserves exact source passages, conditions and limits;
it proposes bounded derivations without approving them.

Verification: 294 ML tests passed, three skipped; eight backend adapter tests
passed; Ruff, compilation and whitespace checks passed. Tests establish mechanics,
not general semantic accuracy. Human spot-check labels remain unset. Current
local result exports are separate from previously saved backend audits; no audit
or Manager decision was overwritten, and no frontend code changed.

## ABCD licence

MIT License

Copyright (c) 2021 ASAPP Research

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.

## Recognition expansion, 2026-11-09

The latest local results use `observable-rule-checks-v13` and
`contextual-request-links-v6`. All original source text, selected factual passages,
interpretation limits, point allocations, weights and approval metadata remain
unchanged. The implementation fingerprint records the explicitly authorized
recognition changes. Earlier runs, including intermediate attempts, are retained.

The request linker now has finite material, colour, warranty, status, date, care
and policy question forms, plus passive transaction-response forms. Each answer
must match the requested subject and attribute. Pronouns require explicit product
context; its canonical antecedent is included in the individual check. Quoted or
competing products cannot silently retarget a request. Independent cancellation
and refund requests stay separate. A directly linked refusal establishes addressing;
its business justification and fulfilment remain separate unresolved questions.

`rule_facts.py` isolates pure factual normalization and comparison. It recognizes
selected shipping-price and membership-benefit equivalents, decimal values and
number-word durations while preserving units, subjects and conditions. A stronger
"always" claim cannot inherit weaker authority. A personalized benefit statement
may support only the explicit policy condition; actual customer status and action
completion retain a separate unresolved check. Sentence fragments that may qualify
a nearby claim are retained together rather than discarded during segmentation.

The same 117 conversations completed without technical failures; a second run
revalidated all 117 cached results. Supported category scores changed as follows:
Completeness 1 to 7, Answer support 1 to 3, Communication style 74 to 75 and
Procedure unchanged at 11. Eighty conversations now have at least one score;
none has all four and an overall. Available percentages remain 100% of assessed
points. Completeness coverage is about 11.1–33.3% where its inventory is known
(one mixed-purpose case has unknown coverage); Answer-support coverage is about
5.9–11.1%. These are candidate-check coverage figures, not semantic accuracy.

Verification: 329 ML tests passed, three skipped; eight backend adapter tests
passed; Ruff, compilation and whitespace checks passed. Independent AI review
inspected 12 resolved checks across ten conversations and observed no unsupported
atomic conclusions. The other 157 unchanged resolved checks were not re-reviewed
in that pass. Human case judgements remain unset. Updated local CSV/JSON and
calculation ledgers include all 117 records, before/after counts and the specific
additional reference needs. No saved backend audit or Manager decision was replaced.


## Backend coverage follow-up (2026-11-11)

Rule v14 and request-link v7 add bounded question forms, immediate question-bound
pronouns and explicit extension responses. A refusal addresses a request but does
not prove that refusing was justified. Personal tier assertions remain unresolved
when extracting a tier-conditioned policy claim. A documented `unlimted` spelling
variant maps to `unlimited` only inside the exact return-benefit frame; `limited`,
negation, other tiers and extra conditions do not match. Canonical quotations are
never normalized or rewritten.

The policy approval still binds v13/v6 and its original November 9 review date.
The table, rubric and reference approval records are unchanged. Current runs of
all 117 complete, but the new version cannot issue approved scores. Historical
backend assessments remain unchanged; new recognition observations are separate
review material, not a replacement assessment or human annotation.

Recognised request dispositions increased from 7 to 10. Historically eligible
policy comparisons increased from 3 to 4 conversations. These figures count
bounded observations, not complete conversation grades. Remaining product facts,
customer-specific account/order outcomes and unapproved guidance cannot be
verified from the agent's answer itself. Existing missing-reference requirements
still apply. Mechanical tests do not establish corpus-wide semantic accuracy.

`ml.knowledge_candidates.generate_candidates(organization_id, evidence_records)`
reuses canonical validation, request links and citations to propose exact quoted
Q&A. It accepts one prepared training conversation per record, isolates invalid
records, and excludes personal account/status answers, promises and unlinked
answers. All output stays untrusted and audit-ineligible. It preserves complete
source passages, including qualifications; a source passage can address only part
of a multi-part customer turn. It does not infer additional policy conditions.
The Manager must check relevance, applicability and an independent authoritative
reference before approval. Automatic duplicate grouping and conflict detection
are not claimed by this bounded generator.

Backend composition opts in with `MEMORIA_KNOWLEDGE_ENGINE=rules`; the existing
Manager-only import endpoint reads only canonical evidence from that organization
and frozen cohort, then uses the existing idempotent pending-draft importer.
Generation never changes an approved entry, verification date or human decision.


## Completeness and wording expansion (2026-11-11)

Rule v15 and request-link v8 add bounded field-list/courtesy patterns, contextual
policy questions and explicit information-unavailable responses. Conditional
answers must retain a matching cancellation or late-payment frame; other
conditions, negation, quoted speech and ambiguous request attachment remain
unresolved. Addressing a question does not establish factual correctness.
Courtesies count at most once per conversation; field clarity proves neither
identity nor collection authority. Canonical quotations remain unchanged.

Across the same 117 training conversations, supported Completeness links increased
from 10 checks in 10 conversations to 13 in 13. Supported wording checks increased
from 108 in 78 conversations to 154 in 91. Candidate-check denominators are
939 → 940 and 1,704 → 1,675 respectively; courtesy deduplication explains why a
denominator can shrink. These are recognition counts, not complete grades.
All 117 current-date evaluations completed and checkpoint resumption reproduced
their reports. Existing approvals still bind the earlier version/date; no new
approvals, published scores, human annotations or stored assessments were changed.
The local comparison and limited AI review are under
`ml/output/completeness-style-expansion/`; unresolved checks remain explicit.
