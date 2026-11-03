"""Narrow request links and wording checks for the refund-initiation experiment.

Recognised requests use explicit want/need/would-like, please, or can-you forms
for a refund, returning an item, a refund method, or explaining the next step.
Explicit "actually ... instead" replacements and unambiguous cancellations
preserve their source links. Answers, actionable promises and recorded actions
can address a request; only an explicit recorded outcome establishes completion
within the supplied record, not independent transaction success or authority.

Wording positives require a closed inventory of agent utterances: greetings,
explicit refund/return acknowledgements, supported instructions, response forms,
thanks and closings. The only negative wording forms are a direct personal insult
or the explicit contradictory order-ID instruction below. Everything else is
uninterpreted, not bad. These patterns do not provide general language understanding.
An adjacent repeat/quote request or reporting introduction/attribution makes a
matching negative phrase or request response uncertain. Reported answers and
promises cannot address a request or clear a refusal; an apology alone cannot
erase an insult. Capability wording such as "I can process" is not a promise;
commitments require "I will" or "I'll". Quoted customer wording cannot create or
change requests. An unsupported explicit change leaves candidate requests
uncertain until a supported clarification resolves them; no new intent is guessed.
The same request grammar applies to separate turns and explicit clauses; citations
always identify the original source turn rather than invented clause positions.
Clause separators inside single ASCII, curly or backtick spans stay quoted.
Unmatched quotes or unsupported delimiter runs leave the rest uninterpreted.
Question marks are meaningful: only explicit can-you requests/instructions and the known
closing question are recognised as questions, not assertion-shaped questions.
"""

import re

from .abcd import conversation_passages, transcript_version
from .audit import (
    category_result,
    criteria_issues,
    eligible_criteria,
)
from .references import eligible_references, reference_passages
from .wording import quotation_context

RULE_VERSION = "refund-initiation-completeness-style-v5"
CRITERION_VERSIONS = {
    "clarity": "sha256:0a3402a0f339e93d82e5a2bc79504b592659a1913c835ee55feb100c10734e39",
    "respect": "sha256:0a8f546f87b4f980619ed49012e4935be9f788e9b3b96f532013d79ff1ec1ce1",
    "acknowledgement": "sha256:21f20fe4d1147f49d1431aadffaae60e154470b2024542e0a0241b197e4f9f1a",
}
METHODS = {
    "credit card": "credit-card",
    "gift card": "gift-card",
    "paper check": "paper-check",
    "account": "account",
}
TRANSACTION = (
    r"(?:i (?:want|need|would like|would like to get)|i'd like) (?:a |my )?refund"
)
RETURN = r"(?:i (?:want|need|would like)|i'd like) to return (?:an|the|my|this) item"
REFUND_REQUESTS = (
    TRANSACTION,
    r"please (?:refund my purchase|issue (?:a|my) refund)",
    r"can you (?:refund (?:my purchase|the item|me)|issue (?:a|my) refund)",
)
RETURN_REQUESTS = (
    RETURN,
    r"please (?:return (?:the|my|this) item|help me return (?:the|my) item)",
    r"can you help me return (?:the|my|this) item",
)
NEXT_STEP = r"(?:please explain|can you (?:explain|tell me)) the next step"
METHOD_REQUEST = r"(?:please use (?:my |a )?|(?:i'd|i would) like (?:it to be refunded to (?:my |a )?|a ))(credit card|gift card|paper check|account)"
COURTESY = r"(?:hi|hello|hey|hi there|yes|no|sure|ok|okay|thanks|thank you|thanks for your help|no thanks|that's all|bye|have a great day|thank you and have a great day)"
GREETING = r"(?:hello|hi)(?: \[person_\d+\])?"
ACKNOWLEDGEMENT = r"(?:i (?:understand|see) (?:you want|you'd like)|i can help (?:you )?with (?:your|the)) (refund|return)"
PROMISE = r"(?:i will|i'll) (?:process|sort|help with) (?:your|the) (refund|return)"
METHOD_PROMISE = r"(?:i will|i'll) refund it to (?:your |a )?(credit card|gift card|paper check|account)"
REFUSAL = r"i (?:will not|won't) address your (refund|return) request"
INSTRUCTION = r"(?:please (?:provide|give me)|can you (?:provide|give me)) your username,? email(?: address)? and order id"
NEXT_ANSWER = r"the next step is to provide your order id"
INSULT = r"(?:you are|you're) (?:an idiot|stupid)"
CONTRADICTION = "provide your order id and do not provide your order id"


def _normal(text):
    return " ".join(text.casefold().replace("’", "'").split()).rstrip(".!")


