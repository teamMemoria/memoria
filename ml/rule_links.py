"""Finite contextual request patterns; unrecognised wording is retained, not guessed."""

import re

from .wording import quotation_context

VERSION = "contextual-request-links-v8"
GOALS = {
    "extend": r"(?:extension|extend|extended)",
    "email": r"(?:email|e-mail|send)",
    "cancel": r"(?:cancel|end|terminate|stop)",
    "change": r"(?:change|update|modify)",
    "refund": r"(?:refund(?:s|ed|ing)?|money back)",
    "return": r"(?:return|exchange|replace)",
    "recover": r"(?:recover|reset|retrieve)",
    "explain": r"(?:explain|tell|how|where|when|what|why)",
}


def goal(text):
    if re.search(r"\b(?:explain|tell me|how|where|when|what|why)\b", text):
        return "explain"
    for name, pattern in GOALS.items():
        if re.search(r"\b" + pattern + r"\b", text):
            return name
    return None


TOPICS = {
    "extension": r"(?:extension|extend|extended)",
    "email": r"(?:e-?mail(?:ing)?(?: me)?|send (?:me )?(?:an? |the )?e-?mail)",
    "refund": r"(?:refund(?:s|ed|ing)?|money back)",
    "return": r"(?:return(?:s|ed|ing)?|exchange|replacement)",
    "address": r"(?:address|shipping address|billing address)",
    "payment": r"(?:payment|credit card|debit card|payment method)",
    "account": r"(?:account|password|username|login|log in)",
    "subscription": r"(?:subscription|membership|newsletter)",
    "shipment": r"(?:shipment|shipping|delivery|package|tracking)",
    "order": r"(?:order|purchase|item|product|size|stock|availability)",
    "website": r"(?:website|web site|site|page|browser)",
}
REQUEST_START = r"(?:(?:can|could) i (?:get|have) |please |(?:can|could|would) you |i (?:want|need|would like)(?: to)? |i'd like(?: to)? |how (?:do|can) i |(?:what|where|when|why|how much|how long) (?:is|are|will|does|do|can) )"
WITHDRAW = r"(?:actually[, ]+)?(?:please )?(?:do not|don't|no longer|never mind|forget|stop|cancel)(?:\s|$)"
COURTESY = r"(?:hi|hello|hey|thanks|thank you|yes|no|ok|okay|sure|bye|goodbye|no thanks|that's all|that is all)[.!? ]*"


def normal(text):
    return " ".join(text.casefold().replace("’", "'").split())


def topics(text):
    found = [
        key
        for key, pattern in TOPICS.items()
        if re.search(r"\b" + pattern + r"\b", text)
    ]
    # An order mentioned as the object of a refund/return is not a second request.
    if len(found) > 1 and "order" in found:
        found.remove("order")
    if "extension" in found and "subscription" in found:
        found.remove("subscription")
    return found


def unquoted(text):
    """Remove attributed spans only for recognition; citations keep original text."""
    result = []
    closing = None
    pairs = {'"': '"', "“": "”", "'": "'", "‘": "’", "`": "`"}
    for index, character in enumerate(text):
        apostrophe = (
            character in "'’"
            and index
            and index + 1 < len(text)
            and text[index - 1].isalnum()
            and text[index + 1].isalnum()
        )
        if apostrophe:
            if closing is None:
                result.append(character)
        elif closing:
            if character == closing:
                closing = None
            result.append(" ")
        elif character in pairs:
            closing = pairs[character]
            result.append(" ")
        else:
            result.append(character)
    return "".join(result)


