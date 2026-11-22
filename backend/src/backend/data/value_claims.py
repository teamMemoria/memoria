"""Read the values agents state in ABCD calls, for Layer 2.

Only agent speech is used. ABCD's recorded actions ("[Pull up Account]") are
skipped: they mirror the guidelines, so learning from them would be reading
the answer key. Each value is read from the original sentence, and the
sentence is kept with customer details masked.
"""

import re

from backend.data.masking import mask_text
from backend.entities.inferred_knowledge import Claim

LEVELS = ("guest", "bronze", "silver", "gold")
NUMBERS = {
    "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6,
    "seven": 7, "eight": 8, "nine": 9, "ten": 10, "twelve": 12, "fourteen": 14,
    "fifteen": 15, "twenty": 20, "thirty": 30, "sixty": 60, "ninety": 90,
}  # fmt: skip
UNITS = {"business day": ("business days", 1), "week": ("days", 7), "day": ("days", 1),
         "month": ("months", 1), "year": ("years", 1), "hour": ("hours", 1), "minute": ("minutes", 1)}  # fmt: skip
NUMBER = r"(\d+(?:\.\d+)?|" + "|".join(NUMBERS) + r")"
MONEY = re.compile(r"\$\s?(\d[\d,]*(?:\.\d+)?)")
PERCENT = re.compile(r"(\d+(?:\.\d+)?)\s?(?:%|percent)")
DURATION = re.compile(rf"\b{NUMBER}[\s-]+({'|'.join(UNITS)})s?\b", re.IGNORECASE)
STOPWORDS = {
    "the", "and", "for", "you", "your", "our", "are", "can", "will", "that", "this", "with",
    "have", "has", "was", "were", "not", "but", "all", "any", "its", "from", "they", "them",
    "their", "then", "than", "there", "what", "when", "which", "who", "how", "about", "just",
    "also", "may", "would", "could", "should", "been", "being", "into", "out", "over",
    "please", "thank", "thanks", "sure", "okay", "let", "get", "need", "see", "like", "know",
    "one", "per",
}  # fmt: skip


def _number(text: str) -> str:
    n = float(NUMBERS.get(text.lower(), 0) or text.replace(",", ""))
    return f"{n:g}"


def values(sentence: str) -> list[str]:
    """ "$4.99" -> "4.99 usd", "one week" -> "7 days", "20%" -> "20 percent"."""
    found = [f"{_number(m[1])} usd" for m in MONEY.finditer(sentence)]
    found += [f"{_number(m[1])} percent" for m in PERCENT.finditer(sentence)]
    for m in DURATION.finditer(sentence):
        unit, times = UNITS[m[2].lower()]
        found.append(f"{float(_number(m[1])) * times:g} {unit}")
    return found


def stem(word: str) -> str:
    for suffix in ("ing", "ed", "es", "s"):
        if word.endswith(suffix) and len(word) - len(suffix) >= 3:
            return word[: -len(suffix)]
    return word


def subject(sentence: str) -> frozenset[str]:
    """Words saying what the values are about, without the values themselves."""
    skip = (
        STOPWORDS | set(NUMBERS) | set(LEVELS) | {w for u in UNITS for w in u.split()}
    )
    words = re.findall(r"[a-z]+", re.sub(r"\[\w+\]", " ", sentence.lower()))
    return frozenset(
        stem(w) for w in words if len(w) > 2 and w not in skip and stem(w) not in skip
    )


def claims(record: dict) -> list[Claim]:
    """Claims from one call in the ABCD v1.1 format."""
    scenario = record["scenario"]
    found = []
    for speaker, text in record["original"]:
        if speaker != "agent":
            continue
        for sentence in re.split(r"(?<=[.!?])\s+", text):
            levels = tuple(level for level in LEVELS if level in sentence.lower())
            masked = mask_text(sentence, scenario)
            for value in values(sentence):
                scope = (scenario["subflow"], levels, value.split(" ", 1)[1])
                found.append(
                    Claim(
                        str(record["convo_id"]), scope, value, subject(masked), masked
                    )
                )
    return found