def _customer_clauses(text):
    text = " ".join(text.casefold().split())
    quotes = {'"': '"', "'": "'", "“": "”", "‘": "’", "`": "`"}
    separator = re.compile(
        r";\s*| and (?=(?:please|can you|i (?:want|need|would like))\b)"
    )
    start = position = 0
    closing = None
    while position < len(text):
        character = text[position]
        if (
            character in "'’"
            and position
            and position + 1 < len(text)
            and text[position - 1].isalnum()
            and text[position + 1].isalnum()
        ):
            pass
        elif closing:
            if character == "\\":
                position += 2
                continue
            if character == closing:
                closing = None
        elif character in quotes:
            if position + 1 < len(text) and text[position + 1] == character:
                break
            closing = quotes[character]
        elif character in "”’":
            break
        elif match := separator.match(text, position):
            yield text[start:position]
            position = start = match.end()
            continue
        position += 1
    yield text[start:]


def _request(text):
    if text.endswith("?"):
        if not text.startswith("can you "):
            return None
        text = text[:-1]
    if any(re.fullmatch(pattern, text) for pattern in REFUND_REQUESTS):
        return "refund", None
    if any(re.fullmatch(pattern, text) for pattern in RETURN_REQUESTS):
        return "return", None
    if re.fullmatch(NEXT_STEP, text):
        return "next-step", None
    match = re.fullmatch(METHOD_REQUEST, text)
    return ("method", METHODS[match[1]]) if match else None


def _agent_form(text):
    """Return only explicit forms; a missing match is never a negative finding."""
    if text.endswith("?"):
        text = text[:-1]
        if text != "is there anything else i can help you with" and not (
            text.startswith("can you ") and re.fullmatch(INSTRUCTION, text)
        ):
            return "unknown", None
    for pattern, kind in (
        (ACKNOWLEDGEMENT, "acknowledgement"),
        (PROMISE, "promise"),
        (METHOD_PROMISE, "method-promise"),
        (REFUSAL, "refusal"),
    ):
        match = re.fullmatch(pattern, text)
        if match:
            value = METHODS.get(match[1], match[1])
            return kind, value
    if re.fullmatch(INSTRUCTION, text):
        return "instruction", None
    if text == NEXT_ANSWER:
        return "answer", "next-step"
    if re.fullmatch(r"(?:your|the) refund is in progress", text):
        return "answer", "refund"
    if re.fullmatch(r"i have credited your card for \$\d+(?:\.\d{2})?", text):
        return "method-answer", "credit-card"
    if re.fullmatch(r"your refund is \$\d+(?:\.\d{2})?", text):
        return "answer", "refund"
    if re.fullmatch(GREETING, text) or re.fullmatch(COURTESY, text):
        return "courtesy", None
    if text == "is there anything else i can help you with":
        return "closing", None
    if re.fullmatch(INSULT, text):
        return "insult", None
    if text == CONTRADICTION:
        return "contradiction", None
    return "unknown", None


def _check(rule, result, explanation, citations, advice):
    return {
        "rule_id": f"{RULE_VERSION}:{rule}",
        "result": result,
        "explanation": explanation,
        "advice": advice,
        "citations": citations,
    }


def _applies(request, form, value):
    if form in ("method-promise", "method-answer"):
        return request["topic"] == "refund" or (
            request["topic"] == "method" and request["method"] == value
        )
    return request["topic"] == value


