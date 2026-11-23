import pytest

from backend.entities.draft_matches import promo_days
from backend.entities.guidelines import (
    GUIDELINE_URL,
    GUIDELINES,
    PROMO_AGE,
    SHIPPING_FEE,
)
from backend.entities.policies import matches_verification
from backend.interface_adapters.controllers.assessments import validate_payload
from backend.interface_adapters.guideline_checks import shipping_fee
from tests.scoring_fixtures import (
    approved_guideline,
    events,
    scoring_request,
    scoring_service,
)

WAIVER = [
    ("customer", "I want a refund on my shipping fee"),
    ("action", "Account has been pulled up for [PERSON_1]."),
    ("customer", "Username: [USERNAME_1], email: [EMAIL_1], order: [ORDER_ID_1]"),
    ("action", "Purchase validation in progress ..."),
    ("action", "Shipping status of order received has been noted."),
    ("agent", "I will waive your fee."),
    ("action", "Order has been updated with waive fee."),
]


@pytest.mark.parametrize("key", GUIDELINES)
def test_scoped_policy_requires_the_exact_independent_reference(key):
    guide = GUIDELINES[key]
    assert len(guide.quote) <= 500
    assert matches_verification(key, guide.answer, guide.quote, GUIDELINE_URL)
    assert not matches_verification(
        key, guide.answer, "Different wording.", GUIDELINE_URL
    )
    assert not matches_verification(
        key, guide.answer, guide.quote, "https://example.test"
    )
    assert not matches_verification(key, "Different claim", guide.quote, GUIDELINE_URL)


def test_typical_promo_approval_is_separate_from_the_standard_expiry_verifier():
    guide = GUIDELINES[PROMO_AGE]
    assert promo_days(guide.quote) is None
    assert not matches_verification(
        "layer2-promo-days-7",
        "Standard promo codes expire after 7 days.",
        guide.quote,
        GUIDELINE_URL,
    )


def test_scoped_waiver_needs_approved_reference_and_full_citation_chain():
    service = scoring_service()
    reference = {**approved_guideline(SHIPPING_FEE), "status": "pending"}
    request = scoring_request(
        {"id": "target", "transcript_version": "v1", "events": events(WAIVER)},
        [reference],
    )

    def assert_policy_unresolved():
        report = service.adapter.analyse(request)
        parsed = service.report_parser(request, report)
        validate_payload(request, parsed, policy=service.percentage_policy)
        categories = {row["category"]: row["scoring"] for row in report["categories"]}
        assert categories["procedure"]["coverage"] == 0
        assert categories["answer-support"]["coverage"] == 0

    assert_policy_unresolved()
    reference["status"] = "approved"
    reference["draft_conversation_ids"] = ["target"]
    assert_policy_unresolved()
    reference["draft_conversation_ids"] = ["other"]
    report = service.adapter.analyse(request)
    parsed = service.report_parser(request, report)
    validate_payload(request, parsed, policy=service.percentage_policy)
    procedure = next(
        c["scoring"] for c in report["categories"] if c["category"] == "procedure"
    )
    assert (procedure["score"], procedure["coverage"]) == (90, 80)
    findings = {c["rule_id"]: c for c in procedure["checks"]}
    assert findings["procedure.order_permission"]["outcome"] == "unresolved"
    assert {c["kind"] for c in findings["procedure.actions"]["citations"]} == {
        "conversation",
        "reference",
    }
    answer_support = next(
        c["scoring"] for c in report["categories"] if c["category"] == "answer-support"
    )
    listed = {c["rule_id"]: c for c in answer_support["checks"]}
    assert listed["answer-support.facts"]["outcome"] == "supported"
    assert listed["answer-support.recorded_outcomes"]["outcome"] == "unresolved"


@pytest.mark.parametrize(
    "changed",
    [
        WAIVER[:4]
        + [("action", "Shipping status of delivered has been noted.")]
        + WAIVER[5:],
        WAIVER[:-1] + [("action", "Order has been updated with .")],
        WAIVER[:-1]
        + [("customer", "Actually, don't waive the shipping fee.")]
        + WAIVER[-1:],
        WAIVER[:-2] + [("agent", "I cannot waive your fee.")] + WAIVER[-1:],
    ],
)
def test_waiver_does_not_use_wrong_branch_generic_update_or_withdrawal(changed):
    assert not shipping_fee(events(changed))
