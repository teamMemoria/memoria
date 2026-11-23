"""Check recorded membership decisions within the approved extension branches."""

from functools import partial

from backend.interface_adapters.call_checks import event, ordered_turns

EXTENSION_QUESTIONS = {
    "procedure.information": "Was the account pulled up and the membership tier recorded?",
    "procedure.actions": "Did the response follow the refusal branch for the recorded tier?",
    "procedure.order_permission": "Did identity lookup start before the tier-based decision?",
    "completeness.direct_response": "Did the Agent answer the extension request?",
    "completeness.promises_next_steps": "Did the refusal leave promised actions or instructions to complete?",
    "completeness.followups": "Did the Agent explain the reason when the customer asked why?",
    "communication-style.clarity": "Did the wording make the refusal and its reason clear?",
    "communication-style.acknowledgement": "Did the Agent acknowledge the refusal courteously?",
    "communication-style.consistency": "Did the initial refusal and the explanation agree?",
    "answer-support.recorded_outcomes": "Did the Agent claim that an account change was completed?",
    "answer-support.facts": "Did the reason for refusal match the recorded tier and approved rule?",
    "answer-support.values": "Did the Agent state an amount, date or duration for the extension?",
}

EXTENSION_LIMITS = {
    "procedure": "The record establishes that identity lookup started. It does not establish successful verification.",
    "answer-support": "The score covers the stated reason for refusing the extension. It does not verify the customer's identity.",
}


def _judgments(turns, reference, missing_approval):
    def judgment(message, *keys, outcome="supported"):
        return outcome, message, [turns[key] for key in keys]

    def policy(message, *keys):
        if reference is None:
            return judgment(
                missing_approval,
                *keys,
                outcome="unresolved",
            )
        return "supported", message, [*(turns[key] for key in keys), reference]

    return judgment, policy


def extension_checks(turns, reference):
    judgment, policy = _judgments(
        turns,
        reference,
        "The subscription-extension guideline requires Manager approval.",
    )
    return {
        "procedure.information": policy(
            "The transcript records an account lookup and an ineligible tier.",
            "request",
            "account",
            "tier",
        ),
        "procedure.actions": policy(
            "The Agent declined the requested extension for the recorded tier.",
            "request",
            "tier",
            "refusal",
        ),
        "procedure.order_permission": policy(
            "Identity lookup was started before the membership-based decision.",
            "verification",
            "tier",
            "refusal",
        ),
        "completeness.direct_response": judgment(
            "The Agent directly declined the requested extension.",
            "request",
            "refusal",
        ),
        "completeness.promises_next_steps": judgment(
            "The refusal and closing exchange leave no promised action for the extension request.",
            "request",
            "refusal",
            "reason",
            "close",
            "decline_more",
            outcome="not-applicable",
        ),
        "completeness.followups": judgment(
            "The Agent answered the request for a reason with the membership rule.",
            "why",
            "reason",
        ),
        "communication-style.clarity": judgment(
            "The Agent states the refusal and explains the reason in direct language.",
            "refusal",
            "reason",
        ),
        "communication-style.acknowledgement": judgment(
            "The refusal includes an apology, and the Agent asks whether more help is needed.",
            "refusal",
            "close",
        ),
        "communication-style.consistency": judgment(
            "The explanation maintains the decision stated in the initial refusal.",
            "refusal",
            "reason",
        ),
        "answer-support.recorded_outcomes": judgment(
            "The Agent stated a refusal and made no claim of a completed extension.",
            "refusal",
            "reason",
            outcome="not-applicable",
        ),
        "answer-support.facts": policy(
            "The recorded tier is ineligible under the approved extension guideline.",
            "tier",
            "refusal",
            "reason",
        ),
        "answer-support.values": judgment(
            "The refusal and explanation give no amount, date or duration.",
            "refusal",
            "reason",
            outcome="not-applicable",
        ),
    }


GOLD_QUESTIONS = {
    "procedure.information": "Was the account pulled up and the Gold tier recorded?",
    "procedure.actions": "Was the eligible extension update recorded?",
    "procedure.order_permission": "Did identity lookup start before the Gold-tier update?",
    "completeness.direct_response": "Did the Agent address the subscription extension request?",
    "completeness.promises_next_steps": "Was the promised extension recorded?",
    "completeness.followups": "Did the Agent respond to the observed follow-up questions?",
    "communication-style.clarity": "Did the Agent clearly state the extension decision?",
    "communication-style.acknowledgement": "Did the Agent acknowledge the request courteously?",
    "communication-style.consistency": "Did the promised action and stated outcome agree?",
    "answer-support.recorded_outcomes": "Does the action log support the Agent’s extension claim?",
    "answer-support.facts": "Does the approved guideline support the Gold eligibility statement?",
    "answer-support.values": "Can an independent source verify the claimed extension length?",
}


