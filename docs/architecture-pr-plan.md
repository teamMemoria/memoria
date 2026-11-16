# Proposed PR split for #130

Nothing is staged, committed, pushed or merged. These are local implementation
slices to turn into PRs only after authorization. Each PR must remain runnable
and include its own tests; do not submit a file-move-only intermediate state.

## Base and existing dependencies

Inspected GitHub main: `634e719ede6af6c0e01f3a73506e7cd31fd0e686`.
The selected worktree base is #123's engine-independent integration:
`5664bc15d94dc65c3e3d9c36281b4005d634c83a`.
This contains the APIs and persisted assessment contracts needed by the screens.

The published design changes from #124–128 were applied as uncommitted patches
for verification. They are existing dependency work, not new #130 design work:

| PR | Source commit | Dependency |
|---|---|---|
| #124 | `bbc2f93bd4b75d0dacd1891908eeb2395f355048` | Procedure |
| #125 | `33a3253129ecacac92fefba81d95a096de8163fe` | Answer support |
| #126 | `1766aaefc50040367f8b4a77f7aae94c5e0be2ad` | Completeness |
| #127 | `55c3477fdce5cb8d6f3ecd5cc9bd13e61b0763bf` | Communication style |
| #128 | `36956169130c43a766c3b9e1f1e669b5092a69c6` | Knowledge review |

At inspection, #123–128 were open draft PRs. No merge was performed. The existing
main checkout remains on `05235ed6662024a1889a78d3b5f357741cdbd80a`; it was not
switched, updated or reset. No other worktree was edited.

Before publishing, confirm the dependency PR states again. If they have merged,
base the focused PRs on that updated integration; otherwise use an explicit
stack. Do not include those screens a second time in #130 diffs.

## Local tested slices

The split is materialized under
`/Users/nicol/Desktop/PROJECTS/memoria-worktrees/clean-architecture-slices`.
Each numbered directory is a separate worktree on `codex/130-<directory-name>`.
All branch tips remain at the selected base: with commits prohibited, these
are **cumulative uncommitted snapshots**, not a committed Git stack.

`patches/00-existing-design-dependencies.patch` contains only the pre-existing
#124–128 dependencies. Each following patch contains only the delta from the
preceding slice. Do not publish the cumulative worktree diff as a single PR;
after authorization, commit the reviewed deltas in dependency order.

| Slice | Focus | Proof required locally |
|---|---|---|
| 01-baseline | CI, disposable test configuration; one prerequisite formatting correction | Full baseline backend/frontend/ML checks |
| 02-runtime | Per-app engine/session lifetime | Backend suite and resource-isolation tests |
| 03-shared-contracts | Neutral vocabulary, identity/errors, record shapes, model relocation | Backend suite and unchanged HTTP schema |
| 04-reviews | Domain decision validation, neutral output, ReviewInteractor | Pure invalid-input regressions; persistence/concurrency tests |
| 05-knowledge-decisions | Reference/version/permission decisions | Backend approval/rejection, conflict and visibility tests |
| 06-assessments | Run input/output boundary, report validation and storage | Backend retry/evidence tests; fake-repository HTTP test |
| 07-data-access | Shared read/feedback adapters and compatibility paths | Backend suite and unchanged projections |
| 08-ml-boundaries | Pure rules/scoring and execution adapter | Backend + ML regressions; unchanged rule versions |
| 09-knowledge-import | Pure import validation and injected pipeline | Backend import/idempotency/concurrency tests |
| 10-procedure | Procedure controller/presenter extraction | Frontend tests, lint, TypeScript and build |
| 11-answer-support | Answer support controller/presenter | Same frontend checks |
| 12-completeness | Completeness controller/presenter | Same frontend checks |
| 13-communication-style | Communication controller/presenter | Same frontend checks |
| 14-interactions | Entry, conversation and knowledge decision controllers | Same frontend checks |
| 15-acceptance | Remaining HTTP module moves, stronger guards, diagrams and full acceptance | Entire suite, dependency violations, persistent flows, contracts and design comparison |

The ordering differs slightly from the initial plan because shared model and
record contracts are needed before the feature-specific slices. Temporary
compatibility paths in early snapshots are replaced by their implementations
when the owning slice lands. The final acceptance snapshot must equal the
combined worktree's source; no feature is silently left out.

Every snapshot receives lint, formatting, compilation, OpenAPI comparison,
patch-applicability and empty-index checks. Backend changes receive the full
backend suite. Frontend changes receive the full frontend suite and build.
The ML slice and final acceptance receive the ML suite. Logs and the machine
readable `verification.json` identify the exact checks actually run.

Use `Refs #130` in intermediate PRs. Reserve `Closes #130` for final acceptance
after the dependency stack is reviewed. No PR, commit, push, merge or issue
state change is performed by this local split.
