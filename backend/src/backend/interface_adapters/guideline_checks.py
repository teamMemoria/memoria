"""Recognize specific call evidence before an approved guideline can earn points."""

import re
from functools import partial

from backend.entities.fulfilment import (
    FEE_REQUEST,
    recorded_return_method,
    single_order,
)
from backend.entities.guidelines import (
    CART,
    OVERNIGHT,
    PRICE,
    PROMO_AGE,
    RETURN_COLOUR,
    RETURN_SIZE,
    SHIPPING_FEE,
)
from backend.interface_adapters.call_checks import ordered_turns
from backend.interface_adapters.draft_examples import (
    CART_REQUEST,
    PROMO_REQUEST,
    WRONG_COLOUR,
    WRONG_SIZE,
    event,
)
from backend.interface_adapters.fulfilment_checks import fulfilment_request


def _finding(reason, *turns):
    distinct = {turn["turn_id"]: turn for turn in turns if turn is not None}
    return "supported", reason, [distinct[key] for key in sorted(distinct)]


def _shipping_fee_guideline(events):
    find = partial(event, events)
    request = find(
        "customer",
        r"^(?:hi[ ,]+)?(?:i (?:want|would like) (?:a refund on (?:my|the) shipping fee|(?:my|the) shipping fee waived)|i want to check the cost of shipping)",
    )
    if request is None:
        return {}
    start = request["turn_id"]
    if waiver := _find_waiver(events, request, strict=True):
        return waiver

    # A cancellation request only changes scope after an explicit contextual withdrawal.
    question = find("agent", r"^and what is the status of the order\?", after=start)
    if question is None:
        return {}
    reported = find(
        "customer",
        r"^(?:delivered|out for delivery)(?:[. !]*|[. ]+so i guess not[.!]?)$",
        after=question["turn_id"],
        before=question["turn_id"] + 2,
    )
    if reported is None:
        return {}
    cancellation = find(
        "customer", r"^i want to cancel (?:it|the order)[.!]?$", after=start
    )
    if cancellation and (
        cancellation["turn_id"] >= reported["turn_id"]
        or not reported["text"].casefold().rstrip(".! ").endswith("so i guess not")
    ):
        return {}
    refund_offer = find(
        "agent",
        r"^(?:unfortunately )?i can only give you a partial refund if the item is already delivered[.!]?$",
        after=reported["turn_id"],
    )
    if refund_offer is None:
        return {}
    consent = find(
        "customer",
        r"^(?:ok(?:ay)?[, ]+that would be fine|yes(?: please)?)[.!]?$",
        after=refund_offer["turn_id"],
        before=refund_offer["turn_id"] + 2,
    )
    if consent is None:
        return {}
    refund = find(
        "action",
        r"^a refund has been made for the amount of \$8(?:\.00)?\.$",
        after=consent["turn_id"],
    )
    checks = {
        "answer-support.facts": _finding(
            "The guideline confirms the partial shipping refund option for the reported delivered status.",
            request,
            cancellation,
            question,
            reported,
            refund_offer,
            consent,
        ),
    }
    if refund:
        change = _finding(
            "The customer accepted a partial shipping refund, and the action matches the guideline's $8 partial refund.",
            request,
            cancellation,
            reported,
            refund_offer,
            consent,
            refund,
        )
        checks.update(_shipping_information(events, request, reported, change))
    return checks


def shipping_fee(events):
    existing = _shipping_fee_guideline(events)
    if existing or not single_order(events):
        return existing
    request = fulfilment_request(events, "shipping")
    if request is None or not re.search(FEE_REQUEST, request["text"], re.IGNORECASE):
        return {}
    return _find_waiver(events, request, strict=False)


