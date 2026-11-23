from copy import deepcopy
from dataclasses import replace

import pytest

from backend.core.config import Settings
from backend.entities.assessments import AnalysisUnavailableError
from backend.entities.guidelines import (
    GUIDELINES,
    OVERNIGHT,
    SHIPPING_FEE,
)
from backend.frameworks.data_access.scoring_setup import pilot_services
from backend.interface_adapters.controllers.assessments import validate_payload
from backend.interface_adapters.policy_review import PolicyScoring
from tests.scoring_fixtures import approved_guideline, events, scoring_request


def approved(key, identifier="7"):
    return {
        **approved_guideline(key, identifier),
        "version": "review-11",
        "title": GUIDELINES[key].title,
    }


@pytest.fixture
def case():
    service, _ = pilot_services(None, Settings(app_env="test"))
    cases = {}
    scorer = PolicyScoring(service.adapter, cases)
    request = scoring_request(
        {
            "id": "101",
            "transcript_version": "transcript-v1",
            "events": events(
                [
                    ("customer", "Can you waive my shipping fee?"),
                    ("agent", "I can get that started for you."),
                    ("action", "Order lookup is in progress ..."),
                ]
            ),
        },
        [approved(SHIPPING_FEE)],
        as_of="2026-11-23",
        scope="northwind",
        canonical={"conversations": [{"id": "9055", "split": "train"}]},
    )
    reply = {
        "category": "shipping",
        "request_turns": [1],
        "checks": [
            {
                "id": key,
                "outcome": "unresolved",
                "turns": [1, 2, 3],
                "references": [],
                "reason": "More evidence is needed.",
                "policy_gap": "",
            }
            for key in scorer.templates
        ],
    }
    entry = {
        "binding": scorer.binding(request),
        "proposal": deepcopy(reply),
        "review": deepcopy(reply),
    }
    cases["101"] = entry
    return service, scorer, request, entry


def set_answer(entry, rule, **changes):
    for phase in ("proposal", "review"):
        check = next(row for row in entry[phase]["checks"] if row["id"] == rule)
        check.update(changes)


def check(report, rule):
    return next(
        c
        for row in report["categories"]
        for c in row["scoring"]["checks"]
        if c["rule_id"] == rule
    )


def test_distinct_citation_ids_and_locally_calculated_midpoint(case):
    service, scorer, request, entry = case
    payload, schema = scorer.task(request)
    assert payload["layer1"][0]["id"] == "policy:7"
    assert schema["properties"]["checks"]["items"]["properties"]["references"]["items"][
        "enum"
    ] == ["policy:7"]
    set_answer(entry, "completeness.direct_response", outcome="supported", turns=[1, 2])
    report = scorer.analyse(request)
    validate_payload(
        request, scorer.parse(request, report), policy=service.percentage_policy
    )
    target = check(report, "completeness.direct_response")
    assert target["earned"] == target["maximum"]
    assert [citation["quote"] for citation in target["citations"]] == [
        "Can you waive my shipping fee?",
        "I can get that started for you.",
    ]
    assert report["overall"]["coverage"] > 0
    assert report["overall"]["score"] is None
    assert check(report, "procedure.actions")["earned"] is None
    assert (
        next(row for row in report["categories"] if row["category"] == "procedure")[
            "scoring"
        ]["score"]
        is None
    )


@pytest.mark.parametrize(
    "rule,refs",
    [
        ("procedure.actions", ["policy:7"]),
        ("answer-support.facts", ["policy:7"]),
        ("answer-support.values", []),
    ],
)
def test_model_agreement_cannot_replace_local_policy_proof(case, rule, refs):
    _, scorer, request, entry = case
    set_answer(entry, rule, outcome="supported", references=refs)
    result = check(scorer.analyse(request), rule)
    assert result["outcome"] == "unresolved"
    assert result["earned"] is None


@pytest.mark.parametrize(
    "change",
    [
        {"status": "pending"},
        {"version": "review-12"},
        {"draft_conversation_ids": ["101"]},
    ],
)
def test_pending_stale_or_self_referential_guidance_invalidates_review(case, change):
    _, scorer, request, _ = case
    newer = replace(request, references=[{**request.references[0], **change}])
    with pytest.raises(AnalysisUnavailableError, match="current transcript"):
        scorer.analyse(newer)


def test_fabricated_reference_rejected_and_unmatched_review_is_unresolved(case):
    _, scorer, request, entry = case
    set_answer(entry, "answer-support.values", references=["policy:999"])
    with pytest.raises(AnalysisUnavailableError, match="usable assessment"):
        scorer.analyse(request)
    set_answer(entry, "answer-support.values", references=[])
    set_answer(entry, "completeness.direct_response", outcome="supported")
    next(
        row
        for row in entry["review"]["checks"]
        if row["id"] == "completeness.direct_response"
    )["outcome"] = "breach"
    assert (
        check(scorer.analyse(request), "completeness.direct_response")["outcome"]
        == "unresolved"
    )


def test_generic_reference_does_not_prove_same_category_scenario(case):
    _, scorer, request, entry = case
    request = replace(request, references=[approved(OVERNIGHT)])
    entry["binding"] = scorer.binding(request)
    set_answer(
        entry, "answer-support.facts", outcome="supported", references=["policy:7"]
    )
    assert (
        check(scorer.analyse(request), "answer-support.facts")["outcome"]
        == "unresolved"
    )


