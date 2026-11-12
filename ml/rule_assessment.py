"""Deterministic check composition over canonical evidence and reviewed tables."""

import re
from copy import deepcopy

from .abcd import conversation_passages, validate_evidence
from .audit import CATEGORIES, category_result
from .procedure_support import check_procedure_support
from .references import reference_passages
from .rule_facts import (
    assertion_clause,
    claim_atoms,
    claim_frame,
    compare_facts,
    fact_frame,
    nonfactual_phrase,
)
from .rule_links import VERSION as LINK_VERSION
from .rule_links import information_question, normal, request_links, unquoted
from .scoring import (
    VERSION,
    content_version,
    critical_rule,
    eligible_sources,
    overall_score,
    policy_issues,
    policy_version,
    prioritise_findings,
    score_checks,
    validate_scored_report,
)
from .wording import quotation_context

RULE_VERSION = "observable-rule-checks-v15"


def sentence_clauses(text):
    """Keep decimal values and qualifications within their original sentence."""
    return [part.strip() for part in re.split(r"(?<=[.!?])\s+", text) if part.strip()]


def workflow_candidates(conversation, tables):
    signals = {}
    product_context = None
    for position, event in enumerate(conversation["events"]):
        if event["speaker"] == "agent" and product_context:
            introduced = set(
                re.findall(r"\b(?:boots|shirt|jeans|jacket)\b", normal(event["text"]))
            )
            if introduced - {product_context[0]}:
                product_context = None
        if event["speaker"] != "customer" or quotation_context(
            conversation["events"], position
        ):
            continue
        text = normal(unquoted(event["text"]))
        if re.search(r"\b(?:said|wrote|quoted)\b", text):
            product_context = None
            continue
        context = product_context
        product_context = None
        products = set(re.findall(r"\b(?:boots|shirt|jeans|jacket)\b", text))
        if (
            len(products) == 1
            and re.search(r"\b(?:buying|purchasing|looking at|product:)\s", text)
            and not re.search(
                r"\b(?:not|never|if|unless|don't|do not|no longer)\b", text
            )
        ):
            product_context = (next(iter(products)), event["turn_id"])
        segments = [text, *sentence_clauses(text)]
        for sentence in list(dict.fromkeys(segments)):
            conditional = re.sub(
                r"\b(?:know|check|tell me|wondering|what happens) if\b",
                "inquiring whether",
                sentence,
            )
            if re.search(r"\b(?:if|unless)\b", conditional):
                continue
            clauses = [sentence, *re.split(r"\s+(?:but|because)\s+", sentence)]
            for clause in dict.fromkeys(clauses):
                if re.search(r"\b(?:no longer|don't want|do not want)\b", clause):
                    continue
                for workflow in tables["workflows"]:
                    direct = any(
                        re.search(pattern, clause, re.IGNORECASE)
                        for pattern in workflow["purpose_patterns"]
                    )
                    linked = bool(
                        context
                        and workflow["id"].startswith("single-item-query-")
                        and (not products or products == {context[0]})
                        and information_question(clause.strip(" .!?"), context[0])
                        and any(
                            re.search(
                                pattern, context[0] + ". " + clause, re.IGNORECASE
                            )
                            for pattern in workflow["purpose_patterns"]
                        )
                    )
                    if direct or linked:
                        turns = signals.setdefault(workflow["id"], [])
                        for turn in ([context[1]] if linked else []) + [
                            event["turn_id"]
                        ]:
                            if turn not in turns:
                                turns.append(turn)
    return signals


def _check(
    rule,
    requirement,
    outcome,
    explanation,
    turn_ids,
    reference_ids,
    citations,
    authority,
    blocked,
    *,
    unique=True,
    advice=None,
):
    evidence = [citations[turn] for turn in dict.fromkeys(turn_ids)]
    sources = [
        authority[identifier]
        for identifier in dict.fromkeys(reference_ids)
        if identifier in authority
    ]
    reasons = []
    if blocked:
        reasons.append("Scoring policy approval is pending or no longer valid.")
    if not unique:
        reasons.append("Workflow applicability remains ambiguous.")
    if not sources:
        reasons.append("The applicable guideline or criterion is not eligible.")
    if reasons:
        outcome = "unresolved"
    return {
        "id": "check-" + content_version([rule, turn_ids, reference_ids])[7:27],
        "ruleId": rule,
        "requirement": requirement,
        "outcome": outcome,
        "earned": {"supported": 1, "breach": 0}.get(outcome),
        "maximum": 1,
        "explanation": " ".join([explanation, *reasons]),
        "advice": advice
        or "Review the cited evidence and stated limitation before making a decision.",
        "citations": evidence + sources,
        "critical": False,
    }