PRODUCT = r"(?:boots?|shirts?|jeans|jackets?|hood|lining|buttons?|laces?)"
INFORMATION_SUBJECT = rf"(?:(?:standard |overnight )?shipping|(?:(?:single )?annual |premium )?(?:subscription|membership)|subscription fee|annual fee|extension|refund|order|shipment|package|annual sale|fall collection|gift wrapping|stitching|{PRODUCT})"
INFORMATION_VALUE = {
    "cost": r"(?:[$€£]\s*\d+(?:\.\d+)?|\d+(?:\.\d+)? (?:dollars|euros|pounds|cents))",
    "duration": r"(?:\d+|one|two|three|four|five|six|seven|eight|nine|ten|twelve) (?:business |calendar )?(?:days?|weeks?|months?|years?)",
    "due-date": r"(?:(?:january|february|march|april|may|june|july|august|september|october|november|december|jan|feb|mar|apr|jun|jul|aug|sep|oct|nov|dec)\.? \d{1,2}(?:st|nd|rd|th)?|\d{4}-\d{2}-\d{2}|today|tomorrow|yesterday|the (?:beginning|end) of (?:the )?(?:this|next) month)",
}
MATERIAL = r"(?:[\d.]+% ?)?(?:cotton|linen|leather|polyester|plyester|nylon|tricot|synthetic materials?|synthetic fabric|wool|denim)"
COLOR = r"(?:dark |light )?(?:black|brown|blue|red|white|green|gray|grey|yellow|orange)"
INFORMATION_PREFIX = r"^(?:what i want to know is|i am trying to see|i'm trying to see|can you (?:please )?tell me|could you (?:please )?tell me|could you let me know|do you know|i (?:just )?(?:want|wanted|would like|need) to know|i'd like to know) "


def information_question(text, context=None):
    """Finite question frames bind an attribute to a named or explicit product."""
    prefaced = bool(re.match(INFORMATION_PREFIX, text))
    text = re.sub(INFORMATION_PREFIX, "", text)
    if prefaced:
        text = re.sub(r"^if ", "", text)
    text = re.sub(r"^(?:and |i am wondering )", "", text)
    subject = rf"(?:the |my |your |this |these )?({INFORMATION_SUBJECT}|{re.escape(context) if context else '(?!)'}|it|its|they|them)"
    forms = {
        "cost": [
            rf"how much (?:is |does )?{subject}(?: costs?)?",
            rf"what is (?:the )?(?:cost|price) of {subject}",
            rf"how much {subject} (?:is|costs)",
        ],
        "duration": [
            rf"how long (?:does |is )?{subject}(?: lasts?| take)?(?: once i get it)?"
        ],
        "due-date": [
            rf"when is {subject} due",
            rf"when (?:does |will )?{subject} (?:end|ends|start|launch|expire)",
            rf"when {subject} is due",
            rf"when {subject} (?:ends|expires|starts)",
        ],
        "property": [
            rf"(?:is|are) {subject} (detachable|removable|waterproof|leather|windproof|wind-proof)"
        ],
        "material": [
            rf"what (?:is|are) {subject} made (?:of|from)",
            rf"what {subject} (?:is|are) made (?:of|from)",
            rf"(?:what|the) (?:type of )?materials? (?:(?:is|are) )?(?:used in |used for ){subject}(?: construction)?",
            rf"(?:the )?(?:type of )?materials? used in {subject} construction",
        ],
        "color": [
            rf"what colo(?:u)?r (?:is|are) {subject}",
            rf"(?:if )?(?:the |this )?(buttons|laces) are ({COLOR}) or ({COLOR})(?: though)?",
        ],
        "warranty": [
            rf"(?:does|do) {subject} (?:have|come with) a warranty",
            *(
                [rf"{subject} (?:have|has|come with|comes with) a warranty"]
                if prefaced
                else []
            ),
            rf"what is (?:the )?warranty (?:on|for) {subject}",
        ],
        "status": [
            r"(?:what is|where is|where's) (?:the |my )?(?:status of (?:the |my )?)?(refund|order|shipment|package)",
            r"(?:check|what is) (?:the |my )?(refund|order|shipping) status",
        ],
        "care": [rf"how (?:do|should|can) i (wash|clean|store|dry) {subject}"],
        "account-data": [
            r"(?:can|could) you (?:help me )?(?:recover|find|retrieve) (?:my )?(username|password)"
        ],
        "policy": [
            r"what is (?:the |your )?(refund|return|subscription|membership) policy(?: (?:you|you guys) offer)?",
            r"what happens if i (cancel my subscription|am late on (?:the |my )?subscription payment)",
        ],
    }
    for kind, patterns in forms.items():
        for pattern in patterns:
            match = re.fullmatch(pattern, text)
            if not match:
                continue
            parts = [part for part in match.groups() if part is not None]
            item = parts[1] if kind == "care" else parts[0]
            if item in {"it", "its", "they", "them"}:
                if not context:
                    return None
                item = context
            if item.startswith(("cancel my", "am late on")):
                item = "subscription"
            item = {"boot": "boots", "shirts": "shirt", "jackets": "jacket"}.get(
                item, item
            )
            attribute = (
                parts[1]
                if kind == "property"
                else parts[0]
                if kind == "care"
                else "cancellation"
                if kind == "policy" and parts[0].startswith("cancel my")
                else "late-payment"
                if kind == "policy" and parts[0].startswith("am late on")
                else None
            )
            named = topics(item)
            return {
                "kind": kind,
                "subject": item,
                "attribute": attribute,
                "topic": named[0]
                if len(named) == 1
                else "extension"
                if item == "extension"
                else "order",
            }
    return None


