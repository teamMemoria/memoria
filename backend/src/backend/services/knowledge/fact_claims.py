"""Turn knowledge drafts into the value claims that inferred knowledge learns from.

This is the only place that knows how a claim is read out of text. It reuses
the existing pipeline: ``extract_drafts`` (#16) removes personal details and
picks the agent's answer sentences, and the helpers in ``text.py`` find values,
membership levels and subject words.

Only what the agent said is used. Recorded system actions (ABCD's
``[Pull up Account]``-style buttons) are left out on purpose: they mirror the
guideline steps, so learning from them would be reading the answer key.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from decimal import Decimal, InvalidOperation
from typing import Any

from backend.entities.inferred_knowledge import FactClaim

from .extraction import Extractor, RuleExtractor, extract_drafts
from .text import (
    MEMBERSHIP_LEVELS,
    Quantity,
    content_terms,
    membership_levels,
    quantities,
)

# Words that are part of a value rather than what the value is about.
_VALUE_WORDS = frozenset(
    content_terms(
        "a an one two three four five six seven eight nine ten twelve fifteen twenty thirty "
        "sixty ninety hundred thousand day days week weeks month months year years hour hours "
        "minute minutes business dollar dollars percent usd"
    )
)
# Level names as content_terms writes them ("bronze" -> "bronz").
_LEVEL_WORDS = frozenset(content_terms(" ".join(MEMBERSHIP_LEVELS))) | {"member"}


def normalise_value(quantity: Quantity) -> str:
    """$2.00 and $2 are the same value, and "3 out of 4" stays a count."""
    try:
        number = Decimal(quantity.value).normalize()
    except InvalidOperation:
        return str(quantity)
    return f"{number:f} {quantity.unit}"


def claims_from_text(
    text: str, company_id: str, call_id: str, category: str
) -> list[FactClaim]:
    """One claim per value in one sentence an agent said."""
    found = quantities(text)
    if not found:
        return []
    levels = frozenset(membership_levels(text))
    subject = frozenset(
        word
        for word in content_terms(text)
        if word not in _VALUE_WORDS
        and word not in _LEVEL_WORDS
        and not word[0].isdigit()
    )
    return [
        FactClaim(
            company_id=company_id,
            call_id=call_id,
            category=category,
            value=normalise_value(q),
            subject=subject,
            levels=levels,
            quote=text,
        )
        for q in found
    ]


def claims_from_drafts(
    drafts: Iterable[Mapping[str, Any]], company_id: str
) -> list[FactClaim]:
    """Claims from the agent's answer passages of each draft."""
    claims = []
    for draft in drafts:
        call_id = draft["source"]["source_key"]
        category = draft["scope"]["subflow"]
        for passage in draft["answer_passages"]:
            if passage["speaker"] != "agent":
                continue
            claims.extend(
                claims_from_text(passage["quote"], company_id, call_id, category)
            )
    return claims


class ConversationClaimSource:
    """Claims from a set of conversations, read through the #16 extractor.

    Conversations that can't be read are skipped and kept in ``failures``, so
    one bad record doesn't stop the rest. The same call given twice counts once.
    If two records claim to be the same call but say different things, neither
    is used, since there's no fair way to pick one.
    """

    def __init__(
        self,
        conversations: Iterable[Mapping[str, Any]],
        extractor: Extractor | None = None,
    ):
        self.conversations = conversations
        self.extractor = extractor or RuleExtractor()
        self.failures: list[dict[str, Any]] = []
        self.calls_read = 0

    def claims(self, company_id: str) -> list[FactClaim]:
        by_call: dict[str, list[FactClaim]] = {}
        differing: set[str] = set()
        self.failures = []
        self.calls_read = 0
        for record in self.conversations:
            name = None
            if isinstance(record, Mapping):
                name = record.get("id") or record.get("convo_id")
            result = extract_drafts(record, company_id, extractor=self.extractor)
            if result.status != "ok":
                self.failures.append({"conversation": name, "errors": result.errors})
                continue
            self.calls_read += 1
            in_record: dict[str, list[FactClaim]] = {}
            for draft in result.drafts:
                key = draft["source"]["source_key"]
                in_record.setdefault(key, []).extend(
                    claims_from_drafts([draft], company_id)
                )
            for key, found in in_record.items():
                if key in by_call and by_call[key] != found:
                    differing.add(key)
                by_call.setdefault(key, found)
        for key in sorted(differing):
            del by_call[key]
            self.failures.append(
                {"conversation": key, "errors": [{"code": "duplicate_call_differs"}]}
            )
        return [claim for key in sorted(by_call) for claim in by_call[key]]
