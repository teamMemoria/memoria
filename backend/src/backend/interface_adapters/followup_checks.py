"""Local evidence gates for Luna's unresolved-check proposals."""

import re

from ml.metrics.followup_task import proposals
from ml.metrics.resolution_claims import recorded_resolution_claims
from ml.wording import quotation_context

from backend.entities.guidelines import SHIPPING_FEE
from backend.interface_adapters.call_checks import ACKNOWLEDGE

PURPOSE = re.compile(
    r"\b(?:refund|return|cancel|exchange|upgrade|delay|shipping|delivery|order|password|"
    r"username|promo|coupon|discount|website|cart|subscription|billing|price|jacket|"
    r"shirt|boots|jeans|charge|membership|payment)\b",
    re.IGNORECASE,
)
ASK = re.compile(
    r"\?|\b(?:i need|i want|i would like|i['’]d like|please|i was hoping)\b",
    re.IGNORECASE,
)
IMPERATIVE = re.compile(
    r"^(?:please )?(?:cancel|refund|return|change|upgrade) (?:it|the|my)\b",
    re.IGNORECASE,
)
ATTRIBUTED = re.compile(
    r"\b(?:said|told (?:me|us|you)|wrote|quoted|if|might)\b", re.IGNORECASE
)
DISMISSIVE = re.compile(
    r"\b(?:idiot|stupid|shut up|not my problem|moron)\b", re.IGNORECASE
)
CORRECTED = re.compile(
    r"\b(?:actually|instead|never mind|changed my mind|forget that|no longer|scratch that)\b",
    re.IGNORECASE,
)
CLAIM = re.compile(
    r"\b(?:has been|have been|was|were|i['’]ve|i have|i just)\b.{0,55}"
    r"\b(?:refunded|issued|processed|cancel(?:l)?ed|changed|updated|completed|sent|notified|shipped|waived|extended|generated|pulled up|opened)\b"
    r"|\b(?:refund(?:ed)?|cancel(?:l)?ed|changed|updated|sent|waived|extended|opened)\b.{0,40}"
    r"\b(?:done|complete|your|the order|the fee)\b",
    re.IGNORECASE,
)
VALUE = re.compile(
    r"\$\s*\d+(?:\.\d+)?|\b\d+(?:\.\d+)?\s*(?:%|percent|dollars?|cents?|days?|weeks?|months?|years?|hours?|minutes?|business days?)\b",
    re.IGNORECASE,
)


def _unquoted(events, position):
    return not quotation_context(events, position) and not any(
        mark in events[position]["text"] for mark in '"“”'
    )


def _topics(turn):
    return {word.casefold() for word in PURPOSE.findall(turn["text"])}


def _anchored_acknowledgement(events):
    if any(t["speaker"] == "agent" and DISMISSIVE.search(t["text"]) for t in events):
        return
    for pos, turn in enumerate(events):
        if turn["speaker"] != "customer" or not (
            (ASK.search(turn["text"]) or IMPERATIVE.search(turn["text"]))
            and PURPOSE.search(turn["text"])
        ):
            continue
        if not _unquoted(events, pos):
            continue
        for index in range(pos + 1, min(pos + 4, len(events))):
            reply = events[index]
            if reply["speaker"] == "customer":
                if (
                    "?" in reply["text"]
                    or IMPERATIVE.search(reply["text"])
                    or CORRECTED.search(reply["text"])
                ):
                    break
                continue
            if reply["speaker"] == "action":
                continue
            if (
                re.search(
                    ACKNOWLEDGE
                    + r"|\b(?:i understand(?: your| how)|i(?:['’]m| am) sorry to hear|i can do that for you|i(?:['’]d| would) be (?:glad|happy) to (?:do that|help))\b",
                    reply["text"],
                    re.IGNORECASE,
                )
                and _unquoted(events, index)
                and not ATTRIBUTED.search(reply["text"])
            ):
                yield (
                    "communication-style.acknowledgement",
                    "supported",
                    "The Agent acknowledged the customer's stated request or problem.",
                    [turn, reply],
                )
            break


