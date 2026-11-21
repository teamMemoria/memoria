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


# ---------------------------------------------------------------------- topics


@dataclass
class _Signature:
    """Claims with the same scope, value and subject words, and their calls."""

    value: str
    subject: frozenset[str]
    calls: set[str] = field(default_factory=set)
    examples: set[str] = field(default_factory=set)

    def sort_key(self) -> tuple:
        return (-len(self.calls), self.value, tuple(sorted(self.subject)))


def _signatures(claims: Sequence[FactClaim]) -> dict[tuple, list[_Signature]]:
    by_key: dict[tuple, _Signature] = {}
    for claim in claims:
        key = (claim.scope, claim.value, claim.subject)
        item = by_key.setdefault(key, _Signature(claim.value, claim.subject))
        item.calls.add(claim.call_id)
        item.examples.add(claim.quote)
    by_scope: dict[tuple, list[_Signature]] = defaultdict(list)
    for (scope, _, _), item in by_key.items():
        by_scope[scope].append(item)
    return by_scope


def _cluster(items: list[_Signature], threshold: float) -> list[list[_Signature]]:
    """Join signatures about the same thing.

    Biggest first, each joins the most similar cluster at or above the
    threshold. The visiting order is fixed by the data, so input order never
    changes the result. The same value can end up in several topics.
    """
    clusters: list[tuple[Counter, list[_Signature]]] = []
    for item in sorted(items, key=_Signature.sort_key):
        vector = Counter(dict.fromkeys(item.subject, len(item.calls)))
        best = None
        for index, (terms, _) in enumerate(clusters):
            score = similarity(terms, vector)
            if score >= threshold and (best is None or score > best[0]):
                best = (score, index)
        if best is None:
            clusters.append((vector, [item]))
        else:
            terms, members = clusters[best[1]]
            terms.update(vector)
            members.append(item)
    # Second pass: a short sentence can miss a big cluster it belongs to, so
    # merge whole clusters whose words are similar enough, most similar first.
    while True:
        best = None
        for i in range(len(clusters)):
            for j in range(i + 1, len(clusters)):
                score = similarity(clusters[i][0], clusters[j][0])
                if score >= threshold and (best is None or score > best[0]):
                    best = (score, i, j)
        if best is None:
            break
        _, i, j = best
        clusters[i][0].update(clusters[j][0])
        clusters[i][1].extend(clusters[j][1])
        del clusters[j]
    return [members for _, members in clusters]


def _new_topic_id(scope: tuple, terms: Sequence[tuple[str, int]]) -> str:
    category, levels, unit = scope
    top = ",".join(sorted(term for term, _ in terms[:5]))
    raw = f"{category}|{','.join(levels)}|{unit}|{top}"
    return f"{category}:" + hashlib.sha256(raw.encode()).hexdigest()[:12]


def _topic(scope: tuple, members: list[_Signature], topic_id: str = "") -> Topic:
    terms = Counter()
    values_by_call: dict[str, set[str]] = defaultdict(set)
    examples: dict[str, set[str]] = defaultdict(set)
    for item in members:
        terms.update(dict.fromkeys(item.subject, len(item.calls)))
        examples[item.value] |= item.examples
        for call in item.calls:
            values_by_call[call].add(item.value)
    votes = Counter(next(iter(v)) for v in values_by_call.values() if len(v) == 1)
    answers = tuple(
        Answer(value, count, min(examples[value]))
        for value, count in sorted(votes.items(), key=lambda kv: (-kv[1], kv[0]))
    )
    ordered_terms = tuple(sorted(terms.items(), key=lambda t: (-t[1], t[0])))
    category, levels, unit = scope
    return Topic(
        topic_id=topic_id or _new_topic_id(scope, ordered_terms),
        category=category,
        levels=levels,
        unit=unit,
        terms=ordered_terms,
        answers=answers,
        total_calls=len(values_by_call),
        unclear_calls=sum(1 for v in values_by_call.values() if len(v) > 1),
    )


