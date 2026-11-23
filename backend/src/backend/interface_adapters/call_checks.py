"""Recognize narrow, cited request/response and wording checks across workflows."""

import re
from functools import partial
from operator import itemgetter

from ml.wording import quotation_context

from backend.interface_adapters.draft_examples import event

WORKFLOWS = {
    "website": (
        r"\b(?:website|site)\b.{0,45}\b(?:running|is|too)\b.{0,28}\bslow\b",
        r"\b(?:file|submit|send|write up) a report to (?:our|the) website team\b",
        "The Agent described escalating the slow website issue.",
        "The conversation does not establish a permanent repair.",
    ),
    "account": (
        r"\blost (?:my|the) phone\b.*\b(?:2fa|two.factor)\b",
        r"\b(?:able to reset|resetting) your (?:2fa|two.factor)\b",
        "The Agent described a reset path for the reported access problem.",
        "The customer can report a reset succeeded. The record does not independently confirm identity checks or delivery of a separate promised link.",
    ),
    "shipping": (
        r"\b(?:would like|want|need) to upgrade my shipping\b",
        r"\btoo late to upgrade\b",
        "The Agent directly declined the shipping upgrade.",
        "The timing restriction and projected delivery date need independent support.",
    ),
    "return": (
        r"\b(?:would like|want|need) to return\b.*\bwrong size\b",
        r"\b(?:what|which) method of refund would you like\b",
        "The Agent responded to the return by discussing refund options.",
        "A refund event does not establish purchase validation, refund authority, or return instructions.",
    ),
    "refund": (
        r"\b(?:not (?:been )?reversed|still charged|refund has not arrived)\b.*\breturn\b",
        r"\b(?:your|the) refund should (?:now )?be on (?:it['’]s|its) way\b",
        "The Agent addressed the refund follow-up with a projected outcome.",
        "The empty order update cannot establish that the refund was sent.",
    ),
    "billing": (
        r"\b(?:was|got) charged\b.*\b(?:didn['’]?t buy|did not buy|never bought)\b",
        r"\b(?:issue|process) a refund\b",
        "The Agent responded to the unexpected charge with a refund commitment.",
        "A placeholder in the refund event cannot confirm the amount or the corrected charge.",
    ),
    "payment": (
        r"\b(?:rejecting|declining) my (?:credit )?card\b",
        r"\b(?:has it expired|what is the expiration date on your card)\b",
        "The Agent checked whether the rejected card had expired.",
        "The record does not establish a completed payment.",
    ),
    "pricing": (
        r"\b(?:promo|promotion) code\b.*\b(?:when it expires|when .* expire)\b",
        r"\b(?:most|some) of our promo codes\b.*\b(?:more days?|days? left)\b",
        "The Agent addressed the expiry question with a qualified estimate.",
        "The record has no independently confirmed expiry for this code.",
    ),
    "exchange": (
        r"^(?:it (?:seems to be|is)|i (?:got|received)) the wrong item[.!]?$",
        r"\bi(?:['’]ve| have) changed the item\b",
        "The Agent stated that the wrong-item issue had been addressed.",
        "The item-change event does not confirm the replacement variant, shipment, or how to return the other item.",
    ),
}

QUESTIONS = {
    "completeness.direct_response": "Did the Agent respond directly to the observed request?",
    "completeness.promises_next_steps": "Were promised actions or material next steps addressed?",
    "completeness.followups": "Were the observed follow-up requests addressed?",
    "communication-style.clarity": "Was the observed response stated clearly?",
    "communication-style.acknowledgement": "Did the Agent acknowledge the request in the exchange?",
}

HELP = r"(?:anything else (?:i can|i could|i may|i could help|you need)|can i help you with anything else|does that answer all of your questions)"
NO_MORE = r"^(?:no\b|nope\b|that (?:is|was) all\b|that['’]s all\b|yes it does\b)"
ACKNOWLEDGE = (
    r"\b(?:i(?:['’]m| am) (?:very |so )?sorry|i can help (?:you )?with that|"
    r"absolutely.{0,4} let me check)\b"
)


