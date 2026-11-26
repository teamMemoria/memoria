from __future__ import annotations

import json
import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import date
from enum import StrEnum

from backend.data.provenance import ValueOrigin


class KnowledgeState(StrEnum):
    PENDING = "pending"
    APPROVED = "approved"
    DISPUTED = "disputed"
    STALE = "stale"
    CANNOT_ASSESS = "cannot_assess"


@dataclass(frozen=True)
class PolicyVersion:
    version: str
    delivery_window: str
    effective_from: date
    origin: ValueOrigin = ValueOrigin.SYNTHETIC

    def as_dict(self) -> dict[str, str]:
        return {
            "version": self.version,
            "delivery_window": self.delivery_window,
            "effective_from": self.effective_from.isoformat(),
            "origin": self.origin.value,
        }


@dataclass(frozen=True)
class ConversationPassage:
    conversation_id: str
    occurred_on: date
    speaker: str
    text: str
    supports_policy_version: str | None
    origin: ValueOrigin = ValueOrigin.SYNTHETIC

    def as_dict(self) -> dict[str, str | None]:
        return {
            "conversation_id": self.conversation_id,
            "occurred_on": self.occurred_on.isoformat(),
            "speaker": self.speaker,
            "text": self.text,
            "supports_policy_version": self.supports_policy_version,
            "origin": self.origin.value,
        }


@dataclass(frozen=True)
class ReviewRecord:
    review_id: str
    case_id: str
    reviewer_role: str
    action: str
    reviewed_on: date
    origin: ValueOrigin = ValueOrigin.SYNTHETIC

    def as_dict(self) -> dict[str, str]:
        return {
            "review_id": self.review_id,
            "case_id": self.case_id,
            "reviewer_role": self.reviewer_role,
            "action": self.action,
            "reviewed_on": self.reviewed_on.isoformat(),
            "origin": self.origin.value,
        }


@dataclass(frozen=True)
class ExpectedOutcome:
    case_id: str
    evidence_conversation_ids: tuple[str, ...]
    expected_state: KnowledgeState
    reason: str
    review_id: str | None = None
    origin: ValueOrigin = ValueOrigin.SYNTHETIC

    def as_dict(self) -> dict[str, object]:
        return {
            "case_id": self.case_id,
            "evidence_conversation_ids": list(self.evidence_conversation_ids),
            "expected_state": self.expected_state.value,
            "reason": self.reason,
            "review_id": self.review_id,
            "origin": self.origin.value,
        }


@dataclass(frozen=True)
class KnowledgeConflictFixture:
    fixture_id: str
    topic: str
    as_of_date: date
    stale_after_days: int
    policy_versions: tuple[PolicyVersion, ...]
    passages: tuple[ConversationPassage, ...]
    reviews: tuple[ReviewRecord, ...]
    expected_outcomes: tuple[ExpectedOutcome, ...]
    origin: ValueOrigin = ValueOrigin.SYNTHETIC

    def as_dict(self) -> dict[str, object]:
        return {
            "fixture_id": self.fixture_id,
            "topic": self.topic,
            "as_of_date": self.as_of_date.isoformat(),
            "stale_after_days": self.stale_after_days,
            "policy_versions": [value.as_dict() for value in self.policy_versions],
            "passages": [value.as_dict() for value in self.passages],
            "reviews": [value.as_dict() for value in self.reviews],
            "expected_outcomes": [value.as_dict() for value in self.expected_outcomes],
            "origin": self.origin.value,
        }


def build_knowledge_conflict_fixture() -> KnowledgeConflictFixture:
    fixture = KnowledgeConflictFixture(
        fixture_id="demo-delivery-policy-change-v1",
        topic="standard delivery time",
        as_of_date=date(2026, 6, 30),
        stale_after_days=90,
        policy_versions=(
            PolicyVersion("delivery-v1", "5-7 business days", date(2025, 1, 1)),
            PolicyVersion("delivery-v2", "2-3 business days", date(2026, 4, 1)),
            PolicyVersion(
                "economy-delivery-v1", "8-10 business days", date(2025, 1, 1)
            ),
        ),
        passages=(
            ConversationPassage(
                "SYNTH-ECONOMY-001",
                date(2026, 3, 1),
                "agent",
                "Economy delivery takes 8 to 10 business days.",
                "economy-delivery-v1",
            ),
            ConversationPassage(
                "SYNTH-DELIVERY-002",
                date(2026, 4, 8),
                "agent",
                "The updated standard delivery window is 2 to 3 business days.",
                "delivery-v2",
            ),
            ConversationPassage(
                "SYNTH-DELIVERY-003",
                date(2026, 4, 12),
                "system_action",
                "Policy lookup returned standard delivery in 2 to 3 business days.",
                "delivery-v2",
            ),
            ConversationPassage(
                "SYNTH-DELIVERY-004",
                date(2026, 4, 15),
                "agent",
                "Standard delivery still takes 5 to 7 business days.",
                "delivery-v1",
            ),
            ConversationPassage(
                "SYNTH-DELIVERY-005",
                date(2026, 6, 20),
                "customer",
                "I saw two different delivery estimates and need the current policy.",
                None,
            ),
        ),
        reviews=(
            ReviewRecord(
                "review-delivery-v2-approved",
                "new-policy-approved",
                "manager",
                "approved",
                date(2026, 4, 16),
            ),
        ),
        expected_outcomes=(
            ExpectedOutcome(
                "new-policy-awaiting-review",
                ("SYNTH-DELIVERY-002",),
                KnowledgeState.PENDING,
                "A new policy claim has evidence but has not been approved.",
            ),
            ExpectedOutcome(
                "new-policy-approved",
                ("SYNTH-DELIVERY-002", "SYNTH-DELIVERY-003"),
                KnowledgeState.APPROVED,
                "Reviewed supporting passages agree on delivery-v2.",
                review_id="review-delivery-v2-approved",
            ),
            ExpectedOutcome(
                "post-change-conflict",
                ("SYNTH-DELIVERY-002", "SYNTH-DELIVERY-004"),
                KnowledgeState.DISPUTED,
                "Passages after the change support conflicting policy versions.",
            ),
            ExpectedOutcome(
                "economy-policy-stale",
                ("SYNTH-ECONOMY-001",),
                KnowledgeState.STALE,
                "The only economy-delivery passage is older than the 90-day threshold.",
            ),
            ExpectedOutcome(
                "current-policy-unclear",
                ("SYNTH-DELIVERY-005",),
                KnowledgeState.CANNOT_ASSESS,
                "The passage reports ambiguity but supports no policy version.",
            ),
        ),
    )
    validate_fixture(fixture)
    return fixture


