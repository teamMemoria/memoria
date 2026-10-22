# Conversation Validation and Profiling Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add one command that rejects malformed HVB and ABCD conversation files before import and emits a deterministic, dataset-scoped corpus profile when all files are valid.

**Architecture:** Strict Pydantic models own record-level validation, a corpus service owns sorted discovery and cross-record errors, a profiler owns dataset-scoped aggregation, and a thin CLI owns terminal I/O and exit codes. The command reads the separately supplied corpus by path and never copies real conversations into this repository.

**Tech Stack:** Python 3.13, Pydantic 2 (already present through the FastAPI stack), pytest 9, standard-library `argparse`, `json`, and `pathlib`.

**Spec:** `docs/superpowers/specs/2026-10-21-conversation-validation-profiling-design.md`

## Global Constraints

- Support only source datasets `HarperValleyBank` and `ABCD` for this ticket.
- Require the six top-level keys `id`, `source`, `modifications`, `channel`, `turns`, and `source_fields`.
- Forbid unknown fields and reject explicit `null` for optional source fields; absence and null are not equivalent.
- Allow only positive, strictly increasing turn numbers; preserve and accept gaps.
- Keep topics, agents, speakers, and turn-count distributions nested by dataset.
- Use `unavailable` for ABCD's absent agent identity; never invent an agent.
- Collect all file failures, print no partial profile, and return non-zero if any failure exists.
- Do not add real conversation fixtures to this repository.
- Successful output must be byte-for-byte deterministic for unchanged input.

## Review Focus

- A syntactically valid JSON scalar or array must fail at `$` as “expected an object,” not crash model dispatch (Task 2).
- An empty `turns` array must fail validation because it cannot represent a conversation (Task 1).
- An explicitly null optional field must fail while an absent optional field remains valid (Task 1).
- An empty HVB `task_assigned` list must fail rather than silently disappear from the topic profile (Task 1).
- Duplicate conversation IDs across two files must identify the later filename and its `id` field (Task 2).

---

### Task 1: Strict dataset conversation models

**Files:**
- Create: `backend/src/backend/data/__init__.py`
- Create: `backend/src/backend/data/conversations/__init__.py`
- Create: `backend/src/backend/data/conversations/models.py`
- Create: `backend/tests/data/conversations/conftest.py`
- Create: `backend/tests/data/conversations/test_models.py`

**Interfaces:**
- Consumes: JSON-compatible Python values returned by `json.loads`.
- Produces: `Conversation = HarperValleyBankConversation | ABCDConversation` and `parse_conversation(payload: object) -> Conversation`.

- [ ] **Step 1: Write failing shared and HVB model tests**

Add synthetic fixtures `hvb_payload` and `abcd_payload`. Test that a valid HVB record parses without changing turn numbers `[1, 2, 4]`; parameterize deletion of each required top-level key; reject unknown top-level and nested fields; reject an empty `turns`; reject zero, negative, duplicate, and decreasing turn numbers; reject `bot` and HVB `system_action` speakers; accept absent HVB survey fields but reject an explicitly null survey field; and reject an empty `task_assigned` list.

- [ ] **Step 2: Run the HVB tests and verify RED**

Run: `cd backend && uv run pytest tests/data/conversations/test_models.py -v`

Expected: collection fails because `backend.data.conversations.models` does not exist.

- [ ] **Step 3: Implement shared and HVB models**

In `models.py`, use `ConfigDict(extra="forbid", strict=True)` throughout. Define the shared source fields (`dataset`, `original_id`, `licence`, `url`, `citation`), shared top-level fields, JSON-valued `modifications` and `customer_record`, and HVB-specific source/turn fields. Use literals to bind `HarperValleyBank` to `voice`; require non-empty `task_assigned`; keep source turns in input order; and use a model validator for strictly increasing `n` values.

- [ ] **Step 4: Run the HVB tests and verify GREEN**

Run: `cd backend && uv run pytest tests/data/conversations/test_models.py -v`

Expected: all HVB and shared tests pass.

- [ ] **Step 5: Write failing ABCD and dispatch tests**

Test that valid ABCD records allow `agent`, `customer`, and `system_action`; bind `ABCD` to `chat`; accept an absent `customer_id`; reject explicit null; reject HVB-only timing/ASR fields and `agent_id`; require string `flow`, string `subflow`, and a string list `actions_taken`; and make `parse_conversation` reject an unknown dataset with the location `source.dataset`.

- [ ] **Step 6: Run the new tests and verify RED**

Run: `cd backend && uv run pytest tests/data/conversations/test_models.py -v`

Expected: ABCD parsing cases fail because the ABCD model and dispatcher are missing.

- [ ] **Step 7: Implement the ABCD model and dispatcher**

Add `ABCDConversation` and `parse_conversation(payload: object) -> Conversation`. Dispatch only after confirming that the payload is a mapping and reading `source.dataset`; let the selected model produce precise Pydantic locations for all remaining failures.