def information_context_matches(question, text):
    """Only declared policy conditions may qualify a recognised policy response."""
    if (
        question
        and question["kind"] == "policy"
        and re.search(
            r"\b(?:when|provided|assuming|depending|unless|only|except)\b", text
        )
    ):
        return False
    if not re.search(r"\bif\b", text):
        return True
    if (
        not question
        or question["kind"] != "policy"
        or re.search(r"\b(?:not|never)\b", text)
    ):
        return False
    condition = {
        "cancellation": r"you (?:decide to )?cancel your subscription(?: today)?",
        "late-payment": r"you are (?:a )?(?:gold|silver|bronze|guest)(?: or (?:gold|silver|bronze|guest))? member",
    }.get(question["attribute"])
    return bool(
        condition
        and len(re.findall(r"\bif\b", text)) == 1
        and re.match(r"if " + condition + r"(?:,? you |, )", text)
    )


def information_unavailable(text, request, previous):
    """Bind an explicit inability to the immediately preceding information request."""
    return bool(
        request.get("question")
        and previous
        and previous["speaker"] == "customer"
        and previous["turn_id"] == request["turn_id"]
        and re.fullmatch(
            r"i (?:cannot|can't) (?:find|provide|confirm) (?:that|this) information"
            r"|that information is not (?:in|available in) the faq",
            text,
        )
    )


