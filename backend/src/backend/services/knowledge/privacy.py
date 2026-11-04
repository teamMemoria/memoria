"""Remove personal and account details from conversation text.

Values are replaced by typed placeholders such as ``[CUSTOMER_NAME]`` so the
sentence keeps its meaning ("I can only issue a new code to [CUSTOMER_NAME]
if ...") and nothing is invented in their place. Membership levels, prices,
time limits and policy wording are kept: they carry the reusable meaning.

Two sources of personal data are used:

* the conversation's own customer record (name, username, email, phone,
  address, order id, purchase date), matched wherever it appears;
* patterns for details the record does not list (other emails and phone
  numbers, long digit runs, account-style codes that mix letters and digits).
"""

from __future__ import annotations

import re
import unicodedata
from collections import Counter
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from typing import Any

PLACEHOLDER = re.compile(r"\[[A-Z_]+\]")

EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
PHONE = re.compile(
    r"(?<!\w)(?:\+?1[\s.-]?)?(?:\(\d{3}\)|\d{3})[\s.-]?\d{3}[\s.-]?\d{4}(?!\w)"
)
LONG_NUMBER = re.compile(r"(?<![\w$.])\d{5,}(?![\w%]|\.\d)")
CARD = re.compile(r"(?<![\w])(?:\d{4}[ -]?){3}\d{1,7}(?![\w])")
NUMERIC_DATE = re.compile(
    r"(?<![\d/])\d{1,2}[/-]\d{1,2}[/-]\d{2,4}(?![\d/])|\b\d{4}-\d{2}-\d{2}\b"
)
KEYED_NUMBER = re.compile(
    r"(?i:\b(?:account(?: id| number)?|id|pin|zip(?: code)?|order(?: id| number)?|member(?:ship)? (?:id|number))\b"
    r"(?:\s+(?:is|was))?[\s:#]*)(\d{3,})\b"
)
STREET = re.compile(
    r"\b\d{1,6}\s+(?:[A-Za-z0-9]+\s+){0,3}?"
    r"(?i:ave(?:nue)?|st(?:reet)?|dr(?:ive)?|rd|road|blvd|boulevard|lane|ln|way|ct|court|circle|pl(?:ace)?|terrace|pkwy|parkway)\b\.?"
)
# Account IDs, generated usernames, promo codes, passwords: one token mixing
# letters and digits, at least five characters long ("6VYT5V2JK6", "jbanter1").
MIXED_CODE = re.compile(
    r"(?<![\w$\[])(?=[A-Za-z0-9]*\d)(?=[A-Za-z0-9]*[A-Za-z])[A-Za-z0-9]{5,}(?![\w\]])"
)
# Short all-caps codes the agent hands out ("PX1CE", "ZHYTQ") after "code".
SHARED_CODE = re.compile(
    r"(?i:\b(?:code|promo ?code|here you are|here it is)\b[\s:,-]*(?:is\s+)?)\b([A-Z0-9]{5,8})\b"
)
# A bare all-caps code on its own ("ZHYTQ You can use that ..."), unless the
# whole text is shouted.
CAPS_CODE = re.compile(r"(?<![\w\[])[A-Z][A-Z0-9]{4,7}(?![\w\]])")
# A bare 3-4 digit number ("change this to 7873", "the card ending in 4821") is
# most often part of an address or an account. Prices, percentages, years and
# numbers with a unit ("100 days", "250 points") keep their meaning and stay.
SHORT_NUMBER = re.compile(
    r"(?<![\w$£€.,:/#-])(?!(?:19|20)\d\d\b)\d{3,4}(?![\w%]|[.,:/-]\d|\s*(?:%|percent\b|dollars?\b"
    r"|cents?\b|days?\b|hours?\b|hrs?\b|minutes?\b|mins?\b|seconds?\b|weeks?\b|months?\b|years?\b"
    r"|points?\b|items?\b|pieces?\b|units?\b|times?\b|miles?\b|km\b|kg\b|lbs?\b|gb\b|mb\b))",
    re.IGNORECASE,
)
# Words that, said right before a capitalised word, make it a form of address.
_GREETING = r"(?:hi|hello|hey|thanks|thank you|dear|bye|goodbye|sorry|welcome|morning|afternoon|evening)"
ORDINAL = re.compile(r"^\d+(?:st|nd|rd|th)$", re.IGNORECASE)
UNIT_TOKEN = re.compile(
    r"^\d+(?:am|pm|gb|mb|kg|lbs?|oz|ft|in|cm|mm|hrs?|mins?|days?|x)$", re.IGNORECASE
)