def ordered_turns(events, *steps):
    """Match the first eligible turn for each step, strictly in order."""
    after = 0
    matched = []
    for speaker, pattern in steps:
        turn = event(events, speaker, pattern, after=after)
        if turn is None:
            return ()
        matched.append(turn)
        after = turn["turn_id"]
    return tuple(matched)


def _closure(events, response):
    for index, turn in enumerate(events):
        if turn["turn_id"] <= response["turn_id"] or turn["speaker"] != "agent":
            continue
        if not re.search(HELP, turn["text"], re.IGNORECASE) or quotation_context(
            events, index
        ):
            continue
        next_turn = next(
            (e for e in events[index + 1 :] if e["speaker"] != "action"), None
        )
        if next_turn is None or next_turn["speaker"] != "customer":
            continue
        reply = next_turn["text"].strip()
        # An affirmative answer only closes a question about whether the issue was answered.
        if (
            re.search(NO_MORE, reply, re.IGNORECASE)
            and "?" not in reply
            and (
                not reply.casefold().startswith("yes")
                or re.search(r"does that answer", turn["text"], re.IGNORECASE)
            )
        ):
            return turn, next_turn
    return ()


def _cancellation(events):
    find = partial(event, events)
    matched = ordered_turns(
        events,
        ("agent", r"\bwould you like .*\bcancel the order\?"),
        ("customer", r"^cancel (?:it|the order)(?: completely)?[.!]?$"),
        (
            "customer",
            r"^never mind[.! ,]+(?:my (?:problem|issue) (?:has been|is) solved|i don['’]t need to cancel)",
        ),
    )
    if not matched:
        return None
    choice, request, withdrawal = matched
    if find(
        "action",
        r"\b(?:order (?:was|has been) cancel(?:led|ed)|updated with cancel(?:lation)?)\b",
        after=request["turn_id"],
    ):
        return None
    confirm = next(
        (t for t in events if t["turn_id"] == withdrawal["turn_id"] + 1), None
    )
    accepted = next(
        (t for t in events if t["turn_id"] == withdrawal["turn_id"] + 2), None
    )
    if (
        not confirm
        or confirm["speaker"] != "agent"
        or not re.match(
            r"are you (?:certain|sure)\?", confirm["text"].strip(), re.IGNORECASE
        )
        or not accepted
        or accepted["speaker"] != "customer"
        or not re.search(
            r"^(?:yes|yup|yeah)[,. ]+.*\bsolved\b", accepted["text"], re.IGNORECASE
        )
    ):
        return None
    anchors = [choice, request, withdrawal, confirm, accepted]
    return (
        "order",
        {
            "completeness.direct_response": (
                "supported",
                "The Agent checked whether the customer wanted to withdraw the cancellation.",
                anchors,
            ),
            "completeness.promises_next_steps": (
                "not-applicable",
                "The customer confirmed the original cancellation was no longer needed.",
                anchors,
            ),
            "completeness.followups": (
                "unresolved",
                "The withdrawal is clear. Other refund or shipping obligations are outside this linked cancellation check.",
                anchors,
            ),
        },
        "The cancellation was withdrawn. This does not establish a cancellation or refund outcome.",
    )


def _site_followup(events, request, response, checks):
    find = partial(event, events)
    notification = find(
        "action", r"^the website team has been notified[.]$", after=response["turn_id"]
    )
    if notification is not None:
        checks["completeness.promises_next_steps"] = (
            "supported",
            "The promised Website Team notification is recorded.",
            [request, response, notification],
        )
    followup = find(
        "customer",
        r"\b(?:anything|something) i can do in the meantime\?",
        after=response["turn_id"],
    )
    if followup is None:
        return
    advice = find(
        "agent", r"\bclose (?:any|all) other tabs?\b", after=followup["turn_id"]
    )
    if advice is None:
        return
    result = find(
        "customer",
        r"\b(?:that seemed to do the trick|that helped|it is working better)\b",
        after=advice["turn_id"],
    )
    if result is None:
        return
    checks["completeness.followups"] = (
        "supported",
        "The Agent offered a step in response to the interim-help question. The customer reported improvement.",
        [followup, advice, result],
    )


