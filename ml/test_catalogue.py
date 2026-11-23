"""Regressions for shared checklist arithmetic and product context."""

import json
from copy import deepcopy
from pathlib import Path

import pytest
from ml.metrics.prepare import (
    catalogue,
    category_entries,
    expand_category,
    expand_common,
    faq_question,
)
from ml.metrics.score import score_checks


@pytest.fixture
def templates():
    folder = Path(__file__).with_name("metric_categories")
    common = expand_common(json.loads((folder / "common.json").read_text()))
    index = json.loads((folder / "catalog.json").read_text())
    categories = [
        expand_category(
            common,
            index["category_defaults"],
            json.loads((folder / row["file"]).read_text()),
        )
        for row in category_entries(index)
    ]
    return common, categories


def test_compact_category_defaults_and_overrides(templates):
    _, categories = templates
    shipping = next(c for c in categories if c["id"] == "shipping")
    checks = shipping["metrics"]["completeness"]["checks"]
    assert checks[0]["category_condition"] == checks[2]["category_condition"]
    assert checks[1]["category_condition"] != checks[0]["category_condition"]
    assert checks[0]["id"] == "shipping.completeness.direct_response"
    shipping["approval"]["status"] = "changed"
    assert all(
        c["approval"]["status"] == "pending" for c in categories if c is not shipping
    )


@pytest.mark.parametrize("conditions", [{}, {"unknown": "unsupported"}])
def test_compact_category_rejects_unusable_conditions(templates, conditions):
    common, _ = templates
    with pytest.raises(ValueError, match="[Cc]ategory condition"):
        expand_category(common, {}, {"id": "shipping", "check_conditions": conditions})


def test_draft_catalogue_rejects_modified_points(templates):
    common, categories = templates
    config = catalogue(common, categories)
    assert len(config["categories"]) == 14
    assert config["weight_profile"]["approval"]["status"] == "pending"
    checks = categories[0]["metrics"]["procedure"]["checks"]
    checks[0]["points"] = (
        common["check_templates"][checks[0]["template"]]["part_points"] - 5
    )
    with pytest.raises(ValueError, match="point allocation"):
        catalogue(common, categories)


def test_shared_points_preserve_normalized_categories_and_review_version(templates):
    common, categories = templates
    explicit = deepcopy(categories)
    for category in explicit:
        for metric in category["metrics"].values():
            for check in metric["checks"]:
                assert "points" not in check
                check["points"] = common["check_templates"][check["template"]][
                    "part_points"
                ]
    assert catalogue(common, categories) == catalogue(common, explicit)
    assert "points" not in categories[0]["metrics"]["procedure"]["checks"][0]


@pytest.mark.parametrize("invalid", [None, False, 24, 25.0, -10, 105])
def test_catalogue_rejects_invalid_weights(templates, invalid):
    common, categories = templates
    profile = next(category for category in categories if category["id"] == "unclear")
    profile["weights"]["procedure"] = invalid
    with pytest.raises(ValueError, match="totaling 100"):
        catalogue(common, categories)


def test_changing_weights_preserves_transcript_review_version(templates):
    common, categories = templates
    before = catalogue(common, categories)["version"]
    weights = categories[0]["weights"]
    weights["procedure"] += 5
    weights["answer-support"] -= 5
    assert catalogue(common, categories)["version"] == before


def test_scoring_excludes_inapplicable_points_and_preserves_missing_evidence():
    checks = [
        {"maximum": 50, "outcome": "supported"},
        {"maximum": 30, "outcome": "unresolved"},
        {"maximum": 20, "outcome": "not-applicable"},
    ]
    score = score_checks(checks)
    assert score["score"] == 81.25
    assert score["earned"] == 50
    assert score["possible"] == 80
    assert score["coverage"] == 62.5
    checks[1]["outcome"] = "breach"
    assert score_checks(checks)["score"] == 62.5


@pytest.mark.parametrize(
    ("outcome", "score", "coverage"),
    [
        ("unresolved", None, 0),
        ("not-applicable", None, None),
        ("supported", 100, 100),
        ("breach", 0, 100),
    ],
)
def test_actual_score_and_evidence_coverage(outcome, score, coverage):
    result = score_checks([{"maximum": 30, "outcome": outcome}])
    assert (result["score"], result["coverage"]) == (score, coverage)
    assert result["earned"] == (30 if outcome == "supported" else 0)


def test_failed_processing_cannot_produce_a_score():
    with pytest.raises(ValueError):
        score_checks([{"maximum": 100, "outcome": "processing-error"}])


@pytest.mark.parametrize(
    ("prefix", "question", "expected"),
    [
        (["I need information about this jacket."], "What is it made from?", [1, 2]),
        ([], "What material is this jacket made from?", [1]),
        ([], "What is it made from?", None),
        (
            ["I need information about this jacket.", "Never mind, I want a shirt."],
            "What is it made from?",
            None,
        ),
        (
            ["I need information about this jacket.", "The agent said:"],
            "What is it made from?",
            None,
        ),
    ],
)
def test_faq_request_links_product_across_turns(prefix, question, expected):
    events = [
        {"speaker": "customer", "text": text, "turn_id": position}
        for position, text in enumerate([*prefix, question], start=1)
    ]
    opened = {
        "speaker": "action",
        "text": "Searching the FAQ pages ...",
        "turn_id": len(events) + 1,
    }
    evidence = faq_question([*events, opened], opened, "jacket")
    assert (
        None if evidence is None else [turn["turn_id"] for turn in evidence]
    ) == expected