def _find_waiver(events, request, *, strict):
    start = request["turn_id"]
    find = partial(event, events)
    status = find(
        "action",
        r"^shipping status of (?:order received|in transit) has been noted\.$",
        after=start,
    )
    if status is None:
        return {}

    # The original branch checks the first offer and update after the request.
    # The fallback can use the later offer and update for the same order.
    if strict:
        offer_pattern = r"^i (?:will|can) waive your (?:shipping )?fee[.!]?$"
        fee_pattern = r"waive fee"
    else:
        offer_pattern = (
            r"\b(?:i (?:can|will|'ll) (?:go ahead and )?|we can )"
            r"waive (?:your|the) (?:shipping |delivery )?fee\b"
        )
        fee_pattern = r"waive (?:shipping )?fee"
    offer = find("agent", offer_pattern, after=start if strict else status["turn_id"])
    if offer is None or offer["turn_id"] <= status["turn_id"]:
        return {}
    update = find(
        "action",
        rf"^order has been updated with {fee_pattern}\.$",
        after=start if strict else offer["turn_id"],
    )
    if (
        update is None
        or update["turn_id"] <= offer["turn_id"]
        or _changed(events, start, update["turn_id"])
    ):
        return {}
    reason = (
        "The shipping status permits a waiver, and the order record confirms the fee waiver."
        if strict
        else "The recorded shipping status permits waiving the fee, and the order update records the waiver."
    )
    checks = _shipping_information(
        events, request, status, _finding(reason, request, status, offer, update)
    )
    checks["answer-support.facts"] = _waiver_option(request, status, offer)
    return checks


def _waiver_option(request, status, offer):
    return _finding(
        "A waiver is the option listed for the recorded shipping status. Whether purchase validation was completed remains a separate check.",
        request,
        status,
        offer,
    )


def _shipping_information(events, request, status, change):
    checks = {"procedure.actions": change}
    start, before = request["turn_id"], status["turn_id"]
    inputs = [
        event(
            events,
            "action",
            r"^account has been pulled up for \[(?:PERSON|ACCOUNT_ID)(?:_\d+)?\]\.$",
            after=start,
            before=before,
        ),
        *(
            event(
                events, "customer", rf"\[{label}(?:_\d+)?\]", after=start, before=before
            )
            for label in ("USERNAME", "EMAIL", "ORDER_ID")
        ),
    ]
    if all(inputs):
        checks["procedure.information"] = _finding(
            "The account lookup, username, email, order identifier and shipping status are recorded. Purchase-validation completion is separate.",
            request,
            *inputs,
            status,
        )
    return checks


# Keep the recognition patterns narrow. Evidence of one action never proves a
# different action, a completed prerequisite, or a forecast.
OVERNIGHT_REQUEST = r"\bupgrad\w* (?:my |to |it to )?(?:order to |shipping to )?(?:overnight (?:shipping|delivery)|shipping(?: option)?)\b"
RETURN_REQUEST = r"\b(?:need|want|would like) to (?:make a )?return\b"
PRICE_REQUEST = r"\b(?:more expensive|higher|costs? more) today than yesterday\b"


def _changed(events, after, before):
    return event(
        events,
        "customer",
        r"\b(?:never mind|forget it|no longer (?:want|need)|do not|don['’]t (?:change|return|upgrade|charge|waive)|instead)\b",
        after=after,
        before=before,
    )


