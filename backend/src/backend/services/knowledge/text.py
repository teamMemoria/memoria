"""Small, dependency-free text helpers shared by the pipeline stages."""

from __future__ import annotations

import re
from dataclasses import dataclass

_STOPWORD_TEXT = """
    a about above after again all am an and any are as at be because been before being below between both but by
    could did do does doing down during each few for from further had has have having he her here hers herself him
    himself his how i if in into is it its itself just let me more most my myself no nor not now of off on once only
    or other our ours ourselves out over own same she should so some such than that the their theirs them themselves
    then there these they this those through to too under until up very was we were what when where which while who
    whom why will with would you your yours yourself yourselves can may might must shall also okay ok yes yeah oh
    please thanks thank sure well get got go going really like im ive id ill dont cant wont thats theres youre
    customer customers agent agents
    """
STOPWORDS = frozenset(_STOPWORD_TEXT.split())
# Words whose presence changes what a statement means; never dropped as stopwords
# when comparing claims.
NEGATIONS = frozenset(
    {
        "not",
        "no",
        "never",
        "cannot",
        "can't",
        "cant",
        "won't",
        "wont",
        "don't",
        "dont",
        "unable",
        "nothing",
        "none",
        "doesnt",
        "didnt",
        "isnt",
        "arent",
        "wasnt",
        "werent",
        "couldnt",
        "wouldnt",
        "shouldnt",
        "havent",
        "hasnt",
        "aint",
        "nobody",
        "neither",
        "nor",
    }
)
MEMBERSHIP_LEVELS = ("gold", "silver", "bronze", "guest")

_WORD = re.compile(r"\[[A-Z_]+\]|[a-z0-9]+(?:'[a-z]+)?")
_SENTENCE = re.compile(r"(?<=[.!?])\s+(?=[A-Z0-9\[\"'])|\n+")
_NUMBER_UNIT = re.compile(
    r"(?P<currency>\$)\s?(?P<amount>\d+(?:[.,]\d+)?)"
    r"|(?P<value>\d+(?:\.\d+)?)\s*(?P<unit>%|percent|days?|business days?|weeks?|months?|years?|hours?|minutes?|items?|dollars?)\b",
    re.IGNORECASE,
)
_WORD_NUMBERS = {
    "one": "1",
    "two": "2",
    "three": "3",
    "four": "4",
    "five": "5",
    "six": "6",
    "seven": "7",
    "eight": "8",
    "nine": "9",
    "ten": "10",
    "fourteen": "14",
    "thirty": "30",
    "sixty": "60",
    "ninety": "90",
    "a week": "7 days",
}


def normalise(text: str) -> str:
    return " ".join(text.lower().replace("’", "'").split())


def words(text: str) -> list[str]:
    return _WORD.findall(normalise(text))


def stem(word: str) -> str:
    """A deliberately light suffix stripper: "returns" -> "return", "shipped" -> "ship"."""
    if word.startswith("["):
        return word
    for suffix in ("ingly", "edly", "ing", "ed", "es", "s"):
        if word.endswith(suffix) and len(word) - len(suffix) >= 3:
            word = word[: -len(suffix)]
            break
    if len(word) > 3 and word[-1] == word[-2] and word[-1] not in "aeiouls":
        word = word[:-1]
    if len(word) > 4 and word.endswith("e"):
        word = word[:-1]
    return word


# A few domain synonyms, so "promotional code" and "coupon" meet "promo code".
SYNONYMS = {
    "promotional": "promo",
    "coupon": "promo",
    "voucher": "promo",
    "discount": "promo",
    "expire": "valid",
    "expires": "valid",
    "expired": "valid",
    "expiry": "valid",
    "expiration": "valid",
    "last": "valid",
    "lasts": "valid",
    "reimburse": "refund",
    "reimbursement": "refund",
    "money": "refund",
    "purchase": "order",
    "purchases": "order",
    "bought": "order",
    "buy": "order",
    "deliver": "ship",
    "delivery": "ship",
    "delivered": "ship",
    "shipping": "ship",
    "shipped": "ship",
    "cancellation": "cancel",
    "canceled": "cancel",
    "cancelled": "cancel",
    "membership": "member",
    "members": "member",
    "site": "website",
    "web": "website",
}


def content_terms(text: str) -> list[str]:
    """Stemmed content words, keeping negations and membership levels."""
    out = []
    for word in words(text):
        word = SYNONYMS.get(word, word)
        if word.startswith("["):
            continue
        if word in NEGATIONS:
            out.append("not")
        elif word in STOPWORDS or len(word) < 2:
            continue
        else:
            out.append(stem(word))
    return out


