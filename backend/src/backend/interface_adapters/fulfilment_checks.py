"""Tie fulfilment workflow checks to the request and the Agent's actual response."""

import re

from ml.wording import quotation_context

from backend.entities.fulfilment import REQUESTS, direct_text, matches_request
from backend.interface_adapters.call_checks import ACKNOWLEDGE, _closure, event

RESPONSES = {
    "shipping": (
        r"\b(?:shipping|delivery) (?:fee|cost|date)\b.{0,30}\b(?:waiv\w*|refund\w*|chang\w*)\b"
        r"|\b(?:waiv\w*|refund\w*|credit\w*)\b.{0,40}\b(?:fee|cost|shipping)\b"
        r"|\b(?:cannot|can't|unable to|too late to) (?:change|upgrade|delay|alter)\b"
        r"|\b(?:your|the) (?:order|item|package) (?:has (?:already )?shipped|is (?:currently )?(?:in transit|out for delivery|delivered))\b"
    ),
    "return": (
        r"\b(?:you (?:can|may) return|eligible (?:to|for) return|cannot process a return|"
        r"can't process (?:your|the|a) return|return (?:is processing|has been (?:started|initiated|set up))"
        r"|(?:would you like|how (?:do|would) you want).{0,30}\breturn\b.{0,35}\b(?:mail|store)|"
        r"(?:you|gold members) (?:get|have) unlimited returns)\b"
    ),
    "refund": (
        r"\b(?:refund|credit)\b.{0,50}\b(?:in progress|not started|complete\w*|"
        r"processed|issued|sent|up to|will take)\b"
        r"|\b(?:takes? (?:between |up to )?\d+.{0,35}\bdays?|"
        r"(?:issue|process) (?:your|the|a) refund|refunded you|"
        r"how would you like to (?:receive|get) your refund|wait until)\b"
    ),
}


def fulfilment_request(events, category):
    for index, turn in enumerate(events):
        if matches_request(turn, category) and not quotation_context(events, index):
            return turn
    return None


def fulfilment_workflow(events):
    matches = []
    for category in REQUESTS:
        if (request := fulfilment_request(events, category)) is None:
            continue
        pattern = re.compile(RESPONSES[category], re.IGNORECASE)
        response = next(
            (
                turn
                for i, turn in enumerate(events)
                if turn["speaker"] == "agent"
                and turn["turn_id"] > request["turn_id"]
                and pattern.search(words := direct_text(turn))
                and "?" not in words
                and not quotation_context(events, i)
            ),
            None,
        )
        if response is not None:
            matches.append((category, request, response))
    if len(matches) != 1:
        return None
    category, request, response = matches[0]
    checks = {
        "completeness.direct_response": (
            "supported",
            f"The Agent directly addressed the {category} request.",
            [request, response],
        ),
        "communication-style.clarity": (
            "supported",
            "The Agent used concrete wording about the decision or next step.",
            [response],
        ),
    }
    if acknowledgement := event(
        events,
        "agent",
        ACKNOWLEDGE,
        after=request["turn_id"],
        before=response["turn_id"] + 1,
    ):
        checks["communication-style.acknowledgement"] = (
            "supported",
            "The Agent acknowledged the issue in the exchange.",
            [request, acknowledgement],
        )
    if (closing := _closure(events, response)) and not any(
        e["speaker"] == "customer"
        and request["turn_id"] < e["turn_id"] < closing[0]["turn_id"]
        and (
            any(matches_request(e, family) for family in REQUESTS)
            or re.search(
                r"\?|\b(?:also|instead|what|where|how|why|when|want|need|can|could|would)\b",
                e["text"],
                re.IGNORECASE,
            )
        )
        for e in events
    ):
        checks["completeness.followups"] = (
            "not-applicable",
            "The customer confirmed that no further help was needed.",
            [request, response, *closing],
        )
    return (
        category,
        checks,
        "The operational record covers only the action and fields it explicitly records.",
    )
