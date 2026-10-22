from __future__ import annotations

import copy
import json

import pytest

from backend.services.knowledge.conflicts import find_conflicts
from backend.services.knowledge.errors import PipelineError
from backend.services.knowledge.extraction import extract_drafts
from backend.services.knowledge.grouping import group_drafts
from backend.services.knowledge.verification import (
    HUMAN_STEP,
    VerificationConfig,
    check_drafts,
    load_reference_snapshot,
)

from .conftest import ABCD_DIR, BACKEND, COMPANY, LABELS_DIR, SYNTHETIC_DIR, load_json

SNAPSHOT = BACKEND / "data" / "references" / "abcd-guidelines.snapshot.json"
LABELS = load_json(LABELS_DIR / "verification.json")
PROMO = {"flow": "purchase_dispute", "subflow": "promo_code_invalid"}


def approved(references):
    """Test-only stand-in for a person's review: approve every passage."""
    out = copy.deepcopy(references)
    for reference in out:
        reference["approval"] = {
            "status": "approved",
            "approved_by": "test-reviewer",
            "approved_at": "2026-10-01",
        }
    return out


@pytest.fixture(scope="module")
def references():
    return approved(load_reference_snapshot(SNAPSHOT, COMPANY))


def draft_for(cid: str):
    folder = ABCD_DIR if cid.startswith("ABCD") else SYNTHETIC_DIR
    [draft] = extract_drafts(load_json(folder / f"{cid}.json"), COMPANY).drafts
    return draft


def packet(draft, references, **kwargs):
    [result] = check_drafts([draft], COMPANY, references, **kwargs)["results"]
    return result


@pytest.mark.parametrize("case", LABELS["cases"], ids=lambda c: c["conversation"])
def test_labelled_draft(case, references):
    result = packet(draft_for(case["conversation"]), references)
    assert result["verification_status"] == case["expect"], [
        (c["status"], c["claim"]) for c in result["claims"]
    ]


def test_committed_snapshot_verifies_nothing_until_reviewed():
    unreviewed = load_reference_snapshot(SNAPSHOT, COMPANY)
    assert {r["approval"]["status"] for r in unreviewed} == {"unreviewed"}
    result = packet(draft_for("SYN-0006"), unreviewed)
    assert result["verification_status"] == "unverifiable"
    assert result["ml_recommendation"] == "cannot_be_verified"
    assert result["references_considered"] == 0
    assert {i["reason"] for i in result["ignored_references"]} == {
        "not approved (approval status: unreviewed)"
    }


@pytest.mark.parametrize(
    ("change", "reason"),
    [
        (
            lambda r: r["eligibility"].update(status="stale", reason="replaced by v5"),
            "not eligible (stale: replaced by v5)",
        ),
        (
            lambda r: r["eligibility"].update(status="disputed"),
            "not eligible (disputed)",
        ),
        (
            lambda r: r["eligibility"].update(status="out_of_scope"),
            "not eligible (out_of_scope)",
        ),
        (
            lambda r: r["eligibility"].update(valid_until="2026-01-01"),
            "stale (valid until 2026-01-01)",
        ),
        (
            lambda r: r.update(company_id="another-company"),
            "belongs to another company",
        ),
        (lambda r: r.update(kind="knowledge_entry"), "not an authoritative reference"),
        (
            lambda r: r["approval"].update(status="rejected"),
            "not approved (approval status: rejected)",
        ),
    ],
)
def test_ineligible_references_cannot_verify(change, reason, references):
    promo = [copy.deepcopy(r) for r in references if r["scope"] == PROMO]
    for reference in promo:
        change(reference)
    result = packet(draft_for("SYN-0006"), promo, as_of="2026-10-22")
    assert result["verification_status"] == "unverifiable"
    assert all(c["status"] == "unverifiable" for c in result["claims"])
    assert all(i["reason"].startswith(reason) for i in result["ignored_references"])


def test_expiry_needs_an_as_of_date(references):
    promo = [copy.deepcopy(r) for r in references if r["scope"] == PROMO]
    for reference in promo:
        reference["eligibility"]["valid_until"] = "2027-01-01"
    assert packet(draft_for("SYN-0006"), promo)["verification_status"] == "unverifiable"
    assert (
        packet(draft_for("SYN-0006"), promo, as_of="2026-10-22")["verification_status"]
        == "supported"
    )


