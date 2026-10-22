from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from backend.services.knowledge.abcd import read_conversation
from backend.services.knowledge.extraction import (
    ExtractionConfig,
    ModelExtractor,
    RuleExtractor,
    check_draft_citations,
    extract_drafts,
)
from backend.services.knowledge.llm import FakeModelClient
from backend.services.knowledge.privacy import Redactor

from .conftest import BACKEND, COMPANY, LABELS_DIR, abcd, load_json, synthetic

FORBIDDEN_STATUS_KEYS = {"approved", "approval", "approved_by", "verified_at"}


def _drafts(record, **kwargs):
    result = extract_drafts(record, COMPANY, **kwargs)
    assert result.status == "ok", result.errors
    return result


# ----------------------------------------------------------------- shape and safety


def test_draft_links_every_claim_to_exact_passages():
    result = _drafts(abcd("ABCD-0041"))
    [draft] = result.drafts
    conversation = read_conversation(abcd("ABCD-0041"), COMPANY)
    assert check_draft_citations(draft, conversation) == []
    assert draft["question_passages"][0]["speaker"] == "customer"
    assert all(
        p["speaker"] in {"agent", "system_action"} for p in draft["answer_passages"]
    )
    # The verbatim answer is exactly the cited quotes, nothing added.
    assert draft["wording"] == "verbatim"
    assert draft["answer"] == " ".join(p["quote"] for p in draft["answer_passages"])
    assert draft["source"]["source_key"] == conversation.source_key
    assert draft["source"]["dataset_version"].startswith("abcd_v1.1@")
    assert draft["procedure"] == [a.to_dict() for a in conversation.actions]


def test_drafts_are_never_trusted_or_approved(abcd_records):
    for record in abcd_records:
        for draft in extract_drafts(record, COMPANY).drafts:
            assert draft["status"] == "draft"
            assert draft["trusted"] is False
            assert draft["audit_eligible"] is False
            assert draft["verification"]["status"] == "not_verified"
            assert not FORBIDDEN_STATUS_KEYS & draft.keys()


def test_every_abcd_draft_cites_exactly_and_leaks_nothing(abcd_records):
    drafts = 0
    for record in abcd_records:
        conversation = read_conversation(record, COMPANY)
        redactor = Redactor(conversation.customer_record)
        for draft in extract_drafts(record, COMPANY).drafts:
            drafts += 1
            assert check_draft_citations(draft, conversation) == [], draft["draft_id"]
            assert redactor.leaks(json.dumps(draft)) == [], draft["draft_id"]
    assert drafts >= 80  # the baseline extracts from most of the 100 records


def test_extraction_is_deterministic_and_reprocessing_is_stable():
    first = extract_drafts(abcd("ABCD-0073"), COMPANY).to_dict()
    second = extract_drafts(copy.deepcopy(abcd("ABCD-0073")), COMPANY).to_dict()
    assert first == second


def test_conditions_are_kept_with_their_basis():
    [draft] = _drafts(synthetic("SYN-0004")).drafts
    texts = [c["text"] for c in draft["conditions"]]
    assert any(
        "within 90 days" in t and "unless the item was on final sale" in t
        for t in texts
    )
    assert any("within 30 days with a receipt" in t for t in texts)
    [draft] = _drafts(abcd("ABCD-0046")).drafts
    assert {"recorded_action"} <= {c["basis"] for c in draft["conditions"]}
    assert any("guest" in c["text"].lower() for c in draft["conditions"])


def test_no_draft_comes_with_a_reason():
    for cid in ("SYN-0001", "SYN-0002"):
        result = _drafts(synthetic(cid))
        assert result.drafts == []
        assert result.no_draft_reason == "no_reusable_answer"


def test_topic_filter():
    config = ExtractionConfig(topics=frozenset({"account_access"}))
    assert (
        _drafts(abcd("ABCD-0041"), config=config).no_draft_reason
        == "topic_not_selected"
    )
    assert _drafts(abcd("ABCD-0002"), config=config).drafts


def test_wrong_company_is_an_error():
    conversation = read_conversation(abcd("ABCD-0041"), "other-company")
    result = extract_drafts(conversation, COMPANY)
    assert result.status == "error"
    assert result.errors[0]["field"] == "company_id"


# ----------------------------------------------------------------- errors are not empty successes


@pytest.mark.parametrize(
    ("record", "code"),
    [
        ({"id": "x"}, "invalid_input"),
        ("not json object", "invalid_input"),
        (
            {
                **abcd("ABCD-0041"),
                "turns": [
                    {"n": i + 1, "speaker": "agent", "text": "hi"} for i in range(500)
                ],
            },
            "oversized_input",
        ),
    ],
)
def test_invalid_and_oversized_inputs_return_errors(record, code):
    result = extract_drafts(record, COMPANY)
    assert result.status == "error"
    assert result.drafts == []
    assert result.errors[0]["code"] == code


