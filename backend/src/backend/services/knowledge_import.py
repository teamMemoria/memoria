"""Store knowledge-pipeline output as pending drafts for an authorized reviewer.

The pipeline (``knowledge-pipeline/1``) returns drafts with cited passages,
groups with duplicate links and matches to approved entries, possible
conflicts, and its own verification hints. This module checks that output and
stores it. It never approves, rejects or disputes anything:

* new drafts are stored as ``pending``; approved guidance (``knowledge_entries``)
  and reviews are never written, so no entry is approved, renewed or replaced;
* a draft a reviewer has already decided keeps its content;
* possible conflicts go to ``knowledge_conflicts`` and never change an entry's
  status, so they stay separate from disputes a reviewer confirms.

Importing the same output again changes nothing. Each draft is keyed by the
pipeline's draft ID and each conflict by its conflict ID, and counts are
computed from stored rows, so reprocessing cannot add duplicates or inflate
distinct-conversation counts.
"""

import asyncio
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Any, Protocol

from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from backend.models import (
    Conversation,
    DraftStatus,
    KnowledgeConflict,
    KnowledgeDraft,
    KnowledgeDraftEntryMatch,
    KnowledgeDraftPassage,
    KnowledgeEntry,
    Organization,
    Topic,
)
from backend.providers.base import RecordNotFoundError
from backend.providers.database import SessionFactory, unavailable_on_database_error
from backend.services.clock import utc_now

PIPELINE_SCHEMA = "knowledge-pipeline/1"
IMPORTABLE_STATUSES = {"ok", "completed_with_failures"}
CONFLICT_STATUSES = {"possible_conflict", "unresolved"}
PASSAGE_SPEAKERS = {"agent", "customer", "system_action"}
TURN_ID = re.compile(r"#t(\d+)$")
# Advisory lock class for imports; the second key is the organization ID.
IMPORT_LOCK = 7901


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