- [ ] **Step 8: Run model tests and the backend suite**

Run: `cd backend && uv run pytest tests/data/conversations/test_models.py -v && uv run pytest`

Expected: all tests pass without warnings.

- [ ] **Step 9: Commit the model boundary**

```bash
git add backend/src/backend/data backend/tests/data/conversations
git commit -m "feat: validate curated conversation records"
```

### Task 2: Whole-corpus validation and actionable errors

**Files:**
- Create: `backend/src/backend/data/conversations/validation.py`
- Create: `backend/tests/data/conversations/test_validation.py`
- Modify: `backend/tests/data/conversations/conftest.py`

**Interfaces:**
- Consumes: `parse_conversation(payload: object) -> Conversation` from Task 1.
- Produces: immutable `ValidationIssue(file: Path, field: str, message: str)`, immutable `CorpusValidation(conversations: tuple[Conversation, ...], issues: tuple[ValidationIssue, ...])`, `validate_corpus(directory: Path) -> CorpusValidation`, and `format_issue(issue: ValidationIssue) -> str`.

- [ ] **Step 1: Write failing directory and aggregation tests**

Add a writer fixture for synthetic JSON files. Test lexicographic discovery of only top-level `*.json`; successful parsing into filename order; missing path, regular-file path, and empty-directory failures; malformed JSON at `$`; valid non-object JSON at `$`; conversion of nested Pydantic locations to `turns[1].speaker`; aggregation sorted by filename then field; and no retained conversations when any issue exists.

- [ ] **Step 2: Run the service tests and verify RED**

Run: `cd backend && uv run pytest tests/data/conversations/test_validation.py -v`

Expected: collection fails because `validation.py` does not exist.

- [ ] **Step 3: Implement sorted discovery and issue conversion**

Implement `validate_corpus` with `Path.glob("*.json")`, explicit directory checks, UTF-8 reads, `json.loads`, Task 1 dispatch, and exhaustive issue collection. Convert tuple Pydantic locations to dotted/indexed fields such as `turns[1].speaker`; sort issues by `(file name, field, message)`; and return an empty conversation tuple whenever issues are present.

- [ ] **Step 4: Run the service tests and verify GREEN**

Run: `cd backend && uv run pytest tests/data/conversations/test_validation.py -v`

Expected: all tests pass.

- [ ] **Step 5: Write a failing duplicate-ID test**

Write two valid files with the same `id`. Assert that validation fails on the lexicographically later file, uses field `id`, mentions the earlier filename in the message, and returns no conversations.

- [ ] **Step 6: Run the duplicate-ID test and verify RED**

Run: `cd backend && uv run pytest tests/data/conversations/test_validation.py -k duplicate -v`

Expected: FAIL because duplicate IDs are not yet checked.

- [ ] **Step 7: Add deterministic duplicate-ID detection**

Track the first filename for each parsed conversation ID during sorted traversal and append a `ValidationIssue` for every later occurrence.

- [ ] **Step 8: Run validation tests and the backend suite**

Run: `cd backend && uv run pytest tests/data/conversations/test_validation.py -v && uv run pytest`

Expected: all tests pass without warnings.

- [ ] **Step 9: Commit corpus validation**

```bash
git add backend/src/backend/data/conversations/validation.py backend/tests/data/conversations
git commit -m "feat: validate conversation directories"
```

### Task 3: Deterministic, dataset-scoped profiling

**Files:**
- Create: `backend/src/backend/data/conversations/profiling.py`
- Create: `backend/tests/data/conversations/test_profiling.py`

**Interfaces:**
- Consumes: `Sequence[Conversation]` from Task 1 after Task 2 reports no issues.
- Produces: `build_profile(conversations: Sequence[Conversation]) -> dict[str, object]` and `serialize_profile(profile: Mapping[str, object]) -> str`.

- [ ] **Step 1: Write failing profile aggregation tests**

Using two synthetic HVB conversations and two ABCD conversations, assert this stable shape: `files`, `conversations`, and `distributions` containing `datasets`, `channels`, `topics`, `agents`, `speakers`, and `turn_counts`. Assert HVB topics use every `task_assigned` value; ABCD topics use `flow/subflow`; the same-looking topic in different datasets remains in separate nested objects; ABCD agents count under `unavailable`; speakers count turns rather than conversations; and turn-count keys are decimal strings.

- [ ] **Step 2: Run aggregation tests and verify RED**

Run: `cd backend && uv run pytest tests/data/conversations/test_profiling.py -v`

Expected: collection fails because `profiling.py` does not exist.

- [ ] **Step 3: Implement `build_profile`**

Aggregate with counters, then convert every level to dictionaries ordered lexicographically by dataset and label. Set both `files` and `conversations` to the input length because each validated file contains exactly one conversation.

