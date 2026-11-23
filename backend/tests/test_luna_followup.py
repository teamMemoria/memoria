"""Luna proposes evidence. Local checks decide which proposals can affect scores."""

from types import SimpleNamespace

import pytest
from ml.metrics.followup_task import binding, make_task, proposals

from backend.interface_adapters.followup_checks import verified_followup
from tests.scoring_fixtures import events, scoring_request, scoring_service

RULE = "communication-style.acknowledgement"
PROCEDURE = "procedure.actions"


def case(*exchanges):
    return SimpleNamespace(
        canonical_evidence={"conversations": [{"transcript_version": "test-v1"}]},
        conversation={
            "id": "test",
            "transcript_version": "test-v1",
            "events": events(exchanges),
        },
    )


def citation(turn):
    return {"kind": "conversation", "turn_id": turn["turn_id"]}


def row(rule=RULE):
    return {"rule_id": rule, "requirement": "Can this rule be verified?"}


def result(rule=RULE, turns=(1, 2), references=(), outcome="supported"):
    return {
        "checks": [
            {
                "id": rule,
                "outcome": outcome,
                "turns": list(turns),
                "references": list(references),
            }
        ]
    }


def test_requires_the_actual_request_and_linked_acknowledgement():
    request = case(
        ("customer", "Can you help with my refund?"),
        ("agent", "I can help with that."),
    )
    changes = verified_followup(request, [row()], result(), [], {}, citation)
    assert changes[RULE][0] == "supported"
    assert [c["turn_id"] for c in changes[RULE][2]] == [1, 2]
    assert not verified_followup(request, [row()], result(turns=(2,)), [], {}, citation)


@pytest.mark.parametrize(
    "response",
    [
        "Hello, I hope you are having a good day.",
        'The last Agent told me "I can help with that."',
        "My colleague said I can help with that.",
    ],
)
def test_does_not_treat_greeting_or_reported_speech_as_acknowledgement(response):
    request = case(("customer", "Can you help with my refund?"), ("agent", response))
    assert not verified_followup(request, [row()], result(), [], {}, citation)


def test_procedure_requires_same_approved_reference_and_local_interpretation():
    request = case(
        ("customer", "I want the shipping fee waived."),
        ("action", "Order has been updated with waive fee."),
    )
    reference = {
        "id": "7",
        "version": "review-5",
        "section_id": "7",
        "text": "Eligible waiver",
    }
    ref_cite = {"kind": "reference", "reference_id": "7"}
    evidence = [citation(t) for t in request.conversation["events"]]
    local = {
        PROCEDURE: (
            "supported",
            "Scoped policy and recorded action",
            [*evidence, ref_cite],
        )
    }
    rows = [row(PROCEDURE)]
    picks = result(PROCEDURE, references=("7",))
    assert (
        verified_followup(request, rows, picks, [reference], local, citation) == local
    )
    assert not verified_followup(request, rows, picks, [], local, citation)
    assert not verified_followup(
        request, rows, result(PROCEDURE), [reference], local, citation
    )
    assert not verified_followup(request, rows, picks, [reference], {}, citation)


def test_task_contains_only_requested_checks_and_binding_changes_with_approval_version():
    request = case(("customer", "I need a refund."), ("agent", "I can help with that."))
    rules = [
        row(r)
        for r in (
            PROCEDURE,
            RULE,
            "completeness.direct_response",
            "answer-support.facts",
        )
    ]
    common = {"check_templates": {r["rule_id"]: {"conditions": {}} for r in rules}}
    category = {"id": "refund", "title": "Refund"}
    ref = {
        "id": "2",
        "version": "review-10",
        "section_id": "2",
        "text": "Eligible refund",
    }
    payload, schema = make_task(request, common, category, rules, [ref])
    assert len(payload["checks"]) == 4
    assert schema["additionalProperties"] is False
    assert binding(request, category, rules, [ref]) != binding(
        request, category, rules, [{**ref, "version": "review-11"}]
    )