FOLLOWUP_RECORDS = {
    "account": (
        "action",
        r"^a link will be sent[.]$",
        "The record describes a future link. It does not show that the separate promised link was delivered.",
    ),
    "refund": (
        "action",
        r"^order has been updated with\s*[.]$",
        "The order update lacks a value and does not confirm the projected refund.",
    ),
    "billing": (
        "action",
        r"^a refund has been made for the amount of \$give credit[.]$",
        "The refund entry contains a placeholder amount. The promised refund cannot be verified from it.",
    ),
    "exchange": (
        "customer",
        r"\bi will send the other item back\b",
        "The customer mentioned returning the other item. The next step for that return remains unclear.",
    ),
}

RESPONSE_RECORDS = {
    "account": (
        "customer",
        r"\b(?:that reset it|i was able to reset it|i can sign in now)\b",
        "The Agent described a reset path, and the customer reported that the reset worked.",
    ),
    "return": (
        "action",
        r"^a refund has been made for the amount of \$[0-9]+(?:[.][0-9]{2})?[.]$",
        "The Agent discussed refund options, and the action log records a refund amount.",
    ),
    "exchange": (
        "action",
        r"^order has been updated with change item[.]$",
        "The Agent addressed the wrong-item issue, and the log records an item change.",
    ),
}


def _recorded_check(events, request, response, record_rule, outcome):
    speaker, pattern, description = record_rule
    if record := event(events, speaker, pattern, after=request["turn_id"]):
        return (
            outcome,
            description,
            sorted([request, response, record], key=itemgetter("turn_id")),
        )
    return None


def observed_workflow(events):
    """Return only checks whose request, response and relevant outcome can be linked."""
    find = partial(event, events)
    matches = []
    for key, (ask, answer, description, gap) in WORKFLOWS.items():
        request = find("customer", ask)
        if request is None or re.search(
            r"\b(?:don['’]t|do not|no longer|never) (?:want|need|wish)\b|\bnot asking\b",
            request["text"],
            re.IGNORECASE,
        ):
            continue
        response = find("agent", answer, after=request["turn_id"])
        if response is not None:
            matches.append((key, request, response, description, gap))
    cancellation = _cancellation(events)
    if len(matches) + bool(cancellation) != 1:
        return None
    if cancellation:
        return cancellation
    key, request, response, description, gap = matches[0]
    checks = {
        "completeness.direct_response": ("supported", description, [request, response]),
        "communication-style.clarity": (
            "supported",
            "The observed response names a concrete decision or next step.",
            [response],
        ),
        "answer-support.facts": ("unresolved", gap, [request, response]),
    }
    if key in RESPONSE_RECORDS and (
        finding := _recorded_check(
            events, request, response, RESPONSE_RECORDS[key], "supported"
        )
    ):
        checks["completeness.direct_response"] = finding
    acknowledgement = find(
        "agent",
        ACKNOWLEDGE,
        after=request["turn_id"] - 1,
        before=response["turn_id"] + 1,
    )
    if acknowledgement is not None:
        checks["communication-style.acknowledgement"] = (
            "supported",
            "The Agent acknowledged the request with an apology or offer to help.",
            [request, acknowledgement],
        )
    if key == "website":
        _site_followup(events, request, response, checks)
    elif key in FOLLOWUP_RECORDS:
        if finding := _recorded_check(
            events, request, response, FOLLOWUP_RECORDS[key], "unresolved"
        ):
            checks["completeness.promises_next_steps"] = finding
    elif key in {"shipping", "payment", "pricing"} and (
        closing := _closure(events, response)
    ):
        other_questions = [
            turn
            for turn in events
            if turn["speaker"] == "customer"
            and "?" in turn["text"]
            and turn["turn_id"] > request["turn_id"]
        ]
        if not other_questions:
            checks["completeness.followups"] = (
                "not-applicable",
                "The customer confirmed the exchange was complete without a further question.",
                [request, response, *closing],
            )
        promise = find(
            "agent",
            r"\b(?:i|we)(?:['’]ll| will| am going to) (?:send|call|email|change|upgrade|refund|notify|process|file|pay|follow up)\b",
        )
        if not promise:
            checks["completeness.promises_next_steps"] = (
                "not-applicable",
                "The response was advice or a refusal, and the closing exchange identified no pending commitment.",
                [request, response, *closing],
            )
    return key, checks, gap
