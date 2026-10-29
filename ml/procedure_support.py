"""Narrow refund-initiation checks, not general language understanding.

Recognised action forms are ABCD account lookup, validation-in-progress, entered
details and refund records, plus explicit validation-completion forms used in
constructed tests. Recognised speech is the finite policy/skip/correction forms
below and tested equivalents. Adjacent explicit quotation/repetition cues leave
the affected statement unattributed. Unmatched speech is never interpreted as fault.
"""

import re

from .abcd import conversation_passages, transcript_version
from .audit import category_result, quotation_context
from .citations import validate_citations
from .references import eligible_references, reference_issues, reference_passages

RULE_VERSION = "refund-initiation-procedure-support-v3"
SUPPORTED = {
    "account-lookup": "sha256:246f40ce9e1d2b814b533a4b06178296f9a23aeeb746cd9de6eed262106bea46",
    "purchase-validation": "sha256:93169ef390df0df481e67f916fec58c8bd21c17179ef42a2e90d345e6b86383a",
    "refund-details": "sha256:a698c20ea2a73a22649496d02336bb31ef713d3d9b6d14c9f98bceab8276b7cc",
    "refund-reason": "sha256:96b7f2c0b761b08608b17c2c582168d1a50494bdacd05f353c5e73d168c03eb3",
    "closing": "sha256:d8e63e4782173ee48cec0a9fa28c79cb7c97b8e3d517e2ac38321591d8b96823",
}
SKIPS = {
    "account-lookup": ("i skipped account lookup.", "i did not look up the account."),
    "purchase-validation": (
        "i skipped purchase validation.",
        "i processed the refund without validating the purchase.",
    ),
    "refund-reason": ("i did not ask for or receive a refund reason.",),
    "refund-details": (
        "i processed the refund without entering the required details.",
    ),
    "closing": (),
}
POLICY_FORMS = (
    (
        "validation-fields",
        "purchase-validation",
        "meets-criteria",
        r"(?:purchase validation requires a username, email(?: address)? and order id|(?:we|i) need your username, email(?: address)? and order id to validate (?:the|your) purchase)\.",
    ),
    (
        "validation-fields",
        "purchase-validation",
        "needs-review",
        r"(?:purchase validation requires only an email address|we do not need an order id to validate your purchase|you do not need to provide your username to validate the purchase)\.",
    ),
    (
        "address-details",
        "refund-details",
        "meets-criteria",
        r"for a (?:gift card|paper check) refund, we need your full address\.",
    ),
    (
        "address-details",
        "refund-details",
        "needs-review",
        r"(?:gift cards do not require an address|for a (?:gift card|paper check) refund, we do not need your full address)\.",
    ),
    (
        "account-details",
        "refund-details",
        "meets-criteria",
        r"for a (?:credit card|add value) refund, we need your account id\.",
    ),
    (
        "account-details",
        "refund-details",
        "needs-review",
        r"for a (?:credit card|add value) refund, we do not need your account id\.",
    ),
)
CLOSINGS = {
    "is there anything else i can help you with today?",
    "can i help with anything else?",
    "do you need any further assistance?",
}
CONTROL_SPEECH = CLOSINGS | {
    "hi!",
    "hello.",
    "thanks.",
    "thank you.",
    "have a great day.",
}
VALIDATION_SUCCESS = {"purchase validation succeeded.", "purchase has been validated."}
VALIDATION_ACTIVITY = VALIDATION_SUCCESS | {
    "purchase validation in progress ...",
    "purchase validation complete.",
}
REASONS = {
    "the item is the wrong size.",
    "the item was damaged.",
    "the item is damaged.",
    "the item looks different from the picture.",
    "i do not like the item.",
    "i don't like the item.",
    "because the item is damaged.",
}


def _text(event):
    return " ".join(event["text"].casefold().split())


def _check(
    rule,
    result,
    explanation,
    citations=(),
    advice="Inspect the cited evidence and the applicable approved requirement.",
):
    return {
        "rule_id": f"{RULE_VERSION}:{rule}",
        "result": result,
        "explanation": explanation,
        "advice": advice,
        "citations": list(citations),
    }