def test_invented_turn_unexpected_rule_or_duplicated_anchor_is_rejected():
    for response in (result(turns=(1, 9)), result(PROCEDURE), result(turns=(1, 1, 2))):
        with pytest.raises(ValueError):
            proposals(response, {RULE}, {1, 2}, set())


def test_acknowledgement_accepts_a_direct_reply_to_a_cancel_request():
    request = case(
        ("customer", "Cancel the order, please."), ("agent", "I can do that for you.")
    )
    assert RULE in verified_followup(request, [row()], result(), [], {}, citation)


def test_delivery_waiting_step_does_not_require_proof_of_delivery():
    rule = "completeness.promises_next_steps"
    request = case(
        ("customer", "I have not received my order."),
        (
            "agent",
            "It is possible it will arrive this week. Please wait a few more days.",
        ),
        ("customer", "Okay, I can do that."),
    )
    review = result(rule, turns=(2, 3))
    assert rule in verified_followup(request, [row(rule)], review, [], {}, citation)
    request.conversation["events"].append(
        {
            "turn_id": 4,
            "speaker": "agent",
            "kind": "message",
            "text": "I will call the carrier.",
        }
    )
    assert not verified_followup(request, [row(rule)], review, [], {}, citation)


def test_scorer_only_applies_bound_proposals_to_unresolved_checks():
    from backend.interface_adapters.controllers.assessments import validate_payload

    fixture = case(
        ("customer", "The website is running really slow. Can you help?"),
        ("agent", "I can do that for you."),
        ("agent", "I will file a report to our website team."),
    )
    request = scoring_request(
        fixture.conversation, canonical=fixture.canonical_evidence
    )
    request.canonical_evidence["conversations"][0]["id"] = "test"
    service = scoring_service()
    baseline = service.adapter.analyse(request)
    signature, payload, _ = service.adapter.followup_task(request, baseline)
    rows = [
        result(rule["id"], outcome="supported" if rule["id"] == RULE else "unresolved")[
            "checks"
        ][0]
        for rule in payload["checks"]
    ]
    service.adapter.luna_followup["test"] = {
        "binding": signature,
        "result": {"checks": rows},
    }
    report = service.adapter.analyse(request)
    parsed = service.report_parser(request, report)
    validate_payload(request, parsed, policy=service.percentage_policy)
    prior_checks = {
        c["rule_id"]: c for m in baseline["categories"] for c in m["scoring"]["checks"]
    }
    changed = {
        c["rule_id"]
        for m in report["categories"]
        for c in m["scoring"]["checks"]
        if c != prior_checks[c["rule_id"]]
    }
    assert changed == {RULE}
    service.adapter.luna_followup["test"]["binding"] = "stale"
    assert service.adapter.analyse(request) == baseline


@pytest.mark.parametrize(
    ("validation", "accepted"),
    [
        ("Purchase has been validated for [ORDER_ID_1].", True),
        ("Purchase validation in progress ...", False),
        ("Purchase has been validated for [ORDER_ID_2].", False),
    ],
)
def test_shipping_prerequisite_uses_a_completed_validation_for_the_same_order(
    validation, accepted
):
    from backend.entities.guidelines import SHIPPING_FEE

    request = case(
        ("customer", "Order ID: [ORDER_ID_1]."),
        ("action", validation),
        ("action", "Shipping status of order received has been noted."),
        ("action", "Order has been updated with waive fee."),
    )
    events = request.conversation["events"]
    rule = "procedure.order_permission"
    reference = {"id": "7", "draft_source_key": SHIPPING_FEE}
    ref = {"kind": "reference", "reference_id": "7"}
    proven = {
        "procedure.information": (
            "supported",
            "Evidence",
            [citation(events[0]), citation(events[2]), ref],
        ),
        "procedure.actions": (
            "supported",
            "Evidence",
            [citation(events[2]), citation(events[3]), ref],
        ),
    }
    changes = verified_followup(
        request,
        [row(rule)],
        result(rule, (1, 2, 3, 4), ("7",)),
        [reference],
        proven,
        citation,
    )
    assert (rule in changes) == accepted