def test_publisher_policy_can_be_used_only_after_approval(case):
    service, scorer, request, entry = case
    key = "layer2-abc-site-search-troubleshooting-v1"
    request = replace(
        request,
        conversation={
            **request.conversation,
            "events": events(
                [
                    ("customer", "The search bar isn't working."),
                    ("agent", "Please clear your browser cookies."),
                ]
            ),
        },
        references=[{**approved(key), "status": "pending"}],
    )
    entry["binding"] = scorer.binding(request)
    for step in ("proposal", "review"):
        entry[step]["category"] = "website"
        for item in entry[step]["checks"]:
            item["turns"] = [1, 2]
    rule = "answer-support.facts"
    assert check(scorer.analyse(request), rule)["outcome"] == "unresolved"

    request = replace(request, references=[approved(key)])
    entry["binding"] = scorer.binding(request)
    set_answer(entry, rule, outcome="supported", references=["policy:7"])
    report = scorer.analyse(request)
    validate_payload(
        request, scorer.parse(request, report), policy=service.percentage_policy
    )
    assert check(report, rule)["outcome"] == "supported"
    assert check(report, rule)["citations"][-1]["reference_version"] == "review-11"


def verified_cart_review(case, reply="Please sign out and back in.", *, later=()):
    service, scorer, request, entry = case
    request = replace(
        request,
        conversation={
            **request.conversation,
            "events": events(
                [
                    ("customer", "My cart is not updating."),
                    ("agent", reply),
                    *later,
                ]
            ),
        },
        references=[approved("layer2-abc-cart-v1")],
    )
    rule = "answer-support.facts"
    for phase in ("proposal", "review"):
        entry[phase]["category"] = "website"
        for item in entry[phase]["checks"]:
            item["turns"] = [1, 2]
    set_answer(entry, rule, outcome="supported", references=["policy:7"])
    entry["binding"] = scorer.binding(request)
    binding, *_ = scorer.evidence_task(request, entry["proposal"], entry["review"])
    proof = {
        "check": rule,
        "outcome": "supported",
        "policy": "7",
        "policy_line": "Instruct the customer to log out of their account and log back in.",
        "request": {"turn": 1, "quote": "My cart is not updating."},
        "observations": [{"turn": 2, "quote": reply}],
        "use": "general-guidance",
        "condition_facts": [],
        "reason": "Signing out and back in is an approved option for a cart that does not update.",
    }
    entry["policy_evidence"] = {"binding": binding, "proofs": [proof]}
    return service, scorer, request, entry, proof


def test_independent_policy_review_can_verify_paraphrased_advice(case):
    service, scorer, request, _, proof = verified_cart_review(
        case, "You could exit your account and then sign back in."
    )
    report = scorer.analyse(request)
    validate_payload(
        request, scorer.parse(request, report), policy=service.percentage_policy
    )
    result = check(report, "answer-support.facts")
    assert result["outcome"] == "supported"
    assert result["explanation"] == proof["reason"]
    assert [
        c["turn_id"] for c in result["citations"] if c["kind"] == "conversation"
    ] == [1, 2]
    assert result["citations"][-1]["reference_version"] == "review-11"


@pytest.mark.parametrize(
    "reply",
    ["Do not sign out and back in.", "My name is Jamie. Have a nice day."],
    ids=["contradicts-policy", "unrelated"],
)
def test_policy_review_cannot_score_from_an_unsupporting_reply(case, reply):
    service, scorer, request, _, proof = verified_cart_review(case, reply)

    report = scorer.analyse(request)
    validate_payload(
        request, scorer.parse(request, report), policy=service.percentage_policy
    )
    finding = check(report, proof["check"])
    assert finding["outcome"] == "unresolved"
    assert all(c["kind"] != "reference" for c in finding["citations"])


def test_policy_review_must_cite_the_reply_that_actually_supports_the_score(case):
    _, scorer, request, _, proof = verified_cart_review(
        case,
        "I'm happy to help.",
        later=[("agent", "Please sign out and back in.")],
    )
    finding = check(scorer.analyse(request), proof["check"])

    assert finding["outcome"] == "supported"
    assert [
        c["turn_id"] for c in finding["citations"] if c["kind"] == "conversation"
    ] == [1, 3]


@pytest.mark.parametrize(
    "alteration", ["quote", "source", "binding", "duplicate", "agent-as-fact"]
)
def test_local_gate_rejects_invalid_policy_proofs(case, alteration):
    _, scorer, request, entry, proof = verified_cart_review(
        case, "You could exit your account and then sign back in."
    )
    if alteration == "quote":
        proof["observations"][0]["quote"] = "Invented advice."
    elif alteration == "source":
        proof["policy_line"] = "A policy line that does not exist."
    elif alteration == "binding":
        entry["policy_evidence"]["binding"] = "stale-snapshot"
    elif alteration == "duplicate":
        entry["policy_evidence"]["proofs"].append(dict(proof))
    else:
        proof.update(use="case-fact", condition_facts=proof["observations"])
    report_with_bad_proof = scorer.analyse(request)
    entry.pop("policy_evidence")
    assert report_with_bad_proof == scorer.analyse(request)


def test_cart_policy_allows_either_approved_option():
    from backend.interface_adapters.guideline_checks import cart

    for reply in (
        "Please sign out and back in.",
        "Please refresh the page and try adding the item to the cart again.",
    ):
        finding = cart(
            events([("customer", "My cart is not updating."), ("agent", reply)])
        )
        assert finding["answer-support.facts"][0] == "supported"
    assert not cart(
        events(
            [
                ("customer", "My cart is not updating."),
                ("agent", "Do not sign out and back in."),
            ]
        )
    )
