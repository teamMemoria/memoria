"""Regression tests for problems found in review before the first PRs."""

from __future__ import annotations

import copy
import json
import unicodedata

import pytest

from backend.services.knowledge.abcd import MAX_BATCH_CONVERSATIONS, read_conversation
from backend.services.knowledge.conflicts import find_conflicts
from backend.services.knowledge.errors import PipelineError
from backend.services.knowledge.extraction import (
    ExtractionConfig,
    ModelExtractor,
    extract_drafts,
)
from backend.services.knowledge.grouping import group_drafts
from backend.services.knowledge.llm import FakeModelClient
from backend.services.knowledge.pipeline import release_checks, run_pipeline
from backend.services.knowledge.privacy import Redactor
from backend.services.knowledge.verification import check_drafts

from .conftest import ABCD_DIR, COMPANY, abcd, load_json, synthetic

SCOPE = {"flow": "product_defect", "subflow": "return_size"}


def chat(cid, answer, question="Can I return this?", record=None, flow=SCOPE):
    out = {
        "id": cid,
        "source": {"dataset": "SYNTHETIC", "original_id": cid},
        "modifications": [],
        "channel": "chat",
        "turns": [
            {"n": 1, "speaker": "customer", "text": question},
            {"n": 2, "speaker": "agent", "text": answer},
        ],
        "source_fields": {**flow, "actions_taken": []},
        "customer_record": record or {},
    }
    return out


def reference(text, rid="r1", **extra):
    return {
        "reference_id": rid,
        "company_id": COMPANY,
        "kind": "authoritative_reference",
        "scope": SCOPE,
        "version": "1",
        "text": text,
        "approval": {"status": "approved"},
        "eligibility": {"status": "eligible"},
        **extra,
    }


def draft(record):
    [d] = extract_drafts(record, COMPANY).drafts
    return d


@pytest.mark.parametrize(
    ("claim", "ref"),
    [
        (
            "Gold members cannot return items after purchase.",
            "Gold members can return items after purchase.",
        ),
        (
            "Guests are not eligible to return items after purchase.",
            "Guests are eligible to return items after purchase.",
        ),
    ],
)
def test_a_reference_saying_the_opposite_contradicts(claim, ref):
    [result] = check_drafts([draft(chat("T1", claim))], COMPANY, [reference(ref)])[
        "results"
    ]
    assert result["verification_status"] == "contradicted"


def test_model_text_is_redacted_and_made_up_ids_are_not_echoed():
    record = abcd("ABCD-0002")
    reply = {
        "drafts": [],
        "no_draft_reason": "Joseph Banter's account 78985 in san mateo, jbanter1",
    }
    result = extract_drafts(
        record, COMPANY, extractor=ModelExtractor(FakeModelClient([reply]))
    )
    assert (
        "Joseph" not in result.no_draft_reason and "78985" not in result.no_draft_reason
    )
    bad_ids = {
        "drafts": [
            {
                "question": "q",
                "question_turn_ids": ["Joseph Banter 78985"],
                "answer": "a",
                "answer_turn_ids": ["x"],
            }
        ]
    }
    result = extract_drafts(
        record, COMPANY, extractor=ModelExtractor(FakeModelClient([bad_ids]))
    )
    assert "Joseph" not in json.dumps(result.to_dict(), ensure_ascii=False)


@pytest.mark.parametrize(
    "reply", [["not", "an", "object"], {"drafts": [{"question": 1}]}]
)
def test_odd_model_replies_are_errors_or_rejections_not_crashes(reply):
    result = extract_drafts(
        abcd("ABCD-0041"), COMPANY, extractor=ModelExtractor(FakeModelClient([reply]))
    )
    assert result.status == "error" or result.rejected


def test_model_conditions_null_is_accepted():
    reply = {
        "drafts": [
            {
                "question": "My promo code does not work. Can I get a new one?",
                "question_turn_ids": ["ABCD-0041#t2"],
                "answer": "A replacement promo code can only be issued to existing members.",
                "answer_turn_ids": ["ABCD-0041#t21"],
                "conditions": None,
            }
        ]
    }
    result = extract_drafts(
        abcd("ABCD-0041"), COMPANY, extractor=ModelExtractor(FakeModelClient([reply]))
    )
    assert result.status == "ok" and result.drafts


def test_an_extractor_bug_is_an_error_not_an_empty_result():
    class Broken:
        name, version = "broken", "0"

        def select(self, redacted, config):
            raise KeyError("oops")

    result = extract_drafts(abcd("ABCD-0041"), COMPANY, extractor=Broken())
    assert result.status == "error" and result.errors[0]["code"] == "internal_error"


@pytest.mark.parametrize(
    "kwargs",
    [
        {"topics": "account_access"},
        {"min_answer_words": "5"},
        {"max_drafts_per_conversation": 0},
        {"max_placeholder_share": 2},
    ],
)
def test_bad_extraction_config_is_refused(kwargs):
    with pytest.raises(PipelineError):
        ExtractionConfig(**kwargs)
    output = run_pipeline(
        {"company_id": COMPANY, "conversations": [], "config": {"extraction": kwargs}}
    )
    assert output["status"] == "error"


