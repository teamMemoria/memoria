"""setup-demo runs the documented data steps in order; each step has its own tests."""

import sys
from pathlib import Path

import pytest

from backend.data import (
    assign_synthetic_dates,
    assign_topics,
    import_conversations,
    seed_demo_profiles,
    seed_policies,
    setup_demo,
)


@pytest.fixture
def steps(monkeypatch):
    called = []

    def record(name):
        async def step(*args):
            called.append((name, args))

        return step

    monkeypatch.setattr(import_conversations, "run", record("import"))
    monkeypatch.setattr(assign_topics, "run", record("topics"))
    monkeypatch.setattr(assign_synthetic_dates, "run", record("dates"))
    monkeypatch.setattr(seed_demo_profiles, "run", record("profiles"))
    monkeypatch.setattr(seed_policies, "run", record("policies"))
    return called


@pytest.fixture
def conversations(tmp_path):
    (tmp_path / "C1.json").write_text("{}")
    return tmp_path


def run_main(monkeypatch, *args):
    monkeypatch.setattr(sys, "argv", ["setup-demo", *args])
    setup_demo.main()


def test_runs_every_step_in_the_documented_order(monkeypatch, steps, conversations):
    run_main(monkeypatch, str(conversations), "--organization", "acme")
    assert steps == [
        ("import", (conversations, "acme")),
        ("topics", (assign_topics.DEFAULT_MAPPING, "acme")),
        (
            "dates",
            (
                assign_synthetic_dates.DEFAULT_START,
                assign_synthetic_dates.DEFAULT_WEEKS,
                assign_synthetic_dates.DEFAULT_SEED,
                "acme",
            ),
        ),
        ("profiles", ("acme",)),
        ("policies", ("acme",)),
    ]


def test_the_directory_can_come_from_the_environment(monkeypatch, steps, conversations):
    monkeypatch.setenv("MEMORIA_CONVERSATIONS_DIR", str(conversations))
    run_main(monkeypatch)
    assert steps[0] == ("import", (conversations, "default"))


def test_defaults_to_the_docs_repo_next_to_this_one(monkeypatch):
    monkeypatch.delenv("MEMORIA_CONVERSATIONS_DIR", raising=False)
    repo = Path(__file__).resolve().parents[2]
    assert setup_demo.conversations_dir(None) == (
        repo.parent / "uoft-ftli-2026-genesys-docs" / "curated" / "conversations"
    )


@pytest.mark.parametrize("make", [lambda p: p / "missing", lambda p: p])
def test_a_missing_or_empty_directory_stops_before_any_step(
    monkeypatch, steps, tmp_path, make
):
    # An empty folder is what Docker mounts when the docs repo is not there.
    with pytest.raises(SystemExit, match="Conversations not found"):
        run_main(monkeypatch, str(make(tmp_path)))
    assert steps == []
