"""Bounded reusable-information links, independent of assessment scoring.

Recognizers are retained from contextual-request-links-v8. Unknown wording,
ambiguous conditions and later corrections do not establish reusable answers.
"""

import re

from .wording import quotation_context

VERSION = "knowledge-information-links-v1"

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


def request_links(conversation):
    """Retain canonical turns; only uniquely matched information answers qualify.

    A new substantive customer turn closes the preceding question's short-answer
    context. Corrections and withdrawals invalidate prior links conservatively,
    including after an answer. This extractor makes no fulfilment judgments.
    """
    requests, previous = [], None
    context, context_turn = None, None
    for position, event in enumerate(conversation["events"]):
        if event["kind"] == "action":
            continue
        text = normal(event["text"])
        safe = (
            unquoted(event["text"]) == event["text"]
            and not quotation_context(conversation["events"], position)
            and not re.search(r"\b(?:said|says|wrote|quoted|heard)\b", text)
        )
        if not safe:
            context, context_turn = None, None
            previous = event
            continue
        if (
            event["speaker"] == "customer"
            and text.strip(" .!?") in {"no", "no thanks"}
            and previous
            and previous["speaker"] == "agent"
            and not re.fullmatch(
                r"(?:is there|can i help (?:you )?with) anything else(?: i can help (?:you )?with)?(?: today)?",
                normal(previous["text"]).strip(" .!?"),
            )
        ):
            # A contextual decline/disagreement cannot approve reuse of an earlier answer.
            for row in requests:
                row["state"] = "changed"
            previous = event
            continue
        if re.search(
            r"\b(?:actually|correction|instead|ignore|wrong|not true|"
            r"don't|do not|no longer|never mind|forget)\b",
            text,
        ):
            # Do not silently publish a superseded answer as reusable guidance.
            for row in requests:
                row["state"] = "changed"
            context, context_turn = None, None
            previous = event
            continue
        products = set(
            re.findall(
                r"\b(?:boots|shirt|jeans|jacket|hood|lining|buttons|laces)\b", text
            )
        )
        if event["speaker"] == "agent" and context and products - {context}:
            context, context_turn = None, None
        if event["speaker"] == "customer" and len(products) == 1:
            context, context_turn = next(iter(products)), event["turn_id"]
        clauses = re.split(r";|(?<=[.!?])\s+", text)
        for clause in clauses:
            is_question = clause.endswith("?")
            clause = clause.strip(" .!?")
            # Agent Yes/No still needs the customer's preceding question.
            if (not clause or re.fullmatch(COURTESY, clause)) and (
                event["speaker"] != "agent" or clause not in {"yes", "no"}
            ):
                continue
            if event["speaker"] == "customer":
                question = information_question(clause, context)
                if question:
                    requests.append(
                        {
                            "id": str(event["turn_id"]) + ":" + str(len(requests)),
                            "turn_id": event["turn_id"],
                            "question": question,
                            "context_turn_ids": [context_turn]
                            if context_turn and context_turn != event["turn_id"]
                            else [],
                            "state": "active",
                            "history": [],
                        }
                    )
            elif event["speaker"] == "agent" and not is_question:
                # A second answer may correct the first without a correction cue.
                # Keep that ambiguity out of automatic reusable candidates.
                for row in requests:
                    if (
                        row["state"] == "answered"
                        and row["history"][-1]["turn_ids"] != [event["turn_id"]]
                        and information_response(
                            clause, row, previous, event["turn_id"]
                        )
                    ):
                        row["state"] = "changed"
                matches = [
                    row
                    for row in requests
                    if row["state"] == "active"
                    and information_context_matches(row["question"], text)
                    and information_response(clause, row, previous, event["turn_id"])
                ]
                if len(matches) == 1:
                    row = matches[0]
                    row["state"] = "answered"
                    row["history"].append({"turn_ids": [event["turn_id"]]})
        previous = event
    return requests, []
