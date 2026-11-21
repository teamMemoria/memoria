"""Knowledge inferred from a company's own calls (Layer 2).

Layer 1 is the fixed set of generic checks. Layer 2 is learned per company:
when enough calls in one category give the same piece of information, that
information becomes a rule, and later calls are checked against it.

Only facts that carry a value are learned here, such as "promo codes last
7 days" or "gift wrapping costs $4.99". A fact is described by:

* ``category``: the call category it was said in (an ABCD subflow);
* ``levels``: membership levels named next to it, kept apart from each other;
* ``subject``: the words saying what the value is about;
* ``value``: the value itself, normalised ("7 days", "4.99 usd").

The rules here are plain Python with no I/O, so they can be tested and reused
without a database, the API or the text processing that produces the claims.
"""

from __future__ import annotations

import hashlib
import math
from collections import Counter, defaultdict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from typing import Literal

SCHEMA_VERSION = "inferred-knowledge/1"

Verdict = Literal["matches_rule", "differs_from_rule", "no_rule", "several_values"]


class InvalidKnowledgeInput(ValueError):
    """Claims, settings or overrides that cannot be used as given."""


@dataclass(frozen=True)
class InferenceSettings:
    """When information becomes a rule, and when a split goes to a manager.

    ``agreement_share``: share of a topic's calls that must give the same value.
    ``min_calls``: calls a topic needs before anything is decided about it.
    ``conflict_calls``: calls each of two answers needs for the split to count
    as a common conflict that a manager should review.
    ``topic_similarity``: how alike two subjects must be to be the same topic.
    """

    agreement_share: float = 0.7
    min_calls: int = 10
    conflict_calls: int = 5
    topic_similarity: float = 0.3

    def __post_init__(self) -> None:
        if not 0.5 < self.agreement_share <= 1:
            raise InvalidKnowledgeInput(
                "agreement_share must be above 0.5 and at most 1"
            )
        if not 0 < self.topic_similarity <= 1:
            raise InvalidKnowledgeInput(
                "topic_similarity must be above 0 and at most 1"
            )
        for name in ("min_calls", "conflict_calls"):
            if getattr(self, name) < 1:
                raise InvalidKnowledgeInput(f"{name} must be at least 1")


def unit_of(value: str) -> str:
    """The unit part of a normalised value: "7 days" -> "days"."""
    return value.rsplit(" ", 1)[-1]


@dataclass(frozen=True)
class FactClaim:
    """One value an agent stated in one call."""

    company_id: str
    call_id: str
    category: str
    value: str
    subject: frozenset[str]
    levels: frozenset[str] = frozenset()
    quote: str = ""

    def __post_init__(self) -> None:
        for name in ("company_id", "call_id", "category", "value"):
            if not getattr(self, name):
                raise InvalidKnowledgeInput(f"a claim needs a {name}")

    @property
    def scope(self) -> tuple[str, tuple[str, ...], str]:
        """Only claims with the same category, levels and unit can share a topic."""
        return (self.category, tuple(sorted(self.levels)), unit_of(self.value))


@dataclass(frozen=True)
class Answer:
    """One value given for a topic, with the number of calls that gave it."""

    value: str
    calls: int
    example: str


@dataclass(frozen=True)
class Topic:
    """Claims about the same thing in one category, whatever value they give.

    ``answers`` only counts calls that gave one value for the topic. A call that
    gave several (for example a list of prices) is in ``total_calls`` and
    ``unclear_calls`` but votes for none of them.
    """

    topic_id: str
    category: str
    levels: tuple[str, ...]
    unit: str
    terms: tuple[tuple[str, int], ...]
    answers: tuple[Answer, ...]
    total_calls: int
    unclear_calls: int = 0

    @property
    def subject(self) -> tuple[str, ...]:
        """The most common subject words, for showing what the topic is about."""
        return tuple(term for term, _ in self.terms[:6])


@dataclass(frozen=True)
class Rule:
    """A value that calls in a category agree on, or that a manager set."""

    topic: Topic
    value: str
    supporting_calls: int
    source: Literal["inferred", "manager"] = "inferred"
    note: str | None = None

    @property
    def share(self) -> float:
        if not self.topic.total_calls:
            return 0.0
        return round(self.supporting_calls / self.topic.total_calls, 4)


@dataclass(frozen=True)
class Conflict:
    """A topic where calls are split and no value reached the agreement share."""

    topic: Topic


@dataclass(frozen=True)
class Override:
    """A manager's change to one topic: set its value, or remove the rule."""

    topic_id: str
    value: str | None
    changed_by: str
    reason: str

    def __post_init__(self) -> None:
        if not self.topic_id or not self.changed_by:
            raise InvalidKnowledgeInput("an override needs a topic_id and who made it")
        if not self.reason or not self.reason.strip():
            raise InvalidKnowledgeInput("an override needs a reason")
        if self.value is not None and not self.value.strip():
            raise InvalidKnowledgeInput("an override value cannot be empty")


@dataclass(frozen=True)
class KnowledgeBase:
    """Everything learned for one company from the calls seen so far.

    ``removed`` holds the managers' changes that removed a rule, and
    ``unmatched_overrides`` the changes whose topic is not in this version (it
    may come back as more calls arrive).
    """

    company_id: str
    version: int
    calls_with_values: int
    rules: tuple[Rule, ...]
    conflicts: tuple[Conflict, ...]
    undecided: tuple[Topic, ...]
    settings: InferenceSettings = field(default_factory=InferenceSettings)
    removed: tuple[Override, ...] = ()
    unmatched_overrides: tuple[Override, ...] = ()

    def topics(self) -> Iterable[Topic]:
        yield from (rule.topic for rule in self.rules)
        yield from (conflict.topic for conflict in self.conflicts)
        yield from self.undecided

    def topic(self, topic_id: str) -> Topic | None:
        return next((t for t in self.topics() if t.topic_id == topic_id), None)

    def rule_for(self, topic_id: str) -> Rule | None:
        return next((r for r in self.rules if r.topic.topic_id == topic_id), None)


@dataclass(frozen=True)
class CheckedClaim:
    claim: FactClaim
    verdict: Verdict
    rule_value: str | None
    topic_id: str | None


@dataclass(frozen=True)
class CallScore:
    """How the information given in one call compares with the rules."""

    company_id: str
    call_id: str
    knowledge_base_version: int
    checked: tuple[CheckedClaim, ...]

    @property
    def matches(self) -> int:
        return sum(1 for item in self.checked if item.verdict == "matches_rule")

    @property
    def differences(self) -> int:
        return sum(1 for item in self.checked if item.verdict == "differs_from_rule")

    @property
    def score(self) -> float | None:
        """Share of rule-covered values that matched, or ``None`` if none were covered."""
        covered = self.matches + self.differences
        return round(self.matches / covered, 4) if covered else None


# --------------------------------------------------------------------- similarity


def similarity(a: Mapping[str, int], b: Mapping[str, int]) -> float:
    """Cosine similarity of two word-count vectors."""
    dot = sum(count * b.get(term, 0) for term, count in a.items())
    norm = math.sqrt(sum(v * v for v in a.values()) * sum(v * v for v in b.values()))
    return dot / norm if norm else 0.0


def _check_claims(company_id: str, claims: Sequence[FactClaim]) -> None:
    if not company_id:
        raise InvalidKnowledgeInput("a company_id is required")
    for claim in claims:
        if claim.company_id != company_id:
            raise InvalidKnowledgeInput(
                "claims from another company cannot be mixed into this knowledge base"
            )
