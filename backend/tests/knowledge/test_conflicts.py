from __future__ import annotations

import copy
import json

import pytest

from backend.services.knowledge.conflicts import ConflictConfig, find_conflicts
from backend.services.knowledge.errors import PipelineError
from backend.services.knowledge.extraction import extract_drafts
from backend.services.knowledge.grouping import group_drafts

from .conftest import ABCD_DIR, COMPANY, LABELS_DIR, SYNTHETIC_DIR, load_json

LABELS = load_json(LABELS_DIR / "conflicts.json")
SCOPE = {"flow": "purchase_dispute", "subflow": "promo_code_invalid"}


def draft_for(cid: str):
    folder = ABCD_DIR if cid.startswith("ABCD") else SYNTHETIC_DIR
    [draft] = extract_drafts(load_json(folder / f"{cid}.json"), COMPANY).drafts
    return draft


def findings(result):
    return [*result["possible_conflicts"], *result["explained_differences"]]


@pytest.mark.parametrize("case", LABELS["cases"], ids=lambda c: f"{c['a']}-{c['b']}")
def test_labelled_pair(case):
    result = find_conflicts([draft_for(case["a"]), draft_for(case["b"])], COMPANY)
    statuses = {f["status"] for f in findings(result)}
    kinds = {f["kind"] for f in findings(result)}
    expect = case["expect"]
    if expect == "none":
        assert not result["possible_conflicts"], result["possible_conflicts"]
        return
    wanted = {
        "conflict": "possible_conflict",
        "unresolved": "unresolved",
        "explained": "explained_difference",
    }[expect]
    assert wanted in statuses, statuses
    if expect != "conflict":
        assert "possible_conflict" not in statuses
    assert case["kind"] in kinds


def test_conflict_links_both_exact_passages_with_sources():
    a, b = draft_for("ABCD-0041"), draft_for("ABCD-0046")
    [conflict] = find_conflicts([a, b], COMPANY)["possible_conflicts"]
    sides = {
        conflict["a"]["draft_id"]: conflict["a"],
        conflict["b"]["draft_id"]: conflict["b"],
    }
    for draft in (a, b):
        side = sides[draft["draft_id"]]
        assert side["passage"] in draft["answer_passages"]
        assert side["source_key"] == draft["source"]["source_key"]
        assert side["source_version"] == draft["source"]["version"]
        assert side["reference_status"] == "unverified draft"
        assert side["conditions"] == [c["text"] for c in draft["conditions"]]
    assert conflict["explanation"]
    assert conflict["compared_conditions"]["a"] and conflict["compared_conditions"]["b"]
    assert "guest" in json.dumps(conflict["compared_conditions"])


def test_existing_entries_are_compared_with_their_status_and_version():
    entry = {
        "entry_id": "kb-promo-validity",
        "company_id": COMPANY,
        "scope": SCOPE,
        "status": "approved",
        "version": "4",
        "question": "How long is a promo code valid?",
        "answer": "Promo codes are valid for 7 days after they are issued.",
    }
    result = find_conflicts([draft_for("SYN-G09")], COMPANY, existing_entries=[entry])
    [conflict] = result["possible_conflicts"]
    entry_side = (
        conflict["a"] if conflict["a"]["type"] == "existing_entry" else conflict["b"]
    )
    assert entry_side["entry_id"] == "kb-promo-validity"
    assert entry_side["reference_status"] == "approved"
    assert entry_side["version"] == "4"
    assert entry_side["passage"]["quote"] == entry["answer"]
    # Agreement with the entry is not reported at all.
    assert (
        find_conflicts([draft_for("SYN-G01")], COMPANY, existing_entries=[entry])[
            "possible_conflicts"
        ]
        == []
    )


def test_other_company_knowledge_is_never_compared():
    entry = {
        "entry_id": "kb-other",
        "company_id": "another-company",
        "scope": SCOPE,
        "question": "How long is a promo code valid?",
        "answer": "Promo codes are valid for 30 days.",
    }
    result = find_conflicts([draft_for("SYN-G01")], COMPANY, existing_entries=[entry])
    assert findings(result) == []
    foreign = copy.deepcopy(draft_for("SYN-G01"))
    foreign["company_id"] = "another-company"
    with pytest.raises(PipelineError):
        find_conflicts([foreign], COMPANY)