def _request_links(conversation, citations):
    requests, unknown, agent_forms = [], [], []

    def uncertain(candidates, citation):
        for request in candidates:
            request["state"] = "uncertain"
            request["change_citations"].append(citation)

    def customer_clause(text, citation, turn):
        active = [
            request
            for request in requests
            if request["state"] in ("active", "uncertain")
        ]
        if text in (
            "actually, the item is not shipped yet",
            "the item has not shipped yet",
        ):
            if len(active) == 1:
                active[0]["change_citations"].append(citation)
            else:
                uncertain(active, citation)
                unknown.append(citation)
            return
        replacement = re.fullmatch(
            r"(?:actually|i mean)\b(?:,\s*|\s+)?(.*?)(?: instead)?", text
        )
        if replacement and (request := _request(replacement[1])):
            related = [
                item
                for item in active
                if item["topic"] == request[0]
                or {item["topic"], request[0]} <= {"refund", "return"}
            ]
            if len(related) != 1:
                uncertain(related or active, citation)
                unknown.append(citation)
                return
            related[0]["state"] = "superseded"
            related[0]["change_citations"].append(citation)
            text = replacement[1]
        elif replacement:
            uncertain(active, citation)
            unknown.append(citation)
            return
        else:
            withdrawal = re.fullmatch(
                r"(?:cancel (?:the |my )?(refund|return) request|never mind|cancel that request|i don't need that anymore)",
                text,
            )
            if withdrawal:
                targets = [
                    item
                    for item in active
                    if not withdrawal[1] or item["topic"] == withdrawal[1]
                ]
                if len(targets) == 1:
                    targets[0]["state"] = "withdrawn"
                    targets[0]["change_citations"].append(citation)
                else:
                    uncertain(targets, citation)
                    unknown.append(citation)
                return
            if re.fullmatch(COURTESY, text) or re.fullmatch(
                r"(?:my (?:name|username|email|order id|account id) is )?\[[a-z_]+_\d+\](?:[,; ]+\[[a-z_]+_\d+\])*",
                text,
            ):
                return
        parsed = _request(text)
        if parsed is None:
            unknown.append(citation)
            return
        topic, method = parsed
        requests.append(
            {
                "id": f"{conversation['id']}:request:{turn}:{len(requests) + 1}",
                "topic": topic,
                "method": method,
                "state": "active",
                "request_citations": [citation],
                "change_citations": [],
                "response_citations": [],
                "response_kind": None,
                "recorded_completion_observed": False,
            }
        )

    for position, event in enumerate(conversation["events"]):
        text, turn = _normal(event["text"]), event["turn_id"]
        citation = citations[turn]
        if event["speaker"] == "customer":
            context = quotation_context(conversation["events"], position)
            if context:
                unknown.extend(
                    [citation, *[citations[cue["turn_id"]] for cue in context]]
                )
            else:
                for clause in _customer_clauses(event["text"]):
                    if clause:
                        customer_clause(_normal(clause), citation, turn)
            continue
        active = [request for request in requests if request["state"] == "active"]
        if event["speaker"] == "action":
            if re.fullmatch(
                r"a refund has been made for the amount of \$\d+(?:\.\d{2})?", text
            ):
                form, value = "observed-action", "refund"
            elif (
                re.fullmatch(r"account has been pulled up for \[person_\d+\]", text)
                or text == "purchase validation in progress "
                or text == "purchase validation in progress"
                or re.fullmatch(
                    r"(?:a reason of .+ has been recorded|details of \[[a-z_]+_\d+\] have been entered)",
                    text,
                )
            ):
                continue
            else:
                unknown.append(citation)
                continue
        else:
            form, value = _agent_form(text)
            if form != "unknown":
                context = quotation_context(conversation["events"], position)
                if context:
                    form = "unknown"
                    unknown.extend(citations[cue["turn_id"]] for cue in context)
            agent_forms.append(
                (
                    event,
                    form,
                    value,
                    any(_applies(request, form, value) for request in active),
                )
            )
            if form == "unknown":
                unknown.append(citation)
                continue
        for request in active:
            if form not in (
                "promise",
                "method-promise",
                "answer",
                "method-answer",
                "observed-action",
                "refusal",
            ) or not _applies(request, form, value):
                continue
            request["response_citations"].append(citation)
            request["response_kind"] = "promise" if "promise" in form else form
            request["recorded_completion_observed"] |= form == "observed-action"
    return requests, unknown, agent_forms


def _completeness_result(conversation, requests, unknown, limits):
    checks = []
    for request in requests:
        evidence = (
            request["request_citations"]
            + request["change_citations"]
            + request["response_citations"]
        )
        if request["state"] in ("withdrawn", "superseded"):
            result, reason = (
                "meets-criteria",
                "The request was explicitly withdrawn or superseded; it is not an unanswered active request.",
            )
        elif request["response_kind"] == "refusal":
            result, reason = (
                "needs-review",
                "The agent explicitly stated that this request would not be addressed.",
            )
        elif request["state"] == "uncertain":
            result, reason = (
                "cannot-assess",
                "An explicit change is unresolved; later wording cannot be confidently linked to this request.",
            )
        elif request["response_kind"]:
            result, reason = (
                "meets-criteria",
                "A directly linked response addresses this request; a promise or answer does not establish completed action.",
            )
        else:
            result, reason = (
                "cannot-assess",
                "No confidently linked response is recognised; absence does not prove that the request was ignored.",
            )
        checks.append(
            _check(
                "request-" + request["id"],
                result,
                reason,
                evidence,
                "Explain the response or next step for this particular request; verify outcomes separately.",
            )
        )
    if (
        unknown
        or not requests
        or conversation["coverage"]["transcript"]["status"] != "complete"
    ):
        checks.append(
            _check(
                "request-inventory",
                "cannot-assess",
                "The request inventory or surrounding wording is partial, unrecognised or reported/repeated; a complete assessment is unavailable.",
                unknown,
                "Review the surrounding transcript and clarify any additional or changed requests.",
            )
        )
    return category_result(
        conversation,
        "completeness",
        checks,
        details={
            "requests": requests,
            "guideline_limits": limits,
            "outcome_basis": "Recorded outcomes are source observations, not independent transaction verification or refund authority.",
            "recognition_boundary": "Only the explicit request and response forms documented in this module are recognised.",
        },
    )


