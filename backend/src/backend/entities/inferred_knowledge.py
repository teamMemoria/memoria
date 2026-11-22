"""Layer 2: rules a company gets from its own calls.

Layer 1 is our fixed set of generic checks. Layer 2 learns facts with a value
("promo codes last 7 days") from the calls themselves: when 70% of the calls
about something give the same value, it becomes a rule, and later calls are
checked against it.
"""

from collections import Counter, defaultdict
from dataclasses import dataclass
from math import sqrt


@dataclass(frozen=True)
class Settings:
    agreement: float = 0.7  # share of a topic's calls that must agree for a rule
    min_calls: int = 10  # calls a topic needs before anything is decided
    conflict_calls: int = 5  # calls each of two answers needs to be a conflict
    similarity: float = 0.3  # how alike two subjects must be to be one topic


DEFAULT = Settings()


@dataclass(frozen=True)
class Claim:
    """One value an agent gave in one call.

    ``scope`` is (category, membership levels, unit): only claims with the same
    scope can be about the same thing. ``subject`` is the words saying what the
    value is about.
    """

    call_id: str
    scope: tuple[str, tuple[str, ...], str]
    value: str
    subject: frozenset[str]
    quote: str = ""


@dataclass
class Topic:
    scope: tuple[str, tuple[str, ...], str]
    words: Counter
    values_by_call: dict[str, set[str]]
    example: dict[str, str]

    def votes(self) -> list[tuple[str, int]]:
        """Calls per value, most first. A call that gave several values doesn't vote."""
        counts = Counter(
            next(iter(v)) for v in self.values_by_call.values() if len(v) == 1
        )
        return sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))

    def decide(self, s: Settings) -> str:
        """``rule``, ``conflict`` (for a manager) or ``undecided``."""
        votes, calls = self.votes(), len(self.values_by_call)
        if calls < s.min_calls or not votes:
            return "undecided"
        if votes[0][1] / calls >= s.agreement:
            return "rule"
        return (
            "conflict"
            if sum(n >= s.conflict_calls for _, n in votes) >= 2
            else "undecided"
        )

    @property
    def rule(self) -> str:
        return self.votes()[0][0]


def similarity(a: Counter, b: Counter) -> float:
    dot = sum(n * b[w] for w, n in a.items())
    norm = sqrt(sum(n * n for n in a.values()) * sum(n * n for n in b.values()))
    return dot / norm if norm else 0.0


def learn(claims: list[Claim], s: Settings = DEFAULT) -> list[Topic]:
    """Group claims into topics.

    Claims with the same scope, value and subject are grouped first. Biggest
    group first, each joins the most similar topic in its scope, then similar
    topics merge. The order comes from the data, never from the input order.
    """
    groups: dict[tuple, set[str]] = defaultdict(set)
    examples: dict[tuple, str] = {}
    for c in claims:
        groups[c.scope, c.value, c.subject].add(c.call_id)
        key = (c.scope, c.value, c.subject)
        examples[key] = min(examples.get(key, c.quote), c.quote)

    topics: list[Topic] = []
    for (scope, value, subject), calls in sorted(
        groups.items(), key=lambda g: (-len(g[1]), g[0][0], g[0][1], sorted(g[0][2]))
    ):
        words = Counter(dict.fromkeys(subject, len(calls)))
        same_scope = [t for t in topics if t.scope == scope]
        best = max(same_scope, key=lambda t: similarity(t.words, words), default=None)
        if best is None or similarity(best.words, words) < s.similarity:
            best = Topic(scope, Counter(), defaultdict(set), {})
            topics.append(best)
        best.words.update(words)
        best.example.setdefault(value, examples[scope, value, subject])
        for call in calls:
            best.values_by_call[call].add(value)

    merged = True
    while merged:
        merged = False
        for a in topics:
            for b in topics:
                if (
                    a is not b
                    and a.scope == b.scope
                    and similarity(a.words, b.words) >= s.similarity
                ):
                    a.words.update(b.words)
                    a.example = {**b.example, **a.example}
                    for call, values in b.values_by_call.items():
                        a.values_by_call[call] |= values
                    topics.remove(b)
                    merged = True
                    break
            if merged:
                break
    return topics


def topic_of(claim: Claim, topics: list[Topic], s: Settings = DEFAULT) -> Topic | None:
    """The most similar topic in the claim's scope, if it's similar enough."""
    words = Counter(claim.subject)
    candidates = [t for t in topics if t.scope == claim.scope]
    best = max(candidates, key=lambda t: similarity(t.words, words), default=None)
    return best if best and similarity(best.words, words) >= s.similarity else None


def score_call(claims: list[Claim], topics: list[Topic], s: Settings = DEFAULT) -> dict:
    """Count how many values in one call match or differ from a rule.

    A repeated value counts once. Several values for one rule are not scored.
    """
    said: dict[int, set[str]] = defaultdict(set)
    rules: dict[int, Topic] = {}
    for c in claims:
        topic = topic_of(c, topics, s)
        if topic and topic.decide(s) == "rule":
            said[id(topic)].add(c.value)
            rules[id(topic)] = topic
    matches = sum(v == {rules[k].rule} for k, v in said.items())
    differs = sum(len(v) == 1 and v != {rules[k].rule} for k, v in said.items())
    covered = matches + differs
    return {
        "matches": matches,
        "differs": differs,
        "score": matches / covered if covered else None,
    }