def _reported_check(rule, event, context, citations):
    return _check(
        rule,
        "cannot-assess",
        "Adjacent quotation or repetition context does not establish the agent's own admission or factual claim.",
        [citations[item["turn_id"]] for item in [event, *context]],
        "Review the cited context before attributing this statement to the agent.",
    )


def _method(events):
    methods = []
    unclear = False
    for event in events:
        if event["speaker"] != "customer":
            continue
        text = _text(event)
        matched = False
        for method in ("credit card", "gift card", "paper check", "add value"):
            forms = {
                f"i want a {method}.",
                f"i would like a {method}.",
                f"i'd like a {method} refund.",
                f"please refund my {method}.",
                f"i'd like it refunded to my {method}.",
                f"i'd like it to be refunded to me {method}. thanks",
            }
            if text in forms or (
                method == "add value" and text == "please add value to my account."
            ):
                methods.append((method, event))
                matched = True
        if not matched and (
            re.search(r"\b(?:gift card|paper check|credit card|add value)\b", text)
            or methods
            and re.search(
                r"\b(?:actually|instead|rather|change|different|maybe|perhaps)\b", text
            )
        ):
            unclear = True
    return (
        methods[0]
        if methods and not unclear and len({method for method, _ in methods}) == 1
        else (None, None)
    )


def _needs_recovery(events):
    return any(
        event["speaker"] == "customer"
        and re.search(
            r"(?:forgot|forget|don't remember|do not remember).*username", _text(event)
        )
        for event in events
    )


def _detail_evidence(events, method):
    if method in {"gift card", "paper check"}:
        for customer in events:
            address = re.fullmatch(
                r"my full address is (\[address_\d+\])\.", _text(customer)
            )
            if customer["speaker"] != "customer" or not address:
                continue
            action = next(
                (
                    event
                    for event in events
                    if event["kind"] == "action"
                    and event["turn_id"] > customer["turn_id"]
                    and _text(event) == f"details of {address[1]} have been entered."
                ),
                None,
            )
            if action:
                return [customer, action]
        return []
    return [
        event
        for event in events
        if event["kind"] == "action"
        and re.fullmatch(
            r"details of \[account_id_\d+\] have been entered\.", _text(event)
        )
    ]


def _prior_satisfaction(section, events, skip, method):
    prior = [event for event in events if event["turn_id"] < skip["turn_id"]]
    if section == "refund-reason":
        return [
            event
            for event in prior
            if event["speaker"] == "customer" and _text(event) in REASONS
        ]
    if section == "account-lookup":
        return [
            event
            for event in prior
            if event["kind"] == "action"
            and re.fullmatch(
                r"account has been pulled up for \[person_\d+\]\.", _text(event)
            )
        ]
    if section == "purchase-validation":
        return [
            event
            for event in prior
            if event["kind"] == "action" and _text(event) in VALIDATION_SUCCESS
        ]
    return _detail_evidence(prior, method) if section == "refund-details" else []


