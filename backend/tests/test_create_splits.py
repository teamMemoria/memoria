import json
from pathlib import Path

import pytest

from backend.data.create_splits import (
    ConversationRecord,
    build_manifests,
    create_splits,
    format_coverage,
    write_manifests,
)

BACKEND_DIR = Path(__file__).resolve().parents[1]


def corpus():
    records = []
    hvb_topics = ("Balance", "Bills", "Cards", "Transfers")
    for agent_index in range(10):
        for conversation_index in range(10):
            records.append(
                ConversationRecord(
                    conversation_id=f"HVB-{agent_index:02d}-{conversation_index:02d}",
                    dataset="HarperValleyBank",
                    topic=hvb_topics[
                        (agent_index + conversation_index) % len(hvb_topics)
                    ],
                    agent_id=f"hvb-agent-{agent_index:02d}",
                )
            )

    for topic_index in range(10):
        for conversation_index in range(10):
            records.append(
                ConversationRecord(
                    conversation_id=f"ABCD-{topic_index:02d}-{conversation_index:02d}",
                    dataset="ABCD",
                    topic=f"Topic {topic_index:02d}",
                    agent_id="abcd-unknown-agent",
                )
            )
    return records


def ids(records):
    return {record.conversation_id for record in records}


def test_split_is_reproducible_and_uses_every_conversation_once():
    records = corpus()

    first = create_splits(records, development_ratio=0.7, seed=43)
    second = create_splits(list(reversed(records)), development_ratio=0.7, seed=43)

    assert first == second
    assert ids(first.development).isdisjoint(ids(first.evaluation))
    assert ids(first.development) | ids(first.evaluation) == ids(records)


def test_split_has_expected_dataset_counts_and_topic_coverage():
    split = create_splits(corpus(), development_ratio=0.7, seed=43)

    for partition, expected in ((split.development, 70), (split.evaluation, 30)):
        assert sum(record.dataset == "ABCD" for record in partition) == expected
        assert (
            sum(record.dataset == "HarperValleyBank" for record in partition)
            == expected
        )

    for dataset in ("ABCD", "HarperValleyBank"):
        all_topics = {record.topic for record in corpus() if record.dataset == dataset}
        assert {
            record.topic for record in split.development if record.dataset == dataset
        } == all_topics
        assert {
            record.topic for record in split.evaluation if record.dataset == dataset
        } == all_topics


def test_identified_hvb_agents_never_cross_splits():
    split = create_splits(corpus(), development_ratio=0.7, seed=43)

    development_agents = {
        record.agent_id
        for record in split.development
        if record.dataset == "HarperValleyBank"
    }
    evaluation_agents = {
        record.agent_id
        for record in split.evaluation
        if record.dataset == "HarperValleyBank"
    }

    assert development_agents.isdisjoint(evaluation_agents)
    assert len(development_agents) == 7
    assert len(evaluation_agents) == 3


def test_seed_is_configurable_and_changes_tied_assignments():
    first = create_splits(corpus(), development_ratio=0.7, seed=43)
    second = create_splits(corpus(), development_ratio=0.7, seed=44)

    assert ids(first.evaluation) != ids(second.evaluation)


def test_manifests_contain_ids_configuration_and_coverage_only():
    manifests = build_manifests(
        create_splits(corpus(), development_ratio=0.7, seed=43),
        development_ratio=0.7,
        seed=43,
    )

    assert set(manifests) == {"development", "evaluation"}
    assert manifests["development"]["seed"] == 43
    assert manifests["development"]["development_ratio"] == 0.7
    assert manifests["development"]["conversation_ids"] == sorted(
        manifests["development"]["conversation_ids"]
    )
    assert manifests["evaluation"]["coverage"]["total"] == 60
    assert set(manifests["evaluation"]["coverage"]["datasets"]) == {
        "ABCD",
        "HarperValleyBank",
    }
    assert "transcript" not in json.dumps(manifests).lower()


def test_manifest_serialization_is_byte_identical(tmp_path):
    split = create_splits(corpus(), development_ratio=0.7, seed=43)
    manifests = build_manifests(split, development_ratio=0.7, seed=43)

    write_manifests(manifests, tmp_path)
    first = {name: (tmp_path / f"{name}.json").read_bytes() for name in manifests}
    write_manifests(manifests, tmp_path)

    assert {
        name: (tmp_path / f"{name}.json").read_bytes() for name in manifests
    } == first


def test_committed_manifests_match_the_default_configuration():
    development = json.loads((BACKEND_DIR / "splits/development.json").read_text())
    evaluation = json.loads((BACKEND_DIR / "splits/evaluation.json").read_text())

    development_ids = set(development["conversation_ids"])
    evaluation_ids = set(evaluation["conversation_ids"])
    assert development["seed"] == evaluation["seed"] == 43
    assert development["development_ratio"] == evaluation["development_ratio"] == 0.7
    assert len(development_ids) == development["coverage"]["total"] == 140
    assert len(evaluation_ids) == evaluation["coverage"]["total"] == 60
    assert development_ids.isdisjoint(evaluation_ids)
    assert len(development_ids | evaluation_ids) == 200
    assert {
        dataset: coverage["count"]
        for dataset, coverage in development["coverage"]["datasets"].items()
    } == {"ABCD": 70, "HarperValleyBank": 70}
    assert {
        dataset: coverage["count"]
        for dataset, coverage in evaluation["coverage"]["datasets"].items()
    } == {"ABCD": 30, "HarperValleyBank": 30}


def test_coverage_output_reports_each_dataset_and_topic():
    split = create_splits(corpus(), development_ratio=0.7, seed=43)
    manifests = build_manifests(split, development_ratio=0.7, seed=43)

    output = format_coverage(manifests)

    assert "development: 140 conversations" in output
    assert "evaluation: 60 conversations" in output
    assert "HarperValleyBank: 70" in output
    assert "Cards: 17" in output or "Cards: 18" in output
    assert "ABCD: 30" in output
    assert "Topic 09: 3" in output


@pytest.mark.parametrize("development_ratio", [0, 1, -0.1, 1.1])
def test_ratio_must_leave_data_in_both_splits(development_ratio):
    with pytest.raises(ValueError, match="between 0 and 1"):
        create_splits(corpus(), development_ratio=development_ratio, seed=43)


def test_duplicate_ids_and_missing_required_metadata_are_rejected():
    records = corpus()
    with pytest.raises(ValueError, match="Duplicate conversation ID"):
        create_splits([*records, records[0]], development_ratio=0.7, seed=43)

    invalid = ConversationRecord(
        conversation_id="HVB-invalid",
        dataset="HarperValleyBank",
        topic="",
        agent_id="hvb-agent-99",
    )
    with pytest.raises(ValueError, match="topic"):
        create_splits([*records, invalid], development_ratio=0.7, seed=43)


def test_hvb_requires_at_least_two_identified_agents():
    records = [
        ConversationRecord(
            conversation_id=f"HVB-{index}",
            dataset="HarperValleyBank",
            topic="Cards",
            agent_id="one-agent",
        )
        for index in range(3)
    ]

    with pytest.raises(ValueError, match="at least two identified Agents"):
        create_splits(records, development_ratio=0.7, seed=43)
