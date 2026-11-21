"""Mask customer-specific details in transcripts before knowledge extraction.

Two passes:

1. Known details: values from the conversation's `customer_record` (name,
   username, email, phone, address, order ID, ...) are replaced wherever they
   appear, in any case and, for phone numbers, with any separators.
2. Patterns: emails, phone numbers, street addresses, money amounts (written
   or spoken), long digit runs and spoken digit sequences are replaced even
   when they aren't in the record.

Durations and counts that make up general answers ("5 to 7 business days",
"within 24 hours") contain no currency and no long digit runs, so they are
left alone.
"""

import re
from collections.abc import Iterable
from typing import Any

NAME = "[NAME]"
USERNAME = "[USERNAME]"
EMAIL = "[EMAIL]"
PHONE = "[PHONE]"
ADDRESS = "[ADDRESS]"
AMOUNT = "[AMOUNT]"
NUMBER = "[NUMBER]"
ID = "[ID]"

# customer_record keys that identify a customer, and what to replace them with.
# Anything else (member level, account type, products, ...) is not identifying.
RECORD_FIELDS = {
    "customer_name": NAME,
    "username": USERNAME,
    "email": EMAIL,
    "phone": PHONE,
    "street": ADDRESS,
    "full_address": ADDRESS,
    "city": ADDRESS,
    "zip_code": ADDRESS,
    "order_id": ID,
    "company name": NAME,
    "company address": ADDRESS,
}

DIGIT_WORDS = r"(?:zero|oh|one|two|three|four|five|six|seven|eight|nine)"
SPOKEN_NUMBER = (
    r"(?:zero|one|two|three|four|five|six|seven|eight|nine|ten|eleven|"
    r"twelve|thirteen|fourteen|fifteen|sixteen|seventeen|eighteen|nineteen|"
    r"twenty|thirty|forty|fifty|sixty|seventy|eighty|ninety|hundred|thousand|"
    r"million)"
)
NUMBER_WORDS = rf"(?:a|and|{SPOKEN_NUMBER}|\d[\d,]*(?:\.\d+)?)"
STREET_SUFFIX = (
    r"(?:st|street|ave|avenue|dr|drive|rd|road|ln|lane|blvd|boulevard|way|"
    r"ct|court|pl|place|cir|circle|pkwy|parkway|ter|terrace|hwy|highway)"
)

PATTERNS: list[tuple[re.Pattern[str], str]] = [
    # Also catches typos like "name@emailcom".
    (re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)*"), EMAIL),
    (re.compile(r"(?<!\d)\(?\d{3}\)?[\s.-]?\d{3}[\s.-]?\d{4}(?!\d)"), PHONE),
    (
        re.compile(
            rf"\b\d{{1,6}}\s+(?:[a-z]+\s+){{0,3}}{STREET_SUFFIX}\b\.?", re.IGNORECASE
        ),
        ADDRESS,
    ),
    # Spoken house numbers ("ninety nine river road"). At least one word must
    # sit between the number and the suffix, so "one way" is left alone.
    (
        re.compile(
            rf"\b(?:{SPOKEN_NUMBER}[\s-]+)+(?:[a-z]+\s+){{1,3}}{STREET_SUFFIX}\b",
            re.IGNORECASE,
        ),
        ADDRESS,
    ),
    (re.compile(r"\$\s?\d[\d,]*(?:\.\d+)?"), AMOUNT),
    (
        re.compile(
            rf"\b(?:{NUMBER_WORDS}[\s-]+)+(?:dollars?|bucks)"
            rf"(?:\s+and\s+(?:{NUMBER_WORDS}[\s-]+)+cents?)?\b",
            re.IGNORECASE,
        ),
        AMOUNT,
    ),
    (
        re.compile(rf"\b(?:{DIGIT_WORDS}[\s-]+){{3,}}{DIGIT_WORDS}\b", re.IGNORECASE),
        NUMBER,
    ),
    (re.compile(r"\b\d{5,}\b"), NUMBER),
    # Account IDs like "KEMFGSWSOV".
    (re.compile(r"\b[A-Z0-9]{10}\b"), ID),
]

# Words that can follow "my name is X" without being part of the name.
NOT_NAMES = {
    "and", "i", "im", "how", "the", "from", "with", "calling", "here", "on",
    "uh", "um", "what", "can", "is", "thank", "thanks", "but", "so", "yes",
}  # fmt: skip
INTRODUCTION = re.compile(
    r"\b(my name is|name's|name is)\s+(\w+)(?:\s+(\w+))?", re.IGNORECASE
)
USERNAME_MENTION = re.compile(r"\b(username(?:\s+is|:)\s+)([\w.-]*\w)", re.IGNORECASE)


def _record_values(record: Any, key: str | None = None) -> Iterable[tuple[str, str]]:
    if isinstance(record, dict):
        for k, v in record.items():
            yield from _record_values(v, k)
    elif isinstance(record, list):
        for v in record:
            yield from _record_values(v, key)
    elif key in RECORD_FIELDS and record not in (None, ""):
        yield str(record), RECORD_FIELDS[key]


def known_details(customer_record: dict[str, Any] | None) -> list[tuple[str, str]]:
    """Identifying values in a customer record, with their replacement."""
    details: set[tuple[str, str]] = set()
    for value, label in _record_values(customer_record or {}):
        value = value.strip()
        details.add((value, label))
        if label == NAME:
            details.update((part, NAME) for part in value.split() if len(part) > 1)
        if label == ADDRESS and "," in value:
            # Only the street and zip parts. Towns and states in a written
            # address (e.g. "Harper Valley, Ca") are also general terms.
            parts = (p.strip() for p in value.split(","))
            details.update((p, ADDRESS) for p in parts if re.search(r"\d", p))
    return sorted(details, key=lambda d: -len(d[0]))


def _detail_pattern(value: str, label: str) -> re.Pattern[str]:
    if label == PHONE:
        digits = re.sub(r"\D", "", value)
        # Match the digits with any separators, e.g. "(810) 186-0026" or "810 186 0026".
        return re.compile(r"(?<!\d)" + r"[\s().-]*".join(digits) + r"(?!\d)")
    words = (re.escape(w) for w in value.split())
    return re.compile(r"(?<!\w)" + r"[\s,]+".join(words) + r"(?!\w)", re.IGNORECASE)


def _mask_introductions(text: str) -> str:
    def replace(m: re.Match[str]) -> str:
        if m[2].lower() in NOT_NAMES:
            return m[0]
        if m[3] and m[3].lower() not in NOT_NAMES:
            return f"{m[1]} {NAME}"
        return f"{m[1]} {NAME}" + (f" {m[3]}" if m[3] else "")

    return INTRODUCTION.sub(replace, text)


def mask_text(text: str, customer_record: dict[str, Any] | None = None) -> str:
    """Return `text` with customer-specific details replaced by placeholders."""
    for value, label in known_details(customer_record):
        text = _detail_pattern(value, label).sub(label, text)
    for pattern, label in PATTERNS:
        text = pattern.sub(label, text)
    text = USERNAME_MENTION.sub(rf"\g<1>{USERNAME}", text)
    return _mask_introductions(text)


def mask_transcript(
    texts: Iterable[str], customer_record: dict[str, Any] | None = None
) -> list[str]:
    """Mask every turn of one conversation using its customer record."""
    return [mask_text(t, customer_record) for t in texts]