def _procedure(events, reference_for, citations, reported):
    checks, steps = [], []
    method, method_event = _method(events)
    recovery = _needs_recovery(events)
    for section in (
        "refund-reason",
        "account-lookup",
        "purchase-validation",
        "refund-details",
        "closing",
    ):
        skips = [
            event
            for event in events
            if event["speaker"] == "agent" and _text(event) in SKIPS[section]
        ]
        for event in skips:
            if event["turn_id"] in reported:
                checks.append(
                    _reported_check(
                        f"reported-{section}-{event['turn_id']}",
                        event,
                        reported[event["turn_id"]],
                        citations,
                    )
                )
        requirement, issue = reference_for(section)
        if section == "purchase-validation" and recovery:
            check = _check(
                section,
                "cannot-assess",
                "Account recovery is needed, but reviewed recovery guidance is unavailable; standard validation rules cannot establish a breach.",
                ([requirement] if requirement else [])
                + [
                    citations[event["turn_id"]]
                    for event in events
                    if _needs_recovery([event])
                ],
            )
        elif section == "refund-details" and method is None:
            check = _check(
                section,
                "cannot-assess",
                "The selected method or its change is unknown, so a required-details breach cannot be established.",
                [requirement] if requirement else [],
            )
        elif issue:
            check = _check(section, "cannot-assess", issue)
        else:
            skip = next(
                (event for event in skips if event["turn_id"] not in reported),
                None,
            )
            satisfied = (
                _prior_satisfaction(section, events, skip, method) if skip else []
            )
            if (
                skip
                and section == "refund-details"
                and method_event["turn_id"] > skip["turn_id"]
            ):
                check = _check(
                    section,
                    "cannot-assess",
                    "The method was selected after the statement; its required branch cannot be applied retrospectively.",
                    [requirement, citations[skip["turn_id"]]],
                )
            elif skip and satisfied:
                check = _check(
                    section,
                    "cannot-assess",
                    "The statement conflicts with earlier evidence satisfying this requirement; a skipped step is not established.",
                    [
                        requirement,
                        citations[skip["turn_id"]],
                        *[citations[event["turn_id"]] for event in satisfied],
                    ],
                )
            elif skip:
                check = _check(
                    section,
                    "needs-review",
                    "The agent explicitly states that the required step was not performed.",
                    [requirement, citations[skip["turn_id"]]],
                    "Follow the cited requirement; do not treat a later action as erasing this admission.",
                )
            else:
                observed = []
                result = "cannot-assess"
                explanation = "No recognised evidence establishes this step; absence is not a skipped step."
                if section == "refund-reason":
                    observed = [
                        event
                        for event in events
                        if event["speaker"] == "customer" and _text(event) in REASONS
                    ]
                    if observed:
                        result, explanation = (
                            "meets-criteria",
                            "The customer supplied a recognised refund reason; no repeated question is required.",
                        )
                elif section == "account-lookup":
                    observed = [
                        event
                        for event in events
                        if event["kind"] == "action"
                        and re.fullmatch(
                            r"account has been pulled up for \[person_\d+\]\.",
                            _text(event),
                        )
                    ]
                    if observed:
                        result, explanation = (
                            "meets-criteria",
                            "Account lookup is recorded. This does not establish identity or refund authority.",
                        )
                elif section == "purchase-validation":
                    observed = [
                        event
                        for event in events
                        if event["kind"] == "action"
                        and _text(event) in VALIDATION_ACTIVITY
                    ]
                    complete = [
                        event
                        for event in observed
                        if _text(event) in VALIDATION_SUCCESS
                    ]
                    if complete:
                        preceding_customers = [
                            event
                            for event in events
                            if event["speaker"] == "customer"
                            and event["turn_id"] < complete[0]["turn_id"]
                        ]
                        before = " ".join(
                            event["text"] for event in preceding_customers
                        )
                        if all(
                            re.search(r"\[" + field + r"_\d+\]", before)
                            for field in ("USERNAME", "EMAIL", "ORDER_ID")
                        ):
                            result, explanation = (
                                "meets-criteria",
                                "Standard purchase fields precede an explicit recorded validation completion.",
                            )
                            observed = preceding_customers + complete
                        else:
                            explanation = "Validation completion is recorded, but the standard input checks cannot be established."
                    elif observed:
                        explanation = (
                            "Validation is recorded as in progress; this is not evidence of successful validation."
                            if any(
                                _text(event) == "purchase validation in progress ..."
                                for event in observed
                            )
                            else "Validation activity is complete, but no successful outcome is stated."
                        )
                elif section == "refund-details":
                    observed = _detail_evidence(events, method)
                    if observed:
                        observed = [method_event, *observed]
                        result, explanation = (
                            "meets-criteria",
                            "Recorded details match the recognised selected-method branch, not refund authority.",
                        )
                    else:
                        explanation = "The selected method is recognised, but its required detail entry is not established."
                elif section == "closing":
                    closings = [
                        event
                        for event in events
                        if event["speaker"] == "agent" and _text(event) in CLOSINGS
                    ]
                    observed = [
                        event for event in closings if event["turn_id"] not in reported
                    ]
                    if observed:
                        result, explanation = (
                            "meets-criteria",
                            "A recognised equivalent offer of further assistance is present; no vocal tone is inferred.",
                        )
                    elif closings:
                        explanation = "Only reported or repeated closing wording is present; the agent's own offer of further assistance is not established."
                        observed = [
                            evidence
                            for event in closings
                            for evidence in [event, *reported[event["turn_id"]]]
                        ]
                check = _check(
                    section,
                    result,
                    explanation,
                    [requirement, *[citations[event["turn_id"]] for event in observed]],
                )
        checks.append(check)
        steps.append(
            {
                "step": section,
                "result": check["result"],
                "explanation": check["explanation"],
            }
        )
    ordering = [
        event
        for event in events
        if event["speaker"] == "agent"
        and _text(event) == "i validated the purchase before the first account lookup."
    ]
    for event in ordering:
        if event["turn_id"] in reported:
            checks.append(
                _reported_check(
                    f"reported-order-{event['turn_id']}",
                    event,
                    reported[event["turn_id"]],
                    citations,
                )
            )
    ordering = [event for event in ordering if event["turn_id"] not in reported]
    if ordering and recovery:
        checks.append(
            _check(
                "unavailable-recovery-order",
                "cannot-assess",
                "Reviewed recovery guidance is unavailable, so the standard validation-order rule is not applicable.",
                [citations[ordering[0]["turn_id"]]],
            )
        )
    elif ordering:
        lookup, lookup_issue = reference_for("account-lookup")
        validation, validation_issue = reference_for("purchase-validation")
        if not lookup_issue and not validation_issue:
            checks.append(
                _check(
                    "explicit-order-breach",
                    "needs-review",
                    "The agent explicitly describes reversing the required lookup/validation sequence.",
                    [lookup, validation, citations[ordering[0]["turn_id"]]],
                )
            )
    elif {"refund-reason", "account-lookup", "purchase-validation"} <= {
        step["step"] for step in steps if step["result"] == "meets-criteria"
    }:
        lookups = [
            event
            for event in events
            if event["kind"] == "action"
            and re.fullmatch(
                r"account has been pulled up for \[person_\d+\]\.", _text(event)
            )
        ]
        validations = [
            event
            for event in events
            if event["kind"] == "action" and _text(event) in VALIDATION_SUCCESS
        ]
        if lookups[0]["turn_id"] > validations[0]["turn_id"]:
            checks.append(
                _check(
                    "observed-order",
                    "cannot-assess",
                    "The recorded order does not establish the required prerequisite order; an earlier unrecorded action cannot be ruled out.",
                    [
                        citations[lookups[0]["turn_id"]],
                        citations[validations[0]["turn_id"]],
                    ],
                )
            )
    return checks, steps