FIELD_TOKENS = {
    "name": "PERSON",
    "account-id": "ACCOUNT_ID",
    "username": "USERNAME",
    "email": "EMAIL",
    "order-id": "ORDER_ID",
    "address": "ADDRESS",
}


def supplied_fields(conversation):
    supplied = {}
    for position, event in enumerate(conversation["events"]):
        if event["speaker"] != "customer" or quotation_context(
            conversation["events"], position
        ):
            continue
        text = normal(unquoted(event["text"]))
        for clause in re.split(r",|;|\s+and\s+", text):
            match = re.fullmatch(
                r"\s*(?:(?:my )?(?:full name|name|account id|username|email(?: address)?|order id|address)(?: is|:)?)?\s*(\[([a-z_]+)_\d+\])[.! ]*",
                clause,
            )
            if match:
                for field, token in FIELD_TOKENS.items():
                    if match[2] == token.casefold():
                        supplied.setdefault(field, []).append(
                            (event["turn_id"], event["text"].casefold().find(match[1]))
                        )
    return supplied


def _procedure(conversation, selected, tables, make):
    checks, matched = [], set()
    supplied = supplied_fields(conversation)
    actions = [event for event in conversation["events"] if event["kind"] == "action"]
    for workflow in selected:
        for index, requirement in enumerate(workflow["actions"]):
            button = requirement["button"]
            form = tables["action_forms"].get(button, {})
            complete, started = [], []
            for event in actions:
                for field, target in [
                    ("completed_pattern", complete),
                    ("started_pattern", started),
                ]:
                    if form.get(field) and re.fullmatch(
                        form[field], event["text"], re.IGNORECASE
                    ):
                        target.append(event["turn_id"])
                        matched.add(event["turn_id"])
            rule = f"{workflow['id']}:action:{index}"
            condition = requirement.get("condition")
            outcome = "supported" if complete and not condition else "unresolved"
            explanation = (
                f"A recorded {button} action is present. {form.get('limit', '')}"
                if complete
                else f"{button} is started, not established as complete."
                if started
                else f"No supported {button} record was recognised; this is not evidence of omission."
            )
            if condition:
                explanation += (
                    " The source condition needs a supported interpretation: "
                    + condition
                )
            checks.append(
                make(
                    rule,
                    f"Recorded action: {button}",
                    outcome,
                    explanation,
                    complete[:1] or started[:1],
                    [requirement["reference_id"]],
                    unique=len(selected) == 1,
                )
            )
            # A recorded payload does not prove its adequacy, inputs or authority.
            for number, prerequisite in enumerate(requirement.get("prerequisites", [])):
                fields = [prerequisite["field"], *prerequisite.get("alternatives", [])]
                cutoff = min(complete + started) if complete or started else 0
                provided = [
                    point
                    for field in fields
                    for point in supplied.get(field, [])
                    if point[0] < cutoff
                ]
                description = " or ".join(fields)
                checks.append(
                    make(
                        f"{rule}:prerequisite:{number}",
                        "Supply " + description,
                        "supported" if provided else "unresolved",
                        "Previously volunteered information counts; this establishes supplied input, not identity."
                        if provided
                        else "No supported input/action link establishes this prerequisite; no omission is inferred.",
                        [min(provided)[0], cutoff] if provided else [],
                        [requirement["reference_id"]],
                        unique=len(selected) == 1,
                    )
                )
            for number, relation in enumerate(requirement.get("required_before", [])):
                before, after = (
                    supplied.get(relation["before"], []),
                    supplied.get(relation["after"], []),
                )
                supported = bool(before and after and min(before) < min(after))
                checks.append(
                    make(
                        f"{rule}:order:{number}",
                        relation["before"] + " before " + relation["after"],
                        "supported" if supported else "unresolved",
                        "Canonical positions establish the explicitly required input relationship."
                        if supported
                        else "The required relationship is not established; volunteered order or missing records do not prove a breach.",
                        [min(before)[0], min(after)[0]] if supported else [],
                        [requirement["reference_id"]],
                        unique=len(selected) == 1,
                    )
                )
            if button in {
                "Enter Details",
                "Enter Detail",
                "Record Reason",
                "Update Order",
                "Update Account",
            }:
                checks.append(
                    make(
                        f"{rule}:payload",
                        f"Applicable values for {button}",
                        "unresolved",
                        "The recorded value must be linked to the requested value and all applicable conditions; arbitrary payloads cannot earn this point.",
                        complete[:1],
                        [requirement["reference_id"]],
                    )
                )
    for event in actions:
        if event["turn_id"] not in matched:
            checks.append(
                make(
                    f"action-unrecognised:{event['turn_id']}",
                    "Unrecognised recorded action",
                    "unresolved",
                    "This action form has no supported interpretation; no omission or success is inferred.",
                    [event["turn_id"]],
                    [],
                )
            )
    return checks


