"""Scope-specific evidence subchecks must never give credit for a different obligation."""

import pytest

from backend.entities.assessments import (
    AnalysisUnavailableError,
    ReportRejectedError,
)
from backend.entities.guidelines import (
    RETURN_COLOUR,
    RETURN_SIZE,
)
from backend.entities.refund_amount import (
    REFUND_AMOUNT_CHECK,
    SUBSCRIPTION_PRICE_CHECK,
)
from backend.interface_adapters.controllers.assessments import validate_payload
from backend.interface_adapters.guideline_checks import SCOPED_CHECKS, return_size
from tests.scoring_fixtures import (
    approved_guideline,
    events,
    scoring_request,
    scoring_service,
)

RETURN = [
    ("customer", "I want to return a jacket. It doesn't fit."),
    ("customer", "[PERSON_1] [ORDER_ID_1] [USERNAME_1] [EMAIL_1]"),
    ("agent", "How would you like the refund sent to you?"),
    ("agent", "What is your membership level?"),
    ("customer", "Hmm."),
    ("customer", "Gold."),
    ("customer", "Transferred to my bank account."),
    ("action", "Details of [ADDRESS_1] have been entered."),
    (
        "agent",
        "Would you like to return it by mail, in store, or at a drop off center?",
    ),
    ("customer", "In store."),
    ("action", "Order has been updated with in store."),
]
BILLING = [
    ("customer", "I was charged for something I didn't buy."),
    ("agent", "I can issue a refund."),
    ("customer", "Do you know how much a subscription is supposed to cost?"),
    ("agent", "A single annual subscription is $79."),
    ("customer", "I got charged $158."),
    ("agent", "I will refund $79."),
    ("action", "A refund has been made for the amount of $79."),
]
ROUTE = "procedure.actions.return_method"
PAYOUT = "procedure.actions.refund_destination"


def approved_return(key=RETURN_SIZE, reference_id="1"):
    return approved_guideline(key, reference_id)


def report(pairs, *, references=None):
    service = scoring_service()
    req = scoring_request(
        {"id": "test", "transcript_version": "test-v1", "events": events(pairs)},
        references,
    )
    result = service.adapter.analyse(req)
    parsed = service.report_parser(req, result)
    validate_payload(req, parsed, policy=service.percentage_policy)
    return result, req, parsed, service


def scoring(result, name):
    data = next(c["scoring"] for c in result["categories"] if c["category"] == name)
    return data, {c["rule_id"]: c for c in data["checks"]}


def test_approved_in_store_route_and_bank_payout_are_separate_applicable_checks():
    result, *_ = report(RETURN, references=[approved_return()])
    data, checks = scoring(result, "procedure")
    assert [(checks[k]["outcome"], checks[k]["maximum"]) for k in (ROUTE, PAYOUT)] == [
        ("supported", 25),
        ("unresolved", 25),
    ]
    assert checks["procedure.order_permission"]["outcome"] == "unresolved"
    assert (data["possible"], data["score"], data["coverage"]) == (100, 77.5, 55)
    assert {c["kind"] for c in checks[ROUTE]["citations"]} == {
        "conversation",
        "reference",
    }


@pytest.mark.parametrize(
    "tail",
    [
        [("action", "Order has been updated with mail.")],
        [("agent", "Order has been updated with in store.")],
        [
            ("customer", "Actually, by mail."),
            ("action", "Order has been updated with in store."),
        ],
    ],
)
def test_wrong_or_withdrawn_route_is_unresolved_and_retains_its_points(tail):
    result, *_ = report(RETURN[:-1] + tail, references=[approved_return()])
    data, checks = scoring(result, "procedure")
    assert checks[ROUTE]["outcome"] == checks[PAYOUT]["outcome"] == "unresolved"
    assert data["possible"] == 100


def test_return_approval_and_membership_context_are_required():
    with pytest.raises(AnalysisUnavailableError):
        report(RETURN, references=[{**approved_return(), "status": "pending"}])
    altered = [*RETURN[:4], ("agent", "Let me change subjects."), *RETURN[5:]]
    assert not return_size(events(altered))


