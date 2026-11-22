"""Regression tests for problems found in the second review, before the PRs."""

from __future__ import annotations

import copy
import json

import pytest

from backend.services.knowledge.__main__ import main
from backend.services.knowledge.conflicts import find_conflicts
from backend.services.knowledge.errors import PipelineError
from backend.services.knowledge.extraction import ExtractionConfig, extract_drafts
from backend.services.knowledge.pipeline import release_checks, run_pipeline
from backend.services.knowledge.privacy import Redactor, pattern_leaks
from backend.services.knowledge.verification import (
    VerificationConfig,
    check_drafts,
)

from .conftest import COMPANY, abcd

SCOPE = {"flow": "product_defect", "subflow": "return_size"}


def chat(cid, answer, question="Can I return this?", record=None, extra_turns=()):
    turns = [
        {"n": 1, "speaker": "customer", "text": question},
        {"n": 2, "speaker": "agent", "text": answer},
    ]
    for i, (speaker, text) in enumerate(extra_turns):
        turns.append({"n": 3 + i, "speaker": speaker, "text": text})
    return {
        "id": cid,
        "source": {"dataset": "SYNTHETIC", "original_id": cid},
        "customer_record": record if record is not None else {},
        "modifications": [],
        "turns": turns,
        "source_fields": {**SCOPE, "actions_taken": []},
    }


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


def verdict(claim, ref_text):
    [draft] = extract_drafts(chat("T1", claim), COMPANY).drafts
    [result] = check_drafts([draft], COMPANY, [reference(ref_text)])["results"]
    return result["claims"][0]["status"]


# --- verification ---------------------------------------------------------------


@pytest.mark.parametrize(
    "claim",
    [
        "Sorry about that, promo codes can be used on sale items.",
        "I think promo codes can be used on sale items.",
        "Right now promo codes can be used on sale items.",
    ],
)
def test_hedged_or_time_bound_claims_are_still_contradicted(claim):
    assert verdict(claim, "Promo codes cannot be used on sale items.") == "contradicted"


def test_a_negation_on_both_sides_about_different_verbs_contradicts():
    assert (
        verdict(
            "Promo codes never expire, you can use them any time.",
            "Promo codes expire, you cannot use them any time.",
        )
        == "contradicted"
    )


def test_the_same_negation_on_both_sides_still_supports():
    assert (
        verdict(
            "Sorry, promo codes cannot be used on sale items at all.",
            "Promo codes cannot be used on sale items.",
        )
        == "supported"
    )


def test_thresholds_of_zero_are_refused():
    with pytest.raises(PipelineError):
        VerificationConfig(support_threshold=0.0, partial_threshold=0.0)


def test_sub_points_are_read_in_the_same_order_whatever_the_input_order():
    [draft] = extract_drafts(
        chat("T1", "Gold members can always get a refund on this order."), COMPANY
    ).drafts
    refs = [
        reference("Whether they get a refund depends on the level", rid="p"),
        reference("Guest", rid="p.1", parent="p"),
        reference("Gold members can always get a refund", rid="p.2", parent="p"),
    ]
    forward = check_drafts([draft], COMPANY, refs)["results"]
    backward = check_drafts([draft], COMPANY, list(reversed(refs)))["results"]
    assert forward == backward
    assert forward[0]["verification_status"] == "supported"


def test_a_reference_is_cited_once_per_claim():
    [draft] = extract_drafts(
        chat("T1", "Gold members can always get a refund on this order."), COMPANY
    ).drafts
    refs = [
        reference("Refunds depend on the level", rid="p"),
        reference("Gold members can always get a refund", rid="p.1", parent="p"),
    ]
    [result] = check_drafts([draft], COMPANY, refs)["results"]
    ids = [c["reference_id"] for c in result["claims"][0]["citations"]]
    assert len(ids) == len(set(ids))


def test_a_malformed_reference_field_is_a_reference_error():
    with pytest.raises(PipelineError) as error:
        check_drafts(
            [], COMPANY, [reference("x", eligibility={"status": "x", "reason": 7})]
        )
    assert error.value.code == "reference_invalid"


