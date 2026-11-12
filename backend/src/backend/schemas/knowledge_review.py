from typing import Literal

from backend.schemas.base import ApiModel
from backend.schemas.knowledge import KnowledgeEntry

# Matches KnowledgeDraft and KnowledgeReviewDetail in frontend/src/types/knowledge.ts,
# with the pipeline evidence added. The frontend ignores fields it does not use.
DraftQueueStatus = Literal["all", "draft", "approved", "rejected"]


class ConversationPassage(ApiModel):
    conversation_id: str
    turn_number: int
    speaker: Literal["Agent", "Customer"]
    text: str
    # Where the quote came from, so a reviewer can check it against the source.
    role: Literal["question", "answer", "condition"]
    source_key: str
    source_version: str


class KnowledgeDecision(ApiModel):
    outcome: Literal["approved", "rejected"]
    reason: str | None
    manager_name: str
    decided_at: str


class VerificationReference(ApiModel):
    title: str
    url: str


class PossibleConflict(ApiModel):
    """A conflict the pipeline suspects. Never a confirmed dispute."""

    id: str
    kind: str
    status: Literal["possible_conflict", "unresolved"]
    explanation: str
    other_draft_id: str | None
    other_entry_id: str | None


class EntryMatch(ApiModel):
    entry_id: str
    kind: str
    similarity: float


class KnowledgeDraft(KnowledgeEntry):
    source_conversation_ids: list[str]
    updated_at: str
    passages: list[ConversationPassage]
    verification_reference: VerificationReference | None
    decision: KnowledgeDecision | None
    question: str | None
    # Distinct stored conversations behind this draft's group, counted once each.
    distinct_conversation_count: int
    duplicate_of_id: str | None
    possible_conflicts: list[PossibleConflict]
    existing_matches: list[EntryMatch]
    # The pipeline's own reading of its references; a hint, not a verification.
    ml_verification: str | None


class KnowledgeReviewDetail(ApiModel):
    entry: KnowledgeDraft
    # Knowledge permission, separate from call review.
    can_decide: bool


class KnowledgeQueueCounts(ApiModel):
    total: int
    draft: int
    approved: int
    rejected: int
    with_possible_conflicts: int


class KnowledgeImportResult(ApiModel):
    created: int
    updated: int
    unchanged: int
    skipped: list[dict[str, str]]
    conflicts_stored: int
