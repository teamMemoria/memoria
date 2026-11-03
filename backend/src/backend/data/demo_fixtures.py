from __future__ import annotations

import json
import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import date
from enum import StrEnum


class ValueOrigin(StrEnum):
    SYNTHETIC = "synthetic"


class KnowledgeState(StrEnum):
    PENDING = "pending"
    APPROVED = "approved"
    DISPUTED = "disputed"
    STALE = "stale"
    CANNOT_ASSESS = "cannot-assess"


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
class ExpectedOutcome:
    case_id: str
    evidence_conversation_ids: tuple[str, ...]
    expected_state: KnowledgeState
    reason: str
    origin: ValueOrigin = ValueOrigin.SYNTHETIC

    def as_dict(self) -> dict[str, object]:
        return {
            "case_id": self.case_id,
            "evidence_conversation_ids": list(self.evidence_conversation_ids),
            "expected_state": self.expected_state.value,
            "reason": self.reason,
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
        ),
        passages=(
            ConversationPassage(
                "SYNTH-DELIVERY-001",
                date(2025, 12, 15),
                "agent",
                "Standard delivery takes 5 to 7 business days.",
                "delivery-v1",
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
            ),
            ExpectedOutcome(
                "post-change-conflict",
                ("SYNTH-DELIVERY-002", "SYNTH-DELIVERY-004"),
                KnowledgeState.DISPUTED,
                "Passages after the change support conflicting policy versions.",
            ),
            ExpectedOutcome(
                "old-policy-expired",
                ("SYNTH-DELIVERY-001",),
                KnowledgeState.STALE,
                "The last supporting passage is older than the 90-day threshold.",
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

    expected_states = {outcome.expected_state for outcome in fixture.expected_outcomes}
    if expected_states != set(KnowledgeState):
        raise ValueError("expected outcomes must cover every knowledge state")
    for outcome in fixture.expected_outcomes:
        unknown = set(outcome.evidence_conversation_ids) - passages_by_id.keys()
        if unknown:
            raise ValueError("expected outcomes must reference known conversations")

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