def _answers(events, reference_for, citations, reported):
    checks, claims = [], []
    for event in events:
        if event["speaker"] != "agent":
            continue
        text = _text(event)
        correction = text.startswith("correction: ")
        candidate = text.removeprefix("correction: ")
        matched = next(
            (form for form in POLICY_FORMS if re.fullmatch(form[3], candidate)), None
        )
        if matched:
            if event["turn_id"] in reported:
                checks.append(
                    _reported_check(
                        f"reported-claim-{event['turn_id']}",
                        event,
                        reported[event["turn_id"]],
                        citations,
                    )
                )
                continue
            family, section, state, _ = matched
            if family in {"address-details", "account-details"}:
                condition = next(
                    method
                    for method in (
                        "gift card",
                        "paper check",
                        "credit card",
                        "add value",
                    )
                    if method in candidate
                )
                family += ":" + condition
            requirement, issue = reference_for(section)
            if section == "purchase-validation" and _needs_recovery(events):
                issue = "Account recovery is needed, but reviewed recovery guidance is unavailable."
            check = _check(
                f"claim-{family}-{event['turn_id']}",
                "cannot-assess" if issue else state,
                issue
                or (
                    "The recognised factual statement agrees with the approved requirement."
                    if state == "meets-criteria"
                    else "The explicit factual statement contradicts the approved requirement."
                ),
                [citations[event["turn_id"]]]
                if issue
                else [requirement, citations[event["turn_id"]]],
                "Use the approved requirement, including its conditions, rather than the contradicted statement.",
            )
            if correction and state == "meets-criteria" and not issue:
                for previous in claims:
                    if (
                        previous["family"] == family
                        and previous["check"]["result"] == "needs-review"
                    ):
                        earlier = previous["check"]
                        earlier.update(
                            result="meets-criteria",
                            explanation="An explicit correction is linked to the same factual claim.",
                        )
                        earlier["citations"].extend(check["citations"])
                        previous["state"] = "corrected"
            checks.append(check)
            claims.append(
                {
                    "family": family,
                    "turn_id": event["turn_id"],
                    "state": check["result"],
                    "check": check,
                }
            )
        elif text.startswith(
            (
                "correction:",
                "actually, that's not correct",
                "actually, that is not correct",
            )
        ):
            checks.append(
                _check(
                    f"unclear-correction-{event['turn_id']}",
                    "cannot-assess",
                    "The correction is outside the explicitly supported claim forms.",
                    [citations[event["turn_id"]]],
                )
            )
        elif text not in CONTROL_SPEECH:
            checks.append(
                _check(
                    f"unrecognised-answer-{event['turn_id']}",
                    "cannot-assess",
                    "This statement is outside the supported factual forms, or requires unavailable refund/identity authority.",
                    [citations[event["turn_id"]]],
                )
            )
    if not checks:
        checks.append(
            _check(
                "no-supported-claims",
                "cannot-assess",
                "No factual answer in the supported forms was established.",
            )
        )
    return checks, [
        {key: value for key, value in claim.items() if key != "check"}
        for claim in claims
    ]


