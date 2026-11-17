"""Authored generator tests; no real approvals or model calls."""

from copy import deepcopy

import pytest
from ml.abcd import prepare_dataset
from ml.knowledge_candidates import generate_candidates
from ml.test_evidence import SOURCE, source_record


def test_candidates_are_exact_untrusted_and_repeatable():
    source = evidence(
        [
            ["customer", "What is the return policy?"],
            ["agent", "The return policy requires a valid receipt."],
        ]
    )
    result = generate_candidates("test-company", [source])
    assert result == generate_candidates("test-company", [source])
    (draft,) = result["drafts"]
    assert draft["answer"] == source["conversations"][0]["events"][1]["text"]
    assert draft["question_passages"][0]["span"] == [0, len(draft["question"])]
    assert (
        draft["answer_passages"][0]["source_version"]
        == source["conversations"][0]["transcript_version"]
    )
    assert draft["trusted"] is False and draft["audit_eligible"] is False
    assert draft["status"] == "draft"
    assert result["verification"]["results"][0]["verification_status"] == "unverifiable"


def test_no_draft_for_unlinked_personal_quoted_promised_or_withdrawn_answer():
    cases = [
        [
            ["customer", "What is the return policy?"],
            ["agent", "Your order was delivered."],
        ],
        [
            ["customer", "What is the status of my order?"],
            ["agent", "Your order was shipped."],
        ],
        [
            ["customer", "Please email me the invoice."],
            ["agent", "I'll email you the invoice."],
        ],
        [
            ["customer", "Is the hood removable?"],
            ["agent", 'The guide says "The hood is removable."'],
        ],
        [
            ["customer", "How much is shipping?"],
            ["agent", "Shipping costs $12 if you qualify."],
        ],
    ]
    for messages in cases:
        result = generate_candidates("company", [evidence(messages)])
        assert not result["drafts"], messages
        assert result["records"][0]["reason"]


def test_invalid_record_is_isolated_and_other_record_retains_exact_sources():
    valid = evidence(
        [["customer", "Is the hood removable?"], ["agent", "The hood is removable."]]
    )
    invalid = deepcopy(valid)
    invalid["conversations"][0]["events"][1]["text"] = (
        "Changed without updating version"
    )
    output = generate_candidates("company", [invalid, valid])
    assert [r["status"] for r in output["records"]] == ["failed", "completed"]
    assert len(output["drafts"]) == 1


def test_generator_identity_and_versions_do_not_change_semantic_selection():
    messages = [
        ["customer", "What is the return policy?"],
        ["agent", "The return policy requires a valid receipt."],
    ]
    first = generate_candidates("company", [evidence(messages, identifier=123)])
    second = generate_candidates("company", [evidence(messages, identifier=456)])
    assert first["drafts"][0]["answer"] == second["drafts"][0]["answer"]
    assert first["drafts"][0]["draft_id"] != second["drafts"][0]["draft_id"]


def evidence(turns, identifier=1234):
    """Authored training records; no local corpus or dataset answer labels."""
    record = source_record(identifier)
    record["original"] = turns
    record["delexed"] = [
        {
            "speaker": speaker,
            "text": text.lower(),
            "turn_count": turn,
            "targets": ["LABEL_CANARY"],
            "candidates": ["LABEL_CANARY"],
        }
        for turn, (speaker, text) in enumerate(turns, 1)
    ]
    return prepare_dataset(
        {"train": [record], "dev": [], "test": []}, SOURCE, (str(identifier),)
    )


@pytest.mark.parametrize(
    "question,answer",
    [
        (
            "Could you tell me what is the return policy?",
            "The return policy requires a valid receipt.",
        ),
        ("How much does shipping cost?", "Shipping costs $12."),
        ("How long does shipping take?", "Shipping takes three business days."),
        ("Is the hood removable?", "No."),
        ("What is the shirt made of?", "The shirt is made of cotton."),
        ("What color are the buttons?", "The buttons are blue."),
        ("Does the jacket have a warranty?", "Yes."),
        ("How should I wash the shirt?", "Wash the shirt in cold water."),
    ],
)
def test_supported_information_slots_retain_full_canonical_answers(question, answer):
    result = generate_candidates(
        "company", [evidence([["customer", question], ["agent", answer]])]
    )
    assert len(result["drafts"]) == 1
    assert result["drafts"][0]["answer"] == answer


@pytest.mark.parametrize(
    "suffix",
    [
        [["customer", "Actually, don't tell me about the hood."]],
        [["customer", "Instead, what color are the laces?"]],
        [["agent", "Correction, the hood is not removable."]],
        [["agent", "The hood is not removable."]],
    ],
)
def test_later_changes_and_corrections_never_publish_the_old_answer(suffix):
    messages = [
        ["customer", "Is the hood removable?"],
        ["agent", "The hood is removable."],
    ]
    assert not generate_candidates("company", [evidence(messages + suffix)])["drafts"]


@pytest.mark.parametrize(
    "messages",
    [
        [
            ["customer", "Is the hood removable?"],
            ["agent", "I will check that."],
            ["customer", "Actually, don't check the hood."],
        ],
        [
            ["customer", "Is the hood removable? Is the lining waterproof?"],
            ["agent", "Yes."],
        ],
        [
            ["customer", "How much is shipping?"],
            ["agent", "Is this about your order?"],
            ["customer", "No."],
        ],
        [
            ["customer", "Is the hood removable?"],
            ["agent", "The customer said:"],
            ["agent", "The hood is removable."],
            ["agent", "Those were the customer's words."],
        ],
        [["customer", 'They asked "Is the hood removable?"'], ["agent", "Yes."]],
        [
            ["customer", "Is the hood removable?"],
            ["agent", "The hood is removable unless damaged."],
        ],
    ],
)
def test_ambiguous_context_qualifications_and_quoted_speech_do_not_form_candidates(
    messages,
):
    assert not generate_candidates("company", [evidence(messages)])["drafts"]


def test_product_context_and_short_answer_cite_both_question_turns():
    messages = [
        ["customer", "I am looking at the jacket."],
        ["customer", "Is it waterproof?"],
        ["agent", "Yes."],
    ]
    result = generate_candidates("company", [evidence(messages)])
    assert len(result["drafts"]) == 1
    assert len(result["drafts"][0]["question_passages"]) == 2
    assert "LABEL_CANARY" not in str(result)


@pytest.mark.parametrize(
    "previous,expected",
    [
        ("Do you still want information about the hood?", 0),
        ("Is there anything else I can help with?", 1),
        ("Is there anything else?", 1),
    ],
)
def test_customer_no_uses_the_preceding_question(previous, expected):
    messages = [
        ["customer", "Is the hood removable?"],
        ["agent", "Yes."],
        ["agent", previous],
        ["customer", "No."],
    ]
    assert (
        len(generate_candidates("company", [evidence(messages)])["drafts"]) == expected
    )
