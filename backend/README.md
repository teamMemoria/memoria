
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

## Hand-scored evaluation set

`evaluation/` holds the scoring rubric and the score sheet for the
hand-scored evaluation set. The conversations in the sheet were picked with:

    uv run select-eval-set
