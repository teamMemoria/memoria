"""Bounded evidence recognition for a subscription-extension refusal."""

import re


def extension_refusal(events):
    """Recognize a recorded ineligible tier, direct refusal and resolved follow-up."""
    if any(
        event["speaker"] == "action"
        and re.search(
            r"updated|extension granted|notified", event["text"], re.IGNORECASE
        )
        for event in events
    ):
        return None

    steps = (
        (
            "request",
            "customer",
            r"(?:can|could|may) i (?:get|have) an extension (?:on|for) my subscription[?]",
        ),
        ("account", "action", r"account has been pulled up for .+\."),
        ("verification", "action", r"identity verification in progress\s*\.{3}"),
        ("tier", "action", r"membership level of (?:bronze|guest) has been noted[.]"),
        (
            "refusal",
            "agent",
            (
                r"(?:i am|i['’]m) sorry(?: (?:(?:mr|mrs|ms|dr)\. )?\[person_\d+\])?, "
                r"but your account does not qualify for an extension(?: at this time)?[.]"
            ),
        ),
        ("why", "customer", r"why (?:not|is that)[?]"),
        (
            "reason",
            "agent",
            r"your membership level does not qualify(?: i['’]m afraid)?[.]",
        ),
        (
            "close",
            "agent",
            r"(?:[^?]+[.]\s*)?(?:was|is) there anything else (?:you needed|i can help you with)[?]",
        ),
        (
            "decline_more",
            "customer",
            r"(?:nope|no[,.]? thank you|no)[.!]?(?:\s+have a good day[.!]?)?",
        ),
    )
    evidence = {}
    remaining = iter(events)
    for key, speaker, pattern in steps:
        for event in remaining:
            if event["speaker"] == speaker and re.fullmatch(
                pattern, event["text"].strip(), re.IGNORECASE
            ):
                evidence[key] = event
                break
        else:
            return None
    if (
        evidence["why"]["turn_id"] != evidence["refusal"]["turn_id"] + 1
        or evidence["reason"]["turn_id"] != evidence["why"]["turn_id"] + 1
    ):
        return None

    # A new issue or material promise makes this bounded exchange inapplicable.
    recognized_questions = {evidence[key]["turn_id"] for key in ("request", "why")}
    for event in events:
        if (
            event["speaker"] == "customer"
            and "?" in event["text"]
            and event["turn_id"] not in recognized_questions
        ):
            return None
        if event["speaker"] == "agent" and re.search(
            r"\b(?:i['’]ll|i will|we['’]ll|we will)\s+(?:call|email|send|follow up|escalate|extend|update)\b",
            event["text"],
            re.IGNORECASE,
        ):
            return None
    return evidence