@dataclass
class Redaction:
    text: str
    counts: Counter[str] = field(default_factory=Counter)


# Words a name part must never replace: removing them would change what a
# sentence means ("Gold members ..." for a customer named Gould).
_PROTECTED_TEXT = """
    gold silver bronze guest guests member members membership can cannot code codes card order orders
    refund refunds return returns ship shipping item items day days week weeks month months year years
    promo price account help need will would could should may might must new old free fee fees bill
    """
PROTECTED_WORDS = frozenset(_PROTECTED_TEXT.split())


def nfc(text: str) -> str:
    return unicodedata.normalize("NFC", text)


def _strings(values: Iterable[Any]) -> list[str]:
    return [nfc(v.strip()) for v in values if isinstance(v, str) and v.strip()]


def _digits(value: str) -> str:
    return re.sub(r"\D", "", value)


class Redactor:
    """Redacts one conversation's personal details. Deterministic and idempotent."""

    def __init__(self, customer_record: Mapping[str, Any] | None = None) -> None:
        record = dict(customer_record or {})
        address = (
            record.get("address") if isinstance(record.get("address"), Mapping) else {}
        )
        order = record.get("order") if isinstance(record.get("order"), Mapping) else {}
        self._literals: list[tuple[str, str]] = []
        for label, values in (
            ("EMAIL", _strings([record.get("email")])),
            ("ADDRESS", _strings([address.get("full_address"), address.get("street")])),
            ("USERNAME", _strings([record.get("username")])),
            ("ORDER_ID", _strings([order.get("order_id")])),
            ("PURCHASE_DATE", _strings([order.get("purchase_date")])),
            ("ZIP_CODE", _strings([address.get("zip_code")])),
            ("CITY", _strings([address.get("city")])),
        ):
            for value in values:
                self._literals.append((label, value))
        # Longest first so "4146 circle drive  raleigh, tx" wins over "raleigh".
        self._literals.sort(key=lambda item: -len(item[1]))
        name = record.get("customer_name")
        name = nfc(name) if isinstance(name, str) else None
        parts = (
            {p for p in re.split(r"\s+", name.strip()) if len(p) >= 2}
            if name
            else set()
        )
        self._name_parts = sorted(
            {p for p in parts if p.lower() not in PROTECTED_WORDS},
            key=lambda part: -len(part),
        )
        # A name that is also an ordinary word ("Will", "May", "Bill") is only
        # replaced where it is used as a name: capitalised and addressed
        # ("Will, ...", "Thanks Will"), or next to another part of the name.
        self._protected_parts = sorted(
            {p for p in parts if p.lower() in PROTECTED_WORDS},
            key=lambda part: -len(part),
        )
        self._full_name = name.strip() if name and name.strip() else None
        phone = record.get("phone")
        self._phone_digits = _digits(phone) if isinstance(phone, str) else ""

    def _sub(
        self, pattern: re.Pattern[str], label: str, text: str, counts: Counter[str]
    ) -> str:
        def repl(match: re.Match[str]) -> str:
            counts[label] += 1
            return f"[{label}]"

        return pattern.sub(repl, text)

    def redact(self, text: str) -> Redaction:
        counts: Counter[str] = Counter()
        text = nfc(text)
        out = text
        out = self._sub(EMAIL, "EMAIL", out, counts)
        out = self._sub(CARD, "CARD_NUMBER", out, counts)
        for label, value in self._literals:
            # Collapse runs of whitespace in the value so "drive  raleigh" matches.
            parts = [re.escape(p) for p in value.split()]
            pattern = re.compile(
                r"(?<![\w])" + r"\s+".join(parts) + r"(?![\w])", re.IGNORECASE
            )
            out = self._sub(pattern, label, out, counts)
        if self._full_name:
            parts = [re.escape(p) for p in self._full_name.split()]
            out = self._sub(
                re.compile(r"\b" + r"\s+".join(parts) + r"\b", re.IGNORECASE),
                "CUSTOMER_NAME",
                out,
                counts,
            )
        for part in self._name_parts:
            out = self._sub(
                re.compile(rf"\b{re.escape(part)}\b", re.IGNORECASE),
                "CUSTOMER_NAME",
                out,
                counts,
            )
        for part in self._protected_parts:
            out = self._redact_addressed(part, out, counts)
        out = self._fuzzy_names(out, counts)
        out = self._addressed_names(out, counts)
        out = self._sub(PHONE, "PHONE", out, counts)
        out = self._sub(STREET, "ADDRESS", out, counts)
        out = self._sub(NUMERIC_DATE, "DATE", out, counts)

        def keyed_repl(match: re.Match[str]) -> str:
            counts["ACCOUNT_DETAIL"] += 1
            return (
                match.group(0)[: match.start(1) - match.start(0)] + "[ACCOUNT_DETAIL]"
            )

        out = KEYED_NUMBER.sub(keyed_repl, out)
        if len(self._phone_digits) >= 7:
            # The record's phone written with other separators ("319.151.0701").
            spaced = r"\D{0,3}".join(re.escape(d) for d in self._phone_digits[-10:])
            out = self._sub(re.compile(spaced), "PHONE", out, counts)

        def code_repl(match: re.Match[str]) -> str:
            counts["CODE"] += 1
            return match.group(0)[: match.start(1) - match.start(0)] + "[CODE]"

        out = SHARED_CODE.sub(code_repl, out)
        letters = [c for c in text if c.isalpha()]
        if letters and sum(c.isupper() for c in letters) / len(letters) < 0.6:
            out = self._sub(CAPS_CODE, "CODE", out, counts)

        def mixed_repl(match: re.Match[str]) -> str:
            token = match.group(0)
            if ORDINAL.match(token) or UNIT_TOKEN.match(token):
                return token
            counts["ACCOUNT_DETAIL"] += 1
            return "[ACCOUNT_DETAIL]"

        out = MIXED_CODE.sub(mixed_repl, out)
        out = self._sub(LONG_NUMBER, "NUMBER", out, counts)
        out = self._sub(SHORT_NUMBER, "NUMBER", out, counts)
        return Redaction(out, counts)

    @staticmethod
    def _address_pattern(part: str) -> re.Pattern[str]:
        """``part`` used as a name: capitalised, and addressed or set off by punctuation.

        The name itself is the ``name`` group; the rest of the match is context.
        """
        word = re.escape(part[0].upper() + part[1:].lower())
        return re.compile(
            rf"(?i:\b{_GREETING})[ ,]+(?P<name>{word})\b"
            rf"|(?:^|(?<=[.!?] ))(?P<lead>{word})(?=,)"
            rf"|(?<=\[CUSTOMER_NAME\] )(?P<after>{word})\b"
            rf"|\b(?P<before>{word})(?= \[CUSTOMER_NAME\])"
            rf"|(?<=[a-z,] )(?P<tail>{word})(?=[,.!?]|$)"
        )

    def _redact_addressed(self, part: str, text: str, counts: Counter[str]) -> str:
        def repl(match: re.Match[str]) -> str:
            group = next(
                g for g in ("name", "lead", "after", "before", "tail") if match.group(g)
            )
            counts["CUSTOMER_NAME"] += 1
            start, end = (
                match.start(group) - match.start(0),
                match.end(group) - match.start(0),
            )
            whole = match.group(0)
            return whole[:start] + "[CUSTOMER_NAME]" + whole[end:]

        return self._address_pattern(part).sub(repl, text)

    def _addressed_names(self, text: str, counts: Counter[str]) -> str:
        """A short form of the customer's name used to address them ("Thanks Joe")."""
        parts = [p.lower() for p in (*self._name_parts, *self._protected_parts)]
        if not parts:
            return text

        def repl(match: re.Match[str]) -> str:
            word = match.group("word")
            lowered = word.lower()
            if lowered in _COMMON_WORDS or lowered in PROTECTED_WORDS:
                return match.group(0)
            # A short form: same opening letters, no longer than the name.
            if any(
                len(part) >= 4
                and lowered != part
                and lowered[:2] == part[:2]
                and len(lowered) <= len(part)
                for part in parts
            ):
                counts["CUSTOMER_NAME"] += 1
                return match.group(0)[: match.start("word") - match.start(0)] + (
                    "[CUSTOMER_NAME]"
                )
            return match.group(0)

        text = re.sub(
            rf"(?i:\b{_GREETING}),?\s+(?:(?i:it'?s|this is|i'?m|i am)\s+)?(?P<word>[A-Z][a-z]{{2,}})\b",
            repl,
            text,
        )
        # Opening a sentence and set off by a comma: "Joe, promo codes ...".
        return re.sub(r"(?:^|(?<=[.!?] ))(?P<word>[A-Z][a-z]{2,})(?=,)", repl, text)

    def _fuzzy_names(self, text: str, counts: Counter[str]) -> str:
        """Catch misspelled name parts ("Zhange" for "Zhang", "Ming" for "Minh").

        Only capitalised words, or words right after a name placeholder, are
        considered, so ordinary words that happen to be close ("mine") stay.
        """
        if not self._name_parts:
            return text
        tokens = re.split(r"(\W+)", text)
        previous_word = ""
        for index, token in enumerate(tokens):
            if not token or not token[0].isalpha():
                continue
            candidate = token[0].isupper() or previous_word.endswith("CUSTOMER_NAME")
            previous_word = token
            if not candidate or len(token) < 3:
                continue
            lowered = token.lower()
            if lowered in PROTECTED_WORDS or lowered in _COMMON_WORDS:
                continue
            for part in self._name_parts:
                if len(part) < 4 or lowered == part.lower():
                    continue
                limit = 1 if len(part) < 6 else 2
                if _edit_distance(lowered, part.lower(), limit) <= limit:
                    tokens[index] = "[CUSTOMER_NAME]"
                    counts["CUSTOMER_NAME"] += 1
                    previous_word = "CUSTOMER_NAME"
                    break
        return "".join(tokens)

    def leaks(self, text: str) -> list[str]:
        """Labels of this record's values still present in ``text``, matched as whole words.

        Used by the release check and the tests. Checks every record value the
        redactor knows (name, each name part, email, username, address, city,
        zip, order id, purchase date, phone) plus any email or card number.
        """
        found = []
        flat = " ".join(nfc(text).lower().split())

        def present(value: str) -> bool:
            value = " ".join(value.lower().split())
            return bool(re.search(r"(?<![\w])" + re.escape(value) + r"(?![\w])", flat))

        for label, value in self._literals:
            if present(value):
                found.append(label)
        if self._full_name and present(self._full_name):
            found.append("CUSTOMER_NAME")
        if any(len(part) >= 3 and present(part) for part in self._name_parts):
            found.append("CUSTOMER_NAME")
        if any(
            self._address_pattern(part).search(text) for part in self._protected_parts
        ):
            found.append("CUSTOMER_NAME")
        if len(self._phone_digits) >= 7:
            # The number written with up to three separators between digits,
            # never digits gathered from unrelated places in the text.
            spaced = r"\D{0,3}".join(re.escape(d) for d in self._phone_digits[-7:])
            if re.search(spaced, text):
                found.append("PHONE")
        if EMAIL.search(text):
            found.append("EMAIL")
        if CARD.search(text):
            found.append("CARD_NUMBER")
        return sorted(set(found))