def _completeness(requests, unknown, make):
    checks = []
    refs = ["memoria-rule-request-response"]
    for request in requests:
        history = request["history"]
        last = history[-1]
        turns = [
            *request.get("context_turn_ids", []),
            request["turn_id"],
            *last["turn_ids"],
        ]
        state = request["state"]
        if state == "withdrawn":
            outcome, explanation = (
                "supported",
                "The original request and its explicit contextual withdrawal are linked; no completed action is claimed.",
            )
        elif state == "changed":
            outcome, explanation = (
                "supported",
                "The original request is linked to an explicit replacement; the replacement is assessed separately.",
            )
        elif state == "answered":
            outcome, explanation = (
                "supported",
                "A directly linked response addresses the request. This does not establish factual correctness or transaction success.",
            )
        elif state == "refused":
            outcome, explanation = (
                "supported",
                "An explicit refusal addresses the named request. Whether the refusal is justified remains a separate Procedure or Answer-support check; the requested action is not established as complete.",
            )
        else:
            outcome = "unresolved"
            explanation = {
                "promised": "The agent made a linked promise. Its suitability and fulfilment are not established by that promise.",
                "active": "No supported linked disposition was recognised; unrecognised wording or missing records do not prove neglect.",
            }[state]
        if state == "answered" and (request.get("question") or {}).get("attribute") in {
            "cancellation",
            "late-payment",
        }:
            explanation += " Only the named policy consequence is addressed; all other terms, applicability and factual correctness remain unverified."
        checks.append(
            make(
                request["id"] + ":disposition",
                "Address the distinct customer request",
                outcome,
                explanation,
                turns,
                refs,
            )
        )
        if any(item["state"] == "promised" for item in history) and state not in {
            "withdrawn",
            "changed",
        }:
            promise = next(
                item for item in reversed(history) if item["state"] == "promised"
            )
            checks.append(
                make(
                    request["id"] + ":promise",
                    "Clarify the outstanding commitment",
                    "unresolved",
                    "A promise is retained separately; the record does not establish external fulfilment or an overdue obligation.",
                    [request["turn_id"], *promise["turn_ids"]],
                    refs,
                )
            )
    for item in unknown:
        checks.append(
            make(
                f"request-unrecognised:{item['turn_id']}",
                "Resolve customer request or contextual meaning",
                "unresolved",
                item["reason"],
                [item["turn_id"]],
                refs,
            )
        )
    # Multiple unsupported clauses in a turn must not duplicate the same check.
    return list({row["id"]: row for row in checks}.values())


def _state_before(request, turn):
    earlier = [
        change for change in request["history"] if max(change["turn_ids"]) < turn
    ]
    return earlier[-1]["state"] if earlier else None


