from __future__ import annotations

import copy
import json
import random

import pytest

from backend.services.knowledge.abcd import read_conversation
from backend.services.knowledge.errors import PipelineError
from backend.services.knowledge.extraction import extract_drafts
from backend.services.knowledge.grouping import GroupingConfig, group_drafts

from .conftest import ABCD_DIR, COMPANY, LABELS_DIR, SYNTHETIC_DIR, abcd, load_json

LABELS = load_json(LABELS_DIR / "grouping.json")


def record_for(cid: str):
    folder = ABCD_DIR if cid.startswith("ABCD") else SYNTHETIC_DIR
    return load_json(folder / f"{cid}.json")


def draft_for(cid: str, company: str = COMPANY):
    [draft] = extract_drafts(record_for(cid), company).drafts
    return draft


def drafts_for(cids):
    return {cid: draft_for(cid) for cid in cids}


def group_of(result, draft_id):
    [group] = [g for g in result["groups"] if draft_id in g["member_draft_ids"]]
    return group


@pytest.mark.parametrize("case", LABELS["cases"], ids=lambda c: c["name"])
def test_labelled_grouping(case):
    drafts = drafts_for(case["conversations"])
    result = group_drafts(list(drafts.values()), COMPANY)
    gid = {
        cid: group_of(result, d["draft_id"])["group_id"] for cid, d in drafts.items()
    }
    for a, b in case.get("same_group", []):
        assert gid[a] == gid[b], f"{a} and {b} should share a group"
    for a, b in case.get("different_group", []):
        assert gid[a] != gid[b], f"{a} and {b} should not share a group"
    for a, b in case.get("duplicates", []):
        pairs = {
            frozenset((d["draft_id"], d["duplicate_of"]))
            for g in result["groups"]
            for d in g["duplicates"]
        }
        assert frozenset((drafts[a]["draft_id"], drafts[b]["draft_id"])) in pairs
    for a, b in case.get("not_duplicates", []):
        group = group_of(result, drafts[a]["draft_id"])
        pairs = {
            frozenset((d["draft_id"], d["duplicate_of"])) for d in group["duplicates"]
        }
        assert frozenset((drafts[a]["draft_id"], drafts[b]["draft_id"])) not in pairs


def test_representative_is_an_unchanged_draft():
    drafts = drafts_for(["SYN-G01", "SYN-G02", "SYN-G03"])
    result = group_drafts(list(drafts.values()), COMPANY)
    group = group_of(result, drafts["SYN-G01"]["draft_id"])
    rep_id = group["representative_draft_id"]
    [source] = [d for d in drafts.values() if d["draft_id"] == rep_id]
    assert group["status"] == "draft"
    assert group["representative"]["status"] == "draft"
    assert group["representative"]["answer"] == source["answer"]
    assert group["representative"]["answer_passages"] == source["answer_passages"]
    assert {"approved", "verified", "trusted"}.isdisjoint(group)


def test_counts_are_distinct_conversations_and_reprocessing_does_not_raise_them():
    drafts = list(drafts_for(["SYN-G01", "SYN-G02", "SYN-G03"]).values())
    once = group_drafts(drafts, COMPANY)
    again = group_drafts(drafts + copy.deepcopy(drafts), COMPANY)
    assert again["duplicate_input_drafts"] == 3
    assert once["groups"] == again["groups"]
    assert group_of(once, drafts[0]["draft_id"])["distinct_conversation_count"] == 3


def test_the_same_source_conversation_counts_once():
    # ABCD-0041 read from the curated file and from the raw dump: one conversation,
    # so the same draft id and one draft, counted once.
    curated = abcd("ABCD-0041")
    raw = {
        "convo_id": int(curated["source"]["original_id"]),
        "scenario": {
            "personal": {"customer_name": curated["customer_record"]["customer_name"]},
            "order": {},
            "flow": "purchase_dispute",
            "subflow": "promo_code_invalid",
        },
        "original": [
            ["action" if t["speaker"] == "system_action" else t["speaker"], t["text"]]
            for t in curated["turns"]
        ],
    }
    a = extract_drafts(curated, COMPANY).drafts[0]
    b = extract_drafts(raw, COMPANY).drafts[0]
    assert a["draft_id"] == b["draft_id"]
    assert read_conversation(raw, COMPANY).source_key == a["source"]["source_key"]
    result = group_drafts([a, b], COMPANY)
    group = group_of(result, a["draft_id"])
    assert group["draft_count"] == 1
    assert group["distinct_conversation_count"] == 1
    assert result["duplicate_input_drafts"] == 1