def test_supported_claims_cite_approved_authoritative_passages(references):
    by_id = {r["reference_id"]: r for r in references}
    supported = 0
    for path in sorted(ABCD_DIR.glob("*.json")):
        for draft in extract_drafts(load_json(path), COMPANY).drafts:
            for claim in packet(draft, references)["claims"]:
                if claim["status"] != "supported":
                    continue
                supported += 1
                assert claim["citations"], claim
                for citation in claim["citations"]:
                    reference = by_id[citation["reference_id"]]
                    assert reference["kind"] == "authoritative_reference"
                    assert citation["approval"]["status"] == "approved"
                    assert citation["quote"].startswith(reference["text"])
    assert supported > 50


def test_ml_never_decides(references):
    draft = draft_for("SYN-0006")
    before = copy.deepcopy((draft, references))
    result = check_drafts([draft], COMPANY, references)
    assert (draft, references) == before  # no approval, eligibility or date was touched
    [item] = result["results"]
    assert item["decision"] is None
    assert item["ml_recommendation"] == "supported_by_references"
    assert item["requirements_remaining"][-1] == HUMAN_STEP
    text = json.dumps(result)
    for forbidden in (
        '"approved": true',
        '"verified_at"',
        '"audit_eligible": true',
        '"status": "approved"',
    ):
        assert forbidden not in text.replace('"approval": {"status": "approved"', "")


def test_missing_conditions_stay_unresolved(references):
    result = packet(draft_for("ABCD-0031"), references)
    [claim] = [c for c in result["claims"] if "original packaging" in c["claim"]]
    assert claim["missing_conditions"]
    assert any("days limit" in r for r in result["requirements_remaining"])
    assert result["ml_recommendation"] == "needs_more_evidence"


def test_conflicts_and_supporting_conversations_are_carried(references):
    drafts = [draft_for("SYN-0006"), draft_for("SYN-0005")]
    groups = group_drafts(drafts, COMPANY)
    conflicts = find_conflicts(drafts, COMPANY, groups=groups)
    assert conflicts["possible_conflicts"]
    results = {
        r["draft_id"]: r
        for r in check_drafts(
            drafts, COMPANY, references, conflicts=conflicts, groups=groups
        )["results"]
    }
    good = results[drafts[0]["draft_id"]]
    assert good["possible_conflicts"]
    # Fully supported by references, but an open conflict still blocks the recommendation.
    assert good["verification_status"] == "supported"
    assert good["ml_recommendation"] == "needs_more_evidence"
    assert any("Resolve possible conflict" in r for r in good["requirements_remaining"])
    assert good["supporting_conversations"]["source_keys"] == [
        drafts[0]["source"]["source_key"]
    ]
    assert "not verification" in good["supporting_conversations"]["note"]


def test_contradiction_cites_the_reference(references):
    result = packet(draft_for("ABCD-0046"), references)
    [claim] = [c for c in result["claims"] if c["status"] == "contradicted"]
    [first, *_] = claim["contradicted_by"]
    assert first["reference_id"].startswith("abcd:purchase_dispute/promo_code_invalid#")
    assert "guest" in first["reason"]
    assert result["ml_recommendation"] == "contradicted_by_references"


def test_bad_input():
    with pytest.raises(PipelineError) as raised:
        check_drafts([], COMPANY, [{"reference_id": "x"}])
    assert raised.value.code == "reference_invalid"
    with pytest.raises(PipelineError):
        check_drafts([], COMPANY, [], as_of="yesterday")
    with pytest.raises(PipelineError):
        VerificationConfig(support_threshold=0.2, partial_threshold=0.5)


def test_instruction_lines_never_support_a_claim(references):
    # Regression: found by the first held-out run (a list of FAQ topics "supported" a claim).
    result = packet(draft_for("ABCD-0073"), references)
    reasons = {i["reference_id"]: i["reason"] for i in result["ignored_references"]}
    instruction_ids = [r for r in reasons if "#i" in r]
    assert instruction_ids
    assert all(reasons[r].startswith("instruction line") for r in instruction_ids)
    for claim in result["claims"]:
        assert all("#i" not in c["reference_id"] for c in claim["citations"])