def _style_result(
    conversation, criteria, requests, unknown, forms, citations, *, as_of, scope
):
    approved = {
        ref["section_id"]: ref
        for ref in eligible_criteria(criteria, as_of=as_of, scope=scope)
        if CRITERION_VERSIONS.get(ref["section_id"]) == ref["version"]
    }
    checks, states = [], []
    for criterion in criteria:
        reasons = criteria_issues(criterion, as_of=as_of, scope=scope)
        if (
            isinstance(criterion, dict)
            and criterion.get("section_id") in CRITERION_VERSIONS
        ):
            if criterion.get("version") != CRITERION_VERSIONS[criterion["section_id"]]:
                reasons = [
                    *reasons,
                    "This rubric version or its interpretation limits are not supported by these wording rules.",
                ]
            states.append(
                {
                    "id": criterion.get("id"),
                    "version": criterion.get("version"),
                    "limitations": reasons,
                }
            )
    for section in ("clarity", "respect", "acknowledgement"):
        criterion = approved.get(section)
        if criterion is None:
            checks.append(
                _check(
                    section,
                    "cannot-assess",
                    f"No eligible, supported {section} rubric section is available.",
                    [],
                    "Obtain human approval of the applicable rubric version before making a style judgement.",
                )
            )
            continue
        rule_citation = reference_passages([criterion])[0]["citation"]
        negatives = [
            event
            for event, form, _, _ in forms
            if form == ("contradiction" if section == "clarity" else "insult")
            and section != "acknowledgement"
        ]
        positives = [
            event
            for event, form, value, targets_active in forms
            if (
                section == "clarity"
                and form in ("instruction", "answer")
                and value in (None, "next-step")
            )
            or (
                section == "respect"
                and form in ("courtesy", "instruction")
                and re.match(
                    r"(?:please|thanks|thank you|can you)", _normal(event["text"])
                )
            )
            or (
                section == "acknowledgement"
                and form
                in (
                    "acknowledgement",
                    "promise",
                    "method-promise",
                    "answer",
                    "method-answer",
                )
                and targets_active
            )
        ]
        if negatives:
            result, reason, selected = (
                "needs-review",
                f"A directly recognised {section} violation is present in the agent's own wording.",
                negatives,
            )
        elif (
            positives
            and not unknown
            and conversation["coverage"]["transcript"]["status"] == "complete"
            and (
                section != "acknowledgement"
                or all(
                    request["state"] != "active" or request["response_citations"]
                    for request in requests
                )
            )
        ):
            result, reason, selected = (
                "meets-criteria",
                f"The recognised wording supports {section} within this narrow rubric.",
                positives,
            )
        else:
            result, reason, selected = (
                "cannot-assess",
                f"The wording or context is outside the supported {section} patterns; this is not evidence of a fault.",
                [],
            )
        checks.append(
            _check(
                section,
                result,
                reason,
                [rule_citation, *[citations[event["turn_id"]] for event in selected]],
                "Use a clear, relevant response without personal insults; unfamiliar phrasing requires human review, not automatic fault.",
            )
        )
    return category_result(
        conversation,
        "communication-style",
        checks,
        details={
            "rubric_states": states,
            "recognition_boundary": "Wording only; no emotion, intent, personality, satisfaction or vocal-tone inference.",
        },
    )


def check_completeness_style(conversation, references, criteria, *, as_of, scope):
    """Check only recognised wording; callers supply validated masked evidence."""
    try:
        current_version = transcript_version(conversation)
        if conversation["transcript_version"] != current_version:
            raise ValueError("Transcript version does not match its evidence.")
    except (KeyError, TypeError):
        raise ValueError("Invalid conversation evidence.") from None
    guidelines = eligible_references(references, as_of=as_of, scope=scope)
    if scope != "refund-initiation":
        checks = [
            _check(
                "unsupported-scope",
                "cannot-assess",
                "These request and wording patterns cover refund initiation only.",
                [],
                "Use reviewed rules appropriate to the conversation's scope.",
            )
        ]
        return [
            category_result(conversation, category, checks)
            for category in ("completeness", "communication-style")
        ]
    limits = [
        {
            "id": ref["id"],
            "version": ref["version"],
            "interpretation_limits": list(ref.get("interpretation_limits", [])),
        }
        for ref in guidelines
    ]
    passages = conversation_passages([conversation])
    citations = {
        passage["citation"]["turn_id"]: passage["citation"] for passage in passages
    }
    requests, unknown, forms = _request_links(conversation, citations)
    return [
        _completeness_result(conversation, requests, unknown, limits),
        _style_result(
            conversation,
            criteria,
            requests,
            unknown,
            forms,
            citations,
            as_of=as_of,
            scope=scope,
        ),
    ]