def check_procedure_support(
    conversation: dict, references: list[dict], *, as_of: str, scope: str
) -> list[dict]:
    """Assess only documented forms within exact, approved interpretation versions."""
    if conversation.get("transcript_version") != transcript_version(conversation):
        raise ValueError("Transcript version does not match the evidence.")
    eligible = eligible_references(references, as_of=as_of, scope=scope)
    supported = {
        reference["section_id"]: reference
        for reference in eligible
        if SUPPORTED.get(reference["section_id"]) == reference["version"]
    }
    citation_map = {
        passage["citation"]["turn_id"]: passage["citation"]
        for passage in conversation_passages([conversation])
    }
    requirement_map = {
        passage["id"]: passage["citation"]
        for passage in reference_passages(list(supported.values()))
    }

    def reference_for(section):
        reference = supported.get(section)
        if reference:
            return requirement_map[reference["id"]], None
        original = next(
            (
                reference
                for reference in references
                if isinstance(reference, dict)
                and reference.get("section_id") == section
            ),
            None,
        )
        reasons = reference_issues(original, as_of=as_of, scope=scope)
        reason = (
            "; ".join(reasons)
            if reasons
            else "The approved interpretation version is not supported by these rules."
        )
        return None, f"Cannot assess {section}: {reason}"

    events = conversation["events"]
    reported = {
        event["turn_id"]: context
        for position, event in enumerate(events)
        if event["speaker"] == "agent"
        and (context := quotation_context(events, position))
    }
    procedure_checks, steps = _procedure(events, reference_for, citation_map, reported)
    answers, claims = _answers(events, reference_for, citation_map, reported)
    if conversation["coverage"]["transcript"]["status"] != "complete":
        limitation = _check(
            "partial-transcript",
            "cannot-assess",
            "Transcript coverage is partial or unknown; omitted context cannot be inferred.",
        )
        procedure_checks.append(limitation)
        answers.append(dict(limitation))
    all_citations = [
        citation
        for check in [*procedure_checks, *answers]
        for citation in check["citations"]
    ]
    if validate_citations(all_citations, [conversation], list(supported.values())):
        raise ValueError("Procedure/support checks produced an invalid citation.")
    trace = [
        {
            "id": reference["id"],
            "version": reference["version"],
            "interpretation_limits": list(reference.get("interpretation_limits", [])),
        }
        for reference in supported.values()
    ]
    return [
        category_result(
            conversation,
            "procedure",
            procedure_checks,
            details={
                "steps": steps,
                "reference_limits": trace,
                "scope_limit": "Only supported approved steps; no identity, refund-authority or amount-policy conclusion.",
            },
        ),
        category_result(
            conversation,
            "answer-support",
            answers,
            details={"claims": claims, "reference_limits": trace},
        ),
    ]