def test_grouping_does_not_depend_on_input_order():
    drafts = list(drafts_for([f"SYN-G0{i}" for i in range(1, 10)]).values())
    expected = group_drafts(drafts, COMPANY)["groups"]
    shuffled = drafts[:]
    random.Random(7).shuffle(shuffled)
    assert group_drafts(shuffled, COMPANY)["groups"] == expected


def test_thresholds_are_configurable_and_counts_never_verify():
    drafts = list(drafts_for(["SYN-G01", "SYN-G02", "SYN-G03"]).values())
    strict = group_drafts(drafts, COMPANY, config=GroupingConfig(group_threshold=0.99))
    assert len(strict["groups"]) == 2  # only the exact repeat still groups
    lenient = group_drafts(
        drafts, COMPANY, config=GroupingConfig(min_distinct_conversations=2)
    )
    group = group_of(lenient, drafts[0]["draft_id"])
    assert group["meets_source_threshold"] is True
    assert group["status"] == "draft"
    assert "verifies" not in json.dumps(lenient).replace("None of them verifies", "")
    with pytest.raises(PipelineError):
        GroupingConfig(group_threshold=1.5)
    with pytest.raises(PipelineError):
        GroupingConfig(scope_level="company")


def test_existing_knowledge_matches():
    drafts = list(drafts_for(["SYN-G01", "SYN-G09"]).values())
    scope = {"flow": "purchase_dispute", "subflow": "promo_code_invalid"}
    entries = [
        {
            "entry_id": "kb-1",
            "company_id": COMPANY,
            "scope": scope,
            "status": "approved",
            "version": "3",
            "question": "How long is a promo code valid?",
            "answer": "Promo codes are valid for 7 days after they are issued.",
            "conditions": ["valid for 7 days"],
        },
        {
            "entry_id": "kb-other",
            "company_id": "another-company",
            "scope": scope,
            "status": "approved",
            "question": "How long is a promo code valid?",
            "answer": "Promo codes are valid for 7 days after they are issued.",
        },
    ]
    result = group_drafts(drafts, COMPANY, existing_entries=entries)
    seven = group_of(result, drafts[0]["draft_id"])
    thirty = group_of(result, drafts[1]["draft_id"])
    assert [m["entry_id"] for m in seven["existing_matches"]] == ["kb-1"]
    assert seven["existing_matches"][0]["kind"] == "equivalent"
    assert seven["existing_matches"][0]["entry_status"] == "approved"
    # Same question, different figure: shown, but marked as a condition difference.
    assert thirty["existing_matches"][0]["kind"] == "different_conditions"
    # Another company's entry is never compared.
    assert "kb-other" not in json.dumps(result)


@pytest.mark.parametrize(
    ("mutate", "field"),
    [
        (
            lambda d: d.__setitem__("company_id", "another-company"),
            "drafts[0].company_id",
        ),
        (lambda d: d.__setitem__("status", "approved"), "drafts[0]"),
        (lambda d: d.pop("scope"), "drafts[0].scope"),
        (lambda d: d["source"].pop("source_key"), "drafts[0].source.source_key"),
    ],
)
def test_invalid_drafts_are_rejected(mutate, field):
    draft = copy.deepcopy(draft_for("SYN-G01"))
    mutate(draft)
    with pytest.raises(PipelineError) as raised:
        group_drafts([draft], COMPANY)
    assert raised.value.field == field


def test_all_abcd_drafts_group_within_their_scope():
    drafts = []
    for path in sorted(ABCD_DIR.glob("*.json")):
        drafts.extend(extract_drafts(load_json(path), COMPANY).drafts)
    by_id = {d["draft_id"]: d for d in drafts}
    result = group_drafts(drafts, COMPANY)
    assert sum(g["draft_count"] for g in result["groups"]) == len(drafts)
    for group in result["groups"]:
        topics = {by_id[i]["topic"] for i in group["member_draft_ids"]}
        assert len(topics) == 1
        assert group["distinct_conversation_count"] <= group["draft_count"]
