# Backend

## Validate and profile conversations

From the `backend` directory, run the validator against the supplied curated
conversation directory:

```bash
uv run python src/backend/services/conversation_corpus.py /path/to/uoft-ftli-2026-genesys-docs/curated/conversations
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

## Provenance manifests

Generated artifacts store their provenance in a JSON sidecar beside the
artifact. The sidecar name is `<artifact filename>.provenance.json`; for
example, `evaluation.csv` uses `evaluation.csv.provenance.json`. Call
`write_manifest(artifact_path, manifest)` from `backend.data.provenance` to
apply this convention and write deterministic JSON.
