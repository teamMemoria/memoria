import pytest

from backend.services.knowledge import (
    FakeModelClient,
    ModelExtractor,
    check_drafts,
    extract_drafts,
    find_conflicts,
)

from .conftest import COMPANY
from .review_cases import chat, reference
from .review_cases import draft as prepare_draft
from .review_cases import entry as knowledge_entry

ANSWER = "Items can be returned after purchase."


@pytest.mark.parametrize(
    "source,proposed",
    [
        ("Items cannot be returned after purchase.", ANSWER),
        (ANSWER + " only if the packaging is unopened.", ANSWER),
        (
            "Damaged products can be returned for a refund.",
            "A refund is available for damaged products.",
        ),
    ],
)
def test_rewritten_model_wording_is_not_verified_by_its_quotes(source, proposed):
    record = chat("C1", source)
    reply = {
        "drafts": [
            {
                "question": record["turns"][0]["text"],
                "question_turn_ids": ["C1#t1"],
                "answer": proposed,
                "answer_turn_ids": ["C1#t2"],
                "conditions": [],
            }
        ]
    }
    extractor = ModelExtractor(FakeModelClient([reply]))
    result = extract_drafts(record, COMPANY, extractor=extractor)
    assert result.status == "ok" and result.drafts
    packet = check_drafts(result.drafts, COMPANY, [reference(source)])["results"][0]
    assert packet["verification_status"] == "unverifiable"
    assert packet["ml_recommendation"] == "cannot_be_verified"


@pytest.mark.parametrize(
    "condition",
    [
        "only if the packaging is unopened",
        "unless the item was on final sale",
        "provided that a receipt is shown",
        "only with a receipt",
    ],
)
def test_explicit_reference_conditions_must_be_preserved(condition):
    policy = ANSWER.rstrip(".") + " " + condition + "."
    draft = prepare_draft(chat("C1", ANSWER))
    packet = check_drafts([draft], COMPANY, [reference(policy)])["results"][0]
    assert packet["ml_recommendation"] == "needs_more_evidence"
    assert packet["claims"][0]["missing_conditions"]
    faithful = prepare_draft(chat("C2", policy))
    assert (
        check_drafts([faithful], COMPANY, [reference(policy)])["results"][0][
            "ml_recommendation"
        ]
        == "supported_by_references"
    )


@pytest.mark.parametrize(
    "condition",
    ["Only if the packaging is unopened.", "Unless the item was on final sale."],
)
@pytest.mark.parametrize("condition_in_parent", [False, True])
@pytest.mark.parametrize("reverse", [False, True])
def test_reference_conditions_apply_across_parent_and_child(
    condition, condition_in_parent, reverse
):
    parent = reference(condition if condition_in_parent else ANSWER, rid="policy#a1")
    child = reference(
        ANSWER if condition_in_parent else condition,
        rid="policy#a1.1",
        parent="policy#a1",
    )
    refs = [child, parent] if reverse else [parent, child]
    draft = prepare_draft(chat("C1", ANSWER))
    packet = check_drafts([draft], COMPANY, refs)["results"][0]
    assert packet["ml_recommendation"] == "needs_more_evidence"
    source = parent if condition_in_parent else child
    assert any(
        m["reference_id"] == source["reference_id"] and m["quote"] == source["text"]
        for m in packet["claims"][0]["missing_conditions"]
    )
    faithful = prepare_draft(chat("C2", ANSWER + " " + condition))
    assert (
        check_drafts([faithful], COMPANY, refs)["results"][0]["ml_recommendation"]
        == "supported_by_references"
    )


def test_consolidated_conflicts_reach_every_draft_and_keep_entry_versions():
    drafts = [prepare_draft(chat(f"C{i}", ANSWER)) for i in range(3)]
    entry = knowledge_entry("1", "Items cannot be returned after purchase.")
    conflicts = find_conflicts(drafts, COMPANY, existing_entries=[entry])
    assert len(conflicts["possible_conflicts"]) == 1
    packets = check_drafts(drafts, COMPANY, [reference(ANSWER)], conflicts)["results"]
    assert all(p["possible_conflicts"] for p in packets)
    assert {p["ml_recommendation"] for p in packets} == {"needs_more_evidence"}
    versions = find_conflicts(drafts, COMPANY, [entry, {**entry, "version": "2"}])
    assert len(versions["possible_conflicts"]) == 2