def sentences(text: str) -> list[tuple[int, int]]:
    """Character spans of the sentences in ``text`` (exact offsets, nothing rewritten)."""
    spans = []
    start = 0
    for match in _SENTENCE.finditer(text):
        end = match.start()
        if text[start:end].strip():
            spans.append(_trim(text, start, end))
        start = match.end()
    if text[start:].strip():
        spans.append(_trim(text, start, len(text)))
    return spans


def _trim(text: str, start: int, end: int) -> tuple[int, int]:
    while start < end and text[start].isspace():
        start += 1
    while end > start and text[end - 1].isspace():
        end -= 1
    return start, end


@dataclass(frozen=True)
class Quantity:
    value: str
    unit: str

    def __str__(self) -> str:
        return f"{self.value} {self.unit}"


def _unit(raw: str) -> str:
    raw = raw.lower()
    if raw in {"%", "percent"}:
        return "percent"
    if raw.startswith("business day"):
        return "business_days"
    if raw.startswith("dollar"):
        return "usd"
    for base in ("day", "week", "month", "year", "hour", "minute", "item"):
        if raw.startswith(base):
            return base + "s"
    return raw


_UNIT_AHEAD = r"(?=\s+(?:business\s+)?(?:days?|weeks?|months?|years?|hours?|minutes?|items?|dollars?|percent|times)\b)"


def _digits_for_words(lowered: str) -> str:
    """Spell-out numbers become digits only before a unit: "seven days" -> "7 days", "a new one" stays."""
    lowered = re.sub(r"\ba week\b", "7 days", lowered)
    for word, digit in _WORD_NUMBERS.items():
        if " " not in word:
            lowered = re.sub(rf"\b{word}\b{_UNIT_AHEAD}", digit, lowered)
    return lowered


def quantities(text: str) -> list[Quantity]:
    """Numbers with units ("$50", "7 days", "20%", "a week"), normalised to comparable values."""
    lowered = _digits_for_words(normalise(text))
    found = []
    for match in _NUMBER_UNIT.finditer(lowered):
        if match.group("currency"):
            found.append(Quantity(match.group("amount").replace(",", ""), "usd"))
        else:
            value, unit = match.group("value"), _unit(match.group("unit"))
            if unit == "weeks":
                value, unit = str(int(float(value) * 7)), "days"
            found.append(Quantity(value, unit))
    return found


def numbers(text: str) -> set[str]:
    """Every bare number in a text, for "did the model invent a figure?" checks."""
    lowered = _digits_for_words(normalise(text))
    return set(re.findall(r"\d+(?:\.\d+)?", lowered.replace(",", "")))


def is_negated(text: str) -> bool:
    lowered = normalise(text)
    return any(
        re.search(rf"(?<![\w']){re.escape(n)}(?![\w'])", lowered) for n in NEGATIONS
    ) or bool(re.search(r"\bn't\b|\w+n't\b", lowered))


def membership_levels(text: str) -> set[str]:
    lowered = normalise(text)
    found = {
        level for level in MEMBERSHIP_LEVELS if re.search(rf"\b{level}s?\b", lowered)
    }
    if re.search(r"\b(non-?members?|not a member|regular user)\b", lowered):
        found.add("guest")
    return found


def jaccard(a: set[str], b: set[str]) -> float:
    if not a and not b:
        return 1.0
    return len(a & b) / len(a | b)


_NOT_NEGATION = re.compile(
    r"\b(no (problem|worries|trouble|doubt)|not a problem|not to worry|no need to worry|why not|no matter)\b"
)


def negated_terms(text: str, window: int = 4) -> set[str]:
    """Content words a negation applies to: "will not be charged" -> {"charg"}."""
    lowered = _NOT_NEGATION.sub(" ", normalise(text))
    tokens = words(lowered)
    out: set[str] = set()
    for i, token in enumerate(tokens):
        if token in NEGATIONS or token.endswith("n't"):
            for following in tokens[i + 1 : i + 1 + window]:
                term = stem(SYNONYMS.get(following, following))
                if (
                    following not in STOPWORDS
                    and following not in NEGATIONS
                    and len(following) > 1
                ):
                    out.add(term)
    return out


def conditions(text: str) -> set[str]:
    """Explicit conditions only; unfamiliar paraphrases are not assumed equivalent."""
    return {
        normalise(match.group())
        for match in re.finditer(
            r"\b(?:only (?:if|when|with)|if|unless|except(?: for| when| if)?|"
            r"provided(?: that)?|as long as)\b[^,.;!?]*",
            text,
            re.IGNORECASE,
        )
    }
