# Reference snapshots (for #19)

A reference snapshot is a set of passages that drafts can be checked against.
It is the only kind of evidence that can **support** or **contradict** a
claim. Other drafts, repeated agent answers and existing knowledge entries
can't.

## `abcd-guidelines.snapshot.json`

- Built by `scripts/build_reference_snapshot.py` from ABCD's
  `data/guidelines.json` at commit `6b8700ce67c6b37b062dd7a60abc76d7ef832a97`.
  The source file's SHA-256 is recorded in the snapshot.
- Each passage is one guideline action or sub-point, **copied word for word**.
  It records the ABCD subflow(s) it applies to and the guideline it came from.
  There are 916 passages, covering all 55 guideline subflows. FAQ guidelines
  (pricing, policy, membership, timing, product FAQs) describe *how to look an
  answer up*, not the answer itself. Drafts on those topics come out
  `unverifiable`, and that is the correct result.
- Licence: MIT, © 2021 ASAPP Research (`../abcd/LICENSE-ABCD`). Credit ABCD
  wherever these passages are shown or adapted.
- **ABCD guidance is not real company policy.**

## Review status: every passage is `unreviewed`

Nothing in this file can verify a draft yet. `check_drafts` ignores any
passage whose `approval.status` is not `"approved"`, or whose
`eligibility.status` is not `"eligible"`. It also ignores passages past their
`eligibility.valid_until` date, and lists every ignored passage with the
reason.

Before this snapshot is used, a person the team agrees on reads the passages
and records the review. The recording happens either here (set
`approval.status`, `approved_by` and `approved_at` on each passage they
approve, in a commit of their own) or, better, in the backend once it stores
references. The ML code never sets these fields.

Things to decide: who may approve verification sources, and how adapted ABCD
guidelines are approved and credited (issue #19, "To agree").

## Passage fields

| Field | Meaning |
|---|---|
| `reference_id` | `abcd:<flow>/<subflow>#a<action>[.<sub-point>]`, or `#i<n>` for an instruction line |
| `text` | The passage, verbatim |
| `parent` | The action a sub-point belongs to. Checks also read an action together with its sub-points |
| `scope` | `{flow, subflow}` or `{flow, subflow_prefix}` (FAQ guidelines cover many subflows) |
| `guideline` | ABCD's own flow, subflow, button and action type |
| `version` | Snapshot version, e.g. `abcd-guidelines@6b8700ce67c6` |
| `approval` | `{status: unreviewed / approved / rejected, approved_by, approved_at}` |
| `eligibility` | `{status: eligible / stale / disputed / out_of_scope, valid_until, reason}` |

`load_reference_snapshot(path, company_id)` returns the passages as references
for one company. The snapshot itself is company-neutral, so one reviewed file
can serve a demo company. Knowledge bases still never mix: a reference only
applies to drafts of the company it was loaded for.