def overnight(events):
    find = partial(event, events)
    matched = ordered_turns(
        events,
        ("customer", OVERNIGHT_REQUEST),
        ("agent", r"\b(?:shipping status|rec(?:ei|ie)v\w* an update on your order)\b"),
    )
    if not matched:
        return {}
    request, question = matched
    status = find(
        "customer",
        r"\b(?:out for delivery|in transit|order received)\b",
        after=question["turn_id"],
        before=question["turn_id"] + 2,
    )
    if status is None:
        return {}
    checks = {}
    late = status["text"].casefold().find("order received") < 0
    permission = None
    if late:
        refusal = find(
            "agent",
            r"\b(?:too late to upgrade|(?:not possible|unable) to upgrade)\b",
            after=status["turn_id"],
        )
        if refusal:
            checks["answer-support.facts"] = _finding(
                "The guideline disallows an overnight upgrade for the reported shipping status. It does not verify the projected arrival.",
                request,
                question,
                status,
                refusal,
            )
        else:
            refusal = find(
                "agent",
                r"\b(?:can't|cannot|unable to) (?:change|alter) (?:the )?(?:date|delivery)(?: of delivery)?\b"
                r".{0,65}\b(?:already shipped|has already left)\b",
                after=status["turn_id"],
            )
        noted = find(
            "action",
            r"^shipping status of (?:in transit|out for delivery|delivered) has been noted\.$",
            after=status["turn_id"],
            before=refusal["turn_id"] if refusal else None,
        )
        if (
            refusal
            and noted
            and single_order(events)
            and not _changed(events, request["turn_id"], refusal["turn_id"])
            and re.search(
                re.escape(status["text"].strip(" .!")), noted["text"], re.IGNORECASE
            )
        ):
            turns = request, question, status, noted, refusal
            checks["procedure.actions"] = _finding(
                "The status record shows that shipping had started. The Agent stopped the upgrade as the guideline requires.",
                *turns,
            )
            checks.setdefault(
                "answer-support.facts",
                _finding(
                    "The recorded shipping status supports the refusal under the approved upgrade rule. The arrival estimate remains unverified.",
                    *turns,
                ),
            )
    else:
        tier = find(
            "action",
            r"^membership level of (?:guest|bronze|silver) has been noted\.$",
            after=status["turn_id"],
        )
        fee = find(
            "agent",
            r"\b(?:is it okay to|may i|can i) charge your credit card \$20\b",
            after=status["turn_id"],
        )
        if tier is None or fee is None or tier["turn_id"] >= fee["turn_id"]:
            return {}
        consent = find(
            "customer",
            r"^(?:oh )?(?:for sure|yes|sure|okay|ok)\b",
            after=fee["turn_id"],
            before=fee["turn_id"] + 2,
        )
        if consent is None:
            return {}
        permission = (tier, fee, consent)
        update = find(
            "action",
            r"^order has been updated with tomorrow\.$",
            after=consent["turn_id"],
        )
        if update and not _changed(events, fee["turn_id"], update["turn_id"]):
            checks["procedure.actions"] = _finding(
                "The order was received, the customer accepted the tier's charge terms, and the order action records tomorrow. The card charge and dispatch are separate.",
                request,
                status,
                *permission,
                update,
            )
    inputs = [
        find("customer", rf"\[{label}(?:_\d+)?\]", before=status["turn_id"])
        for label in ("PERSON", "ACCOUNT_ID", "ORDER_ID")
    ]
    if all(inputs):
        checks["procedure.information"] = _finding(
            "The requested order identifiers and shipping status were collected. Any applicable fee and consent are recorded separately from identity verification.",
            request,
            *inputs,
            question,
            status,
            *(permission or ()),
        )
    return checks


RETURN_METHODS = {
    "mail": r"(?:by )?mail",
    "in store": r"in[- ]store",
    "drop-off center": r"(?:at (?:a |the )?)?drop[- ]off center",
}


def return_for_reason(events, reason_pattern):
    find = partial(event, events)
    request = find("customer", RETURN_REQUEST)
    if request is None:
        return {}
    reason = find("customer", reason_pattern, after=request["turn_id"] - 1)
    if reason is None:
        return {}
    member_question = find(
        "agent", r"\b(?:membership|member)\b", after=reason["turn_id"]
    )
    if member_question is None:
        return {}
    gold = find(
        "customer",
        r"^(?:i(?:['’]m| am) )?gold[.!]?$",
        after=member_question["turn_id"],
        before=member_question["turn_id"] + 3,
    )
    if gold is None or any(
        member_question["turn_id"] < turn["turn_id"] < gold["turn_id"]
        and turn["speaker"] != "action"
        and not (
            turn["speaker"] == "customer"
            and re.fullmatch(
                r"(?:hmm*|um+|uh+)[.!]?", turn["text"].strip(), re.IGNORECASE
            )
        )
        for turn in events
    ):
        return {}
    checks = {}
    policy = find(
        "agent",
        r"\bgold member(?:s|ship)?\b.{0,35}\bunlimi?ted returns\b",
        after=gold["turn_id"],
    )
    if policy:
        checks["answer-support.facts"] = _finding(
            "The unlimited-returns statement matches the Gold rule for this return reason. Purchase validation and payment are separate.",
            request,
            reason,
            member_question,
            gold,
            policy,
        )
    offer = find(
        "agent",
        r"\b(?:by mail|by shipping)\b.{0,32}\b(?:in store|drop off)\b",
        after=gold["turn_id"],
    )
    if offer is None:
        return checks
    choice = find(
        "customer",
        rf"^(?:{'|'.join(RETURN_METHODS.values())})[.!]?$",
        after=offer["turn_id"],
        before=offer["turn_id"] + 2,
    )
    address = find(
        "action",
        r"^details of \[ADDRESS(?:_\d+)?\].*have been entered\.$",
        after=gold["turn_id"],
        before=offer["turn_id"],
    )
    if not (choice and address):
        return checks
    method, spelling = next(
        (name, pattern)
        for name, pattern in RETURN_METHODS.items()
        if re.fullmatch(pattern, choice["text"].strip(" .!"), re.IGNORECASE)
    )
    if not re.search(rf"\b{spelling}\b", offer["text"], re.IGNORECASE):
        return checks
    updated = find(
        "action",
        rf"^order has been updated with {spelling}\.$",
        after=choice["turn_id"],
    )
    payout = _bank_payout(events, request, offer)
    route = "procedure.actions.return_method" if payout else "procedure.actions"
    anchors = (request, reason, gold, address, offer, choice)
    if updated and not (
        _changed(events, choice["turn_id"], updated["turn_id"])
        or find(
            "customer",
            r"^(?:actually|instead|correction)[:, ]",
            after=choice["turn_id"],
            before=updated["turn_id"],
        )
    ):
        display = (
            "mail return method" if method == "mail" else f"{method} return method"
        )
        checks[route] = _finding(
            f"The selected {display} matches the recorded update. This does not establish label delivery or a completed return.",
            *anchors,
            updated,
        )
    elif payout:
        checks[route] = (
            "unresolved",
            "The selected return method needs a matching order update.",
            list({turn["turn_id"]: turn for turn in anchors}.values()),
        )
    if payout:
        checks["procedure.actions.refund_destination"] = (
            "unresolved",
            "The customer requested a bank transfer. The return method update does not confirm the payout.",
            payout,
        )
    inputs = [
        find("customer", rf"\[{label}(?:_\d+)?\]", before=gold["turn_id"])
        for label in ("PERSON", "USERNAME", "EMAIL", "ORDER_ID")
    ]
    if all(inputs):
        checks["procedure.information"] = _finding(
            f"Name, purchase inputs, membership tier, address and {method} return choice are present. Purchase validation completion remains a separate check.",
            request,
            reason,
            *inputs,
            gold,
            address,
            offer,
            choice,
        )
    return checks


