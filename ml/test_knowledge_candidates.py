"""Authored generator tests; no real approvals or model calls."""

from copy import deepcopy

from ml.knowledge_candidates import generate_candidates
from ml.test_rule_scoring import evidence


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
