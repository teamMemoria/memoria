# Assessment screens without a scoring-engine dependency

This foundation is based directly on main (`634e719`, including database login
#121), with the integration and screen changes from #123–#128. It contains none of
#122's rule engine, rule tables, cohort or grading algorithms, and none of #129's
candidate extraction. Original branches and their uncommitted work stay intact.

## Boundaries

```
Configured scorer + approved-policy validator
                    ↓
Backend source/point validation → stored assessment → existing HTTP API
                                                       ↓
                      Procedure / Completeness / Communication / Answer support
```

The frontend renders `CallReview`, `AuditCriterion.scoring`, `overallScoring`,
request links, citations and missing facts. It performs no assessment, assigns no
points, and has no knowledge of which engine produced a report. `ruleId` and
`assessmentVersion.rules` remain opaque version labels for API compatibility.
Weighted point allocations are supported; the UI already labels them as points.

The original login, Agent/Manager ownership, review requests and separate Manager
decisions are preserved. Knowledge approval/rejection still requires permissions,
the current content version, independent verification and conflict/duplicate
checks. Pending knowledge is not usable by Agents. No human decisions are created.

## Connecting a future scorer

`AnalysisAdapter.analyse(request)` is unchanged. The backend supplies the owned
conversation, exact source version, approved applicable references and active
versioned evaluation criteria. Optional canonical evidence is validated against
the stored turns; dataset answer labels are never part of this request.

A scored adapter also supplies an approval-aware `report_parser(request, raw)`
returning the existing `ParsedReport`, with its `assessment_report` field set.
The parser must check the approved check plan, conditions, eligibility and
interpretation limits. It must reject unsupported judgments; exact quotations
alone do not prove them correct. This is trusted server composition, not an API
option that a user or model can enable.

```python
analysis = AnalysisService(
    sessions,
    adapter=chosen_adapter,
    report_parser=chosen_policy_validator,
)
app = create_app(analysis=analysis)
```

The legacy default parser remains supported. It rejects scored payloads until a
policy validator is explicitly configured. The default adapter is unconfigured;
starting a run fails visibly instead of supplying demo numbers. No model API,
rule catalogue, model cache or API credential is required to start the app.
`MEMORIA_ANALYSIS_ENGINE=rules` no longer auto-loads an engine in this foundation.

## Scored storage contract

The parser returns a JSON `assessment-v1` report containing:

- Conversation ID, transcript version, evaluation-form version and assessment date.
- Four category rows: status, legacy category result, and the existing scoring
  ledger (checks, allocated/earned points, coverage, limits and processing errors).
- Overall score/coverage, or null with the reason; source/version labels and
  optional contextual request links. Human review and approval remain null.

The final storage gate rechecks source identity and exact citations against the
request, including approved-reference versions. Positive and negative checks need
evidence. Procedure and Answer support also require eligible reference evidence;
the scorer's policy parser handles semantic relevance and applicability. Linked
Completeness results need customer and response/action evidence. Wording checks
need Agent passages. Points, denominators, coverage and totals must agree. Unknowns
and processing errors cannot become deductions or automatic passes. Final numeric
scores require a complete resolved inventory; no midpoint estimates are silently
imported as approved grades. Overall weights must match the active evaluation
form, normalized across all four configured metrics without redistributing missing
scores. Partial results remain stored on the failed run, with no completed audit;
independently valid categories remain visible. An explicit retry retains history.

Only the parser/adapter boundary changes when Layer 1 or Layer 2 is connected.
No scoring implementation or knowledge-generation pipeline is included here.
Generated narration remains an optional private cache, independent of scoring.

## Local execution

Use the existing PostgreSQL setup and an appropriate development database. Apply
migrations only to the intended database, never implicitly to another worktree's
running data. From backend:

```sh
uv sync --frozen
MEMORIA_APP_ENV=development \
  uv run uvicorn backend.main:app --host 127.0.0.1 --port 8061
```

From frontend:

```sh
npm ci
MEMORIA_API_TARGET=http://127.0.0.1:8061 \
  npm run dev -- --host 127.0.0.1 --port 5361
```

Existing stored assessments remain readable. Unavailable assessments stay clearly
unavailable. Screens do not invent dates, durations, topics, scores or evidence.

## Verification and PR split

Tests use fake scorers and a disposable database. They approve no real catalogue.
They cover two scorer identities producing the same UI contract, arithmetic and
citation tampering, uncited positives, missing approval context, ownership, partial
results/retry history, unconfigured operation, and startup without scorer imports.
Existing Agent/Manager and knowledge-decision tests remain in the full suite.

Prepare the reusable foundation for #123 against main; retain the four assessment
screens and knowledge-review UI as #124–#128 changes based on that foundation.
#122 stays an isolated optional scoring implementation. Its bridge will need the
foundation's parser contract before it can be enabled. #129 stays separate until
aligned with the Layer 2 owner. This local preparation changes no published PR
bases, commits, statuses or approvals.