def _style(conversation, requests, make):
    checks, seen = [], set()
    field = r"(?:full name|first name|last name|name|account (?:id|number)|username|user name|email(?: address)?|e-mail|order (?:id|number)|address|membership level)"
    fields = field + r"(?:(?:, (?:and |or )?| (?:and|or) )(?:your )?" + field + r")*"
    instruction = (
        r"(?:now |okay,? |ok,? )?(?:please (?:provide|give me) your |"
        r"(?:may|can|could) i (?:also )?(?:have|get) your |"
        r"(?:can|could|would) you (?:please )?(?:provide|give me) your |"
        r"(?:i need|i will need|i'll need) (?:to know )?your |what(?: is|'s) your )"
        + fields
        + r"(?: please)?"
    )
    courtesy = (
        r"(?:thank you|thanks)(?: very much| so much)?(?:,? \[person_\d+\])?"
        r"(?: for (?:your help|waiting|the information|your patience|contacting us))?"
        r"|(?:then )?(?:you )?have a (?:good|great|nice|wonderful|lovely|beautiful|pleasant) (?:day|evening|weekend)(?: too)?"
        r"|(?:you are|you're) (?:very |most )?welcome|(?:it's |it is )?my pleasure"
        r"|good (?:morning|afternoon|evening)(?:,? \[person_\d+\])?"
    )
    for position, event in enumerate(conversation["events"]):
        if event["speaker"] != "agent":
            continue
        quoted = bool(
            quotation_context(conversation["events"], position)
            or unquoted(event["text"]) != event["text"]
            or re.search(r"\b(?:said|wrote|quoted|repeat)\b", normal(event["text"]))
        )
        clauses = [event["text"]] if quoted else sentence_clauses(event["text"])
        for clause_index, clause in enumerate(clauses):
            text = normal(clause).strip(" .!?")
            if not text or text in seen:
                continue
            seen.add(text)
            rule = f"style-respect:{event['turn_id']}:{clause_index}"
            if quoted:
                checks.append(
                    make(
                        rule,
                        "Attribute wording in context",
                        "unresolved",
                        "Reported speech is not a directly addressed statement.",
                        [event["turn_id"]],
                        ["memoria-rule-wording-respect"],
                    )
                )
            elif (
                re.fullmatch(r"(?:you are|you're) (?:an idiot|stupid)", text)
                and "?" not in event["text"]
            ):
                checks.append(
                    make(
                        rule,
                        "Use respectful customer-directed wording",
                        "breach",
                        "This explicit statement directly insults the customer; quotation and question contexts are excluded.",
                        [event["turn_id"]],
                        ["memoria-rule-wording-respect"],
                    )
                )
            elif re.fullmatch(courtesy, text):
                if "respect-courtesy" not in seen:
                    seen.add("respect-courtesy")
                    checks.append(
                        make(
                            rule,
                            "Express a respectful courtesy",
                            "supported",
                            "A directly expressed courtesy is observed. This does not grade all other wording.",
                            [event["turn_id"]],
                            ["memoria-rule-wording-respect"],
                        )
                    )
            elif re.fullmatch(instruction, text):
                checks.append(
                    make(
                        rule,
                        "Give a specific understandable instruction",
                        "supported",
                        "The instruction names its requested fields. Whether they are appropriate is a separate Procedure check.",
                        [event["turn_id"]],
                        ["memoria-rule-wording-clarity"],
                    )
                )
            elif re.fullmatch(
                r"i (?:understand|see) (?:you want|you need|you'd like) (?:a |your |the )?(?:refund|return|address change)",
                text,
            ):
                matching = [
                    r
                    for r in requests
                    if r["turn_id"] < event["turn_id"]
                    and r["topic"] in text
                    and r["goal"] in {"refund", "return", "change"}
                    and _state_before(r, event["turn_id"])
                    not in {"withdrawn", "changed", None}
                ]
                checks.append(
                    make(
                        rule,
                        "Acknowledge the expressed request",
                        "supported" if len(matching) == 1 else "unresolved",
                        "Acknowledgement must match one existing request; it does not establish empathy or customer satisfaction.",
                        ([matching[0]["turn_id"]] if len(matching) == 1 else [])
                        + [event["turn_id"]],
                        ["memoria-rule-wording-acknowledgement"],
                    )
                )
            else:
                checks.append(
                    make(
                        rule,
                        "Assess wording within supported patterns",
                        "unresolved",
                        "This wording has no defined clarity, acknowledgement or respect interpretation; no emotion, intent or tone is inferred.",
                        [event["turn_id"]],
                        ["memoria-rule-wording-clarity"],
                    )
                )
    return checks


