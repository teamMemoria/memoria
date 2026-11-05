from backend.services.knowledge import find_conflicts

from .conftest import COMPANY
from .review_cases import chat, entry
from .review_cases import draft as prepare_draft

ANSWER = "Items can be returned after purchase."


def test_consolidated_conflicts_keep_every_draft_and_entry_version():
    drafts = [prepare_draft(chat(f"C{i}", ANSWER)) for i in range(3)]
    existing = entry("1", "Items cannot be returned after purchase.")
    conflicts = find_conflicts(drafts, COMPANY, existing_entries=[existing])
    [conflict] = conflicts["possible_conflicts"]
    assert set(conflict["affected_draft_ids"]) == {d["draft_id"] for d in drafts}
    assert conflict["repeated_pairs"] == 2
    versions = find_conflicts(drafts, COMPANY, [existing, {**existing, "version": "2"}])
    assert len(versions["possible_conflicts"]) == 2
