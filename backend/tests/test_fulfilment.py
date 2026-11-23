import pytest

from backend.entities.assessments import ReportRejectedError
from backend.entities.fulfilment import OUTCOME, VALUE, recorded_outcomes
from backend.interface_adapters.controllers.assessments import validate_payload
from tests.scoring_fixtures import events
from tests.test_split_evidence import approved_return, report, scoring

REFUND = [
    ("customer", "Could I get a refund?"),
    ("agent", "I can issue a refund."),
    ("action", "A refund has been made for the amount of $42."),
    ("agent", "Your refund of $42 has been successfully processed."),
]


@pytest.mark.parametrize("amount, outcome", [("42", "supported"), ("24", "breach")])
def test_refund_record_can_verify_completion_separately_from_the_amount(
    amount, outcome
):
    conversation = [
        *REFUND[:-1],
        ("agent", f"Your refund of ${amount} has been successfully processed."),
    ]
    result, req, parsed, service = report(conversation)
    _, checks = scoring(result, "answer-support")
    assert checks[OUTCOME]["outcome"] == "supported"
    assert checks[VALUE]["outcome"] == outcome
    assert checks["answer-support.facts"]["outcome"] == "unresolved"
    checks[OUTCOME]["citations"] = [
        c
        for c in checks[OUTCOME]["citations"]
        if c["kind"] != "conversation" or c["turn_id"] != 3
    ]
    with pytest.raises(ReportRejectedError, match="reference evidence"):
        validate_payload(req, parsed, policy=service.percentage_policy)


@pytest.mark.parametrize(
    "tail",
    [
        [("action", "A refund has been made for the amount of $.")],
        [REFUND[-2], ("agent", "I will issue your refund for $42.")],
        [REFUND[-2], ("agent", 'They said: "Your refund has been processed."')],
        [("customer", "Actually, don't refund this."), *REFUND[-2:]],
        [("customer", "Can you add this to my existing refund?"), *REFUND[-2:]],
    ],
)
def test_blank_promised_quoted_withdrawn_or_different_refunds_are_unresolved(tail):
    turns = events([*REFUND[:2], *tail])
    assert not recorded_outcomes(turns, "refund", turns[0])


def test_return_route_is_evidence_of_setup_separate_from_eligibility():
    conversation = [
        ("customer", "Can I return this? I ordered the wrong size."),
        ("action", "Purchase validation in progress ..."),
        ("action", "Details of [ADDRESS_1] have been entered."),
        ("agent", "How would you like to return it, by mail or in store?"),
        ("customer", "Mail please."),
        ("action", "Order has been updated with By Mail."),
        ("agent", "Your return is processing."),
    ]
    result, *_ = report(conversation, references=[approved_return()])
    _, procedure = scoring(result, "procedure")
    _, support = scoring(result, "answer-support")
    assert procedure["procedure.actions"]["outcome"] == "supported"
    assert procedure["procedure.order_permission"]["outcome"] == "unresolved"
    assert support[OUTCOME]["outcome"] == "supported"
    assert support["answer-support.facts"]["outcome"] == "unresolved"


def test_recorded_shipping_waiver_does_not_prove_policy_or_a_card_credit():
    conversation = [
        ("customer", "I want my shipping fee waived."),
        ("agent", "I will waive your shipping fee."),
        ("action", "Order has been updated with waive fee."),
        ("agent", "I have waived your shipping fee."),
    ]
    result, *_ = report(conversation)
    _, procedure = scoring(result, "procedure")
    _, support = scoring(result, "answer-support")
    assert procedure["procedure.actions"]["outcome"] == "unresolved"
    assert support[OUTCOME]["outcome"] == "supported"
    assert support[VALUE]["outcome"] == "unresolved"