_PRIVATE_DETAIL_PATTERNS = (
    re.compile(r"\b[\w.+-]+@[\w.-]+\.\w{2,}\b"),
    re.compile(r"\b(?:\+?1[ .-]?)?(?:\(?\d{3}\)?[ .-]?)\d{3}[ .-]\d{4}\b"),
    re.compile(
        r"\b\d{1,5}\s+[A-Za-z]+(?:\s+[A-Za-z]+)*\s+(?:street|st|road|rd|avenue|ave)\b",
        re.IGNORECASE,
    ),
)


def _strings(value: object) -> Iterable[str]:
    if isinstance(value, str):
        yield value
    elif isinstance(value, Mapping):
        for item in value.values():
            yield from _strings(item)
    elif isinstance(value, Iterable):
        for item in value:
            yield from _strings(item)


def validate_fixture(fixture: KnowledgeConflictFixture) -> None:
    policy_versions = {policy.version for policy in fixture.policy_versions}
    if len(policy_versions) != len(fixture.policy_versions):
        raise ValueError("policy versions must be unique")

    passages_by_id = {passage.conversation_id: passage for passage in fixture.passages}
    if len(passages_by_id) != len(fixture.passages):
        raise ValueError("conversation IDs must be unique")
    if any(
        passage.supports_policy_version not in policy_versions
        for passage in fixture.passages
        if passage.supports_policy_version is not None
    ):
        raise ValueError("passages must reference a known policy version")

    reviews_by_id = {review.review_id: review for review in fixture.reviews}
    if len(reviews_by_id) != len(fixture.reviews):
        raise ValueError("review IDs must be unique")

    expected_states = {outcome.expected_state for outcome in fixture.expected_outcomes}
    if expected_states != set(KnowledgeState):
        raise ValueError("expected outcomes must cover every knowledge state")
    for outcome in fixture.expected_outcomes:
        unknown = set(outcome.evidence_conversation_ids) - passages_by_id.keys()
        if unknown:
            raise ValueError("expected outcomes must reference known conversations")
        if outcome.review_id is not None and outcome.review_id not in reviews_by_id:
            raise ValueError("expected outcomes must reference known reviews")
        if outcome.expected_state is KnowledgeState.APPROVED:
            review = reviews_by_id.get(outcome.review_id)
            if (
                review is None
                or review.case_id != outcome.case_id
                or review.reviewer_role != "manager"
                or review.action != "approved"
            ):
                raise ValueError("approved outcomes require a manager approval review")
        if outcome.expected_state is KnowledgeState.PENDING and outcome.review_id:
            raise ValueError("pending outcomes must not have an approval review")
        if outcome.expected_state is KnowledgeState.STALE:
            supported_versions = {
                passages_by_id[conversation_id].supports_policy_version
                for conversation_id in outcome.evidence_conversation_ids
                if passages_by_id[conversation_id].supports_policy_version is not None
            }
            if len(supported_versions) != 1:
                raise ValueError(
                    "a stale outcome must identify exactly one policy version"
                )
            stale_version = supported_versions.pop()
            latest_support = max(
                passage.occurred_on
                for passage in fixture.passages
                if passage.supports_policy_version == stale_version
            )
            if (fixture.as_of_date - latest_support).days <= fixture.stale_after_days:
                raise ValueError(
                    "stale outcome has support within the configured threshold"
                )

    serialized = fixture.as_dict()
    if any(origin != ValueOrigin.SYNTHETIC.value for origin in _origins(serialized)):
        raise ValueError("every fixture object must be marked synthetic")
    if any(
        pattern.search(text)
        for text in _strings(serialized)
        for pattern in _PRIVATE_DETAIL_PATTERNS
    ):
        raise ValueError("fixture contains a possible real customer detail")


def _origins(value: object) -> Iterable[object]:
    if isinstance(value, Mapping):
        yield value.get("origin")
        for item in value.values():
            if isinstance(item, (Mapping, list, tuple)):
                yield from _origins(item)
    elif isinstance(value, (list, tuple)):
        for item in value:
            yield from _origins(item)


def serialize_fixture(fixture: KnowledgeConflictFixture) -> str:
    validate_fixture(fixture)
    return json.dumps(fixture.as_dict(), indent=2, sort_keys=True) + "\n"
