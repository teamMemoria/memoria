from backend.interface_adapters.call_checks import observed_workflow
from backend.interface_adapters.extension_checks import gold_checks


def dialogue(*entries):
    return [
        {"turn_id": i, "speaker": speaker, "text": text}
        for i, (speaker, text) in enumerate(entries, 1)
    ]


def test_acknowledgement_does_not_turn_a_notification_promise_into_completion():
    events = dialogue(
        ("customer", "The website is moving very slow today."),
        (
            "agent",
            "I'm very sorry to hear that. I'll file a report to the Website Team.",
        ),
        ("action", "The website team will be notified."),
        ("customer", "Is there anything I can do in the meantime?"),
        ("agent", "Please close all other tabs."),
        ("customer", "That helped."),
    )
    _, checks, _ = observed_workflow(events)
    assert checks["completeness.followups"][0] == "supported"
    assert "completeness.promises_next_steps" not in checks
    events[2]["text"] = "The website team has been notified."
    _, checks, _ = observed_workflow(events)
    outcome, _, cited = checks["completeness.promises_next_steps"]
    assert outcome == "supported"
    assert [turn["turn_id"] for turn in cited] == [1, 2, 3]
    assert checks["answer-support.facts"][0] == "unresolved"


def test_cancellation_withdrawal_needs_context_and_no_competing_action():
    events = dialogue(
        ("agent", "Would you like slower shipping, or cancel the order?"),
        ("customer", "Cancel the order."),
        ("customer", "Never mind, my issue is solved."),
        ("agent", "Are you sure?"),
        ("customer", "Yes, it is solved."),
    )
    category, checks, _ = observed_workflow(events)
    assert category == "order"
    assert checks["completeness.promises_next_steps"][0] == "not-applicable"
    assert observed_workflow(events[:-1]) is None
    assert (
        observed_workflow(
            [
                *events,
                {"turn_id": 6, "speaker": "action", "text": "Order was cancelled."},
            ]
        )
        is None
    )


def test_negated_shipping_request_does_not_create_a_score():
    events = dialogue(
        ("customer", "I do not want to upgrade my shipping."),
        ("agent", "It is too late to upgrade."),
    )
    assert observed_workflow(events) is None


def test_gold_policy_needs_approval_and_cannot_verify_duration():
    turns = {
        label: {"turn_id": index}
        for index, label in enumerate(
            (
                "request",
                "account",
                "identity",
                "tier",
                "offer",
                "update",
                "duration_question",
                "duration",
            ),
            1,
        )
    }
    pending = gold_checks(turns, None, extra_questions=False)
    assert pending["procedure.actions"][0] == "unresolved"
    assert pending["answer-support.facts"][0] == "unresolved"
    reference = {"kind": "reference", "reference_id": "12"}
    approved = gold_checks(turns, reference, extra_questions=False)
    assert approved["procedure.actions"][2][-1] == reference
    assert approved["answer-support.recorded_outcomes"][0] == "supported"
    assert approved["answer-support.values"][0] == "unresolved"
