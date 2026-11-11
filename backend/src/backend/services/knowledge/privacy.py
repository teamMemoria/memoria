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
CARD = re.compile(r"(?<!\d)(?:\d{4}[ -]?){3}\d{1,7}(?!\d)")
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
ORDINAL = re.compile(r"^\d+(?:st|nd|rd|th)$", re.IGNORECASE)
UNIT_TOKEN = re.compile(
    r"^\d+(?:am|pm|gb|mb|kg|lbs?|oz|ft|in|cm|mm|hrs?|mins?|days?|x)$", re.IGNORECASE
)


@dataclass
class Redaction:
    text: str
    counts: Counter[str] = field(default_factory=Counter)


def _strings(values: Iterable[Any]) -> list[str]:
    return [v.strip() for v in values if isinstance(v, str) and v.strip()]


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
            ("ACCOUNT_DETAIL", _strings([record.get("account_id")])),
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
        self._name_parts = sorted(
            {part for part in re.split(r"\s+", name.strip()) if len(part) >= 2}
            if isinstance(name, str)
            else set(),
            key=lambda part: -len(part),
        )
        self._full_name = (
            name.strip() if isinstance(name, str) and name.strip() else None
        )
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
        out = self._fuzzy_names(out, counts)
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
        return Redaction(out, counts)

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
            for part in self._name_parts:
                if len(part) < 3 or lowered == part.lower():
                    continue
                limit = 1 if len(part) < 6 else 2
                if _edit_distance(lowered, part.lower(), limit) <= limit:
                    tokens[index] = "[CUSTOMER_NAME]"
                    counts["CUSTOMER_NAME"] += 1
                    previous_word = "CUSTOMER_NAME"
                    break
        return "".join(tokens)

    def leaks(self, text: str) -> list[str]:
        """Labels of record values still present in ``text`` (used by tests and evaluation)."""
        found = []
        lowered = text.lower()
        for label, value in self._literals:
            if label == "CITY":
                continue  # a city name alone is not a leak; it is redacted for tidiness
            if " ".join(value.lower().split()) in " ".join(lowered.split()):
                found.append(label)
        if self._full_name and self._full_name.lower() in lowered:
            found.append("CUSTOMER_NAME")
        if len(self._phone_digits) >= 7 and self._phone_digits[-7:] in _digits(text):
            found.append("PHONE")
        if EMAIL.search(text):
            found.append("EMAIL")
        return sorted(set(found))


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