def _answers(conversation, selected, eligible, make):
    checks, seen = [], set()
    sources = {reference["id"]: reference for reference in eligible}
    statements = []
    for workflow in selected:
        for statement in workflow.get("answer_statements", []):
            reference = sources.get(statement["reference_id"])
            if reference is None:
                continue
            quote = statement["quote"]
            if (
                statement["reference_id"] not in workflow["reference_ids"]
                or statement["reference_version"] != reference["version"]
                or not isinstance(quote, str)
                or not quote.strip()
                or quote not in reference["text"]
            ):
                raise ValueError(
                    "Factual quotation does not match its workflow source."
                )
            statements.append((reference, quote))
    for position, event in enumerate(conversation["events"]):
        if event["speaker"] != "agent":
            continue
        attributed = bool(
            quotation_context(conversation["events"], position)
            or unquoted(event["text"]) != event["text"]
            or re.search(
                r"\b(?:not|never|unless|except|only|if|provided|assuming|subject to|on condition|said|wrote|correction|actually|instead)\b",
                normal(event["text"]),
            )
        )
        clauses = [event["text"]] if attributed else sentence_clauses(event["text"])
        if any(
            not assertion_clause(part) and not nonfactual_phrase(part)
            for part in clauses
        ):
            clauses = [event["text"]]
        for clause_index, clause in enumerate(clauses):
            for atom_index, (atom, context_limit) in enumerate(claim_atoms(clause)):
                text = normal(atom)
                if not text:
                    continue
                frame, values = claim_frame(text) if context_limit else fact_frame(text)
                identity = (frame, tuple(values), bool(context_limit))
                if identity in seen:
                    continue
                seen.add(identity)
                if not context_limit and nonfactual_phrase(text):
                    continue
                matches = [
                    (reference, statement, compare_facts(statement, text))
                    for reference, statement in statements
                    if compare_facts(statement, text) is not None
                ]
                unambiguous = (
                    len(matches) == 1
                    and len(selected) == 1
                    and not attributed
                    and not context_limit
                    and unquoted(event["text"]) == event["text"]
                )
                unambiguous = (
                    unambiguous
                    and "?" not in text
                    and not re.search(
                        r"\b(?:not|never|unless|except|said|wrote|correction|actually|instead)\b",
                        text,
                    )
                )
                refs = [matches[0][0]["id"]] if unambiguous else []
                rule = (
                    f"answer-assertion:{event['turn_id']}:{clause_index}:{atom_index}"
                )
                if unambiguous:
                    outcome = matches[0][2]
                    explanation = (
                        "The recognized factual equivalent is supported by the selected guideline passage, with its subjects, units and conditions preserved."
                        if outcome == "supported"
                        else "The same assertion and conditions contain a directly contradictory numeric value."
                    )
                    check = make(
                        rule,
                        "Support the factual assertion and its qualifications",
                        outcome,
                        explanation,
                        [event["turn_id"]],
                        refs,
                    )
                    check["citations"] = [
                        {**citation, "quote": matches[0][1]}
                        if citation["kind"] == "reference"
                        else citation
                        for citation in check["citations"]
                    ]
                    checks.append(check)
                else:
                    checks.append(
                        make(
                            rule,
                            "Support the factual assertion and its qualifications",
                            "unresolved",
                            context_limit
                            or "The claim has no unique complete comparison. Values, units, conditions, reported outcomes and corrections are not inferred from lexical overlap.",
                            [event["turn_id"]],
                            [],
                            unique=len(selected) == 1,
                        )
                    )
    return checks