def _single_topic_reply(events):
    """Verify short, direct replies only when the exchange has one identifiable ask."""
    questions = [
        (i, turn)
        for i, turn in enumerate(events)
        if turn["speaker"] == "customer"
        and ASK.search(turn["text"])
        and PURPOSE.search(turn["text"])
    ]
    if len(questions) != 1 or any(
        t["speaker"] == "customer" and CORRECTED.search(t["text"]) for t in events
    ):
        return
    index, request = questions[0]
    if not _unquoted(events, index):
        return
    topics = _topics(request)
    for pos in range(index + 1, min(index + 7, len(events))):
        turn = events[pos]
        if (
            turn["speaker"] != "agent"
            or not _unquoted(events, pos)
            or ATTRIBUTED.search(turn["text"])
        ):
            continue
        if "?" in turn["text"] or not topics & _topics(turn):
            continue
        if not re.search(
            r"\b(?:please (?:return|send|check|refresh)|you can (?:return|exchange|cancel|reset|check|find)|"
            r"(?:refund|delivery|shipping|membership|subscription|promo code|return) (?:is|will be|costs|lasts|expires))\b",
            turn["text"],
            re.IGNORECASE,
        ):
            continue
        yield (
            "completeness.direct_response",
            "supported",
            "The Agent directly gave an answer or concrete instruction on the customer's stated topic.",
            [request, turn],
        )
        yield (
            "communication-style.clarity",
            "supported",
            "The Agent stated the answer or next step explicitly in the linked response.",
            [request, turn],
        )
        break


def _pending_delivery_step(events):
    """Verify a concrete waiting step with an explicit pending delivery status."""
    for index, turn in enumerate(events):
        if (
            turn["speaker"] != "agent"
            or not _unquoted(events, index)
            or not re.search(
                r"\b(?:it['’]s possible|it is possible|may|might)\b.{0,55}\b(?:delivered|arrive)\b",
                turn["text"],
                re.IGNORECASE,
            )
            or not re.search(
                r"\bplease (?:give it|wait) (?:a few|several|[0-9]+)(?: more)? days\b",
                turn["text"],
                re.IGNORECASE,
            )
        ):
            continue
        replies = [t for t in events[index + 1 :] if t["speaker"] != "action"]
        if (
            not replies
            or replies[0]["speaker"] != "customer"
            or not re.match(
                r"^(?:ok(?:ay)?[, ]+)?i can do that\b",
                replies[0]["text"],
                re.IGNORECASE,
            )
        ):
            continue
        if any(
            t["speaker"] == "agent"
            and t is not turn
            and re.search(
                r"\b(?:i|we) (?:will|am going to|plan to|need to) (?:send|call|email|change|refund|notify|process|file|follow up)\b",
                t["text"],
                re.IGNORECASE,
            )
            for t in events
        ):
            continue
        if any(
            t["speaker"] == "customer"
            and re.search(
                r"\b(?:haven['’]t|have not|did not|didn['’]t) received?\b|\b(?:still|never) (?:received|arrived)\b",
                t["text"],
                re.IGNORECASE,
            )
            for t in events[:index]
        ):
            yield (
                "completeness.promises_next_steps",
                "supported",
                "The Agent described delivery as pending and gave a waiting step that the customer accepted. Actual arrival remains unverified.",
                [turn, replies[0]],
            )


def _verified_records(conversation):
    events = conversation["events"]
    claimed = {
        t["turn_id"]
        for t in events
        if t["speaker"] == "agent" and CLAIM.search(t["text"])
    }
    amounts = [
        t["turn_id"]
        for t in events
        if t["speaker"] == "agent"
        for _ in VALUE.finditer(t["text"])
    ]
    by_turn = {t["turn_id"]: t for t in events}
    checks = list(recorded_resolution_claims(conversation))
    operations = [
        c for c in checks if c["rule_id"].startswith("answer-support.recorded-claim.")
    ]
    supported_turns = {
        c["turn_id"]
        for finding in operations
        for c in finding["citations"]
        if by_turn[c["turn_id"]]["speaker"] == "agent"
    }
    if len(operations) == 1 and claimed and claimed <= supported_turns:
        finding = operations[0]
        yield (
            "answer-support.recorded_outcomes",
            finding["outcome"],
            finding["explanation"],
            [by_turn[c["turn_id"]] for c in finding["citations"]],
        )
    for finding in checks:
        if finding["rule_id"] != "answer-support.recorded-amount" or len(amounts) != 1:
            continue
        turns = [by_turn[c["turn_id"]] for c in finding["citations"]]
        if any(t["speaker"] == "agent" and t["turn_id"] == amounts[0] for t in turns):
            yield (
                "answer-support.values",
                finding["outcome"],
                finding["explanation"],
                turns,
            )


