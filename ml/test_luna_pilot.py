import json
from pathlib import Path

import pytest
from ml.metrics.luna import agreed_checks, make_task, outbound_text
from ml.metrics.prepare import expand_category


def vote(rule, outcome, *turns):
    return {
        "checks": [
            {"id": rule, "outcome": outcome, "turns": list(turns), "reason": "Evidence"}
        ]
    }


def test_luna_agreement_requires_shared_customer_and_response():
    events = [
        {"turn_id": 1, "speaker": "customer", "text": "Could I get a refund?"},
        {"turn_id": 2, "speaker": "agent", "text": "I can look into it."},
        {"turn_id": 3, "speaker": "agent", "text": "Please confirm the purchase."},
    ]
    rule = "completeness.direct_response"
    left = vote(rule, "supported", 1, 2)
    assert agreed_checks(left, vote(rule, "supported", 1, 3), events, {rule}) == {}
    assert agreed_checks(left, vote(rule, "unresolved", 1, 2), events, {rule}) == {}
    assert agreed_checks(left, left, events, {rule})[rule]["turns"] == [1, 2]
    with pytest.raises(ValueError, match="evidence"):
        agreed_checks(left, vote(rule, "supported", 1, 4), events, {rule})


def test_luna_cannot_exclude_core_clarity_check():
    events = [{"turn_id": 1, "speaker": "agent", "text": "Please wait."}]
    rule = "communication-style.clarity"
    answer = vote(rule, "not-applicable", 1)
    assert agreed_checks(answer, answer, events, {rule}) == {}


def test_outbound_masking_preserves_amount_and_omits_identifiers():
    text = "Send 54 dollars to demo@example.test or account A1BC2D3E4. Card 4111 1111 1111 1111."
    masked = outbound_text(text)
    assert "54 dollars" in masked
    assert all(value not in masked for value in ("example.test", "A1BC2D3E4", "4111"))


@pytest.mark.parametrize(
    "reply", ["No, thanks.", "Actually, cancel the email.", 'They said "cancel it".']
)
def test_luna_passes_see_short_replies_changes_and_reported_speech_in_context(reply):
    folder = Path(__file__).with_name("metric_categories")
    common = json.loads((folder / "common.json").read_text())
    defaults = json.loads((folder / "catalog.json").read_text())["category_defaults"]
    category = expand_category(
        common, defaults, json.loads((folder / "general.json").read_text())
    )
    events = [
        {"turn_id": 8, "speaker": "customer", "text": "Please email an update."},
        {"turn_id": 9, "speaker": "agent", "text": "I'll send it. Anything else?"},
        {"turn_id": 10, "speaker": "customer", "text": reply},
        {"turn_id": 11, "speaker": "action", "text": "A link will be sent."},
    ]
    proposal, schema = make_task(events, common, category)
    review, review_schema = make_task(events, common, category, reviewer=True)
    assert (
        proposal["turns"]
        == review["turns"]
        == [
            {"id": turn["turn_id"], "speaker": turn["speaker"], "text": turn["text"]}
            for turn in events
        ]
    )
    assert schema == review_schema
    assert {check["id"].split(".")[0] for check in proposal["checks"]} == {
        "completeness",
        "communication-style",
    }