def information_response(text, request, previous, turn):
    """A response must fill the requested slot; its truth is a separate check."""
    question = request.get("question")
    if not question:
        return False
    kind = question["kind"]
    text = re.sub(r"^(?:it looks like |i've found that |i found that )", "", text)
    immediate = bool(
        previous
        and previous["speaker"] == "customer"
        and previous["turn_id"] == request["turn_id"]
        and information_question(
            normal(unquoted(previous["text"])).strip(" .!?"), question["subject"]
        )
        == question
    )
    item = re.escape(question["subject"])
    subject = rf"(?:the |this |your |our |all (?:of )?our )?{item}"
    if immediate:
        subject = rf"(?:{subject}|it|they)"
    if kind == "property":
        value = r"(?:not )?" + re.escape(question["attribute"])
        pattern, short = rf"{subject} (?:is|are) (?:in fact )?{value}", r"(?:yes|no)"
    elif kind in INFORMATION_VALUE:
        value = INFORMATION_VALUE[kind]
        verb = {
            "cost": r"(?:costs|cost|is|are)",
            "duration": r"(?:lasts|last|takes|take|is|are)",
            "due-date": r"(?:is due(?: on)?|ends?(?: on)?|starts?(?: on)?|launches?(?: on)?|expires?(?: on)?)",
        }[kind]
        pattern, short = rf"{subject} {verb} {value}", value
    elif kind == "material":
        value = rf"{MATERIAL}(?:,? (?:and |such as )?{MATERIAL})*"
        pattern, short = rf"{subject} (?:is|are) made (?:of|from|out of) {value}", value
    elif kind == "color":
        pattern, short = (
            rf"{subject} (?:is|are) (?:{MATERIAL} and (?:is|are) )?{COLOR}",
            COLOR,
        )
    elif kind == "warranty":
        duration = INFORMATION_VALUE["duration"]
        pattern = rf"{subject} (?:have|has|come with|comes with) (?:a )?(?:warranty (?:of |for )?{duration}|{duration} warranty)(?: that covers .+)?"
        short = r"(?:yes|no)"
    elif kind == "status":
        pattern = rf"{subject} (?:is|has been|was) (?:still )?(?:processing|pending|received|shipped|in transit|out for delivery|delivered|cancelled|canceled|refunded)"
        short = r"(?:processing|pending|received|shipped|in transit|out for delivery|delivered|cancelled|canceled|refunded)"
    elif kind == "care":
        action = {
            "wash": r"(?:wash|washing)",
            "clean": r"(?:clean|cleaning)",
            "store": r"(?:store|storing)",
            "dry": r"(?:dry|drying)",
        }[question["attribute"]]
        detail = {
            "wash": r"(?:in|with) (?:cold|warm|hot) water",
            "clean": r"with (?:mild soap|a damp cloth|vinegar)",
            "store": r"in a cool dry place",
            "dry": r"(?:on low heat|flat|in the shade)",
        }[question["attribute"]]
        pattern = rf"(?:you (?:can|should|need to) )?{action} {subject} {detail}"
        short = None
    elif kind == "account-data":
        pattern = rf"your {item} is \[(?:identifier|username|password)_\d+\]"
        short = None
    elif kind == "policy" and question["attribute"] == "late-payment":
        pattern = rf"(?:the )?late payment fee (?:is|costs) {INFORMATION_VALUE['cost']} (?:per|a) day"
        short = None
    elif kind == "policy" and question["attribute"] == "cancellation":
        pattern = (
            r"(?:the |your )?subscription (?:will end|ends) (?:at|on) "
            + INFORMATION_VALUE["due-date"]
        )
        short = None
    elif kind == "policy":
        topic = r"returns?" if question["subject"] in {"return", "refund"} else item
        pattern = rf"(?:the )?(?:policy on {topic}|{topic} policy) (?:depends on (?:your |the )?membership level|allows returns within {INFORMATION_VALUE['duration']}|requires a valid receipt)"
        short = None
    else:
        return False
    if re.fullmatch(pattern, text):
        return True
    return bool(
        short and immediate and turn > previous["turn_id"] and re.fullmatch(short, text)
    )


def extension_disposition(text):
    """Explicit refusal/completion claims; neither proves eligibility or fulfilment."""
    if re.fullmatch(
        r"(?:your (?:account|membership|subscription) does not qualify for an extension(?: at this time)?|"
        r"i (?:cannot|can't) extend your (?:membership|subscription))",
        text,
    ):
        return "refused"
    if re.fullmatch(
        r"(?:i have|i've) extended your (?:membership|subscription)(?: for "
        + INFORMATION_VALUE["duration"]
        + r")?",
        text,
    ):
        return "answered"
    return None


