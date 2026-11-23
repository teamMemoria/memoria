"""Recognize separate subscription price and refund amount claims."""

import re
from decimal import Decimal

REFUND_AMOUNT_CHECK = "answer-support.values.refund_amount"
SUBSCRIPTION_PRICE_CHECK = "answer-support.values.subscription_price"
AMOUNT = r"\$(?P<value>\d+(?:\.\d{1,2})?)"
ANNUAL_PRICE = re.compile(
    rf"(?:yes[, ]+)?(?:an? |the )?(?:single )?annual subscription (?:is|costs) {AMOUNT}[.!]?",
    re.IGNORECASE,
)
REFUND_QUOTE = re.compile(
    rf"(?:(?:got it[, ]+(?:so )?)?(?:the|your) refund (?:should be|will be)(?: for)?|i will refund) {AMOUNT}(?: then)?[.!]?",
    re.IGNORECASE,
)
REFUND_RECORD = re.compile(
    rf"a refund has been made for the amount of {AMOUNT}[.]?",
    re.IGNORECASE,
)


def subscription_refund_claims(events):
    """Return the two Agent assertions and a proven refund record, if present."""
    money = [
        (index, turn)
        for index, turn in enumerate(events)
        if turn["speaker"] == "agent"
        for _ in re.finditer(r"\$\s*\d", turn["text"])
    ]
    if len(money) != 2:
        return None
    (price_index, price), (refund_index, refund) = money
    if price_index == 0 or not ANNUAL_PRICE.fullmatch(price["text"].strip()):
        return None
    question = events[price_index - 1]
    if question["speaker"] != "customer" or not re.search(
        r"\bhow much\b.*\bsubscription\b|\b(?:price|cost)\b.*\bsubscription\b",
        question["text"],
        re.IGNORECASE,
    ):
        return None
    claim = REFUND_QUOTE.fullmatch(refund["text"].strip())
    if claim is None:
        return None
    records = [
        (i, turn, match)
        for i, turn in enumerate(events)
        if turn["speaker"] == "action"
        and (match := REFUND_RECORD.fullmatch(turn["text"].strip()))
    ]
    proven = None
    if len(records) == 1:
        index, turn, logged = records[0]
        # Demand direct adjacency. A later refund can concern a different request.
        if index == refund_index + 1 and Decimal(logged["value"]) == Decimal(
            claim["value"]
        ):
            proven = turn
    return price, refund, proven