def test_malformed_conflicts_are_an_input_error():
    [draft] = extract_drafts(
        chat("T1", "Promo codes can be used on sale items."), COMPANY
    ).drafts
    with pytest.raises(PipelineError):
        check_drafts(
            [draft], COMPANY, [], conflicts={"possible_conflicts": [{"a": {}}]}
        )


# --- release checks -------------------------------------------------------------


@pytest.fixture
def handoff():
    payload = {
        "company_id": COMPANY,
        "conversations": [
            chat("T1", "Promo codes can be used on sale items for seven days."),
            chat("T2", "Promo codes cannot be used on sale items for seven days."),
        ],
        "references": [
            reference("Promo codes can be used on sale items for seven days.")
        ],
    }
    output = run_pipeline(payload)
    assert output["release_checks"]["release_allowed"], output["release_checks"]
    return payload, output


def blocked(payload, output):
    return not release_checks(output, payload)["release_allowed"]


def test_run_pipeline_attaches_its_release_checks(handoff):
    _, output = handoff
    assert {c["check"] for c in output["release_checks"]["checks"]} >= {
        "no_fabricated_citations",
        "no_unsupported_verified_claims",
        "no_personal_data_leaks",
        "ml_approves_nothing",
        "matches_a_fresh_run",
    }


def supported_citation(output):
    for result in output["verification"]["results"]:
        for claim in result["claims"]:
            if claim["status"] == "supported":
                return claim["citations"][0]
    raise AssertionError("no supported claim")


@pytest.mark.parametrize(
    "tamper",
    [
        lambda o: supported_citation(o).update(
            quote=supported_citation(o)["quote"] + " Always."
        ),
        lambda o: supported_citation(o).update(
            approval={"status": "approved", "by": "ml"}
        ),
        lambda o: o["drafts"][0].update(answer=o["drafts"][0]["answer"] + " Always."),
        lambda o: o["drafts"][0]["answer_passages"][0].update(span=[0, 10_000]),
        lambda o: o["drafts"][0]["answer_passages"][0].update(span=[0.0, 5.0]),
        lambda o: o["drafts"][0]["verification"].update(status="verified"),
        lambda o: o["verification"]["results"][0].update(ml_recommendation="approve"),
        lambda o: o["verification"]["results"][0].pop("decision"),
        lambda o: o["drafts"][0].update(approval={"status": "approved"}),
        lambda o: o["groups"]["groups"][0]["representative"].update(status="approved"),
        lambda o: o["verification"]["results"][0]["claims"][0].update(
            claim="Anything at all."
        ),
    ],
)
def test_edited_outputs_are_blocked(handoff, tamper):
    payload, output = handoff
    edited = copy.deepcopy(output)
    tamper(edited)
    assert blocked(payload, edited)


def test_a_reference_that_is_no_longer_approved_blocks_old_output(handoff):
    payload, output = handoff
    changed = copy.deepcopy(payload)
    changed["references"][0]["approval"] = {"status": "unreviewed"}
    assert blocked(changed, output)


def test_an_expired_reference_blocks_old_output(handoff):
    payload, output = handoff
    changed = copy.deepcopy(payload)
    changed["as_of"] = "2026-11-01"
    changed["references"][0]["eligibility"] = {
        "status": "eligible",
        "valid_until": "2020-01-01",
    }
    assert blocked(changed, output)


def test_a_conflict_cannot_be_marked_disputed(handoff):
    payload, output = handoff
    edited = copy.deepcopy(output)
    assert edited["conflicts"]["possible_conflicts"]
    edited["conflicts"]["possible_conflicts"][0]["status"] = "disputed"
    assert blocked(payload, edited)


# --- privacy ----------------------------------------------------------------------


@pytest.mark.parametrize(
    ("name", "text"),
    [
        ("will smith", "Will, promo codes can be used on sale items."),
        ("may chen", "Thanks May, promo codes can be used on sale items."),
        ("joseph banter", "Joe, promo codes can be used on sale items."),
        ("joseph banter", "Thanks Joe, that is all done now."),
    ],
)
def test_names_that_are_words_or_short_forms_are_removed(name, text):
    redacted = Redactor({"customer_name": name}).redact(text).text
    assert "[CUSTOMER_NAME]" in redacted
    assert name.split()[0][:3].title() not in redacted