def request_links(conversation):
    requests, unknown = [], []
    previous = None
    product_context = None
    product_context_turn = None
    for position, event in enumerate(conversation["events"]):
        if event["kind"] == "action":
            continue
        text = normal(unquoted(event["text"]))
        text = re.sub(
            r"\b(jan|feb|mar|apr|jun|jul|aug|sep|oct|nov|dec)\.(?=\s+\d)", r"\1", text
        )
        text = re.sub(r"\b(mr|ms|mrs)\.(?= \[person_\d+\])", r"\1", text)
        products = set(re.findall(r"\b(?:boots|shirt|jeans|jacket)\b", text))
        context_safe = (
            unquoted(event["text"]) == event["text"]
            and not quotation_context(conversation["events"], position)
            and not re.search(r"\b(?:said|wrote|quoted|heard)\b", text)
        )
        if not context_safe:
            product_context = None
            product_context_turn = None
        if (
            event["speaker"] == "agent"
            and product_context
            and products - {product_context.split()[-1]}
        ):
            product_context = None
            product_context_turn = None
        if event["speaker"] == "customer" and products and context_safe:
            product_context = (
                next(iter(products))
                if len(products) == 1
                and not re.search(
                    r"\b(?:not|no longer|said|wrote|quoted|if|unless)\b", text
                )
                else None
            )
            product_context_turn = event["turn_id"] if product_context else None
        if event["speaker"] == "customer" and product_context and context_safe:
            named_products = {
                normal(match[1].replace("_", " "))
                for match in re.finditer(
                    r"\b((?:[A-Z][a-z]+[ _]){1,2}(?:boots|shirt|jeans|jacket))\b",
                    event["text"],
                )
                if match[1].split()[0].lower()
                not in {"my", "the", "this", "these", "your", "product", "our"}
            }
            if named_products:
                product_context = (
                    next(iter(named_products)) if len(named_products) == 1 else None
                )
                product_context_turn = event["turn_id"] if product_context else None
        if quotation_context(conversation["events"], position):
            unknown.append(
                {
                    "turn_id": event["turn_id"],
                    "reason": "Reported or requested quotation is not a current request or response.",
                }
            )
            previous = event
            continue
        clauses = re.split(
            r";|(?<=[.!?])\s+|\s+but\s+(?=what happens if i )|\s+and\s+(?=(?:please|can you|could you|i want|i need|i would like|is there|is the|are the|get a refund|give me a refund|cancel (?:my|the) order)\b)",
            text,
        )
        requested_action = False
        for clause in clauses:
            is_question = clause.rstrip().endswith("?")
            clause = clause.strip(" .!?")
            if event["speaker"] == "agent":
                clause = re.sub(
                    r"^i am sorry(?: (?:mr|ms|mrs)\.?)?(?: \[person_\d+\])?,? but ",
                    "",
                    clause,
                )
            clause = re.sub(
                r"^(?:hi|hello|yes|okay|ok)[, ]+(?=(?:i |i'd |how |what |when |is |can you |could you |do you know )\b)",
                "",
                clause,
            )
            if event["speaker"] == "customer":
                if requested_action and re.match(
                    r"(?:get a refund|give me a refund|cancel (?:my|the) order)\b",
                    clause,
                ):
                    clause = "please " + clause
                requested_action = bool(
                    re.match(REQUEST_START, clause)
                    and goal(clause)
                    in {"cancel", "refund", "return", "change", "email"}
                )
            if (
                event["speaker"] == "agent"
                and not is_question
                and unquoted(event["text"]) == event["text"]
                and not re.search(
                    r"\b(?:unless|actually|correction|said|wrote|ignore|wrong|not true)\b",
                    text,
                )
            ):
                unavailable = [
                    row
                    for row in requests
                    if row["state"] not in {"withdrawn", "changed"}
                    and information_unavailable(clause, row, previous)
                ]
                if len(unavailable) == 1 and not re.search(r"\bif\b", text):
                    _transition(
                        unavailable[0],
                        "refused",
                        [event["turn_id"]],
                        "Explicit inability to supply the asked information; no substantive answer or factual correctness is established.",
                    )
                    unavailable[0]["response_turns"].append(event["turn_id"])
                    continue
                answers = [
                    row
                    for row in requests
                    if row["state"] not in {"withdrawn", "changed"}
                    and (information_context_matches(row.get("question"), text))
                    and information_response(clause, row, previous, event["turn_id"])
                ]
                if len(answers) == 1:
                    _transition(
                        answers[0],
                        "answered",
                        [event["turn_id"]],
                        "The response fills the explicitly asked information slot; its factual correctness is assessed separately.",
                    )
                    answers[0]["response_turns"].append(event["turn_id"])
                    continue
            if not clause or re.fullmatch(COURTESY, clause):
                # Short replies bind only to the immediately preceding explicit question.
                if (
                    event["speaker"] == "customer"
                    and clause in {"no", "no thanks", "yes"}
                    and previous
                    and previous["speaker"] == "agent"
                ):
                    question = normal(unquoted(previous["text"])).rstrip("?.!")
                    match = re.fullmatch(
                        r"do you still (?:want|need) (?:your |the |a |an )?(.+)",
                        question,
                    )
                    if match and len(topics(match[1])) == 1 and clause.startswith("no"):
                        topic = topics(match[1])[0]
                        candidates = [
                            row
                            for row in requests
                            if row["topic"] == topic
                            and row["state"] not in {"withdrawn", "changed"}
                        ]
                        if len(candidates) == 1 and same_request_target(
                            match[1], candidates[0], "agent"
                        ):
                            _transition(
                                candidates[0],
                                "withdrawn",
                                [previous["turn_id"], event["turn_id"]],
                                "Customer declined the explicitly named existing request.",
                            )
                        else:
                            unknown.append(
                                {
                                    "turn_id": event["turn_id"],
                                    "reason": "The question names a different or ambiguous operation, object or recipient; no withdrawal is established.",
                                }
                            )
                    elif not re.fullmatch(
                        r"(?:is there|can i help (?:you )?with) anything else(?: i can help (?:you )?with)?(?: today)?",
                        question,
                    ):
                        unknown.append(
                            {
                                "turn_id": event["turn_id"],
                                "reason": "Short reply does not establish cancellation, fulfilment or a changed request.",
                            }
                        )
                continue
            named = topics(clause)
            if event["speaker"] == "agent" and extension_disposition(clause):
                named = ["extension"]
            if event["speaker"] == "customer":
                if re.search(r"\b(?:said|says|wrote|quoted|heard)\b", clause):
                    unknown.append(
                        {
                            "turn_id": event["turn_id"],
                            "reason": "Reported speech has unresolved attribution.",
                        }
                    )
                    continue
                if re.match(WITHDRAW, clause) and not re.match(
                    r"(?:please )?cancel (?:my |the )?(?:subscription|membership|order)\b",
                    clause,
                ):
                    candidates = [
                        row
                        for row in requests
                        if row["topic"] in named
                        and row["state"] not in {"withdrawn", "changed"}
                    ]
                    # Cancel my subscription/order is a service request, not withdrawal of an earlier cancellation.
                    explicit_withdrawal = bool(
                        re.search(
                            r"\b(?:don't|do not|no longer|never mind|forget|stop)\b",
                            clause,
                        )
                    )
                    if (
                        explicit_withdrawal
                        and len(candidates) == 1
                        and len(named) == 1
                        and same_request_target(clause, candidates[0], "customer")
                    ):
                        _transition(
                            candidates[0],
                            "withdrawn",
                            [event["turn_id"]],
                            "Explicit withdrawal names this existing request.",
                        )
                    else:
                        unknown.append(
                            {
                                "turn_id": event["turn_id"],
                                "reason": "Cancellation wording has a different or unresolved operation, object, recipient or value; no withdrawal is established.",
                            }
                        )
                    continue
                change = re.match(r"(?:actually[, ]+|instead[, ]+)", clause)
                body = re.sub(r"^(?:actually|instead)[, ]+", "", clause).removesuffix(
                    " instead"
                )
                question = (
                    information_question(body, product_context)
                    if unquoted(event["text"]) == event["text"]
                    else None
                )
                if question:
                    named = [question["topic"]]
                if (question or re.match(REQUEST_START, body)) and len(named) == 1:
                    if re.search(r"\b(?:not|never|unless|if)\b", body) and not (
                        question and question["kind"] in {"policy", "color", "warranty"}
                    ):
                        unknown.append(
                            {
                                "turn_id": event["turn_id"],
                                "reason": "Negated or conditional request needs a supported interpretation.",
                            }
                        )
                        continue
                    key = (
                        f"{question['kind']}:{question['subject']}:{question['attribute']}"
                        if question
                        else re.sub(REQUEST_START, "", body)
                    )
                    if re.fullmatch(
                        r"(?:(?:issue|process|give me|get|provide) )?(?:a |my |the )?refund|refund me",
                        key,
                    ):
                        key = "refund"

                    existing = [
                        row
                        for row in requests
                        if row["topic"] == named[0]
                        and row["state"] not in {"withdrawn", "changed"}
                    ]
                    if question and change and "instead" not in clause:
                        unknown.append(
                            {
                                "turn_id": event["turn_id"],
                                "reason": "A follow-up information question does not explicitly replace the earlier request.",
                            }
                        )
                        continue
                    if change:
                        # A change must identify what is being replaced; adjacency alone is insufficient.
                        if len(existing) != 1:
                            unknown.append(
                                {
                                    "turn_id": event["turn_id"],
                                    "reason": "Changed request has no unique named predecessor.",
                                }
                            )
                            continue
                        _transition(
                            existing[0],
                            "changed",
                            [event["turn_id"]],
                            "Explicit replacement names the same request subject.",
                        )
                    elif any(
                        row["key"] == key
                        and row["state"] not in {"withdrawn", "changed"}
                        for row in existing
                    ):
                        continue
                    requests.append(
                        {
                            "id": f"request-{event['turn_id']}-{len(requests) + 1}",
                            "topic": named[0],
                            "key": key,
                            "turn_id": event["turn_id"],
                            "goal": "explain" if question else goal(body),
                            "state": "active",
                            "history": [],
                            "replaces": existing[0]["id"] if change else None,
                            "response_turns": [],
                            "constraints": constraints(body, "customer"),
                            "question": question,
                            "context_turn_ids": [product_context_turn]
                            if question
                            and question["subject"] == product_context
                            and product_context_turn is not None
                            and product_context_turn != event["turn_id"]
                            and re.search(r"\b(?:it|its|they|them)\b", body)
                            else [],
                        }
                    )
                    _transition(
                        requests[-1],
                        "active",
                        [event["turn_id"]],
                        "Explicit request with one recognised subject.",
                    )
                elif not re.fullmatch(
                    r"(?:my |the )?\[[a-z_]+_\d+\](?:[, ]+\[[a-z_]+_\d+\])*", clause
                ):
                    unknown.append(
                        {
                            "turn_id": event["turn_id"],
                            "reason": "Customer wording is not a supported request, clarification or withdrawal pattern.",
                        }
                    )
            else:
                candidates = [
                    row
                    for row in requests
                    if row["topic"] in named
                    and row["state"] not in {"withdrawn", "changed"}
                ]
                if len(candidates) != 1 or len(named) != 1:
                    continue
                if (
                    is_question
                    or unquoted(event["text"]) != event["text"]
                    or re.search(r"\b(?:if|unless|said|wrote|quote)\b", clause)
                ):
                    continue
                expected = candidates[0]["goal"]
                response_goal = goal(
                    clause.replace("sent", "send")
                    .replace("changed", "change")
                    .replace("updated", "update")
                    .replace("cancelled", "cancel")
                    .replace("canceled", "cancel")
                    .replace("refunded", "refund")
                    .replace("returned", "return")
                )
                if expected is None or response_goal != expected:
                    continue
                state = None
                if expected == "extend" and extension_disposition(clause):
                    state = extension_disposition(clause)
                elif re.match(
                    r"i (?:will not|won't|cannot|can't) (?:process|send|change|update|provide|help|cancel|refund|return)",
                    clause,
                ):
                    state = "refused"
                elif re.match(
                    r"(?:i will|i'll) (?:process|send|email|change|update|provide|help|cancel|refund|return)",
                    clause,
                ):
                    state = "promised"
                elif re.match(
                    r"(?:(?:i have|i've|we have) (?:sent|changed|updated|processed|cancelled|canceled|refunded|returned)|i went ahead and (?:sent|changed|updated|processed|cancelled|canceled|refunded|returned)|(?:your |the )?(?:refund|return|order|address) (?:has been|was) (?:processed|initiated|cancelled|canceled|changed|updated))",
                    clause,
                ):
                    state = "answered"
                if state and not matches_constraints(
                    candidates[0]["constraints"], constraints(clause, "agent")
                ):
                    unknown.append(
                        {
                            "turn_id": event["turn_id"],
                            "reason": "Response object, recipient, value or condition does not establish the requested relationship.",
                        }
                    )
                    state = None
                if state:
                    _transition(
                        candidates[0],
                        state,
                        [event["turn_id"]],
                        "Linked wording is an agent response or commitment, not proof of completed action.",
                    )
                    candidates[0]["response_turns"].append(event["turn_id"])
        previous = event
    return requests, unknown