@pytest.mark.parametrize(
    ("response", "code"),
    [
        (TimeoutError("read timed out"), "model_failure"),
        ("this is not json", "model_failure"),
        ({"answer": "no drafts key"}, "model_output_invalid"),
        (
            {"drafts": []},
            "model_output_invalid",
        ),  # nothing and no reason is not a success
    ],
)
def test_model_failures_return_errors(response, code):
    extractor = ModelExtractor(FakeModelClient([response]))
    result = extract_drafts(abcd("ABCD-0041"), COMPANY, extractor=extractor)
    assert result.status == "error"
    assert result.drafts == []
    assert result.errors[0]["code"] == code


# ----------------------------------------------------------------- model extractor checks its reply


def _model_draft(**overrides):
    draft = {
        "question": "My promo code does not work. Can I get a new one?",
        "question_turn_ids": ["ABCD-0041#t2"],
        "answer": "A replacement promo code can only be issued to existing members.",
        "answer_turn_ids": ["ABCD-0041#t21"],
        "conditions": [{"text": "Customer is a guest", "turn_ids": ["ABCD-0041#t20"]}],
    }
    draft.update(overrides)
    return draft


def test_model_draft_is_accepted_when_its_passages_support_it():
    extractor = ModelExtractor(FakeModelClient([{"drafts": [_model_draft()]}]))
    result = extract_drafts(abcd("ABCD-0041"), COMPANY, extractor=extractor)
    assert result.status == "ok"
    [draft] = result.drafts
    assert draft["wording"] == "model"
    assert draft["extractor"]["name"] == "model-extractor"
    assert (
        check_draft_citations(draft, read_conversation(abcd("ABCD-0041"), COMPANY))
        == []
    )
    # The model saw redacted text only.
    assert "Joseph" not in extractor.client.prompts[0]


@pytest.mark.parametrize(
    ("override", "reason"),
    [
        (
            {"answer": "Existing members can get a replacement code within 30 days."},
            "figures",
        ),
        ({"answer_turn_ids": ["ABCD-0041#t999"]}, "do not exist"),
        ({"answer": "Gold members always get a replacement promo code."}, "membership"),
        (
            {"answer": "Refunds are processed by the warehouse team overnight."},
            "content words",
        ),
        ({"question": "Joseph Banter asked about a promo code"}, "personal"),
        ({"question_turn_ids": ["ABCD-0041#t21"]}, "customer turn"),
    ],
)
def test_model_draft_is_rejected_when_unsupported(override, reason):
    extractor = ModelExtractor(
        FakeModelClient([{"drafts": [_model_draft(**override)]}])
    )
    result = extract_drafts(abcd("ABCD-0041"), COMPANY, extractor=extractor)
    assert result.status == "ok"
    assert result.drafts == []
    assert result.no_draft_reason == "model: every proposed draft was rejected"
    assert reason in result.rejected[0]["reason"]


def test_model_no_draft_needs_a_reason():
    extractor = ModelExtractor(
        FakeModelClient([{"drafts": [], "no_draft_reason": "small talk only"}])
    )
    result = extract_drafts(synthetic("SYN-0001"), COMPANY, extractor=extractor)
    assert result.status == "ok"
    assert result.no_draft_reason == "model: small talk only"


# ----------------------------------------------------------------- labelled cases

LABELS = load_json(LABELS_DIR / "extraction.json")


def _case_output(case):
    record = load_json(BACKEND / case["conversation"])
    return record, extract_drafts(record, COMPANY, extractor=RuleExtractor())


@pytest.mark.parametrize(
    "case", LABELS["cases"], ids=lambda c: Path(c["conversation"]).stem
)
def test_labelled_case_has_no_personal_data(case):
    _, result = _case_output(case)
    output = json.dumps(result.to_dict()).lower()
    for value in case.get("must_not_include", []):
        assert value.lower() not in output, value


def test_labelled_cases_meet_the_baseline():
    """Quality of the rule extractor against the labels. Raise the floors as it improves."""
    expected = found = 0
    answer_hits = answer_total = condition_hits = condition_total = 0
    for case in LABELS["cases"]:
        _, result = _case_output(case)
        wants_draft = case["expect"] == "draft"
        expected += 1
        found += wants_draft == bool(result.drafts)
        answers = " ".join(d["answer"] for d in result.drafts).lower()
        conditions = " ".join(
            c["text"] for d in result.drafts for c in d["conditions"]
        ).lower()
        for phrase in case.get("answer_must_include", []):
            answer_total += 1
            answer_hits += phrase.lower() in answers
        for phrase in case.get("conditions_must_include", []):
            condition_total += 1
            condition_hits += phrase.lower() in conditions
    assert found / expected >= 0.95
    assert answer_hits / answer_total >= 0.9
    assert condition_hits / condition_total >= 0.8


def test_fixed_examples_are_current():
    import subprocess
    import sys

    completed = subprocess.run(
        [sys.executable, str(BACKEND / "scripts" / "knowledge_examples.py"), "--check"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
