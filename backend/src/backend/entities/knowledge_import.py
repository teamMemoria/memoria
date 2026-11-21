"""Untrusted pipeline contracts and deterministic source validation."""

import re
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from typing import Any, Protocol

PIPELINE_SCHEMA = "knowledge-pipeline/1"
IMPORTABLE_STATUSES = {"ok", "completed_with_failures"}
CONFLICT_STATUSES = {"possible_conflict", "unresolved"}
PASSAGE_SPEAKERS = {"agent", "customer", "system_action"}
TURN_ID = re.compile(r"#t(\d+)$")


class KnowledgePipelineAdapter(Protocol):
    def run(self, organization_id: str) -> dict[str, Any]:
        """Run the knowledge pipeline for one organization and return its output."""
        ...


class KnowledgePipelineUnavailableError(Exception):
    pass


class UnconfiguredKnowledgePipeline:
    """The default until a pipeline is configured: imports are refused, never faked."""

    def run(self, organization_id: str) -> dict[str, Any]:
        raise KnowledgePipelineUnavailableError("No knowledge pipeline is configured.")


class ImportRejectedError(Exception):
    """The output as a whole cannot be trusted; nothing was stored."""


class DraftSkippedError(Exception):
    """One draft cannot be stored; the message is the reason reported back."""


@dataclass
class ImportResult:
    created: int = 0
    updated: int = 0
    unchanged: int = 0
    # Drafts and conflicts that could not be stored, with the reason.
    skipped: list[dict[str, str]] = field(default_factory=list)
    conflicts_stored: int = 0


def _text(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _similarity(value: Any) -> Decimal | None:
    try:
        number = Decimal(str(value)).quantize(Decimal("0.0001"))
    except (InvalidOperation, ValueError):
        return None
    return number if Decimal(0) <= number <= Decimal(1) else None


def check_output(organization_id: str, output: Any) -> None:
    """Reject output that is not safe to store at all."""
    if not isinstance(output, dict) or output.get("schema") != PIPELINE_SCHEMA:
        raise ImportRejectedError("The pipeline output schema is not supported.")
    if (
        not isinstance(output.get("status"), str)
        or output["status"] not in IMPORTABLE_STATUSES
    ):
        raise ImportRejectedError(
            f"The pipeline finished with status {output.get('status')!r}."
        )
    if output.get("company_id") != organization_id:
        raise ImportRejectedError("The output is for a different organization.")
    checks = output.get("release_checks")
    if not isinstance(checks, dict) or checks.get("release_allowed") is not True:
        raise ImportRejectedError("The pipeline's release checks did not pass.")
    drafts = output.get("drafts")
    if not isinstance(drafts, list):
        raise ImportRejectedError("The output has no draft list.")
    for draft in drafts:
        # Pipeline output can only ever be an untrusted, unapproved draft.
        if (
            not isinstance(draft, dict)
            or draft.get("kind") != "knowledge_draft"
            or draft.get("status") != "draft"
            or draft.get("trusted") is not False
            or draft.get("audit_eligible") is not False
            or draft.get("company_id") != organization_id
            or not _text(draft.get("draft_id"))
            or len(draft["draft_id"]) > 100
        ):
            raise ImportRejectedError(
                "A draft claims to be trusted, approved or from another organization."
            )


@dataclass
class _Passage:
    role: str
    conversation_key: tuple[str, str]
    turn_number: int
    speaker: str
    quote: str
    span: tuple[int, int]
    source_key: str
    source_version: str


def _passages(draft: dict[str, Any]) -> list[_Passage]:
    """Every cited passage, or DraftSkippedError if any is malformed."""
    cited = [("question", p) for p in draft.get("question_passages") or []]
    cited += [("answer", p) for p in draft.get("answer_passages") or []]
    cited += [
        ("condition", condition.get("passage"))
        for condition in draft.get("conditions") or []
        if isinstance(condition, dict) and condition.get("passage") is not None
    ]
    if not any(role == "answer" for role, _ in cited):
        raise DraftSkippedError("no-answer-passage")
    passages = []
    for role, passage in cited:
        if not isinstance(passage, dict):
            raise DraftSkippedError("invalid-passage")
        source_key = passage.get("source_key")
        turn = TURN_ID.search(str(passage.get("turn_id", "")))
        span = passage.get("span")
        speaker = passage.get("speaker")
        if (
            not _text(source_key)
            or len(source_key) > 200
            or ":" not in source_key
            or turn is None
            or not isinstance(speaker, str)
            or speaker not in PASSAGE_SPEAKERS
            or not _text(passage.get("quote"))
            or not _text(passage.get("source_version"))
            or len(passage["source_version"]) > 100
            or not isinstance(span, list)
            or len(span) != 2
            or not all(type(value) is int for value in span)
            or not 0 <= span[0] < span[1]
        ):
            raise DraftSkippedError("invalid-passage")
        dataset, original_id = source_key.split(":", 1)
        passages.append(
            _Passage(
                role=role,
                conversation_key=(dataset, original_id),
                turn_number=int(turn.group(1)),
                speaker=passage["speaker"],
                quote=passage["quote"],
                span=(span[0], span[1]),
                source_key=source_key,
                source_version=passage["source_version"],
            )
        )
    return passages
