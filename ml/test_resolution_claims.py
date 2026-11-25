import pytest
from ml.citations import validate_citations
from ml.metrics.resolution_claims import recorded_resolution_claims


def conversation(*entries):
    return {
        "id": "example",
        "transcript_version": "version-1",
        "events": [
            {
                "turn_id": i,
                "kind": "action" if speaker == "action" else "message",
                "speaker": speaker,
                "text": text,
            }
            for i, (speaker, text) in enumerate(entries, 1)
        ],
    }


@pytest.mark.parametrize("amount, expected", [("17.50", "supported"), ("19", "breach")])
def test_recorded_completion_links_an_exact_refund_assertion(amount, expected):
    source = conversation(
        ("customer", "I received an extra item."),
        ("agent", "I can refund the additional item."),
        ("action", "A refund has been made for the amount of $17.50."),
        (
            "agent",
            "I've refunded you $" + amount + " for the extra item. Anything else?",
        ),
    )
    issued, value = recorded_resolution_claims(source)
    assert issued["outcome"] == "supported"
    assert value["outcome"] == expected
    assert validate_citations(value["citations"], [source], []) == []


def test_cancellation_record_corroborates_only_the_completed_clause():
    source = conversation(
        ("customer", "Please cancel this order."),
        ("action", "Order has been updated with cancel order."),
        ("agent", "Your order has been canceled, and you will not be billed."),
    )
    (check,) = recorded_resolution_claims(source)
    assert check["rule_id"] == "answer-support.recorded-claim.order cancellation"
    assert [c["turn_id"] for c in check["citations"]] == [2, 3]


@pytest.mark.parametrize(
    "record, claim",
    [
        ("Order has been updated with .", "I canceled your order."),
        ("Order has been updated with cancel order.", "I will cancel your order."),
        (
            "Order has been updated with cancel order.",
            "If it ships, the order has been canceled.",
        ),
        (
            "Order has been updated with cancel order.",
            "The order has not been canceled.",
        ),
        ("A refund has been made for the amount of $.", "I've refunded you $17.50."),
        (
            "A refund has been made for the amount of $tomorrow.",
            "I've refunded you $17.50.",
        ),
        (
            "A refund has been made for the amount of $17.50.",
            'They said "I refunded you $17.50".',
        ),
    ],
)
def test_uncertain_records_or_nonassertions_never_establish_completion(record, claim):
    source = conversation(
        ("customer", "Please help with my order."), ("action", record), ("agent", claim)
    )
    assert list(recorded_resolution_claims(source)) == []


def test_existing_refund_change_cannot_be_verified_by_an_unlinked_new_refund():
    source = conversation(
        ("customer", "Can you add the shipping fee to my existing refund?"),
        ("action", "A refund has been made for the amount of $12."),
        ("agent", "I've refunded you $12."),
    )
    assert list(recorded_resolution_claims(source)) == []


def test_refund_links_the_offered_refund_and_confirmed_item_price_to_the_log():
    source = conversation(
        ("agent", "I can issue a refund for the unwanted pair."),
        ("agent", "How much did the pair cost?"),
        ("customer", "It was $24.50."),
        ("action", "A refund has been made for the amount of $24.50."),
        ("agent", "I've refunded you $24.50 for that pair. Anything else?"),
    )
    _, value = recorded_resolution_claims(source)
    assert [citation["turn_id"] for citation in value["citations"]] == [1, 2, 3, 4, 5]