def test_missing_evidence_is_not_a_conflict():
    # One side states a figure, the other states none: nothing to compare.
    entry = {
        "entry_id": "kb-1",
        "company_id": COMPANY,
        "scope": SCOPE,
        "status": "approved",
        "question": "How long is a promo code valid?",
        "answer": "Promo codes can be used on any item.",
    }
    assert (
        find_conflicts([draft_for("SYN-G01")], COMPANY, existing_entries=[entry])[
            "possible_conflicts"
        ]
        == []
    )


def test_ml_never_changes_entry_or_draft_state():
    entry = {
        "entry_id": "kb-promo-validity",
        "company_id": COMPANY,
        "scope": SCOPE,
        "status": "approved",
        "question": "How long is a promo code valid?",
        "answer": "Promo codes are valid for 7 days after they are issued.",
    }
    drafts = [draft_for("SYN-G09"), draft_for("SYN-0005"), draft_for("SYN-G06")]
    before = copy.deepcopy((drafts, entry))
    result = find_conflicts(drafts, COMPANY, existing_entries=[entry])
    assert (drafts, entry) == before
    text = json.dumps(result, ensure_ascii=False)
    for forbidden in (
        '"disputed"',
        '"replaced_by"',
        '"eligible": false',
        '"approved": ',
    ):
        assert forbidden not in text


def test_group_ids_are_attached_when_groups_are_given():
    drafts = [draft_for("SYN-G01"), draft_for("SYN-G02"), draft_for("SYN-G09")]
    groups = group_drafts(drafts, COMPANY)
    [conflict, *_] = find_conflicts(drafts, COMPANY, groups=groups)[
        "possible_conflicts"
    ]
    assert conflict["a"]["group_id"] and conflict["b"]["group_id"]
    assert conflict["a"]["group_id"] != conflict["b"]["group_id"]


def test_one_conversation_read_twice_is_not_compared_with_itself():
    draft = draft_for("SYN-G01")
    twin = copy.deepcopy(draft)
    twin["draft_id"] = "draft_twin"
    assert findings(find_conflicts([draft, twin], COMPANY)) == []


def test_abcd_corpus_finds_the_known_conflict_and_little_else():
    drafts = []
    for path in sorted(ABCD_DIR.glob("*.json")):
        drafts.extend(extract_drafts(load_json(path), COMPANY).drafts)
    result = find_conflicts(drafts, COMPANY)
    pairs = {
        frozenset((c["a"]["source_key"], c["b"]["source_key"]))
        for c in result["possible_conflicts"]
        if c["status"] == "possible_conflict"
    }
    known = frozenset(
        (
            draft_for("ABCD-0041")["source"]["source_key"],
            draft_for("ABCD-0046")["source"]["source_key"],
        )
    )
    assert known in pairs
    assert (
        len(result["possible_conflicts"]) <= 5
    )  # false alarms stay rare on the curated set


def test_config_validation():
    with pytest.raises(PipelineError):
        ConflictConfig(claim_overlap=2)
    with pytest.raises(PipelineError):
        find_conflicts("nope", COMPANY)


@pytest.mark.parametrize(
    ("text", "exclusive"),
    [
        ("Silver members get a refund if they are only 2 days late.", False),
        ("Only gold members get free shipping.", True),
        ("Free shipping is for gold members only.", True),
        ("I could only issue a new code to our existing members.", True),
    ],
)
def test_only_must_be_about_the_level(text, exclusive):
    # Regression: found by the first held-out run ("... if they are only 1 day late" read as "only silver").
    from backend.services.knowledge.conflicts import _claim, _Owner

    owner = _Owner("draft", "d", {}, set(), set(), [], {})
    claim = _claim(owner, text, {}, from_action=False)
    assert claim.exclusive is exclusive
    if not exclusive:
        assert not claim.denied