def test_bad_inputs_to_later_stages_raise_typed_errors():
    d = draft(synthetic("SYN-G01"))
    with pytest.raises(PipelineError):
        check_drafts([d], COMPANY, [], as_of=20261022)
    with pytest.raises(PipelineError):
        check_drafts([d], COMPANY, [reference("x", approval="approved")])
    with pytest.raises(PipelineError):
        check_drafts(
            [d], COMPANY, [reference("x", scope={"flow": "f", "subflow_prefix": 3})]
        )
    with pytest.raises(PipelineError):
        find_conflicts([d], COMPANY, groups={"groups": [{"member_draft_ids": []}]})
    for stage in (group_drafts, find_conflicts):
        broken = copy.deepcopy(d)
        broken["scope"] = ["not", "an", "object"]
        with pytest.raises(PipelineError):
            stage([broken], COMPANY)
        broken = copy.deepcopy(d)
        broken["conditions"] = "nope"
        with pytest.raises(PipelineError):
            stage([broken], COMPANY)
    none_conditions = copy.deepcopy(d)
    none_conditions["conditions"] = None
    assert group_drafts([none_conditions], COMPANY)["groups"]
    raw = {
        "convo_id": 1,
        "scenario": {"personal": "x", "flow": "a", "subflow": "b"},
        "original": [["agent", "hi"]],
    }
    with pytest.raises(PipelineError):
        read_conversation(raw, COMPANY)
    no_id = copy.deepcopy(abcd("ABCD-0041"))
    no_id["source"]["original_id"] = None
    with pytest.raises(PipelineError):
        read_conversation(no_id, COMPANY)


def test_batch_limit_is_enforced():
    output = run_pipeline(
        {"company_id": COMPANY, "conversations": [{}] * (MAX_BATCH_CONVERSATIONS + 1)}
    )
    assert (
        output["status"] == "error" and output["errors"][0]["code"] == "oversized_input"
    )


def test_name_matching_never_eats_meaningful_words():
    assert (
        Redactor({"customer_name": "nora gould"})
        .redact("Gold members can return items.")
        .text
        == "Gold members can return items."
    )
    assert (
        Redactor({"customer_name": "dan lee"}).redact("Can I help? Dan, yes.").text
        == "Can I help? [CUSTOMER_NAME], yes."
    )
    assert (
        Redactor({"customer_name": "will gold"})
        .redact("Gold members can return items.")
        .text
        == "Gold members can return items."
    )


def test_decomposed_unicode_is_still_redacted_and_caught():
    record = {"customer_name": "ana peña"}
    text = unicodedata.normalize("NFD", "Hi, I am Ana Peña.")
    redacted = Redactor(record).redact(text).text
    assert "Pe" not in redacted
    assert Redactor(record).leaks(unicodedata.normalize("NFD", "Peña")) == [
        "CUSTOMER_NAME"
    ]


def test_all_abcd_records_pass_the_release_checks():
    records = [load_json(p) for p in sorted(ABCD_DIR.glob("*.json"))]
    payload = {"company_id": COMPANY, "conversations": records}
    output = run_pipeline(payload)
    checks = release_checks(output, payload)
    assert checks["release_allowed"], [c for c in checks["checks"] if not c["passed"]]


def test_levels_in_the_answer_keep_groups_apart():
    a = draft(
        chat(
            "T1",
            "Gold members can get a new promo code right away.",
            "Can I get a new promo code?",
        )
    )
    b = draft(
        chat(
            "T2",
            "Guests can get a new promo code right away.",
            "Can I get a new promo code?",
        )
    )
    groups = group_drafts([a, b], COMPANY)["groups"]
    assert len(groups) == 2


def test_two_sentences_of_one_turn_get_different_conflict_ids():
    a = draft(
        chat(
            "T1",
            "Returns are accepted within 30 days. Refunds take 10 days to arrive.",
            "How do returns and refunds work?",
        )
    )
    b = draft(
        chat(
            "T2",
            "Returns are accepted within 60 days. Refunds take 5 days to arrive.",
            "How do returns and refunds work?",
        )
    )
    conflicts = find_conflicts([a, b], COMPANY)["possible_conflicts"]
    assert len(conflicts) == 2
    assert len({c["conflict_id"] for c in conflicts}) == 2


def test_unresolved_conflicts_also_block_a_supported_recommendation():
    a = draft(
        chat(
            "T1",
            "Returns are accepted within 30 days of purchase.",
            "How long do I have to return?",
        )
    )
    b = draft(
        chat(
            "T2",
            "I think returns are usually accepted within 60 days of purchase.",
            "How long do I have to return?",
        )
    )
    conflicts = find_conflicts([a, b], COMPANY)
    assert {c["status"] for c in conflicts["possible_conflicts"]} == {"unresolved"}
    ref = reference("Returns are accepted within 30 days of purchase.")
    result = {
        r["draft_id"]: r
        for r in check_drafts([a, b], COMPANY, [ref], conflicts=conflicts)["results"]
    }[a["draft_id"]]
    assert result["verification_status"] == "supported"
    assert result["ml_recommendation"] == "needs_more_evidence"


def test_other_companies_references_are_not_listed():
    ref = reference("Gold members can return items.", company_id="another-company")
    [result] = check_drafts(
        [draft(chat("T1", "Gold members can return items."))], COMPANY, [ref]
    )["results"]
    assert result["ignored_references"] == []
    assert "another-company" not in json.dumps(result)