- [ ] **Step 4: Run aggregation tests and verify GREEN**

Run: `cd backend && uv run pytest tests/data/conversations/test_profiling.py -v`

Expected: aggregation tests pass.

- [ ] **Step 5: Write failing deterministic serialization tests**

Build equivalent profiles from differently ordered input sequences. Assert `serialize_profile` returns identical text, uses two-space indentation, sorts object keys, ends in exactly one newline, and can be parsed back by `json.loads`.

- [ ] **Step 6: Run serialization tests and verify RED**

Run: `cd backend && uv run pytest tests/data/conversations/test_profiling.py -k serial -v`

Expected: FAIL because `serialize_profile` is missing.

- [ ] **Step 7: Implement deterministic serialization**

Implement `serialize_profile` with `json.dumps(profile, indent=2, sort_keys=True, ensure_ascii=False)` plus one newline.

- [ ] **Step 8: Run profiling tests and the backend suite**

Run: `cd backend && uv run pytest tests/data/conversations/test_profiling.py -v && uv run pytest`

Expected: all tests pass without warnings.

- [ ] **Step 9: Commit profiling**

```bash
git add backend/src/backend/data/conversations/profiling.py backend/tests/data/conversations/test_profiling.py
git commit -m "feat: profile curated conversations"
```

### Task 4: One-command interface, documentation, and corpus verification

**Files:**
- Create: `backend/src/backend/data/conversations/cli.py`
- Create: `backend/tests/data/conversations/test_cli.py`
- Modify: `backend/pyproject.toml`
- Modify: `backend/README.md`

**Interfaces:**
- Consumes: `validate_corpus`, `format_issue`, `build_profile`, and `serialize_profile` from Tasks 2 and 3.
- Produces: `main(argv: Sequence[str] | None = None) -> int` and project script `profile-conversations`.

- [ ] **Step 1: Write failing CLI tests**

Call `main` directly with synthetic directories. Assert success returns `0`, writes only the serialized profile to stdout, and leaves stderr empty. Assert invalid input returns `1`, leaves stdout empty, and writes every sorted issue as `<filename>: <field>: <message>` to stderr. Assert argparse rejects a missing directory argument.

- [ ] **Step 2: Run CLI tests and verify RED**

Run: `cd backend && uv run pytest tests/data/conversations/test_cli.py -v`

Expected: collection fails because `cli.py` does not exist.

- [ ] **Step 3: Implement the CLI and register the project script**

Implement `main(argv: Sequence[str] | None = None) -> int` with `argparse`, write success/error streams exactly as tested, and add `profile-conversations = "backend.data.conversations.cli:main"` under `[project.scripts]` in `pyproject.toml`.

- [ ] **Step 4: Run CLI tests and verify GREEN**

Run: `cd backend && uv run pytest tests/data/conversations/test_cli.py -v`

Expected: all CLI tests pass.

- [ ] **Step 5: Document the command**

Add a “Validate and profile conversations” section to `backend/README.md` with:

```bash
uv run profile-conversations /path/to/uoft-ftli-2026-genesys-docs/curated/conversations
```

Document stdout JSON, stderr errors, non-zero failure, the pinned corpus commit `c39d2e0610417256bf05811b774d400deea7456f`, and the rule against copying real conversations into Memoria.

- [ ] **Step 6: Run formatting, lint, and the full backend suite**

Run: `cd backend && uv run ruff format --check . && uv run ruff check . && uv run pytest`

Expected: all commands exit `0` without warnings or test failures.

- [ ] **Step 7: Verify all 200 pinned records with one command**

Run:

```bash
cd backend
uv run profile-conversations /private/tmp/memoria-docs-corpus/curated/conversations > /private/tmp/ticket35-profile.json
jq '.files, .conversations, .distributions.datasets' /private/tmp/ticket35-profile.json
```

Expected: exit `0`; `files` and `conversations` are both `200`; datasets are exactly `ABCD: 100` and `HarperValleyBank: 100`.

- [ ] **Step 8: Verify byte-for-byte determinism**

Run the command again into `/private/tmp/ticket35-profile-second.json`, then run `cmp /private/tmp/ticket35-profile.json /private/tmp/ticket35-profile-second.json`.

Expected: `cmp` exits `0` with no output.

- [ ] **Step 9: Commit the command and documentation**

```bash
git add backend/src/backend/data/conversations/cli.py backend/tests/data/conversations/test_cli.py backend/pyproject.toml backend/README.md
git commit -m "feat: add conversation profiling command"
```

- [ ] **Step 10: Review branch state and ticket coverage**

Run: `git status --short && git log --oneline --decorate -5`

Expected: no uncommitted implementation files; the recent commits correspond to strict models, corpus validation, profiling, and the CLI. Confirm `PROJECT.md`, `ARCHITECTURE.md`, `DECISIONS.md`, `PROGRESS.md`, and `AGENTS.md` are not staged or committed.