def gold_extension(events):
    """Match a Gold subscription extension through the recorded update and answer."""
    find = partial(event, events)
    steps = (
        ("scope", "customer", r"\bmy subscription\b"),
        (
            "request",
            "customer",
            r"\b(?:can|could|may) i (?:get|have) an extension(?: to pay for it| on my subscription)[?]",
        ),
        ("account", "action", r"^account has been pulled up for .+[.]$"),
        ("identity", "action", r"^identity verification in progr?ess\s*\.{3}$"),
        ("tier", "action", r"^membership level of gold has been noted[.]$"),
        ("offer", "agent", r"\bgold members?\b.*\b(?:give|grant) you an extension\b"),
        (
            "update",
            "action",
            r"^account has been updated with (?:extension|extend subscription)[.]$",
        ),
        ("duration_question", "customer", r"\bhow much longer i have now[?]"),
        (
            "duration",
            "agent",
            r"\bi(?:['’]ve| have) extended your (?:membership|subscription) for\b",
        ),
    )
    matched = ordered_turns(
        events, *((speaker, pattern) for _, speaker, pattern in steps)
    )
    if not matched:
        return None
    evidence = {key: turn for (key, _, _), turn in zip(steps, matched, strict=True)}
    after = matched[-1]["turn_id"]
    if acknowledgement := find(
        "agent",
        r"\bi(?:['’]m| am) sorry to hear that\b",
        after=evidence["request"]["turn_id"],
        before=evidence["offer"]["turn_id"],
    ):
        evidence["acknowledgement"] = acknowledgement
    customer_name_question = find(
        "customer", r"\bwhat(?:['’]s| is) your name[?]", after=after
    )
    if customer_name_question and (
        introduction := find(
            "agent", r"\bmy name is\b", after=customer_name_question["turn_id"]
        )
    ):
        evidence["name_question"] = customer_name_question
        evidence["introduction"] = introduction
    return evidence


def gold_checks(turns, reference, extra_questions):
    judgment, policy = _judgments(
        turns, reference, "The Gold extension rule needs a verified Manager approval."
    )
    followups = ["duration_question", "duration"]
    if "name_question" in turns:
        followups += ["name_question", "introduction"]
    checks = {
        "procedure.information": policy(
            "Account lookup and the Gold membership tier are recorded.",
            "request",
            "account",
            "tier",
        ),
        "procedure.actions": policy(
            "The record shows the eligible account was updated with an extension.",
            "tier",
            "update",
        ),
        "procedure.order_permission": policy(
            "Identity lookup started before the Gold eligibility response and extension update.",
            "identity",
            "tier",
            "offer",
            "update",
        ),
        "completeness.direct_response": judgment(
            "The Agent addressed the extension request and offered the requested change.",
            "request",
            "offer",
        ),
        "completeness.promises_next_steps": judgment(
            "The promised extension update is recorded.", "request", "offer", "update"
        ),
        "completeness.followups": judgment(
            "The observed questions received direct responses."
            if not extra_questions
            else "Some follow-up questions could not be linked safely.",
            *followups,
            outcome="unresolved" if extra_questions else "supported",
        ),
        "communication-style.clarity": judgment(
            "The Agent stated the extension decision and the claimed duration explicitly.",
            "offer",
            "duration",
        ),
        "communication-style.consistency": judgment(
            "The stated outcome matches the kind of action the Agent offered.",
            "offer",
            "duration",
        ),
        "answer-support.recorded_outcomes": policy(
            "The action record supports the claim that an extension was applied.",
            "duration",
            "update",
        ),
        "answer-support.facts": policy(
            "The recorded Gold tier matches the approved eligibility rule.",
            "tier",
            "offer",
        ),
        "answer-support.values": judgment(
            "The extension record and approved guideline omit its length. The claimed duration remains unverified.",
            "duration_question",
            "duration",
            "update",
            outcome="unresolved",
        ),
    }
    if "acknowledgement" in turns:
        checks["communication-style.acknowledgement"] = judgment(
            "The Agent recognized the customer’s difficulty before checking the request.",
            "request",
            "acknowledgement",
        )
    return checks