def _shipping_prerequisite(events, references, policy_checks, cite):
    """An approved fee workflow still needs independent purchase validation."""
    if not {"procedure.information", "procedure.actions"} <= policy_checks.keys():
        return
    source_ids = {
        r["id"] for r in references if r.get("draft_source_key") == SHIPPING_FEE
    }
    information = policy_checks["procedure.information"]
    operation = policy_checks["procedure.actions"]
    if any(
        status != "supported"
        or not any(c.get("reference_id") in source_ids for c in citations)
        for status, _, citations in (information, operation)
    ):
        return
    input_turns = {c["turn_id"] for c in information[2] if c["kind"] == "conversation"}
    related = [t for t in events if t["turn_id"] in input_turns]
    order_inputs = [
        (t["turn_id"], match.group())
        for t in related
        if t["speaker"] == "customer"
        for match in re.finditer(r"\[ORDER_ID_\d+\]", t["text"])
    ]
    status = next(
        (
            t
            for t in related
            if t["speaker"] in {"action", "customer"}
            and re.search(
                r"\b(?:order received|in transit|out for delivery|delivered)\b",
                t["text"],
                re.IGNORECASE,
            )
        ),
        None,
    )
    if len(order_inputs) != 1 or status is None:
        return
    supplied, order_id = order_inputs[0]
    validations = [
        t
        for t in events
        if t["speaker"] == "action"
        and supplied < t["turn_id"] < status["turn_id"]
        and re.fullmatch(
            rf"Purchase has been validated for {re.escape(order_id)}\.",
            t["text"],
            re.IGNORECASE,
        )
    ]
    if len(validations) == 1:
        citations = [*information[2], *operation[2], cite(validations[0])]
        unique = {
            (c["kind"], c.get("turn_id", c.get("reference_id"))): c for c in citations
        }
        yield (
            "procedure.order_permission",
            "supported",
            "The matching purchase was validated before the shipping status and approved fee operation.",
            list(unique.values()),
        )


def verified_followup(request, rows, reply, references, local_policy_checks, cite):
    """Apply only conclusions independently supported by a local check."""
    events = request.conversation["events"]
    try:
        picks = proposals(
            reply,
            {row["rule_id"] for row in rows},
            {t["turn_id"] for t in events},
            {ref["id"] for ref in references},
        )
    except ValueError:
        return {}
    proven = [(rule, *finding) for rule, finding in local_policy_checks.items()]
    proven.extend(_shipping_prerequisite(events, references, local_policy_checks, cite))
    for checks in (
        _anchored_acknowledgement(events),
        _single_topic_reply(events),
        _pending_delivery_step(events),
        _verified_records(request.conversation),
    ):
        proven.extend(
            (rule, outcome, reason, [cite(t) for t in turns])
            for rule, outcome, reason, turns in checks
        )
    accepted = {}
    for rule, outcome, reason, citations in proven:
        pick = picks.get(rule)
        if not pick or pick["outcome"] != outcome or outcome == "unresolved":
            continue
        turns = {c["turn_id"] for c in citations if c["kind"] == "conversation"}
        sources = {c["reference_id"] for c in citations if c["kind"] == "reference"}
        if (
            rule.startswith("procedure.") or rule == "answer-support.facts"
        ) and not sources:
            continue
        if turns <= set(pick["turns"]) and sources == set(pick["references"]):
            accepted.setdefault(rule, (outcome, reason, citations))
    return accepted