def _keep_ids(
    topics: list[Topic], previous: KnowledgeBase | None, threshold: float
) -> list[Topic]:
    """Give each topic the id it had in the previous version, if it is the same topic.

    Ids must survive relearning, or managers' changes would be lost the moment
    the majority answer flips. A new topic takes the id of the most similar
    earlier topic in the same scope, one to one.
    """
    old = list(previous.topics()) if previous else []
    pairs = []
    for i, topic in enumerate(topics):
        for j, before in enumerate(old):
            if (topic.category, topic.levels, topic.unit) != (
                before.category,
                before.levels,
                before.unit,
            ):
                continue
            score = similarity(dict(topic.terms), dict(before.terms))
            if score >= threshold:
                pairs.append((-score, topic.topic_id, before.topic_id, i, j))
    renamed: dict[int, str] = {}
    used_old: set[int] = set()
    for _, _, _, i, j in sorted(pairs):
        if i not in renamed and j not in used_old:
            renamed[i] = old[j].topic_id
            used_old.add(j)
    taken = set(renamed.values())
    result = []
    for i, topic in enumerate(topics):
        topic_id = renamed.get(i, topic.topic_id)
        if i not in renamed:
            base, n = topic_id, 2
            while topic_id in taken:
                topic_id, n = f"{base}-{n}", n + 1
        taken.add(topic_id)
        result.append(replace(topic, topic_id=topic_id))
    return result


def find_topics(
    claims: Sequence[FactClaim],
    settings: InferenceSettings,
    previous: KnowledgeBase | None = None,
) -> list[Topic]:
    topics = []
    for scope, items in sorted(_signatures(claims).items()):
        for members in _cluster(items, settings.topic_similarity):
            topics.append(_topic(scope, members))
    return _keep_ids(topics, previous, settings.topic_similarity)


# ---------------------------------------------------------------------- policy


def decide(topic: Topic, settings: InferenceSettings) -> Rule | Conflict | None:
    """The Layer 2 policy for one topic.

    * Fewer than ``min_calls`` calls: nothing is decided yet.
    * One value given in at least ``agreement_share`` of the calls: a rule.
    * Otherwise, two or more values each given in ``conflict_calls`` calls or
      more: a common conflict, for a manager to review.
    * Otherwise nothing is decided yet.
    """
    if topic.total_calls < settings.min_calls or not topic.answers:
        return None
    answers = sorted(topic.answers, key=lambda a: (-a.calls, a.value))
    top = answers[0]
    if top.calls / topic.total_calls >= settings.agreement_share:
        return Rule(topic, top.value, top.calls)
    if sum(1 for a in answers if a.calls >= settings.conflict_calls) >= 2:
        return Conflict(topic)
    return None


def build_knowledge_base(
    company_id: str,
    claims: Sequence[FactClaim],
    settings: InferenceSettings | None = None,
    previous: KnowledgeBase | None = None,
) -> KnowledgeBase:
    """Learn rules and conflicts for one company from all of its claims.

    Pass the previous version so topics keep their ids; the version number
    then goes up by one.
    """
    settings = settings or InferenceSettings()
    claims = list(claims)
    _check_claims(company_id, claims)
    if previous is not None and previous.company_id != company_id:
        raise InvalidKnowledgeInput(
            "the previous knowledge base belongs to another company"
        )
    rules, conflicts, undecided = [], [], []
    for topic in find_topics(claims, settings, previous):
        outcome = decide(topic, settings)
        if isinstance(outcome, Rule):
            rules.append(outcome)
        elif isinstance(outcome, Conflict):
            conflicts.append(outcome)
        else:
            undecided.append(topic)
    return KnowledgeBase(
        company_id=company_id,
        version=previous.version + 1 if previous else 1,
        calls_with_values=len({c.call_id for c in claims}),
        rules=tuple(rules),
        conflicts=tuple(conflicts),
        undecided=tuple(undecided),
        settings=settings,
    )