@dataclass
class KnowledgeImportService:
    sessions: SessionFactory
    adapter: KnowledgePipelineAdapter = field(
        default_factory=UnconfiguredKnowledgePipeline
    )
    now: Callable[[], datetime] = utc_now

    async def run(self, organization_id: str) -> ImportResult:
        """Run the configured pipeline and store its output."""
        try:
            # The pipeline is synchronous and may be slow; keep it off the event loop.
            output = await asyncio.to_thread(self.adapter.run, organization_id)
        except KnowledgePipelineUnavailableError:
            raise
        except Exception as error:
            # Any pipeline crash is reported as the pipeline failing, never hidden.
            raise KnowledgePipelineUnavailableError(
                f"The knowledge pipeline failed with {type(error).__name__}."
            ) from error
        return await self.import_output(organization_id, output)

    @unavailable_on_database_error
    async def import_output(self, organization_id: str, output: Any) -> ImportResult:
        check_output(organization_id, output)
        async with self.sessions() as session:
            organization = await session.scalar(
                select(Organization).where(Organization.slug == organization_id)
            )
            if organization is None:
                raise RecordNotFoundError("Organization not found")
            # One import per organization at a time, so two runs cannot both
            # insert the same draft or undo each other's group facts.
            await session.execute(
                select(func.pg_advisory_xact_lock(IMPORT_LOCK, organization.id))
            )
            result = ImportResult()
            try:
                stored = await self._store_drafts(session, organization, output, result)
                await self._store_groups(session, organization, output, stored, result)
                await self._store_conflicts(
                    session, organization, output, stored, result
                )
            except (TypeError, AttributeError) as error:
                # A value of the wrong type somewhere in the output: store nothing.
                await session.rollback()
                raise ImportRejectedError(
                    "The pipeline output has a value of the wrong type."
                ) from error
            await session.commit()
            return result

    async def _store_drafts(
        self,
        session: AsyncSession,
        organization: Organization,
        output: dict[str, Any],
        result: ImportResult,
    ) -> dict[str, KnowledgeDraft]:
        verification = {
            item["draft_id"]: item.get("verification_status")
            for item in (output.get("verification") or {}).get("results") or []
            if isinstance(item, dict) and isinstance(item.get("draft_id"), str)
        }
        stored: dict[str, KnowledgeDraft] = {}
        for draft in output["drafts"]:
            draft_id = draft["draft_id"]
            if draft_id in stored:
                result.skipped.append({"draftId": draft_id, "reason": "repeated"})
                continue
            try:
                passages = _passages(draft)
                question = draft.get("question")
                if (
                    not _text(draft.get("answer"))
                    or not _text(draft.get("topic"))
                    or (question is not None and not isinstance(question, str))
                ):
                    raise DraftSkippedError("invalid-draft")
            except DraftSkippedError as error:
                result.skipped.append({"draftId": draft_id, "reason": str(error)})
                continue

            conversations = await self._conversations(
                session, organization, {p.conversation_key for p in passages}
            )
            reason = self._check_passages(passages, conversations)
            if reason is not None:
                result.skipped.append({"draftId": draft_id, "reason": reason})
                continue

            existing = await session.scalar(
                select(KnowledgeDraft)
                .where(
                    KnowledgeDraft.organization_id == organization.id,
                    KnowledgeDraft.source_key == draft_id,
                )
                .options(
                    selectinload(KnowledgeDraft.passages),
                    selectinload(KnowledgeDraft.supporting_conversations),
                )
                # Held until commit, so a reviewer's decision cannot land between
                # the "still pending" check below and the update.
                .with_for_update()
            )
            if existing is not None and existing.status is not DraftStatus.PENDING:
                # A reviewer has decided; the pipeline never changes that draft.
                stored[draft_id] = existing
                result.unchanged += 1
                continue

            # The dataset of the first answer passage, so the same output
            # always picks the same topic.
            first_answer = next(p for p in passages if p.role == "answer")
            topic = await self._topic(
                session,
                organization,
                conversations[first_answer.conversation_key].source_dataset,
                draft["topic"],
            )
            hint = verification.get(draft_id)
            content = {
                "topic_id": topic.id,
                "question": draft.get("question") or None,
                "answer_text": draft["answer"],
                "ml_verification": hint[:30] if isinstance(hint, str) else None,
            }
            passage_rows = [
                (
                    p.role,
                    position,
                    conversations[p.conversation_key].id,
                    p.turn_number,
                    p.speaker,
                    p.quote,
                    p.span,
                    p.source_key,
                    p.source_version,
                )
                for position, p in enumerate(passages)
            ]
            sources = sorted(
                {conversation.id for conversation in conversations.values()}
            )

            new_passages = [
                KnowledgeDraftPassage(
                    organization_id=organization.id,
                    role=role,
                    position=position,
                    conversation_id=conversation_id,
                    turn_number=turn_number,
                    speaker=speaker,
                    quote=quote,
                    span_start=span[0],
                    span_end=span[1],
                    source_key=source_key,
                    source_version=source_version,
                )
                for (
                    role,
                    position,
                    conversation_id,
                    turn_number,
                    speaker,
                    quote,
                    span,
                    source_key,
                    source_version,
                ) in passage_rows
            ]
            if existing is None:
                row = KnowledgeDraft(
                    organization_id=organization.id,
                    source_key=draft_id,
                    status=DraftStatus.PENDING,
                    updated_at=self.now(),
                    passages=new_passages,
                    supporting_conversations=list(conversations.values()),
                    **content,
                )
                session.add(row)
                result.created += 1
            else:
                row = existing
                same = (
                    all(getattr(row, key) == value for key, value in content.items())
                    and self._passage_rows(row) == passage_rows
                    and sorted(c.id for c in row.supporting_conversations) == sources
                )
                if same:
                    stored[draft_id] = row
                    result.unchanged += 1
                    continue
                for key, value in content.items():
                    setattr(row, key, value)
                row.updated_at = self.now()
                # Passages and sources describe the current output; replace them.
                # The old passages go first so their positions can be reused.
                row.passages.clear()
                await session.flush()
                row.passages = new_passages
                row.supporting_conversations = list(conversations.values())
                result.updated += 1
            await session.flush()
            stored[draft_id] = row
        return stored

    @staticmethod
    def _passage_rows(row: KnowledgeDraft) -> list[tuple]:
        return [
            (
                p.role,
                p.position,
                p.conversation_id,
                p.turn_number,
                p.speaker,
                p.quote,
                (p.span_start, p.span_end),
                p.source_key,
                p.source_version,
            )
            for p in sorted(row.passages, key=lambda p: p.position)
        ]

    async def _conversations(
        self,
        session: AsyncSession,
        organization: Organization,
        keys: set[tuple[str, str]],
    ) -> dict[tuple[str, str], Conversation]:
        found = {}
        for dataset, original_id in keys:
            conversation = await session.scalar(
                select(Conversation)
                .where(
                    Conversation.organization_id == organization.id,
                    Conversation.source_dataset == dataset,
                    Conversation.original_id == original_id,
                )
                .options(selectinload(Conversation.turns))
            )
            if conversation is not None:
                found[(dataset, original_id)] = conversation
        return found

    @staticmethod
    def _check_passages(
        passages: list[_Passage], conversations: dict[tuple[str, str], Conversation]
    ) -> str | None:
        """Every passage must quote a stored turn of a stored conversation."""
        for passage in passages:
            conversation = conversations.get(passage.conversation_key)
            if conversation is None:
                return "conversation-not-found"
            turn = next(
                (t for t in conversation.turns if t.line_number == passage.turn_number),
                None,
            )
            if (
                turn is None
                or turn.speaker.value != passage.speaker
                or passage.quote not in turn.text
            ):
                return "passage-not-in-transcript"
        return None

    async def _topic(
        self,
        session: AsyncSession,
        organization: Organization,
        source_dataset: str,
        name: str,
    ) -> Topic:
        name = name.strip()[:100]
        topic = await session.scalar(
            select(Topic).where(
                Topic.organization_id == organization.id,
                Topic.source_dataset == source_dataset,
                Topic.name == name,
            )
        )
        if topic is None:
            topic = Topic(
                organization_id=organization.id,
                source_dataset=source_dataset,
                name=name,
            )
            session.add(topic)
            await session.flush()
        return topic

    async def _store_groups(
        self,
        session: AsyncSession,
        organization: Organization,
        output: dict[str, Any],
        stored: dict[str, KnowledgeDraft],
        result: ImportResult,
    ) -> None:
        """Group membership, duplicate links and matches to approved entries.

        Each import is the pipeline's complete current view, so these replace
        what earlier imports stored for every pending pipeline draft, including
        drafts this output no longer mentions. Decided drafts keep theirs.
        """
        groups = (output.get("groups") or {}).get("groups") or []
        entry_ids = set(
            await session.scalars(
                select(KnowledgeEntry.id).where(
                    KnowledgeEntry.organization_id == organization.id
                )
            )
        )
        pending = {
            key: row for key, row in stored.items() if row.status is DraftStatus.PENDING
        }
        pending_pipeline_drafts = (
            KnowledgeDraft.organization_id == organization.id,
            KnowledgeDraft.source_key.is_not(None),
            KnowledgeDraft.status == DraftStatus.PENDING,
        )
        await session.execute(
            update(KnowledgeDraft)
            .where(*pending_pipeline_drafts)
            .values(group_key=None, duplicate_of_id=None, duplicate_similarity=None)
            .execution_options(synchronize_session="fetch")
        )
        await session.execute(
            delete(KnowledgeDraftEntryMatch).where(
                KnowledgeDraftEntryMatch.organization_id == organization.id,
                KnowledgeDraftEntryMatch.draft_id.in_(
                    select(KnowledgeDraft.id).where(*pending_pipeline_drafts)
                ),
            )
        )
        matched: set[tuple[int, int]] = set()

        for group in groups:
            if not isinstance(group, dict) or not _text(group.get("group_id")):
                continue
            members = [
                pending[draft_id]
                for draft_id in group.get("member_draft_ids") or []
                if draft_id in pending
            ]
            for row in members:
                row.group_key = group["group_id"][:100]
            for duplicate in group.get("duplicates") or []:
                if not isinstance(duplicate, dict):
                    continue
                row = pending.get(duplicate.get("draft_id"))
                original = stored.get(duplicate.get("duplicate_of"))
                if row is not None and original is not None and original is not row:
                    row.duplicate_of_id = original.id
                    row.duplicate_similarity = _similarity(duplicate.get("similarity"))
            for match in group.get("existing_matches") or []:
                if not isinstance(match, dict):
                    continue
                entry_id = str(match.get("entry_id", ""))
                similarity = _similarity(match.get("similarity"))
                if (
                    not entry_id.isdigit()
                    or int(entry_id) not in entry_ids
                    or similarity is None
                ):
                    result.skipped.append(
                        {"entryId": entry_id, "reason": "entry-not-found"}
                    )
                    continue
                for row in members:
                    # The same entry may be listed twice; store each pair once.
                    if (row.id, int(entry_id)) in matched:
                        continue
                    matched.add((row.id, int(entry_id)))
                    session.add(
                        KnowledgeDraftEntryMatch(
                            organization_id=organization.id,
                            draft_id=row.id,
                            entry_id=int(entry_id),
                            kind=str(match.get("kind", "similar"))[:30],
                            similarity=similarity,
                        )
                    )
        await session.flush()

    async def _store_conflicts(
        self,
        session: AsyncSession,
        organization: Organization,
        output: dict[str, Any],
        stored: dict[str, KnowledgeDraft],
        result: ImportResult,
    ) -> None:
        conflicts = (output.get("conflicts") or {}).get("possible_conflicts") or []
        entry_ids = set(
            await session.scalars(
                select(KnowledgeEntry.id).where(
                    KnowledgeEntry.organization_id == organization.id
                )
            )
        )

        def side(value: Any) -> tuple[str, int] | None:
            if not isinstance(value, dict):
                return None
            draft_id = value.get("draft_id")
            if (
                value.get("type") == "draft"
                and isinstance(draft_id, str)
                and draft_id in stored
            ):
                return "draft", stored[value["draft_id"]].id
            entry_id = str(value.get("entry_id", ""))
            if (
                value.get("type") == "existing_entry"
                and entry_id.isdigit()
                and int(entry_id) in entry_ids
            ):
                return "entry", int(entry_id)
            return None

        current: set[str] = set()
        for conflict in conflicts:
            if not isinstance(conflict, dict) or not _text(conflict.get("conflict_id")):
                continue
            key = conflict["conflict_id"][:100]
            sides = [side(conflict.get("a")), side(conflict.get("b"))]
            drafts = [value for kind, value in filter(None, sides) if kind == "draft"]
            entries = [value for kind, value in filter(None, sides) if kind == "entry"]
            if (
                None in sides
                or not drafts
                or not isinstance(conflict.get("status"), str)
                or conflict["status"] not in CONFLICT_STATUSES
                or not _text(conflict.get("explanation"))
            ):
                result.skipped.append({"conflictId": key, "reason": "unresolved-side"})
                continue
            values = {
                "kind": str(conflict.get("kind", "conflict"))[:30],
                "status": conflict["status"],
                "explanation": conflict["explanation"],
                "draft_id": drafts[0],
                "other_draft_id": drafts[1] if len(drafts) > 1 else None,
                "other_entry_id": entries[0] if entries else None,
            }
            existing = await session.scalar(
                select(KnowledgeConflict).where(
                    KnowledgeConflict.organization_id == organization.id,
                    KnowledgeConflict.source_key == key,
                )
            )
            if existing is None:
                session.add(
                    KnowledgeConflict(
                        organization_id=organization.id,
                        source_key=key,
                        updated_at=self.now(),
                        **values,
                    )
                )
            elif any(getattr(existing, k) != v for k, v in values.items()):
                for k, v in values.items():
                    setattr(existing, k, v)
                existing.updated_at = self.now()
            current.add(key)
            result.conflicts_stored += 1
        await session.flush()
        # Conflicts the pipeline no longer reports are no longer suspected.
        await session.execute(
            delete(KnowledgeConflict).where(
                KnowledgeConflict.organization_id == organization.id,
                KnowledgeConflict.source_key.not_in(current),
            )
        )
