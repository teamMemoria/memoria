"""Store knowledge-pipeline output as pending drafts for an authorized reviewer.

The pipeline (``knowledge-pipeline/1``) returns drafts with cited passages,
groups with duplicate links and matches to approved entries, possible
conflicts, and its own verification hints. This module checks that output and
stores it as pending for review:

* only the built-in Layer 2 pilot can auto-approve source-verified facts;
* a draft a reviewer has already decided keeps its content;
* possible conflicts go to ``knowledge_conflicts`` and never change an entry's
  status, so they stay separate from disputes a reviewer confirms.

Importing the same output again changes nothing. Each draft is keyed by the
pipeline's draft ID and each conflict by its conflict ID, and counts are
computed from stored rows, so reprocessing cannot add duplicates or inflate
distinct-conversation counts.
"""

import asyncio
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from functools import partial
from typing import Any

from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from backend.entities.knowledge_import import (
    CONFLICT_STATUSES,
    IMPORTABLE_STATUSES,
    PASSAGE_SPEAKERS,
    PIPELINE_SCHEMA,
    TURN_ID,
    DraftSkippedError,
    ImportRejectedError,
    ImportResult,
    KnowledgePipelineAdapter,
    KnowledgePipelineUnavailableError,
    UnconfiguredKnowledgePipeline,
    _Passage,
    _passages,
    _similarity,
    _text,
    check_output,
)
from backend.entities.policies import verification_source
from backend.frameworks.data_access.database import (
    SessionFactory,
    load_membership,
    unavailable_on_database_error,
)
from backend.frameworks.data_access.knowledge_approval import approve_draft
from backend.frameworks.database.models import (
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
from backend.interface_adapters.ports import RecordNotFoundError
from backend.services.clock import utc_now
from backend.use_cases.knowledge import KnowledgeImportInteractor

# PostgreSQL lock namespace; deliberately outside the business rules.
IMPORT_LOCK = 7901


@dataclass
class KnowledgeImportService:
    sessions: SessionFactory
    adapter: KnowledgePipelineAdapter = field(
        default_factory=UnconfiguredKnowledgePipeline
    )
    now: Callable[[], datetime] = utc_now
    generate: Callable[[str, list[dict]], dict] | None = None
    source_prefix: str | None = None

    async def run(
        self, organization_id: str, *, requested_by: str | None = None
    ) -> ImportResult:
        """Run the configured pipeline and store its output."""

        async def run_pipeline(scope):
            if self.generate is None:
                return await asyncio.to_thread(self.adapter.run, scope)
            from backend.frameworks.data_access.assessment_storage import (
                validate_prepared,
            )

            async with self.sessions() as session:
                sources = await session.scalars(
                    select(Conversation.canonical_evidence)
                    .join(Organization, Organization.id == Conversation.organization_id)
                    .where(
                        Organization.slug == scope,
                        Conversation.source_dataset == "ABCD",
                        Conversation.canonical_evidence["conversations"][0][
                            "split"
                        ].as_string()
                        == "train",
                        Conversation.canonical_evidence["conversations"][0][
                            "id"
                        ].as_string()
                        == Conversation.original_id,
                    )
                    .order_by(Conversation.original_id)
                )
                conversations = [validate_prepared(source) for source in sources]
            return await asyncio.to_thread(self.generate, scope, conversations)

        store = partial(
            self.import_output, approver_id=requested_by if self.generate else None
        )
        return await KnowledgeImportInteractor(store, run_pipeline).execute(
            organization_id
        )

    @unavailable_on_database_error
    async def import_output(
        self, organization_id: str, output: Any, *, approver_id: str | None = None
    ) -> ImportResult:
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
            if approver_id is not None and self.generate is not None:
                membership = await load_membership(
                    session, organization_id, approver_id
                )
                if membership and membership.can_approve_knowledge:
                    await self._auto_approve(
                        session, membership, stored, output["drafts"]
                    )
            await session.commit()
            return result

    async def _auto_approve(self, session, membership, stored, drafts):
        for item in drafts:
            draft = stored.get(item["draft_id"])
            if (
                "agreement" not in item
                or draft is None
                or draft.status is not DraftStatus.PENDING
                or draft.duplicate_of_id
            ):
                continue
            support, total = item["agreement"]
            source = verification_source(draft.source_key, draft.answer_text)
            if source is None or total < 10 or support * 10 < total * 7:
                continue
            if await session.scalar(
                select(KnowledgeConflict.id)
                .where(
                    KnowledgeConflict.organization_id == draft.organization_id,
                    KnowledgeConflict.lifecycle_status == "open",
                    KnowledgeConflict.status.in_(CONFLICT_STATUSES),
                    (KnowledgeConflict.draft_id == draft.id)
                    | (KnowledgeConflict.other_draft_id == draft.id),
                )
                .limit(1)
            ):
                continue
            await session.refresh(draft, ["topic"])
            if draft.topic.disputed:
                continue
            _, quote, url = source
            draft.verification_reference = {
                "title": "ABCD guidelines",
                "url": url,
                "quote": quote if isinstance(quote, str) else "\n".join(quote),
            }
            entry = await approve_draft(session, draft, membership)
            entry.approved_review.verified_reference_url = url
            entry.approved_review.note = (
                f"Automatically approved: {support}/{total} calls agreed."
            )

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
            canonical = conversation.canonical_evidence
            if (
                canonical
                and passage.source_version
                != canonical["conversations"][0]["transcript_version"]
            ):
                return "source-version-mismatch"
            turn = next(
                (t for t in conversation.turns if t.line_number == passage.turn_number),
                None,
            )
            if (
                turn is None
                or turn.speaker.value != passage.speaker
                or turn.text[passage.span[0] : passage.span[1]] != passage.quote
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
            *(
                [KnowledgeDraft.source_key.startswith(self.source_prefix)]
                if self.source_prefix
                else []
            ),
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
                *(
                    [KnowledgeConflict.source_key.startswith(self.source_prefix)]
                    if self.source_prefix
                    else []
                ),
                KnowledgeConflict.lifecycle_status == "open",
                KnowledgeConflict.draft_id.not_in(
                    select(KnowledgeDraft.id)
                    .join(KnowledgeDraft.topic)
                    .where(Topic.disputed.is_(True))
                ),
            )
        )


__all__ = [
    "CONFLICT_STATUSES",
    "IMPORTABLE_STATUSES",
    "IMPORT_LOCK",
    "PASSAGE_SPEAKERS",
    "PIPELINE_SCHEMA",
    "TURN_ID",
    "DraftSkippedError",
    "ImportRejectedError",
    "ImportResult",
    "KnowledgePipelineAdapter",
    "KnowledgePipelineUnavailableError",
    "UnconfiguredKnowledgePipeline",
    "_Passage",
    "_passages",
    "_similarity",
    "_text",
    "check_output",
]