def test_refund_amount_can_be_verified_without_awarding_subscription_price_points():
    result, *_ = report(BILLING)
    data, checks = scoring(result, "answer-support")
    assert checks[REFUND_AMOUNT_CHECK]["outcome"] == "supported"
    assert checks[SUBSCRIPTION_PRICE_CHECK]["outcome"] == "unresolved"
    assert all(
        checks[k]["maximum"] == 10
        for k in (REFUND_AMOUNT_CHECK, SUBSCRIPTION_PRICE_CHECK)
    )
    assert (data["score"], data["coverage"], data["possible"]) == (55, 10, 100)


@pytest.mark.parametrize(
    "tail",
    [
        [("action", "A refund has been made for the amount of $78.")],
        [("action", "A refund has been made for the amount of .")],
        [("customer", "Actually, I want to refund a different order."), BILLING[-1]],
        [BILLING[-1], BILLING[-1]],
    ],
)
def test_ambiguous_or_mismatched_refund_records_do_not_earn_credit_or_remove_points(
    tail,
):
    result, *_ = report(BILLING[:-1] + tail)
    data, checks = scoring(result, "answer-support")
    assert (
        checks[REFUND_AMOUNT_CHECK]["outcome"]
        == checks[SUBSCRIPTION_PRICE_CHECK]["outcome"]
        == "unresolved"
    )
    assert (data["score"], data["coverage"], data["possible"]) == (None, 0, 100)


def test_an_extra_agent_statement_cannot_substitute_for_an_independent_action():
    result, *_ = report(
        [*BILLING[:-1], ("agent", "A refund has been made for the amount of $79.")]
    )
    data, checks = scoring(result, "answer-support")
    assert checks["answer-support.values"]["outcome"] == "unresolved"
    assert (data["score"], data["coverage"], data["possible"]) == (None, 0, 100)


def test_storage_requires_the_actual_refund_record_citation():
    result, req, parsed, service = report(BILLING)
    _, checks = scoring(result, "answer-support")
    checks[REFUND_AMOUNT_CHECK]["citations"].pop()
    with pytest.raises(ReportRejectedError, match="matching recorded action"):
        validate_payload(req, parsed, policy=service.percentage_policy)


MIXED_RETURN = [
    ("customer", "I would like to return a jacket."),
    ("customer", "It is the wrong colour."),
    ("customer", "It is too small."),
    ("agent", "What membership level do you have?"),
    ("customer", "Gold."),
    ("agent", "Gold members get unlimited returns."),
]
RETURN_FACT = "answer-support.facts"


def test_mixed_return_keeps_both_approved_sources_without_double_counting():
    result, *_ = report(
        MIXED_RETURN,
        references=[approved_return(), approved_return(RETURN_COLOUR, "2")],
    )
    data, checks = scoring(result, "answer-support")
    fact = checks[RETURN_FACT]
    assert fact["outcome"] == "supported"
    refs = [c for c in fact["citations"] if c["kind"] == "reference"]
    assert [(c["reference_id"], c["reference_version"]) for c in refs] == [
        ("2", "review-2"),
        ("1", "review-1"),
    ]
    turns = [c["turn_id"] for c in fact["citations"] if c["kind"] == "conversation"]
    assert sorted(turns) == [1, 2, 3, 4, 5, 6]
    assert (data["possible"], data["coverage"], data["score"]) == (100, 30, 65)


@pytest.mark.parametrize("key", [RETURN_COLOUR, RETURN_SIZE])
def test_disagreeing_scoped_findings_keep_both_sources_and_withhold_points(
    monkeypatch, key
):
    def unresolved(turns):
        return {
            RETURN_FACT: (
                "unresolved",
                "The terms for this return remain unclear.",
                turns[1:2],
            )
        }

    monkeypatch.setitem(SCOPED_CHECKS, key, ("return", unresolved))
    result, *_ = report(
        MIXED_RETURN,
        references=[approved_return(), approved_return(RETURN_COLOUR, "2")],
    )
    data, checks = scoring(result, "answer-support")
    fact = checks[RETURN_FACT]
    assert fact["outcome"] == "unresolved"
    assert "disagree" in fact["explanation"]
    assert "The terms for this return remain unclear." in fact["explanation"]
    assert {
        c["reference_id"] for c in fact["citations"] if c["kind"] == "reference"
    } == {"1", "2"}
    assert (data["possible"], data["coverage"], data["score"]) == (100, 0, None)