def assess_conversation(evidence, references, rubric, tables, *, as_of):
    validate_evidence(evidence)
    if len(evidence["conversations"]) != 1:
        raise ValueError("Supply one conversation per isolated assessment.")
    conversation = evidence["conversations"][0]
    signals = workflow_candidates(conversation, tables)
    selected = [row for row in tables["workflows"] if row["id"] in signals]
    scopes = list(signals)
    eligible = eligible_sources(
        references, rubric, tables, as_of=as_of, workflows=scopes
    )
    authority = {row["id"]: row["citation"] for row in reference_passages(eligible)}
    citations = {
        row["citation"]["turn_id"]: row["citation"]
        for row in conversation_passages([conversation])
    }
    blocked = policy_issues(tables, as_of=as_of)
    requests, unknown = request_links(conversation)

    def make(rule, requirement, outcome, explanation, turns, refs, **kwargs):
        check = _check(
            rule,
            requirement,
            outcome,
            explanation,
            turns,
            refs,
            citations,
            authority,
            blocked,
            **kwargs,
        )
        check["critical"] = (
            not blocked and check["outcome"] == "breach" and critical_rule(rule, tables)
        )
        return check

    report = {
        "schema_version": VERSION,
        "conversation_id": conversation["id"],
        "transcript_version": conversation["transcript_version"],
        "as_of": as_of,
        "source": deepcopy(evidence["source"]),
        "masking_version": evidence["masking_version"],
        "workflows": scopes,
        "workflow_evidence": {
            key: [citations[turn] for turn in turns] for key, turns in signals.items()
        },
        "versions": {
            "rules": RULE_VERSION,
            "links": LINK_VERSION,
            "tables": policy_version(tables),
        },
        "processing_status": "completed",
        "categories": [],
        "errors": [],
        "requests": requests,
        "reference_trace": [
            {
                "id": row["id"],
                "version": row["version"],
                "interpretation_limits": row.get("interpretation_limits", []),
            }
            for row in eligible
        ],
    }

    def refund_checks(category):
        if scopes != ["product-defect-initiate-refund"]:
            return None
        pair = check_procedure_support(
            conversation,
            references,
            as_of=as_of,
            scope="refund-initiation",
            masking_version=evidence["masking_version"],
        )
        result = next(row for row in pair if row["category"] == category)
        converted = []
        for row in result["details"]["checks"]:
            turns = [
                citation["turn_id"]
                for citation in row["citations"]
                if citation["kind"] == "conversation"
            ]
            sources = [
                citation["reference_id"]
                for citation in row["citations"]
                if citation["kind"] == "reference"
            ]
            outcome = {"meets-criteria": "supported", "needs-review": "breach"}.get(
                row["result"], "unresolved"
            )
            converted.append(
                make(
                    row["rule_id"],
                    row["explanation"],
                    outcome,
                    row["explanation"],
                    turns,
                    sources,
                    advice=row["advice"],
                )
            )
        return converted

    evaluators = {
        "procedure": lambda: (
            refund_checks("procedure")
            or _procedure(conversation, selected, tables, make)
        ),
        "completeness": lambda: _completeness(requests, unknown, make),
        "communication-style": lambda: _style(conversation, requests, make),
        "answer-support": lambda: (
            refund_checks("answer-support")
            or _answers(conversation, selected, eligible, make)
        ),
    }
    for category in CATEGORIES:
        try:
            checks = evaluators[category]()
            if not checks:
                checks = [
                    make(
                        category + ":unresolved-inventory",
                        "Establish applicable checks",
                        "unresolved",
                        "No supported applicable check inventory is established. No automatic full marks or omission is inferred.",
                        [],
                        [],
                    )
                ]
            legacy = [
                {
                    "rule_id": row["ruleId"],
                    "result": {
                        "supported": "meets-criteria",
                        "breach": "needs-review",
                    }.get(row["outcome"], "cannot-assess"),
                    "explanation": row["explanation"],
                    "advice": row["advice"],
                    "citations": row["citations"],
                }
                for row in checks
            ]
            result = category_result(conversation, category, legacy)
            limitations = result["limitations"] + blocked
            if len(scopes) != 1:
                limitations.append(
                    "Workflow applicability is ambiguous or unrecognised; the denominator is a documented candidate inventory, not proven total coverage."
                )
            scoring = score_checks(
                checks,
                limitations=limitations,
                interpretation_limits=[
                    limit
                    for ref in eligible
                    for limit in ref.get("interpretation_limits", [])
                ],
                inventory_complete=len(scopes) == 1
                and not any(
                    row["ruleId"].endswith("unresolved-inventory") for row in checks
                ),
            )
            report["categories"].append(
                {
                    "category": category,
                    "status": "completed",
                    "error": None,
                    "result": result,
                    "scoring": scoring,
                }
            )
        except (ValueError, TypeError, KeyError, re.error) as error:
            message = f"{type(error).__name__}: category evaluation failed validation."
            report["errors"].append({"category": category, "message": message})
            report["categories"].append(
                {
                    "category": category,
                    "status": "failed",
                    "error": message,
                    "result": None,
                    "scoring": score_checks(
                        [], error=message, inventory_complete=False
                    ),
                }
            )
    if report["errors"]:
        report["processing_status"] = (
            "partial"
            if any(row["status"] == "completed" for row in report["categories"])
            else "failed"
        )
    report["overall"] = overall_score(
        report["categories"], tables.get("profiles", []), scopes, as_of=as_of
    )
    report["priorities"] = prioritise_findings(report["categories"], report["overall"])
    validate_scored_report(report, evidence, eligible, tables, as_of=as_of)
    return report
