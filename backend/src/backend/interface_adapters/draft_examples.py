"""Find cited examples for review using shared call evidence patterns."""

import re

from ml.wording import quotation_context

from backend.entities.guidelines import (
    CART,
    OVERNIGHT,
    PRICE,
    PROMO_AGE,
    RETURN_COLOUR,
    RETURN_SIZE,
    SHIPPING_FEE,
)

WRONG_COLOUR = r"\bwrong colou?r(?:l)?\b"
WRONG_SIZE = r"\b(?:wrong size|too (?:small|large|big)|(?:it )?doesn['’]t fit)\b"
CART_REQUEST = (
    r"\bcart\b.{0,30}\b(?:(?:fail(?:s)? to|won['’]t|doesn['’]t) update"
    r"|(?:is(?:n['’]t| not)|not) updating)\b"
)
PROMO_REQUEST = r"\b(?:promo|promotion) code\b.{0,65}\b(?:invalid|not working|isn['’]t working|doesn['’]t work)\b"


def event(events, speaker, pattern, *, after=0, before=None):
    """Only consult the speaker's own text, or a recorded system action."""
    for index, turn in enumerate(events):
        number = turn["turn_id"]
        if (
            turn["speaker"] != speaker
            or number <= after
            or (before is not None and number >= before)
        ):
            continue
        if not re.search(pattern, turn["text"], re.IGNORECASE):
            continue
        if speaker == "action" or (
            not any(mark in turn["text"] for mark in '"“”')
            and not quotation_context(events, index)
        ):
            return turn
    return None


SCOPED_EXEMPLARS = {
    SHIPPING_FEE: (
        r"\bshipping (?:fee|cost|charge)s?\b|\bcost of shipping\b",
        r"\bwaiv(?:e|ed)\b|\bpartial (?:shipping )?refund\b",
    ),
    OVERNIGHT: (r"\b(?:upgrade|overnight)\b", r"\btoo late|charge|shipping status\b"),
    RETURN_COLOUR: (WRONG_COLOUR, r"\b(?:return|members?)\b"),
    RETURN_SIZE: (WRONG_SIZE, r"\b(?:return|members?)\b"),
    CART: (CART_REQUEST, r"\b(?:refresh|log out)\b"),
    PRICE: (
        r"(?=.*\b(?:yesterday|last night)\b).*\b(?:price|cost|expensive|cheaper|sale|buy|paid)\b",
        r"\b(?:price|prices|pricing|promo|discount)\b",
    ),
    PROMO_AGE: (PROMO_REQUEST, r"\b(?:usually|typically|seven days|7 days|a week)\b"),
}


# Discovery cues for published guidelines, with the category and workflow used in scoring.
PUBLISHER_RULES = {
    "layer2-abc-initial-refund-method-v1": (
        "refund",
        "initial-refund-method",
        r"\b(?:refund|money back)\b",
        r"\b(?:gift card|paper check|credit card|add value)\b",
    ),
    "layer2-abc-update-refund-total-v1": (
        "refund",
        "update-refund-total",
        r"\b(?:add|include|another|second|also)\b.*\brefund\b",
        r"\b(?:refund|total|previous|amount)\b",
    ),
    "layer2-abc-refund-status-escalation-v1": (
        "refund",
        "refund-status-escalation",
        r"\b(?:refund status|status of (?:my|the) refund|where is my refund)\b",
        r"\b(?:status|manager|escalat\w*|in progress|complete)\b",
    ),
    "layer2-abc-stained-item-gold-return-v1": (
        "return",
        "return-stained-gold",
        r"\bstain(?:ed|s)?\b",
        r"\b(?:gold|return|shipping label)\b",
    ),
    "layer2-abc-site-search-troubleshooting-v1": (
        "website",
        "search-not-working",
        r"\b(?:search|results)\b",
        r"\b(?:cookies|log out|sign out|search for a different)\b",
    ),
}


def _publisher_event(events, speaker, pattern, *, after=None):
    """Find a related turn for review of a published guideline."""
    return next(
        (
            turn
            for turn in events
            if turn["speaker"] == speaker
            and (after is None or turn["turn_id"] > after)
            and re.search(pattern, turn["text"], re.IGNORECASE)
        ),
        None,
    )


def _first_example(conversations, find_turn, inquiry, response):
    for conversation in conversations:
        events = conversation["events"]
        question = find_turn(events, "customer", inquiry)
        if question is None:
            continue
        reply = find_turn(events, "agent", response, after=question["turn_id"])
        if reply is not None:
            return conversation, question, reply
    return None


def examples(conversations):
    """Yield a cited example per guideline so a Manager can review the draft."""
    for key, (inquiry, response) in SCOPED_EXEMPLARS.items():
        if example := _first_example(conversations, event, inquiry, response):
            yield key, example
    for key, (_, _, inquiry, response) in PUBLISHER_RULES.items():
        if example := _first_example(
            conversations, _publisher_event, inquiry, response
        ):
            yield key, example
