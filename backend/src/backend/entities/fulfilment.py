"""Evidence of specific recorded shipping, return and refund outcomes."""

import re
from dataclasses import dataclass
from decimal import Decimal

from backend.entities.refund_amount import REFUND_RECORD

OUTCOME = "answer-support.recorded_outcomes"
VALUE = "answer-support.values"
ORDER = re.compile(r"\[ORDER_ID(?:_\d+)?\]", re.IGNORECASE)
FEE_REQUEST = (
    r"\b(?:shipping|delivery) (?:fee|cost|charge|costs)\b|\bfee (?:waived|waivered)\b"
)
REQUESTS = {
    "shipping": (
        FEE_REQUEST + r"|\b(?:shipping (?:status|details|date|option)|"
        r"when.{0,50}\b(?:receive|arrive|deliver|ship)\w*\b|"
        r"where (?:is|are) (?:my|the) (?:order|package)|"
        r"(?:upgrade|downgrade|delay|postpone|change)\b.{0,42}\b(?:shipping|delivery))\b"
    ),
    "return": (
        r"\b(?:(?:can|may|could) i|i (?:want|need|would like) to|i'd like to)"
        r"\s+(?:return|retunr)\b|\b(?:i |we )?(?:received|got|ordered)\s+(?:the )?wrong (?:size|colou?r)\b"
    ),
    "refund": (
        r"\b(?:(?:can|could|may) i (?:please )?(?:get|receive|have)|"
        r"i (?:want|need|would like)|i'd like) (?:a |my |the )?refund\b"
        r"|\b(?:status|state)\b.{0,35}\brefund\b"
        r"|\b(?:checking on|still waiting (?:on|for)) (?:the|my) refund\b"
        r"|\bcharge\b.{0,52}\b(?:has not|hasn't) been reversed\b"
    ),
}
CHANGE = re.compile(
    r"\b(?:never mind|forget (?:it|that)|changed my mind|no longer (?:need|want)"
    r"|(?:do not|don't) (?:return|refund|change|waive|send|charge)"
    r"|(?:another|different|second|wrong) order|instead|actually)\b",
    re.IGNORECASE,
)
ATTRIBUTION = re.compile(
    r"\b(?:(?:they|you|the (?:previous )?agent|the customer) (?:said|wrote|told me)"
    r"|i quote|i was quoting|repeat after me)\b",
    re.IGNORECASE,
)
SUBJECT_CHANGE = re.compile(
    r"\b(?:chang(?:e|ing) (?:the )?subjects?|switch topics?)\b", re.IGNORECASE
)
METHODS = {
    "mail": r"(?:by )?mail",
    "store": r"in[- ](?:(?:a|the) )?store",
    "drop off": r"(?:at (?:a |the )?)?drop[- ]off(?:[- ]cente[re]r?)?",
}
RETURN_OFFER = re.compile(
    r"\b(?:how (?:do|would) you (?:want|like)|how will you|would you (?:prefer|like))"
    r"\b.{0,65}\breturn\b",
    re.IGNORECASE,
)
RETURN_CLAIM = re.compile(
    r"\b(?:i(?:'ve| have)? (?:just )?(?:initiated|started|set up) (?:your|the) return"
    r"|(?:your|the) return(?: process)? (?:has been|was) (?:started|initiated|set up)"
    r"|(?:your|the) return is (?:now )?(?:processing|in progress))\b",
    re.IGNORECASE,
)
WAIVER = re.compile(
    r"order has been updated with waive (?:shipping )?fee\.", re.IGNORECASE
)
WAIVER_CLAIM = re.compile(
    r"\b(?:i(?:'ve| have)? (?:just )?waived (?:your|the) (?:shipping )?fee"
    r"|(?:your|the) (?:shipping )?fee (?:has been|was) waived)\b",
    re.IGNORECASE,
)
REFUND_CLAIM = re.compile(
    r"\b(?:i(?:'ve| have)? (?:just )?(?:refunded you|(?:issued|processed|sent) (?:your|the|a) refund)"
    r"|(?:your|the) refund(?: (?:of|for) \$\d+(?:\.\d{1,2})?)? (?:has been|was) "
    r"(?:successfully )?(?:processed|issued|sent))\b",
    re.IGNORECASE,
)
CLAIM_AMOUNT = r"\$(\d+(?:\.\d{1,2})?)(?![\d.,])"
REFUND_UPDATE = re.compile(
    r"\b(?:add\w*\b.{0,55}\b(?:to|into)\b.{0,25}\b(?:the|my|an existing) refund"
    r"|(?:change|update)\b.{0,25}\b(?:my|the|an existing) refund"
    r"|(?:existing|another|previous|second) refund)\b",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class RecordedFinding:
    outcome: str
    explanation: str
    turns: tuple


def direct_text(turn):
    words = turn["text"].strip().replace("’", "'")
    if any(quote in words for quote in '"“”') or ATTRIBUTION.search(words):
        return ""
    return words


def matches_request(turn, category):
    if turn["speaker"] != "customer" or category not in REQUESTS:
        return False
    words = direct_text(turn)
    return (
        re.search(REQUESTS[category], words, re.IGNORECASE) is not None
        and re.search(
            r"\b(?:don't|do not|no longer) (?:want|need)\b", words, re.IGNORECASE
        )
        is None
        and (
            category != "refund" or re.search(FEE_REQUEST, words, re.IGNORECASE) is None
        )
    )


def single_order(events):
    return (
        len({match.casefold() for e in events for match in ORDER.findall(e["text"])})
        <= 1
    )


def _interruption(turn):
    return turn["speaker"] != "action" and (
        SUBJECT_CHANGE.search(turn["text"])
        or (turn["speaker"] == "customer" and CHANGE.search(turn["text"]))
    )


def _return_method(text):
    return next(
        (
            method
            for method, pattern in METHODS.items()
            if re.fullmatch(
                rf"{pattern}(?:,? please)?", text.strip(" .!?"), re.IGNORECASE
            )
        ),
        None,
    )


def recorded_return_method(events, request):
    """Link the customer's explicit method choice to an exact order update."""
    if not single_order(events):
        return ()
    following = [e for e in events if e["turn_id"] > request["turn_id"]]
    choices = []
    updates = []
    for index, turn in enumerate(following):
        if turn["speaker"] == "action" and turn["text"].casefold().startswith(
            "order has been updated with "
        ):
            method = _return_method(turn["text"][len("order has been updated with ") :])
            if method is not None:
                updates.append((turn, method))
            continue
        if turn["speaker"] != "agent" or not RETURN_OFFER.search(direct_text(turn)):
            continue
        choice = next(
            (e for e in following[index + 1 :] if e["speaker"] != "action"), None
        )
        if (
            choice is not None
            and choice["speaker"] == "customer"
            and (method := _return_method(direct_text(choice)))
        ):
            reported = direct_text(turn)
            if not any(
                re.search(pattern, reported, re.IGNORECASE)
                for pattern in METHODS.values()
            ) or re.search(METHODS[method], reported, re.IGNORECASE):
                choices.append((turn, choice, method))
    if len(choices) != 1 or len(updates) != 1:
        return ()
    offer, choice, selected = choices[0]
    update, recorded = updates[0]
    if (
        selected != recorded
        or not choice["turn_id"] < update["turn_id"]
        or any(_interruption(e) for e in following if e["turn_id"] <= update["turn_id"])
    ):
        return ()
    return offer, choice, update


def _completed_claim(events, start, pattern):
    """A positive, unquoted assertion after the action; promises and alternatives stay open."""
    for turn in events:
        if turn["turn_id"] <= start or turn["speaker"] != "agent":
            continue
        words = direct_text(turn)
        if not pattern.search(words) or re.search(
            r"\b(?:not|never|if|might|should|will|would|maybe|actually|correction|different)\b|\?",
            words,
            re.IGNORECASE,
        ):
            continue
        if not any(
            e["speaker"] == "agent" and ATTRIBUTION.search(e["text"])
            for e in events
            if start < e["turn_id"] < turn["turn_id"]
        ):
            return turn
    return None


def _stated_refund_amount(claim):
    words = direct_text(claim)
    match = REFUND_CLAIM.search(words)
    if match is None:
        return None
    # A price elsewhere in the utterance is separate from the completed refund.
    amount = re.search(CLAIM_AMOUNT, match[0]) or re.match(
        rf"\s+(?:(?:for(?: the amount of)?|of|in the amount of)\s+)?{CLAIM_AMOUNT}",
        words[match.end() :],
    )
    return Decimal(amount[1]) if amount else None


def recorded_outcomes(events, category, request):
    """Corroborate a claimed outcome on this call, without making any eligibility judgment."""
    if not matches_request(request, category) or not single_order(events):
        return {}
    if category == "return":
        route = recorded_return_method(events, request)
        if (
            route
            and (claim := _completed_claim(events, route[-1]["turn_id"], RETURN_CLAIM))
            and not any(
                _interruption(e)
                for e in events
                if route[-1]["turn_id"] < e["turn_id"] < claim["turn_id"]
            )
        ):
            return {
                OUTCOME: RecordedFinding(
                    "supported",
                    "The selected return method and its order update support the Agent's claim that the return was set up.",
                    (request, *route, claim),
                )
            }
        return {}

    fee = category == "shipping"
    if not fee and category != "refund":
        return {}
    if fee and not re.search(FEE_REQUEST, direct_text(request), re.IGNORECASE):
        return {}
    pattern = WAIVER if fee else REFUND_RECORD
    after = [e for e in events if e["turn_id"] > request["turn_id"]]
    records = [
        (e, pattern.fullmatch(e["text"].strip()))
        for e in after
        if e["speaker"] == "action"
        and (
            WAIVER.search(e["text"])
            if fee
            else "a refund has been made" in e["text"].casefold()
        )
    ]
    if len(records) != 1:
        return {}
    record, recorded = records[0]
    if recorded is None or any(
        _interruption(e)
        or (e["speaker"] == "customer" and not fee and REFUND_UPDATE.search(e["text"]))
        for e in after
    ):
        return {}
    claim = _completed_claim(
        after, record["turn_id"], WAIVER_CLAIM if fee else REFUND_CLAIM
    )
    if claim is None:
        return {}
    evidence = (request, record, claim)
    findings = {
        OUTCOME: RecordedFinding(
            "supported",
            "The order update confirms the Agent's statement that the shipping fee was waived."
            if fee
            else "The completed refund record corroborates the Agent's statement that a refund was issued.",
            evidence,
        )
    }
    if not fee and (amount := _stated_refund_amount(claim)) is not None:
        matches = amount == Decimal(recorded["value"])
        findings[VALUE] = RecordedFinding(
            "supported" if matches else "breach",
            "The stated refund amount matches the completed refund record."
            if matches
            else "The stated refund amount differs from the completed refund record.",
            evidence,
        )
    return findings
