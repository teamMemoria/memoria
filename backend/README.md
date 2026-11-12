# Backend

## Validate and profile conversations

From the `backend` directory, run the validator against the supplied curated
conversation directory:

```bash
uv run profile-conversations /path/to/uoft-ftli-2026-genesys-docs/curated/conversations
```

The command validates every JSON file before printing a deterministic profile.
Validation errors are written to stderr with the filename and field, and the
command exits with status 1 without printing a partial profile.

The current 200-file corpus is pinned at commit
`c39d2e0610417256bf05811b774d400deea7456f` of
`marcomarchesanogenesys/uoft-ftli-2026-genesys-docs`. Keep those real
conversation files in the source repository; do not copy them into Memoria.

## Tests

Tests run against a separate `callassist_test` database that is dropped, recreated
and migrated at the start of each run, so they never touch your local data. With
the database running:

    uv run pytest

## Importing the curated conversations

The conversation data lives in the
[uoft-ftli-2026-genesys-docs](https://github.com/marcomarchesanogenesys/uoft-ftli-2026-genesys-docs)
repo, not here. Clone it next to this repo, then from `backend/` with the database
migrated:

    uv run import-conversations ../../uoft-ftli-2026-genesys-docs/curated/conversations

It is safe to run again; existing conversations and turns are updated in place.
Don't copy the dataset files into this repo.

Then give every conversation a topic. The label-to-topic mapping is in
`src/backend/data/topic_mapping.toml`; edit it and re-run to change topics:

    uv run assign-topics

Finally, spread the conversations over an 8-week timeline. These times are
generated (fixed seed, so always the same) and stored in
`synthetic_started_at`, separate from any real source date:

    uv run assign-synthetic-dates

Then create the demo profiles offered on the entry screen: 31 Agents from the
ABCD training conversations and one Manager, listed in
`src/backend/data/demo_profiles.toml`. Each Agent is linked to the imported
conversations listed for it; nothing is assessed, reviewed or approved:

    uv run seed-demo-profiles

To use them from the frontend, start the backend with
`MEMORIA_APP_ENV=development MEMORIA_DATA_SOURCE=database` and the frontend with
`VITE_DEMO_BACKEND=true npm run dev`.

Each data command accepts `--organization <slug>` and defaults to the
migration-created `default` organization.

## Conversation metrics

Importing a conversation creates or updates its one `conversation_metrics` row.
All values are derived from the source record; re-importing recalculates them.

- All channels: `turn_count`, agent/customer word counts, and agent/customer
  text shares (fractions from 0 to 1).
- HarperValleyBank voice: `call_elapsed_ms`, agent/customer speaking time in
  milliseconds, `average_turn_duration_ms`, `asr_word_error_rate` (word errors
  divided by reference words), and `asr_compared_turn_count`.
- ABCD chat: `system_action_count` (system-action turns) and
  `documented_action_count` (entries in `source_fields.actions_taken`).

Channel-specific fields are `NULL` when unsupported or unavailable. Voice
timing requires complete timing data for all agent and customer turns.

## Evaluation set

`evaluation/` holds the scoring rubric and the score sheet for the
evaluation set. The scores in the sheet so far are AI-generated, not human
(see `evaluation/README.md`). The conversations in the sheet were picked by
`select-eval-set`. To check the selection again without touching the sheet,
write it somewhere else:

    uv run select-eval-set --out evaluation/new_selection.csv

`select-eval-set` won't replace an existing file, so it can't wipe recorded
scores. Pass `--overwrite` only when you mean to start the sheet again.

## Provenance manifests

Generated artifacts store their provenance in a JSON sidecar beside the
artifact. The sidecar name is `<artifact filename>.provenance.json`; for
example, `evaluation.csv` uses `evaluation.csv.provenance.json`. Call
`write_manifest(artifact_path, manifest)` from `backend.data.provenance` to
apply this convention and write deterministic JSON.
