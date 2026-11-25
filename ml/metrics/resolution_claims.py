"""Link claims of a completed refund or cancellation to their action records."""

import re
from decimal import Decimal

from ml.wording import quotation_context

REFUND_RECORD = (
    r"a refund has been made for the amount of \$(?P<amount>\d+(?:\.\d{1,2})?)\.?"
)
RESOLUTION_CHECK_VERSION = "abcd-refund-cancellation-claims-v2"
UNSAFE_ASSERTION = (
    r"\b(?:not|never|cannot|can't|didn't|haven't|if|might|should|would)\b"
)
MONEY = r"\$(?P<amount>\d+(?:\.\d{1,2})?)(?!\d|[.,]\d)"
REFUND_COMPLETION = (
    r"\b(?:i(?:'ve| have)? (?:just )?refunded (?:you|your payment|the charge)"
    r"|i(?:'ve| have)? (?:just )?(?:issued|processed|made) (?:your|the|a) refund"
    r"|(?:your|the) refund (?:was|has been) (?:issued|processed|made))"
    r"(?: (?:(?:for|of|in the amount of) )?" + MONEY + r")?(?!\w)"
)
CANCEL_RECORD = (
    r"(?:order has been updated with (?:cancel order|canceled|cancelled)"
    r"|order has been cancel(?:l)?ed)\.?"
)
CANCEL_COMPLETION = (
    r"\b(?:i(?:'ve| have)? (?:just |went ahead and )?cancel(?:l)?ed (?:your|the) order"
    r"|(?:your|the) order (?:was|has been|is now) cancel(?:l)?ed)\b"
)
SEPARATE_RESOLUTION = re.compile(
    r"\b(?:(?:existing|previous|another|additional|second) refund"
    r"|add\b.{0,40}\bto\b.{0,12}\brefund"
    r"|(?:another|different|other|second) order|(?:wrong|old) order)\b",
    re.IGNORECASE,
)
PRICE_QUESTION = (
    r"\b(?:how much (?:did|does|was)|what (?:was|is) the (?:price|amount))\b"
)
PRICE_REPLY = re.compile(
    r"(?:it (?:was|cost) |i paid )?" + MONEY + r"[.!]?",
    re.IGNORECASE,
)
REFUND_OFFER = (
    r"\b(?:give you|issue|process) (?:a|your|the) refund\b|\brefund (?:you|the item)\b"
)


def _match(events, index, speaker, pattern, *, planning=False):
    turn = events[index]
    text = turn["text"].strip().casefold().replace("’", "'")
    if (
        turn["speaker"] != speaker
        or any(mark in text for mark in '"“”')
        or quotation_context(events, index)
        or (
            speaker == "agent"
            and re.search(UNSAFE_ASSERTION, text)
            and not (
                planning and "let me see if i can get an extension for you" in text
            )
        )
    ):
        return None
    return re.search(pattern, text)


def _check(conversation, key, outcome, text, turns):
    return {
        "rule_id": key,
        "outcome": outcome,
        "maximum": 1,
        "earned": int(outcome == "supported"),
        "explanation": text,
        "citations": [
            {
                "kind": "conversation",
                "conversation_id": conversation["id"],
                "transcript_version": conversation["transcript_version"],
                "turn_id": turn["turn_id"],
                "event_kind": turn["kind"],
                "quote": turn["text"],
            }
            for turn in turns
        ],
    }


def _resolution_assertion(events, index, pattern):
    turn = events[index]
    text = turn["text"].strip().casefold().replace("’", "'")
    if (
        turn["speaker"] != "agent"
        or any(mark in text for mark in '"“”')
        or quotation_context(events, index)
        or re.search(r"\b(?:actually|correction|i meant|rather)\b", text)
    ):
        return None
    for sentence in re.split(r"(?<=[.!?])\s+", text):
        # A completed cancellation and a statement about a future charge have
        # different evidence. Only inspect the clause asserting completion.
        clause = re.split(r",?\s+and (?=you will\b)", sentence, maxsplit=1)[0]
        if (
            "?" not in clause
            and not re.search(UNSAFE_ASSERTION, clause)
            and (match := re.search(pattern, clause))
        ):
            return match
    return None


def _refund_amount_context(events, index, amount):
    preceding = [
        (i, turn)
        for i, turn in enumerate(events[:index])
        if turn["speaker"] != "action"
    ]
    if len(preceding) < 2:
        return []
    (_, question), (reply_index, reply) = preceding[-2:]
    reply_amount = PRICE_REPLY.fullmatch(reply["text"].strip())
    if (
        question["speaker"] != "agent"
        or not re.search(PRICE_QUESTION, question["text"], re.IGNORECASE)
        or reply["speaker"] != "customer"
        or not reply_amount
        or Decimal(reply_amount["amount"]) != Decimal(amount)
        or index - reply_index > 3
    ):
        return []
    for i, offer in reversed(preceding[-7:-2]):
        if _match(events, i, "agent", REFUND_OFFER, planning=True):
            return [offer, question, reply]
    return []


def recorded_resolution_claims(conversation):
    """Match explicit, completed claims to a single recorded operation."""
    events = conversation["events"]
    for operation, record_pattern, claim_pattern in (
        ("refund", REFUND_RECORD, REFUND_COMPLETION),
        ("order cancellation", CANCEL_RECORD, CANCEL_COMPLETION),
    ):
        records = [
            (i, match)
            for i, turn in enumerate(events)
            if turn["speaker"] == "action"
            and (
                match := re.fullmatch(
                    record_pattern, turn["text"].strip(), re.IGNORECASE
                )
            )
        ]
        if len(records) != 1:
            continue
        index, record = records[0]
        # An explicit branch or target change makes the pair ambiguous.
        if any(
            SEPARATE_RESOLUTION.search(turn["text"])
            for turn in events
            if turn["speaker"] != "action"
        ):
            continue
        statements = [
            (i, match)
            for i in range(index + 1, min(index + 5, len(events)))
            if (match := _resolution_assertion(events, i, claim_pattern))
            and not any(
                t["speaker"] == "action"
                and re.search(
                    r"\border has been updated\b|\brefund\b", t["text"], re.IGNORECASE
                )
                for t in events[index + 1 : i]
            )
        ]
        if len(statements) != 1:
            continue
        claim_index, claim = statements[0]
        context = (
            _refund_amount_context(events, index, record["amount"])
            if operation == "refund"
            else []
        )
        turns = [*context, events[index], events[claim_index]]
        yield _check(
            conversation,
            "answer-support.recorded-claim." + operation,
            "supported",
            f"The action record corroborates the Agent's statement that the {operation} was recorded.",
            turns,
        )
        amount = claim.groupdict().get("amount")
        if amount is not None:
            matches = Decimal(amount) == Decimal(record["amount"])
            yield _check(
                conversation,
                "answer-support.recorded-amount",
                "supported" if matches else "breach",
                "The completed refund amount matches the record."
                if matches
                else "The completed refund amount conflicts with the record.",
                turns,
            )
