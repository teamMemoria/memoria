"""#20: the whole pipeline through one function, its release checks and the authored safety tests.

Authored scenarios (documented in docs/knowledge-pipeline.md, "#20"):

* repeated wrong answers: three conversations give guests a replacement code;
  repetition must not make it verified.
* missing, stale and disputed references: nothing verifies.
* changed conditions: an old reference version is stale and the current one
  states a different figure; drafts with the old figure are contradicted.
* personal information: nothing from any customer record reaches the output.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from backend.services.knowledge.evaluation import evaluate, render_markdown
from backend.services.knowledge.extraction import ModelExtractor
from backend.services.knowledge.llm import FakeModelClient
from backend.services.knowledge.pipeline import (
    release_checks,
    repeat_processing_check,
    run_pipeline,
)
from backend.services.knowledge.verification import load_reference_snapshot

from .conftest import ABCD_DIR, BACKEND, COMPANY, LABELS_DIR, SYNTHETIC_DIR, load_json

SNAPSHOT = BACKEND / "data" / "references" / "abcd-guidelines.snapshot.json"
PROMO = {"flow": "purchase_dispute", "subflow": "promo_code_invalid"}


def records(*cids):
    out = []
    for cid in cids:
        folder = ABCD_DIR if cid.startswith("ABCD") else SYNTHETIC_DIR
        out.append(load_json(folder / f"{cid}.json"))
    return out


@pytest.fixture(scope="module")
def references():
    refs = load_reference_snapshot(SNAPSHOT, COMPANY)
    for reference in refs:
        reference["approval"] = {
            "status": "approved",
            "approved_by": "test-reviewer",
            "approved_at": "2026-10-01",
        }
    return refs


def results_by_conversation(output):
    by_draft = {r["draft_id"]: r for r in output["verification"]["results"]}
    return {
        d["source"]["conversation_id"]: by_draft[d["draft_id"]]
        for d in output["drafts"]
    }


def test_one_function_runs_every_stage(references):
    payload = {
        "company_id": COMPANY,
        "conversations": records("SYN-0006", "ABCD-0046", "SYN-0004"),
        "references": references,
    }
    output = run_pipeline(payload)
    assert output["status"] == "ok"
    assert output["counts"]["drafts"] == 3
    assert {
        "extraction",
        "drafts",
        "groups",
        "conflicts",
        "verification",
    } <= output.keys()
    statuses = {
        cid: r["verification_status"]
        for cid, r in results_by_conversation(output).items()
    }
    # A supported draft and an unverifiable / conflicting one, side by side; approval stays human.
    assert statuses == {
        "SYN-0006": "supported",
        "ABCD-0046": "contradicted",
        "SYN-0004": "unverifiable",
    }
    assert all(r["decision"] is None for r in output["verification"]["results"])
    assert release_checks(output, payload)["release_allowed"] is True


def test_output_is_reproducible(references):
    payload = {
        "company_id": COMPANY,
        "conversations": records("SYN-0006", "ABCD-0041", "ABCD-0046"),
        "references": references,
    }
    assert run_pipeline(payload) == run_pipeline(copy.deepcopy(payload))
    assert repeat_processing_check(payload)["passed"] is True


def test_technical_failures_are_separate_from_missing_verification(references):
    broken = copy.deepcopy(records("SYN-0006")[0])
    broken["turns"][0]["speaker"] = "robot"
    payload = {
        "company_id": COMPANY,
        "conversations": [broken, *records("SYN-0004")],
        "references": references,
    }
    output = run_pipeline(payload)
    assert output["status"] == "completed_with_failures"
    assert output["technical_failures"][0]["errors"][0]["code"] == "invalid_input"
    assert output["counts"]["verification"] == {"unverifiable": 1}
    model_down = ModelExtractor(FakeModelClient([TimeoutError("down")]))
    output = run_pipeline(
        {"company_id": COMPANY, "conversations": records("SYN-0006")},
        extractor=model_down,
    )
    assert output["technical_failures"][0]["errors"][0]["code"] == "model_failure"
    assert output["counts"]["drafts"] == 0
    assert run_pipeline({"company_id": COMPANY})["status"] == "error"


def test_repeated_wrong_answers_are_not_verified(references):
    payload = {
        "company_id": COMPANY,
        "conversations": records("SYN-R01", "SYN-R02", "SYN-R03"),
        "references": references,
    }
    output = run_pipeline(payload)
    [group] = output["groups"]["groups"]
    assert group["distinct_conversation_count"] == 3
    assert group["meets_source_threshold"] is True  # enough repetition for the queue...
    statuses = {r["verification_status"] for r in output["verification"]["results"]}
    assert statuses == {
        "contradicted"
    }  # ...but the guideline says guests cannot get a code
    assert {r["ml_recommendation"] for r in output["verification"]["results"]} == {
        "contradicted_by_references"
    }


@pytest.mark.parametrize(
    ("change", "as_of"),
    [
        (None, None),  # no references at all
        (lambda r: r["eligibility"].update(status="stale", reason="replaced"), None),
        (
            lambda r: r["eligibility"].update(status="disputed", reason="under review"),
            None,
        ),
        (lambda r: r["approval"].update(status="unreviewed"), None),
        (lambda r: r["eligibility"].update(valid_until="2026-06-30"), "2026-10-22"),
    ],
)
def test_missing_stale_or_disputed_references_verify_nothing(change, as_of, references):
    refs = []
    if change is not None:
        refs = [copy.deepcopy(r) for r in references if r["scope"] == PROMO]
        for reference in refs:
            change(reference)
    payload = {
        "company_id": COMPANY,
        "conversations": records("SYN-0006"),
        "references": refs,
        "as_of": as_of,
    }
    output = run_pipeline(payload)
    [result] = output["verification"]["results"]
    assert result["verification_status"] == "unverifiable"
    assert result["ml_recommendation"] == "cannot_be_verified"
    assert release_checks(output, payload)["release_allowed"] is True


def test_changed_conditions_follow_the_current_reference():
    old = {
        "reference_id": "acme-policy:promo#v1",
        "company_id": COMPANY,
        "kind": "authoritative_reference",
        "scope": PROMO,
        "version": "1",
        "text": "Promo codes are valid for 7 days after they are issued.",
        "approval": {
            "status": "approved",
            "approved_by": "policy-owner",
            "approved_at": "2026-01-10",
        },
        "eligibility": {
            "status": "eligible",
            "valid_until": "2026-06-30",
            "reason": None,
        },
    }
    new = {
        **old,
        "reference_id": "acme-policy:promo#v2",
        "version": "2",
        "text": "Promo codes are valid for 14 days after they are issued.",
        "eligibility": {"status": "eligible", "valid_until": None, "reason": None},
    }
    payload = {
        "company_id": COMPANY,
        "conversations": records("SYN-G01"),
        "references": [old, new],
        "as_of": "2026-10-22",
    }
    [result] = run_pipeline(payload)["verification"]["results"]
    assert result["verification_status"] == "contradicted"
    assert (
        result["claims"][0]["contradicted_by"][0]["reference_id"]
        == "acme-policy:promo#v2"
    )
    assert [i["reference_id"] for i in result["ignored_references"]] == [
        "acme-policy:promo#v1"
    ]
    # Before the change, the same draft was supported by v1 alone.
    payload = {
        "company_id": COMPANY,
        "conversations": records("SYN-G01"),
        "references": [old],
        "as_of": "2026-03-01",
    }
    [result] = run_pipeline(payload)["verification"]["results"]
    assert result["verification_status"] == "supported"


def test_personal_information_never_reaches_the_output(references):
    cids = ("SYN-0003", "SYN-0002", "ABCD-0033", "ABCD-0048", "ABCD-0090")
    payload = {
        "company_id": COMPANY,
        "conversations": records(*cids),
        "references": references,
    }
    output = run_pipeline(payload)
    text = json.dumps(output)
    for value in (
        "Marguerite",
        "4111 1111",
        "415.555.0199",
        "4821937710",
        "cm149696",
        "ZHYTQ",
        "0B04TGRCUS",
    ):
        assert value not in text
    check = {c["check"]: c for c in release_checks(output, payload)["checks"]}
    assert check["no_personal_data_leaks"]["passed"] is True


@pytest.mark.parametrize(
    ("tamper", "check"),
    [
        (
            lambda o: o["drafts"][0]["answer_passages"][0].update(
                quote="Guests always get free codes."
            ),
            "no_fabricated_citations",
        ),
        (
            lambda o: o["verification"]["results"][0]["claims"][0].update(
                status="supported", citations=[]
            ),
            "no_unsupported_verified_claims",
        ),
        (
            lambda o: o["drafts"][0].update(
                question=o["drafts"][0]["question"] + " Call Tomas Reyes."
            ),
            "no_personal_data_leaks",
        ),
        (lambda o: o["drafts"][0].update(status="approved"), "ml_approves_nothing"),
        (
            lambda o: o["verification"]["results"][0].update(decision="approve"),
            "ml_approves_nothing",
        ),
    ],
)
def test_release_is_blocked_by_safety_failures(tamper, check, references):
    payload = {
        "company_id": COMPANY,
        "conversations": records("SYN-0005"),
        "references": references,
    }
    output = run_pipeline(payload)
    tamper(output)
    result = release_checks(output, payload)
    assert result["release_allowed"] is False
    assert {c["check"]: c["passed"] for c in result["checks"]}[check] is False


def test_heldout_conversations_are_kept_out_of_dev():
    def conversations(path: Path) -> set[str]:
        text = path.read_text(encoding="utf-8")
        return set(__import__("re").findall(r"(ABCD-\d{4}|SYN-[A-Z]?\d{2,4})", text))

    dev = set().union(*(conversations(p) for p in LABELS_DIR.glob("*.json")))
    heldout = set().union(
        *(conversations(p) for p in (LABELS_DIR / "heldout").glob("*.json"))
    )
    assert dev and heldout
    assert not dev & heldout
    splits = load_json(BACKEND / "data" / "abcd" / "splits.json")
    assert {splits[c]["split"] for c in heldout if c.startswith("ABCD")} == {"test"}
    assert "test" not in {splits[c]["split"] for c in dev if c.startswith("ABCD")}
    for path in (LABELS_DIR / "heldout").glob("*.json"):
        assert load_json(path)["split"] == "heldout"


def test_dev_evaluation_meets_its_floors():
    report = evaluate("dev", BACKEND)
    assert report["release_checks"]["release_allowed"] is True
    assert report["extraction"]["privacy_errors"] == 0
    assert report["extraction"]["faithfulness_exact_citation_rate"] == 1.0
    assert report["verification"]["unsupported_verified"] == 0
    assert report["conflicts"]["false_alarms"] == 0
    assert report["extraction"]["draft_decision_accuracy"] >= 0.95
    assert "Release allowed: **yes**" in render_markdown(report)
