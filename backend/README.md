
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