def _bank_payout(events, request, offer):
    question = event(
        events,
        "agent",
        r"\bhow would you like (?:your|the) refund sent\b",
        after=request["turn_id"],
        before=offer["turn_id"],
    )
    choice = question and event(
        events,
        "customer",
        r"^(?:please )?(?:transfer(?:red)?|sent) to my bank account[.!]?$",
        after=question["turn_id"],
        before=offer["turn_id"],
    )
    return [question, choice] if choice else []


def cart(events):
    find = partial(event, events)
    request = find("customer", CART_REQUEST)
    if request is None:
        return {}
    refresh = find(
        "agent",
        r"^(?:(?:please|you can|could you|try to|i recommend you)\s+|"
        r"(?:it )?looks like the first (?:step|suggestion) is to )?"
        r"refresh (?:your|the) page and (?:try )?(?:adding|add|re-adding|re-add) "
        r"the item (?:to|back to) (?:your|the) cart\b",
        after=request["turn_id"],
    )
    relog = find(
        "agent",
        r"^(?:ok(?:ay)?[.,]\s*)?(?:(?:please|you can|you could|could you|try to|i recommend you)\s+|"
        r"(?:the )?next step (?:is|would be) to )?"
        r"(?:(?:log|sign) out(?: of (?:your|the) account)?|exit (?:your|the) account) "
        r"and (?:then )?(?:(?:log|sign) )?back in(?:to (?:your|the) account)?\b",
        after=request["turn_id"],
    )
    if refresh is None and relog is None:
        return {}
    return {
        "answer-support.facts": _finding(
            "The recommended troubleshooting option is allowed by the cart guidance. The guidance allows either option in any order.",
            request,
            refresh,
            relog,
        )
    }


def price(events):
    find = partial(event, events)
    matched = ordered_turns(
        events,
        ("customer", PRICE_REQUEST),
        ("action", r"^a reason of yesterday has been recorded\.$"),
        (
            "agent",
            r"\bour prices (?:often )?(?:vary|change)\b.{0,40}\b(?:algorithm|algorithms)\b",
        ),
        ("customer", r"\b(?:is there|can i get|could i get)\b.{0,30}\bcoupon\b"),
        ("agent", r"^the following promo code will give you a discount:"),
        ("action", r"^a promo code has been created\.$"),
    )
    if not matched:
        return {}
    request, reason, explanation, question, offer, created = matched
    sent = find(
        "agent",
        r"^(?=[a-z0-9]{5,10}$)(?=.*[0-9])[a-z0-9]+$",
        after=created["turn_id"],
        before=created["turn_id"] + 2,
    )
    if sent is None:
        return {}
    return {
        "procedure.actions": _finding(
            "The price-dispute reason was recorded and the requested promo code was generated and shared.",
            request,
            reason,
            explanation,
            question,
            created,
            sent,
        ),
        "answer-support.facts": _finding(
            "The general dynamic-pricing explanation and discount option match the guideline. No historical price or specific discount is established.",
            request,
            explanation,
            question,
            offer,
            created,
        ),
    }


