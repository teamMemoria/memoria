"""Find recorded turns used to discover knowledge drafts."""

import re
from itertools import pairwise


def account_lookup(events, *, after):
    return next(
        (
            event
            for event in events
            if event["speaker"] == "action"
            and event["turn_id"] > after
            and re.fullmatch(
                r"Account has been pulled up for .+\.",
                event["text"].strip(),
                re.IGNORECASE,
            )
        ),
        None,
    )


def faq_search(events):
    """Recognize only recorded Search FAQ followed by an apparel topic action."""
    for opened, topic in pairwise(events):
        if opened["speaker"] != "action" or topic["speaker"] != "action":
            continue
        if opened["text"].strip() != "Searching the FAQ pages ...":
            continue
        match = re.fullmatch(
            r"System Action: search (boots|jeans|shirt|jacket)",
            topic["text"].strip(),
            re.IGNORECASE,
        )
        if match:
            return opened, topic, match[1].lower()
    return None


def promo_days(text: str) -> int | None:
    match = re.fullmatch(
        r"standard promo codes (?:expire after|are valid for) ([1-9][0-9]{0,2}) days\.?",
        text.strip(),
        re.IGNORECASE,
    )
    return int(match[1]) if match else None


def promo_exchange(events):
    """Require a complete simple exchange. Other wording awaits broader checks."""
    if len(events) != 2:
        return None
    question, answer = events
    if (
        question["speaker"] != "customer"
        or answer["speaker"] != "agent"
        or question["text"].strip().casefold()
        not in {
            "how long are standard promo codes valid?",
            "when do standard promo codes expire?",
        }
    ):
        return None
    days = promo_days(answer["text"])
    return (question, answer, days) if days is not None else None
