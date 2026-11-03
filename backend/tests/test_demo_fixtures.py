import json
from dataclasses import replace

import pytest

from backend.data.demo_fixtures import (
    ConversationPassage,
    KnowledgeState,
    build_knowledge_conflict_fixture,
    serialize_fixture,
    validate_fixture,
)


def test_fixture_covers_policy_change_support_and_conflict():
    fixture = build_knowledge_conflict_fixture()

    assert [policy.delivery_window for policy in fixture.policy_versions] == [
        "5-7 business days",
        "2-3 business days",
    ]
    assert {passage.supports_policy_version for passage in fixture.passages} == {
        "delivery-v1",
        "delivery-v2",
        None,
    }


def test_fixture_defines_every_expected_knowledge_state():
    fixture = build_knowledge_conflict_fixture()

    assert {outcome.expected_state for outcome in fixture.expected_outcomes} == set(
        KnowledgeState
    )


def test_stale_case_is_older_than_the_configured_threshold():
    fixture = build_knowledge_conflict_fixture()
    stale = next(
        outcome
        for outcome in fixture.expected_outcomes
        if outcome.expected_state is KnowledgeState.STALE
    )
    evidence_dates = {
        passage.conversation_id: passage.occurred_on for passage in fixture.passages
    }

    assert all(
        (fixture.as_of_date - evidence_dates[conversation_id]).days
        > fixture.stale_after_days
        for conversation_id in stale.evidence_conversation_ids
    )


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