def _transition(request, state, turn_ids, reason):
    request["state"] = state
    request["history"].append({"state": state, "turn_ids": turn_ids, "reason": reason})


def same_request_target(text, request, speaker):
    target = re.sub(WITHDRAW, "", text, count=1)
    target = re.sub(r"^(?:want|need)(?: to)? ", "", target)
    verbs = {
        "emailing": "email",
        "sending": "send",
        "changing": "change",
        "updating": "update",
        "refunding": "refund",
        "returning": "return",
        "canceling": "cancel",
        "cancelling": "cancel",
    }
    target = re.sub(r"\b(?:" + "|".join(verbs) + r")\b", lambda m: verbs[m[0]], target)
    remaining = re.sub(
        r"\[[a-z_]+_\d+\]|[$€£]\s*\d+(?:\.\d+)?|\b\d+\s+(?:days?|hours?|weeks?)\b",
        " ",
        target,
    )
    vocabulary = [
        *GOALS.values(),
        *TOPICS.values(),
        r"receipt|invoice|confirmation|tracking number|manager",
        r"a|an|the|my|your|me|you|myself|yourself|to|by|in|anymore|please",
    ]
    remaining = re.sub(r"\b(?:" + "|".join(vocabulary) + r")\b", " ", remaining)
    return (
        not remaining.strip()
        and request["goal"] is not None
        and goal(target) == request["goal"]
        and matches_constraints(constraints(target, speaker), request["constraints"])
    )