_COMMON_TEXT = """
    the and but for not you your yes can could would should will shall may might must have has had was were
    are been being this that these those then than them they their there here what when where which who why
    how all any each few more most other some such only own same very just also into onto over under again
    hello thanks thank please sorry okay sure great good fine nice well done mine hers his him she her
    """
_COMMON_WORDS = frozenset(_COMMON_TEXT.split())


def _edit_distance(a: str, b: str, limit: int) -> int:
    if abs(len(a) - len(b)) > limit:
        return limit + 1
    previous = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        current = [i]
        for j, cb in enumerate(b, 1):
            current.append(
                min(previous[j] + 1, current[j - 1] + 1, previous[j - 1] + (ca != cb))
            )
        previous = current
    return previous[-1]


def placeholder_share(text: str) -> float:
    """Fraction of a text's words that are placeholders, for "nothing reusable here" checks."""
    words = text.split()
    if not words:
        return 1.0
    return sum(1 for w in words if PLACEHOLDER.search(w)) / len(words)


# Patterns for personal details whatever the customer record says. The release
# check runs these on its own, so a missing or wrong record cannot hide a leak.
_LEAK_PATTERNS = {
    "EMAIL": EMAIL,
    "CARD_NUMBER": CARD,
    "PHONE": PHONE,
    "ADDRESS": STREET,
    "NUMBER": LONG_NUMBER,
}


def pattern_leaks(text: str) -> list[str]:
    """Labels of personal-detail patterns found in ``text``, with no record needed."""
    text = PLACEHOLDER.sub(" ", nfc(text))
    return sorted(
        label for label, pattern in _LEAK_PATTERNS.items() if pattern.search(text)
    )
