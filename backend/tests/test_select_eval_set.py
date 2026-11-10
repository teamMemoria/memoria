import csv
import random
from pathlib import Path

import pytest

from backend.data.select_eval_set import (
    Candidate,
    select_balanced,
    select_eval_set,
    template_columns,
    write_template,
)
from backend.models import FindingCategory, FindingResult


def candidates(dataset: str, n: int, topics: int, agents: int) -> list[Candidate]:
    return [
        Candidate(
            f"{dataset}-{i:04d}",
            dataset,
            f"topic-{i % topics}",
            f"agent-{i % agents}",
            10,
        )
        for i in range(n)
    ]


def test_covers_every_topic_and_agent_when_possible():
    pool = candidates("HVB", 100, topics=8, agents=10)
    picked = select_balanced(pool, 14, random.Random(1))

    assert len(picked) == 14
    assert len(set(picked)) == 14
    assert {c.topic for c in picked} == {c.topic for c in pool}
    assert {c.agent for c in picked} == {c.agent for c in pool}


def test_spreads_extra_picks_across_topics():
    pool = candidates("ABCD", 100, topics=11, agents=1)
    picked = select_balanced(pool, 14, random.Random(1))

    counts = [sum(c.topic == t for c in picked) for t in {c.topic for c in pool}]
    assert max(counts) - min(counts) <= 1


def test_selection_is_reproducible_and_seed_dependent():
    pool = candidates("HVB", 100, 8, 10) + candidates("ABCD", 100, 11, 1)
    assert select_eval_set(pool, 14, seed=31) == select_eval_set(pool, 14, seed=31)
    assert select_eval_set(pool, 14, seed=31) != select_eval_set(pool, 14, seed=32)


def test_selects_per_dataset_within_target_size():
    pool = candidates("HVB", 100, 8, 10) + candidates("ABCD", 100, 11, 1)
    selection = select_eval_set(pool, 14, seed=31)

    assert 25 <= len(selection) <= 30
    assert sum(c.source_dataset == "HVB" for c in selection) == 14
    assert sum(c.source_dataset == "ABCD" for c in selection) == 14


def test_small_pool_returns_everything():
    pool = candidates("HVB", 3, 3, 3)
    assert len(select_balanced(pool, 14, random.Random(1))) == 3


def test_template_has_two_scorer_columns_per_category(tmp_path):
    out = tmp_path / "template.csv"
    write_template(candidates("HVB", 2, 2, 2), out)

    with out.open() as f:
        rows = list(csv.DictReader(f))
    columns = template_columns()
    for category in FindingCategory:
        assert f"{category.value}_scorer1" in columns
        assert f"{category.value}_scorer2" in columns
    assert "disagreement_notes" in columns
    assert [r["curated_id"] for r in rows] == ["HVB-0000", "HVB-0001"]
    # Scores are left for people to fill in.
    assert all(r[f"{c.value}_scorer1"] == "" for r in rows for c in FindingCategory)


def test_template_does_not_replace_an_existing_sheet(tmp_path):
    out = tmp_path / "template.csv"
    out.write_text("recorded scores\n")

    with pytest.raises(FileExistsError):
        write_template(candidates("HVB", 2, 2, 2), out)
    assert out.read_text() == "recorded scores\n"

    write_template(candidates("HVB", 2, 2, 2), out, overwrite=True)
    assert out.read_text().startswith("curated_id,")


def test_rubric_values_match_finding_results():
    rubric = (Path(__file__).parents[1] / "evaluation" / "rubric.md").read_text()
    for result in FindingResult:
        assert f"`{result.value}`" in rubric
    for category in FindingCategory:
        assert f"`{category.value}_*`" in rubric