def promo_age(events):
    find = partial(event, events)
    matched = ordered_turns(
        events,
        ("customer", PROMO_REQUEST),
        (
            "agent",
            r"^(?:typically our promo codes only last for|promotions typically only last) 7 days\b",
        ),
    )
    if not matched:
        return {}
    request, claim = matched
    extra = find(
        "agent",
        r"\b(?:[0-9]+%|half off|expires? (?:today|tomorrow|on)|valid for [0-9]+ days)\b",
        after=claim["turn_id"],
    )
    if extra:
        return {}
    return {
        "answer-support.values": _finding(
            "Seven days matches the stated typical duration. The actual expiry and replacement eligibility remain unverified.",
            request,
            claim,
        )
    }


def return_colour(events):
    return _return_with_record(events, WRONG_COLOUR)


def return_size(events):
    return _return_with_record(events, WRONG_SIZE)


def _return_with_record(events, reason_pattern):
    checks = return_for_reason(events, reason_pattern)
    if "procedure.actions" in checks or "procedure.actions.return_method" in checks:
        return checks
    request = fulfilment_request(events, "return")
    if request is None:
        return checks
    route = recorded_return_method(events, request)
    if not route:
        return checks
    offer, choice, update = route
    reason = event(
        events,
        "customer",
        reason_pattern,
        after=request["turn_id"] - 1,
        before=offer["turn_id"],
    )
    address = event(
        events,
        "action",
        r"^details of \[ADDRESS(?:_\d+)?\].*have been entered\.$",
        after=request["turn_id"],
        before=offer["turn_id"],
    )
    if reason and address:
        payout = _bank_payout(events, request, offer)
        rule = "procedure.actions.return_method" if payout else "procedure.actions"
        checks[rule] = _finding(
            "The address and the customer's selected return method were recorded as required. Eligibility, the label and the physical return remain separate.",
            request,
            reason,
            address,
            offer,
            choice,
            update,
        )
        if payout:
            checks["procedure.actions.refund_destination"] = (
                "unresolved",
                "The return method update does not confirm the requested bank payout.",
                payout,
            )
    return checks


def stained_item_gold(events):
    findings = return_for_reason(
        events, r"\b(?:has|have) a stain\b|\b(?:is|are) stained\b"
    )
    fact = findings.get("answer-support.facts")
    return {"answer-support.facts": fact} if fact else {}


def site_search(events):
    matched = ordered_turns(
        events,
        (
            "customer",
            r"\bsearch(?: bar| box| function)?\b.{0,30}\b(?:does not work|doesn['’]t work|isn['’]t working|not working)\b",
        ),
        (
            "agent",
            r"^(?:please |i recommend (?:that )?you |you can (?:try )?)(?:clear(?:ing)? (?:your (?:browser )?|the browser )cookies|sign(?:ing)? out and (?:sign(?:ing)? )?back in)\b",
        ),
    )
    if not matched:
        return {}
    request, advice = matched
    return {
        "answer-support.facts": _finding(
            "The suggested troubleshooting option appears in the approved site search guidance.",
            request,
            advice,
        ),
    }


SCOPED_CHECKS = {
    SHIPPING_FEE: ("shipping", shipping_fee),
    OVERNIGHT: ("shipping", overnight),
    RETURN_COLOUR: ("return", return_colour),
    RETURN_SIZE: ("return", return_size),
    CART: ("website", cart),
    PRICE: ("pricing", price),
    PROMO_AGE: ("pricing", promo_age),
}

PUBLISHER_CHECKS = {
    "layer2-abc-stained-item-gold-return-v1": ("return", stained_item_gold),
    "layer2-abc-site-search-troubleshooting-v1": ("website", site_search),
}