def test_ordinary_uses_of_name_words_stay():
    redactor = Redactor({"customer_name": "will smith"})
    assert redactor.redact("I will check that for you now.").text == (
        "I will check that for you now."
    )


def test_house_numbers_are_removed_and_prices_and_units_stay():
    redactor = Redactor({})
    assert redactor.redact("Change this to 7873, please.").text == (
        "Change this to [NUMBER], please."
    )
    kept = "It is $100, takes 100 days, 25% off, in 2026."
    assert redactor.redact(kept).text == kept


def test_the_abcd_house_number_no_longer_reaches_a_draft():
    result = extract_drafts(abcd("ABCD-0016"), COMPANY)
    assert "7873" not in json.dumps(result.to_dict(), ensure_ascii=False)


def test_the_phone_check_does_not_gather_digits_from_across_the_text():
    redactor = Redactor({"phone": "(822) 577-6709"})
    assert redactor.leaks("$57 then 76 days in Aisle 09") == []
    assert redactor.leaks("call 577-6709") == ["PHONE"]


def test_personal_details_are_found_without_any_record():
    assert pattern_leaks("Reach me at jo@example.com") == ["EMAIL"]
    assert pattern_leaks("Your [PHONE] is saved") == []


@pytest.mark.parametrize(
    "record",
    [
        None,
        ["joseph banter"],
        {"name": "joseph banter"},
        {"customer_name": 7},
    ],
)
def test_a_missing_or_malformed_customer_record_is_refused(record):
    conversation = chat("T1", "Promo codes can be used on sale items.")
    if record is None:
        del conversation["customer_record"]
    else:
        conversation["customer_record"] = record
    result = extract_drafts(conversation, COMPANY)
    assert result.status == "error"
    assert result.errors[0]["code"] == "invalid_input"


def test_text_that_cannot_be_written_out_is_refused():
    result = extract_drafts(chat("T1", "Bad \ud800 text in the answer here."), COMPANY)
    assert result.status == "error"


# --- conflicts and ids ----------------------------------------------------------


def test_identical_drafts_do_not_conflict_with_each_other():
    answer = (
        "Promo codes can be used on sale items. Gold members can use promo codes on "
        "clearance items. Guests cannot use promo codes on clearance items."
    )
    drafts = [
        extract_drafts(chat(f"T{i}", answer), COMPANY).drafts[0] for i in range(6)
    ]
    assert find_conflicts(drafts, COMPANY)["possible_conflicts"] == []


def test_repeated_disagreements_are_counted_once():
    drafts = [
        extract_drafts(
            chat(
                f"T{i}",
                f"Promo codes last {7 if i % 2 else 9} days after they are issued.",
            ),
            COMPANY,
        ).drafts[0]
        for i in range(8)
    ]
    conflicts = find_conflicts(drafts, COMPANY)["possible_conflicts"]
    assert len(conflicts) == 1
    assert conflicts[0]["repeated_pairs"] == 15


def entry(version, answer):
    return {
        "entry_id": "E1",
        "company_id": COMPANY,
        "version": version,
        "status": "approved",
        "scope": SCOPE,
        "question": "Can I return this?",
        "answer": answer,
    }


def test_versions_of_one_entry_get_different_conflict_ids():
    [draft] = extract_drafts(
        chat("T1", "Items can be returned after purchase."), COMPANY
    ).drafts
    result = find_conflicts(
        [draft],
        COMPANY,
        existing_entries=[
            entry("1", "Items cannot be returned after purchase."),
            entry("2", "Items cannot be returned after purchase now."),
            entry("2", "Items cannot be returned after purchase now."),
        ],
    )
    ids = [c["conflict_id"] for c in result["possible_conflicts"]]
    assert len(ids) == 2 == len(set(ids))


# --- extraction and the command line ---------------------------------------------


def test_an_empty_topic_list_is_refused():
    with pytest.raises(PipelineError):
        ExtractionConfig(topics=[])


def test_unreadable_json_is_a_typed_error(tmp_path, capsys):
    bad = tmp_path / "bad.json"
    bad.write_text("{not json", encoding="utf-8")
    assert main(["run", str(bad)]) == 1
    assert json.loads(capsys.readouterr().out)["errors"][0]["code"] == "invalid_input"