def constraints(text, speaker):
    result = {}
    values = sorted(
        set(
            re.findall(
                r"\[[a-z_]+_\d+\]|[$€£]\s*\d+(?:\.\d+)?|\b\d+\s+(?:days?|hours?|weeks?)\b",
                text,
            )
        )
    )
    if values:
        result["values"] = values
    objects = sorted(
        set(re.findall(r"\b(?:receipt|invoice|confirmation|tracking number)\b", text))
    )
    if objects:
        result["objects"] = objects
    products = sorted(set(re.findall(r"\b(?:boots|shirt|jeans|jacket)\b", text)))
    if products:
        result["products"] = products
    recipient = re.search(
        r"\b(?:to|email|e-mail) (me|you|my manager|your manager|the manager|myself|yourself)\b",
        text,
    )
    if recipient:
        party = recipient[1]
        if party in {"me", "myself"}:
            party = speaker
        elif party in {"you", "yourself"}:
            party = "customer" if speaker == "agent" else "agent"
        elif party in {"my manager", "your manager"}:
            owner = (
                speaker
                if party.startswith("my ")
                else ("customer" if speaker == "agent" else "agent")
            )
            party = owner + "-manager"
        result["recipient"] = party
    return result


def matches_constraints(requested, response):
    return all(
        response.get(key) == value
        for key, value in requested.items()
        if key != "products" or key in response
    )
