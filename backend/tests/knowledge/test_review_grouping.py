import pytest

from backend.services.knowledge import group_drafts

from .conftest import COMPANY
from .review_cases import SCOPE, chat
from .review_cases import draft as prepare_draft

ANSWER = "Items can be returned after purchase."


@pytest.mark.parametrize(
    "opposite",
    [
        "Items cannot be returned after purchase.",
        "Items may not be returned after purchase.",
    ],
)
def test_opposite_answers_are_not_duplicates_or_equivalent_entries(opposite):
    a = prepare_draft(chat("C1", ANSWER))
    b = prepare_draft(chat("C2", opposite))
    entry = {
        "entry_id": "E1",
        "company_id": COMPANY,
        "scope": SCOPE,
        "question": a["question"],
        "answer": opposite,
    }
    result = group_drafts([a, b], COMPANY, [entry])
    assert not any(g["duplicates"] for g in result["groups"])
    group = next(g for g in result["groups"] if a["draft_id"] in g["member_draft_ids"])
    assert all(m["kind"] != "equivalent" for m in group["existing_matches"])
