import json
from dataclasses import replace

import pytest

from backend.data.demo_fixtures import (
    ConversationPassage,
    KnowledgeState,
    ValueOrigin,
    build_knowledge_conflict_fixture,
    serialize_fixture,
    validate_fixture,
)
from backend.data.provenance import ValueOrigin as ProvenanceValueOrigin


def test_fixture_covers_policy_change_support_and_conflict():
    fixture = build_knowledge_conflict_fixture()

    assert [policy.delivery_window for policy in fixture.policy_versions] == [
        "5-7 business days",
        "2-3 business days",
        "8-10 business days",
    ]
    assert {passage.supports_policy_version for passage in fixture.passages} == {
        "delivery-v1",
        "delivery-v2",
        "economy-delivery-v1",
        None,
    }


def test_fixture_defines_every_expected_knowledge_state():
    fixture = build_knowledge_conflict_fixture()

    assert {outcome.expected_state for outcome in fixture.expected_outcomes} == set(
        KnowledgeState
    )


def test_cannot_assess_state_matches_the_audit_model_value():
    assert KnowledgeState.CANNOT_ASSESS.value == "cannot_assess"


def test_fixture_reuses_the_shared_value_origin_enum():
    assert ValueOrigin is ProvenanceValueOrigin


def test_approved_case_has_a_manager_review_while_pending_has_none():
    fixture = build_knowledge_conflict_fixture()
    outcomes = {outcome.case_id: outcome for outcome in fixture.expected_outcomes}
    reviews = {review.review_id: review for review in fixture.reviews}

    assert outcomes["new-policy-awaiting-review"].review_id is None
    approved_review = reviews[outcomes["new-policy-approved"].review_id]
    assert approved_review.case_id == "new-policy-approved"
    assert approved_review.reviewer_role == "manager"
    assert approved_review.action == "approved"


def test_stale_case_is_older_than_the_configured_threshold():
    fixture = build_knowledge_conflict_fixture()
    stale = next(
        outcome
        for outcome in fixture.expected_outcomes
        if outcome.expected_state is KnowledgeState.STALE
    )
    passages = {passage.conversation_id: passage for passage in fixture.passages}
    stale_versions = {
        passages[conversation_id].supports_policy_version
        for conversation_id in stale.evidence_conversation_ids
    }

    assert stale_versions == {"economy-delivery-v1"}
    supporting_dates = [
        passage.occurred_on
        for passage in fixture.passages
        if passage.supports_policy_version == "economy-delivery-v1"
    ]

    assert all(
        (fixture.as_of_date - occurred_on).days > fixture.stale_after_days
        for occurred_on in supporting_dates
    )


def test_validation_checks_every_passage_supporting_the_stale_claim():
    fixture = build_knowledge_conflict_fixture()
    fresh_support = ConversationPassage(
        "SYNTH-ECONOMY-002",
        fixture.as_of_date,
        "agent",
        "Economy delivery takes 8 to 10 business days.",
        "economy-delivery-v1",
    )

    with pytest.raises(ValueError, match="stale outcome"):
        validate_fixture(replace(fixture, passages=(*fixture.passages, fresh_support)))


def test_cannot_assess_case_has_no_policy_support():
    fixture = build_knowledge_conflict_fixture()
    cannot_assess = next(
        outcome
        for outcome in fixture.expected_outcomes
        if outcome.expected_state is KnowledgeState.CANNOT_ASSESS
    )
    passages = {passage.conversation_id: passage for passage in fixture.passages}

    assert all(
        passages[conversation_id].supports_policy_version is None
        for conversation_id in cannot_assess.evidence_conversation_ids
    )


def test_every_generated_object_is_marked_synthetic():
    value = build_knowledge_conflict_fixture().as_dict()

    def assert_synthetic(item):
        if isinstance(item, dict):
            assert item["origin"] == "synthetic"
            for child in item.values():
                if isinstance(child, (dict, list)):
                    assert_synthetic(child)
        elif isinstance(item, list):
            for child in item:
                assert_synthetic(child)

    assert_synthetic(value)


def test_fixture_serialization_is_machine_readable_and_deterministic():
    fixture = build_knowledge_conflict_fixture()

    first = serialize_fixture(fixture)
    second = serialize_fixture(build_knowledge_conflict_fixture())

    assert first == second
    assert json.loads(first) == fixture.as_dict()
    assert first.endswith("\n")


@pytest.mark.parametrize(
    "text",
    [
        "Contact person@example.com",
        "Call 416-555-0123",
        "Send it to 123 Example Street",
    ],
)
def test_validation_rejects_possible_customer_details(text):
    fixture = build_knowledge_conflict_fixture()
    unsafe = replace(
        fixture,
        passages=(
            ConversationPassage(
                "SYNTH-UNSAFE-001",
                fixture.as_of_date,
                "customer",
                text,
                None,
            ),
            *fixture.passages,
        ),
    )

    with pytest.raises(ValueError, match="customer detail"):
        validate_fixture(unsafe)


def test_validation_rejects_an_unknown_evidence_conversation():
    fixture = build_knowledge_conflict_fixture()
    outcome = replace(
        fixture.expected_outcomes[0],
        evidence_conversation_ids=("SYNTH-MISSING",),
    )

    with pytest.raises(ValueError, match="known conversations"):
        validate_fixture(
            replace(
                fixture,
                expected_outcomes=(outcome, *fixture.expected_outcomes[1:]),
            )
        )
