"""Read-only shapes consumed by presenters; no ORM or HTTP dependency.

Loaded persistence records satisfy these structural interfaces directly. The
repository owns eager loading; presenters never fetch missing relationships.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Protocol

from backend.entities.results import (
    DraftStatus,
    EntryStatus,
    FindingCategory,
    FindingResult,
    ManagerReviewOutcome,
    ReviewAction,
    Speaker,
)


class User(Protocol):
    external_id: str
    display_name: str


class OrganizationMembership(Protocol):
    user: User


class Topic(Protocol):
    name: str


class Turn(Protocol):
    line_number: int
    conversation_id: int
    speaker: Speaker
    text: str


class Conversation(Protocol):
    id: int
    organization_id: int
    original_id: str | None
    source_dataset: str | None
    conversation_date: date | None
    topic: Topic | None
    turns: list[Turn]
    canonical_evidence: dict | None


class ManagerReview(Protocol):
    id: int
    reviewed_at: datetime
    outcome: ManagerReviewOutcome
    reviewed_result: FindingResult | None
    reason: str
    feedback: str
    reviewer_membership: OrganizationMembership


class FeedbackFlag(Protocol):
    id: int
    finding_id: int
    reason: str
    flagged_at: datetime
    manager_review: ManagerReview | None


class KnowledgeReview(Protocol):
    id: int
    action: ReviewAction
    note: str | None
    reviewed_at: datetime
    reviewer_membership: OrganizationMembership | None
    verified_reference_url: str | None


class KnowledgeEntry(Protocol):
    id: int
    organization_id: int
    topic: Topic
    status: EntryStatus
    answer_text: str
    last_confirmed_at: datetime | None
    approved_review: KnowledgeReview


class Finding(Protocol):
    id: int
    category: FindingCategory
    result: FindingResult
    feedback: str
    suggestion: str | None
    evidence: list[Turn]
    knowledge_entry: KnowledgeEntry | None
    feedback_flag: FeedbackFlag | None


class Audit(Protocol):
    summary: str | None
    findings: list[Finding]
    assessment_report: dict | None


class AgentContextRecord(Protocol):
    text: str
    saved_at: datetime


class Passage(Protocol):
    position: int
    conversation_id: int
    turn_number: int
    speaker: str
    quote: str
    role: str
    source_key: str
    source_version: str


class KnowledgeDraft(Protocol):
    id: int
    topic_id: int
    topic: Topic
    question: str | None
    answer_text: str
    verification_reference: dict | None
    updated_at: datetime | None
    created_at: datetime
    status: DraftStatus
    reviews: list[KnowledgeReview]
    passages: list[Passage]
    supporting_conversations: list[Conversation]
    duplicate_of_id: int | None
    ml_verification: dict | None


class KnowledgeConflict(Protocol):
    id: int
    kind: str
    status: str
    explanation: str
    draft_id: int
    other_draft_id: int | None
    other_entry_id: int | None


class KnowledgeDraftEntryMatch(Protocol):
    entry_id: int
    kind: str
    similarity: Decimal
