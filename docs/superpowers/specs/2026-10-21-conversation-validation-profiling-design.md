# Conversation Validation and Profiling Design

## Purpose

Ticket #35 adds a validation boundary for the 200 curated HarperValleyBank (HVB) and ABCD conversation files. It must reject malformed or surprising source records before later import work can write them to the database, and it must produce a reproducible profile of a valid corpus.

The conversations remain in the separately supplied documentation repository. Memoria will not copy real conversations into this repository. The command accepts the path to that repository's `curated/conversations` directory.

## Scope

The implementation will:

- validate all JSON files in a supplied directory with one command;
- enforce the six required top-level fields: `id`, `source`, `modifications`, `channel`, `turns`, and `source_fields`;
- validate the shared nested structure and the fields allowed for HVB and ABCD;
- reject fields that belong to the other dataset or are otherwise unexpected;
- validate `agent`, `customer`, and `system_action` speaker values;
- require positive, strictly increasing source turn numbers without requiring them to be contiguous;
- collect and report all validation failures with their filename and field path;
- produce deterministic corpus distributions after every file passes validation; and
- include automated tests made only from synthetic fixture records.

The implementation will not normalize topics, import records, modify source files, or combine knowledge and procedures across datasets. Topic normalization remains the responsibility of ticket #28.

## Architecture

The backend will contain a focused data package with three responsibilities:

1. Pydantic models describe the shared conversation contract and the HVB/ABCD variants.
2. A validation and profiling service discovers files, parses every record, applies cross-field checks, and builds a profile.
3. A small command-line entry point presents sorted errors or deterministic JSON output and returns an appropriate exit status.

The project will expose the command through `backend/pyproject.toml`, so it can be run from `backend/` with `uv run`. The exact corpus directory is a command argument rather than an assumed checkout location.

Pydantic is preferred over a new JSON Schema dependency or entirely manual validation because it is already part of the FastAPI stack, provides structured field locations, and leaves only the cross-field turn-order and profiling rules to custom code.

## Validation Contract

Every record must contain the shared six top-level keys and valid values for their nested fields. Unknown datasets, unknown shared fields, and unknown dataset-specific fields fail validation so upstream schema changes are noticed rather than silently ignored.

The supported datasets are:

- HVB: source dataset `HarperValleyBank`, channel `voice`, optional HVB identity, customer-record, source, and per-turn fields.
- ABCD: source dataset `ABCD`, channel `chat`, optional ABCD customer identity and record fields, ABCD source fields, and no HVB timing or transcript fields.

Optional means that the source may omit a field. When an optional field is present, its type and dataset applicability are validated. A field supported only by one dataset is rejected on the other dataset.

Every turn requires `n`, `speaker`, and `text`. `n` must be a positive integer and must be greater than the preceding source turn number. Gaps such as `1, 2, 4` are valid and remain unchanged. Repeated or decreasing values are invalid. Allowed speakers are `agent`, `customer`, and `system_action`; dataset rules additionally prevent unsupported dataset-specific values or turn fields.

## Command Behavior

The command will:

1. accept a conversation-directory path;
2. discover `*.json` files in lexicographic filename order;
3. parse and validate every discovered file, collecting failures rather than stopping after the first;
4. print sorted, filename-qualified errors and return a non-zero exit status if any record is invalid; or
5. print the deterministic JSON profile and return zero if the whole corpus is valid.

Malformed JSON is reported against the file itself. Schema failures include a readable field location such as `turns[4].speaker`. A missing or unreadable directory, and a directory containing no JSON files, are command failures.

The command does not emit a partial profile when validation fails because a summary of only the accepted subset could be mistaken for the corpus profile.

## Profile Contract

The successful JSON profile will include the total file and conversation counts plus these distributions:

- dataset;
- channel;
- source topic, nested by dataset;
- agent identity, nested by dataset;
- speaker turns, nested by dataset; and
- exact conversation turn counts, nested by dataset.

Source topics remain dataset-scoped:

- HVB uses each `source_fields.task_assigned` value.
- ABCD uses the `source_fields.flow/source_fields.subflow` pair.

Values with similar names are never merged across datasets. ABCD records have no agent identity, so their agent distribution uses the explicit label `unavailable` rather than inventing an identifier.

All object keys and distribution entries are emitted in a stable order. Re-running the command against unchanged files produces byte-for-byte identical standard output.

## Testing

Tests will use small, made-up HVB and ABCD fixtures and will cover:

- valid records from both datasets;
- malformed JSON;
- missing required top-level keys;
- unknown datasets and fields;
- dataset-specific optional fields on the correct and incorrect datasets;
- valid and invalid speaker values;
- accepted non-contiguous increasing turn numbers;
- rejected duplicate, decreasing, zero, and negative turn numbers;
- errors containing the filename and exact field path;
- sorted aggregation of multiple file errors;
- rejection of missing, unreadable, and empty input directories;
- dataset-scoped topic and agent distributions;
- deterministic discovery and profile serialization; and
- command success and failure exit statuses.

After the automated suite passes, the command will also be run against the pinned 200-file corpus snapshot at commit `c39d2e0610417256bf05811b774d400deea7456f` to verify the real acceptance criterion.

## Documentation

The backend README will document the command, its directory argument, output behavior, and the pinned external corpus source. It will make clear that real conversation files must not be committed to the Memoria repository.
