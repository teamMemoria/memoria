from __future__ import annotations

import copy

import pytest

from backend.services.knowledge.abcd import (
    ABCD_VERSION,
    MAX_TURN_CHARS,
    MAX_TURNS,
    load_curated_directory,
    read_conversation,
    read_conversations,
)
from backend.services.knowledge.errors import PipelineError

from .conftest import ABCD_DIR, COMPANY, SPLITS, abcd

RAW_RECORD = {
    # Shape of ABCD v1.1 (abcd_v1.1.json.gz), trimmed to one short made-up chat.
    "convo_id": 990001,
    "scenario": {
        "personal": {
            "customer_name": "lee park",
            "email": "lpark@email.com",
            "member_level": "gold",
        },
        "order": {
            "order_id": "1234509876",
            "zip_code": "10001",
            "street_address": "1 main st",
            "full_address": "1 main st  newark, ny 10001",
            "city": "newark",
            "state": "ny",
        },
        "flow": "storewide_query",
        "subflow": "policy_1",
    },
    "original": [
        ["agent", "Hello, how can I help?"],
        ["customer", "What is the return policy for gold members?"],
        ["action", "Searching the FAQ pages ..."],
        ["agent", "Gold members get unlimited returns."],
    ],
    "delexed": [
        {
            "speaker": "agent",
            "text": "hello",
            "turn_count": 1,
            "targets": ["policy_1", "retrieve_utterance", None, [], 1],
        },
        {
            "speaker": "customer",
            "text": "what",
            "turn_count": 2,
            "targets": [None, None, None, [], 2],
        },
        {
            "speaker": "action",
            "text": "searching",
            "turn_count": 3,
            "targets": ["policy_1", "take_action", "search-faq", [], 3],
        },
        {
            "speaker": "agent",
            "text": "gold",
            "turn_count": 4,
            "targets": ["policy_1", "retrieve_utterance", None, [], 4],
        },
    ],
}


def test_curated_record_keeps_source_order_and_actions():
    conversation = read_conversation(abcd("ABCD-0041"), COMPANY)
    assert conversation.conversation_id == "ABCD-0041"
    assert conversation.company_id == COMPANY
    assert conversation.source["dataset"] == "ABCD"
    assert (
        conversation.source["original_id"] == abcd("ABCD-0041")["source"]["original_id"]
    )
    assert conversation.source["dataset_version"] == ABCD_VERSION
    assert conversation.source_key == f"ABCD:{conversation.source['original_id']}"
    numbers = [t.n for t in conversation.turns]
    assert numbers == sorted(numbers)
    assert [t.turn_id for t in conversation.turns][:2] == [
        "ABCD-0041#t1",
        "ABCD-0041#t2",
    ]
    assert [a.name for a in conversation.actions] == [
        "pull-up-account",
        "ask-the-oracle",
    ]
    # Each recorded action is paired with its system message, in order.
    assert [conversation.turn(a.turn_id).speaker for a in conversation.actions] == [
        "system_action"
    ] * 2
    assert (
        conversation.coverage["turns_kept"]
        == conversation.coverage["source_turns"]
        == len(conversation.turns)
    )
    assert conversation.coverage["actions_aligned_to_turns"] == 2


def test_summary_never_contains_customer_record():
    summary = read_conversation(abcd("ABCD-0041"), COMPANY).summary()
    assert "customer_record" not in summary
    assert "joseph" not in str(summary).lower()


def test_raw_abcd_record_is_read_with_actions_from_delexed():
    conversation = read_conversation(RAW_RECORD, COMPANY)
    assert conversation.conversation_id == "ABCD-raw-990001"
    assert conversation.source["record_format"] == "raw"
    assert conversation.source["version"] == ABCD_VERSION
    assert [t.speaker for t in conversation.turns] == [
        "agent",
        "customer",
        "system_action",
        "agent",
    ]
    assert [(a.name, a.turn_id) for a in conversation.actions] == [
        ("search-faq", "ABCD-raw-990001#t3")
    ]
    assert conversation.scope == {"flow": "storewide_query", "subflow": "policy_1"}


def test_same_source_conversation_has_same_key_in_both_shapes():
    curated = abcd("ABCD-0041")
    raw = copy.deepcopy(RAW_RECORD)
    raw["convo_id"] = int(curated["source"]["original_id"])
    assert (
        read_conversation(curated, COMPANY).source_key
        == read_conversation(raw, COMPANY).source_key
    )


def test_split_index_is_attached():
    conversations = load_curated_directory(ABCD_DIR, COMPANY, SPLITS)
    assert len(conversations) == 100
    assert {c.source["split"] for c in conversations} == {"train", "dev", "test"}


@pytest.mark.parametrize(
    ("mutate", "code", "field"),
    [
        (lambda r: r.pop("turns"), "invalid_input", "$"),
        (lambda r: r.__setitem__("turns", "nope"), "invalid_input", "turns"),
        (
            lambda r: r["turns"][1].__setitem__("speaker", "bot"),
            "invalid_input",
            "turns[1].speaker",
        ),
        (lambda r: r["turns"][2].__setitem__("n", 1), "invalid_input", "turns[2].n"),
        (
            lambda r: r["turns"][0].__setitem__("text", None),
            "invalid_input",
            "turns[0].text",
        ),
        (
            lambda r: r["source"].__setitem__("dataset", "HarperValleyBank"),
            "invalid_input",
            "source.dataset",
        ),
        (
            lambda r: r["source_fields"].pop("flow"),
            "invalid_input",
            "source_fields.flow",
        ),
        (lambda r: r.__setitem__("turns", []), "invalid_input", "turns"),
        (
            lambda r: r.__setitem__(
                "turns",
                [
                    {"n": i + 1, "speaker": "agent", "text": "x"}
                    for i in range(MAX_TURNS + 1)
                ],
            ),
            "oversized_input",
            "turns",
        ),
        (
            lambda r: r["turns"][0].__setitem__("text", "x" * (MAX_TURN_CHARS + 1)),
            "oversized_input",
            "turns[0].text",
        ),
    ],
)
def test_bad_records_raise_typed_errors(mutate, code, field):
    record = copy.deepcopy(abcd("ABCD-0041"))
    mutate(record)
    with pytest.raises(PipelineError) as raised:
        read_conversation(record, COMPANY)
    assert raised.value.code == code
    assert raised.value.field == field


def test_non_object_and_missing_company_are_rejected():
    with pytest.raises(PipelineError):
        read_conversation(["not", "a", "record"], COMPANY)
    with pytest.raises(PipelineError) as raised:
        read_conversation(abcd("ABCD-0041"), "")
    assert raised.value.field == "company_id"


def test_batch_reports_position_and_rejects_duplicates():
    bad = copy.deepcopy(abcd("ABCD-0002"))
    bad["turns"][0]["speaker"] = "robot"
    with pytest.raises(PipelineError) as raised:
        read_conversations([abcd("ABCD-0041"), bad], COMPANY)
    assert raised.value.field == "conversations[1].turns[0].speaker"
    with pytest.raises(PipelineError) as raised:
        read_conversations([abcd("ABCD-0041"), abcd("ABCD-0041")], COMPANY)
    assert "duplicate" in raised.value.message
