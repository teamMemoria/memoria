"""Present loaded knowledge records; no database or external calls."""

import hashlib
import json

from backend.data.demo_profiles import profile_display_name
from backend.entities.policies import (
    EXTENSION_KEY,
    FAQ_KEY,
    GOLD_EXTENSION_KEY,
    verification_source,
)
from backend.entities.results import DraftStatus, ReviewAction, Speaker
from backend.interface_adapters.presenters.assessments import (
    SPEAKER_NAMES,
    iso_timestamp,
)
from backend.interface_adapters.records import (
    KnowledgeConflict,
    KnowledgeDraft,
    KnowledgeDraftEntryMatch,
)
from backend.schemas.knowledge_review import (
    ConversationPassage,
    EntryMatch,
    KnowledgeDecision,
    PossibleConflict,
)
from backend.schemas.knowledge_review import KnowledgeDraft as KnowledgeDraftSchema

STATUS_NAMES = {
    DraftStatus.PENDING: "draft",
    DraftStatus.APPROVED: "approved",
    DraftStatus.REJECTED: "rejected",
}
SPEAKERS_BY_VALUE = {speaker.value: name for speaker, name in SPEAKER_NAMES.items()}


def _decision(draft: KnowledgeDraft) -> KnowledgeDecision | None:
    decisions = [
        review
        for review in draft.reviews
        if review.action in (ReviewAction.APPROVED, ReviewAction.REJECTED)
    ]
    if not decisions:
        return None
    review = max(decisions, key=lambda review: (review.reviewed_at, review.id))
    member = review.reviewer_membership
    return KnowledgeDecision(
        outcome=review.action.value,
        reason=review.note,
        manager_name=profile_display_name(
            member.user.external_id, member.user.display_name
        )
        if member
        else "Unknown reviewer",
        decided_at=iso_timestamp(review.reviewed_at),
    )


def draft_version(draft):
    # Content-bound: a changed answer or reference requires another review.
    content = [
        draft.id,
        draft.topic_id,
        draft.question,
        draft.answer_text,
        draft.verification_reference,
        str(draft.updated_at),
    ]
    return (
        "sha256:"
        + hashlib.sha256(json.dumps(content, sort_keys=True).encode()).hexdigest()
    )


def draft_schema(
    draft: KnowledgeDraft,
    distinct_conversations: int,
    conflicts: list[KnowledgeConflict],
    matches: list[KnowledgeDraftEntryMatch],
    authored_policy_version: str | None = None,
) -> KnowledgeDraftSchema:
    passages = [
        ConversationPassage(
            conversation_id=str(passage.conversation_id),
            turn_number=passage.turn_number,
            speaker=SPEAKERS_BY_VALUE[passage.speaker],
            text=passage.quote,
            role=passage.role,
            source_key=passage.source_key,
            source_version=passage.source_version,
        )
        for passage in sorted(draft.passages, key=lambda p: p.position)
        if draft.source_key in {FAQ_KEY, EXTENSION_KEY, GOLD_EXTENSION_KEY}
        or passage.speaker != Speaker.SYSTEM_ACTION.value
    ]
    return KnowledgeDraftSchema(
        id=str(draft.id),
        title=draft.question or draft.topic.name,
        topic=draft.topic.name,
        kind="knowledge",
        status=STATUS_NAMES[draft.status],
        # Drafts are not available to any agent.
        available_to_agent_ids=[],
        version=draft_version(draft),
        approved_at=None,
        approved_by=None,
        effective_at=None,
        last_confirmed_at=None,
        owner=None,
        source=None,
        paragraphs=[
            paragraph.strip()
            for paragraph in draft.answer_text.split("\n\n")
            if paragraph.strip()
        ],
        steps=[],
        source_conversation_ids=sorted(
            str(conversation.id) for conversation in draft.supporting_conversations
        ),
        updated_at=iso_timestamp(draft.updated_at or draft.created_at),
        passages=passages,
        verification_reference=(
            {key: draft.verification_reference[key] for key in ("title", "url")}
            if draft.verification_reference
            else None
        ),
        can_attach_verification=(
            draft.status is DraftStatus.PENDING
            and verification_source(draft.source_key, draft.answer_text) is not None
        ),
        authored_policy_version=authored_policy_version,
        decision=_decision(draft),
        question=draft.question,
        distinct_conversation_count=distinct_conversations,
        duplicate_of_id=(
            str(draft.duplicate_of_id) if draft.duplicate_of_id is not None else None
        ),
        possible_conflicts=[
            PossibleConflict(
                id=str(conflict.id),
                kind=conflict.kind,
                status=conflict.status,
                explanation=conflict.explanation,
                other_draft_id=str(
                    conflict.other_draft_id
                    if conflict.draft_id == draft.id
                    else conflict.draft_id
                )
                if conflict.other_entry_id is None
                else None,
                other_entry_id=(
                    str(conflict.other_entry_id)
                    if conflict.other_entry_id is not None
                    else None
                ),
            )
            for conflict in conflicts
        ],
        existing_matches=[
            EntryMatch(
                entry_id=str(match.entry_id),
                kind=match.kind,
                similarity=float(match.similarity),
            )
            for match in matches
        ],
        ml_verification=draft.ml_verification,
    )
