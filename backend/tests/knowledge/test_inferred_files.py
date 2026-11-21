"""Inferred knowledge (Layer 2): reading claims, the JSON store, the CLI and the test."""

from __future__ import annotations

import ast
import copy
import json
from pathlib import Path

import pytest

from backend.entities.inferred_knowledge import (
    FactClaim,
    Override,
    apply_overrides,
    build_knowledge_base,
)
from backend.services.knowledge import __main__ as cli
from backend.services.knowledge.fact_claims import (
    ConversationClaimSource,
    claims_from_drafts,
    claims_from_text,
)
from backend.services.knowledge.inferred_evaluation import answer_key, evaluate_inferred
from backend.services.knowledge.knowledge_base_files import (
    JsonKnowledgeBaseStore,
    knowledge_base_from_dict,
    knowledge_base_to_dict,
)

COMPANY = "acme-test"
PROMO_ANSWER = "Promo codes are only valid for 7 days after they are issued."


def synthetic_call(n, answer, subflow="promo_code_invalid", record=None, action=None):
    cid = f"SYN-L2-{n:04d}"
    return {
        "id": cid,
        "source": {
            "dataset": "SYNTHETIC",
            "original_id": cid,
            "licence": "MIT (this repository)",
            "url": "",
            "citation": "Made-up conversation written for tests. Not real call data.",
        },
        "customer_record": record or {},
        "modifications": [],
        "channel": "chat",
        "turns": [
            {"n": 1, "speaker": "agent", "text": "Hello, how can I help you today?"},
            {
                "n": 2,
                "speaker": "customer",
                "text": "My promo code is not working when I use it.",
            },
            {"n": 3, "speaker": "agent", "text": answer},
            {
                "n": 4,
                "speaker": "system_action",
                "text": action or "A promo code has been created.",
            },
            {
                "n": 5,
                "speaker": "agent",
                "text": "Is there anything else I can help with?",
            },
        ],
        "source_fields": {
            "flow": "purchase_dispute",
            "subflow": subflow,
            "actions_taken": ["promo-code"],
        },
    }


# ---------------------------------------------------------- reading claims


def test_values_are_normalised_and_levels_kept_out_of_the_subject():
    (a,) = claims_from_text(
        "It is $2.00 per day past the deadline.", COMPANY, "c", "policy_4"
    )
    (b,) = claims_from_text("Late payments cost $2 per day.", COMPANY, "c", "policy_4")
    assert a.value == b.value == "2 usd"
    (c,) = claims_from_text("Promo codes last one week.", COMPANY, "c", "x")
    assert c.value == "7 days" and "week" not in c.subject
    (d,) = claims_from_text(
        "Bronze members can return within 90 days.", COMPANY, "c", "x"
    )
    assert d.levels == {"bronze"} and not {"bronze", "bronz", "member"} & d.subject
    (e,) = claims_from_text("The total is $1234567.", COMPANY, "c", "x")
    assert e.value == "1234567 usd"
    assert claims_from_text("Let me check that for you.", COMPANY, "c", "x") == []


def test_system_action_passages_are_skipped():
    draft = {
        "source": {"source_key": "ABCD:1"},
        "scope": {"subflow": "refund_initiate"},
        "answer_passages": [
            {"speaker": "system_action", "quote": "A refund of $50 has been issued."},
            {"speaker": "agent", "quote": "The refund is $40."},
        ],
    }
    assert [c.value for c in claims_from_drafts([draft], COMPANY)] == ["40 usd"]


def test_values_in_system_actions_never_become_claims_end_to_end():
    record = synthetic_call(
        1,
        "I have issued a brand new code for you right now.",
        action="A promo code for 20% off has been created, valid for 7 days.",
    )
    assert ConversationClaimSource([record]).claims(COMPANY) == []


def test_claims_come_from_masked_agent_speech_and_repeats_count_once():
    record = {"customer_name": "Joseph Banter", "email": "joe@example.com"}
    first = synthetic_call(
        1,
        "Thanks Joseph, our promo codes are only valid for 7 days after they are issued.",
        record=record,
    )
    second = synthetic_call(
        2, "Our promotional codes last one week from the day they are sent."
    )
    claims = ConversationClaimSource([first, first, second]).claims(COMPANY)
    assert [(c.call_id, c.value) for c in claims] == [
        ("SYNTHETIC:SYN-L2-0001", "7 days"),
        ("SYNTHETIC:SYN-L2-0002", "7 days"),
    ]
    assert claims[0].quote.startswith("Thanks [CUSTOMER_NAME],")


def test_two_different_records_for_one_call_are_both_dropped():
    a = synthetic_call(1, PROMO_ANSWER)
    b = synthetic_call(
        1, "Promo codes are only valid for 30 days after they are issued."
    )
    for order in ([a, b], [b, a]):
        source = ConversationClaimSource(order)
        assert source.claims(COMPANY) == []
        assert source.failures[0]["errors"][0]["code"] == "duplicate_call_differs"


def test_bad_conversations_are_skipped_and_named():
    source = ConversationClaimSource(
        [{"id": "broken"}, synthetic_call(1, PROMO_ANSWER)]
    )
    assert len(source.claims(COMPANY)) == 1
    assert source.failures[0]["conversation"] == "broken" and source.calls_read == 1


def test_learning_code_never_imports_the_guidelines():
    root = Path(__file__).resolve().parents[2] / "src" / "backend"
    for path in (
        root / "entities" / "inferred_knowledge.py",
        root / "use_cases" / "inferred_knowledge.py",
        root / "services" / "knowledge" / "fact_claims.py",
    ):
        modules = {
            node.module or ""
            for node in ast.walk(ast.parse(path.read_text(encoding="utf-8")))
            if isinstance(node, ast.ImportFrom)
        }
        assert not any("verification" in m or "references" in m for m in modules), path


# --------------------------------------------------------------------- store


def full_knowledge_base():
    def claims(values, subject, start, levels=frozenset()):
        return [
            FactClaim(
                COMPANY, f"c{start + i}", "policy_1", v, subject, levels, f"It is {v}."
            )
            for i, v in enumerate(values)
        ]

    data = claims(["30 days"] * 10, frozenset({"return"}), 0, frozenset({"gold"}))
    data += claims(["7 days"] * 6 + ["14 days"] * 5, frozenset({"promo"}), 100)
    data += claims(["4.99 usd"] * 10, frozenset({"wrap"}), 200)
    data += claims(["8 usd"] * 3, frozenset({"ship"}), 300)
    kb = build_knowledge_base(COMPANY, data)
    wrap = next(r for r in kb.rules if r.value == "4.99 usd").topic.topic_id
    promo = kb.conflicts[0].topic.topic_id
    return apply_overrides(
        kb,
        [
            Override(promo, "14 days", "m", "New policy"),
            Override(wrap, None, "m", "Not ours"),
            Override("gone", "1 days", "m", "Old"),
        ],
    )


def test_json_store_round_trips_everything(tmp_path):
    kb = full_knowledge_base()
    assert {r.source for r in kb.rules} == {"inferred", "manager"}
    assert kb.removed and kb.unmatched_overrides and kb.undecided
    store = JsonKnowledgeBaseStore(tmp_path)
    store.save(kb)
    assert store.load(COMPANY) == kb
    assert knowledge_base_from_dict(knowledge_base_to_dict(kb)) == kb
    assert not list(tmp_path.glob(".*"))  # no temporary files left behind


def test_store_keeps_companies_apart(tmp_path):
    store = JsonKnowledgeBaseStore(tmp_path)
    for bad in ("../escape", "acme.overrides", "acme corp"):
        with pytest.raises(ValueError):
            store.load(bad)
    store.save(full_knowledge_base())
    (tmp_path / "other.json").write_text((tmp_path / f"{COMPANY}.json").read_text())
    with pytest.raises(ValueError):
        store.load("other")


# ----------------------------------------------------------------------- CLI


def run(capsys, *args):
    code = cli.main([str(a) for a in args])
    out = capsys.readouterr().out
    return code, json.loads(out) if out.strip().startswith(("{", "[")) else out


@pytest.fixture
def learned(tmp_path, capsys, monkeypatch):
    monkeypatch.setenv("KNOWLEDGE_DRAFT_THRESHOLD", "10")
    folder = tmp_path / "calls"
    folder.mkdir()
    for n in range(10):
        (folder / f"{n}.json").write_text(json.dumps(synthetic_call(n, PROMO_ANSWER)))
    store = tmp_path / "kb"
    code, summary = run(capsys, "infer", folder, "--company", COMPANY, "--store", store)
    assert code == 0 and summary["counts"]["rules"] == 1 and summary["calls_read"] == 10
    return folder, store


def test_command_line_learns_overrides_and_scores(learned, tmp_path, capsys):
    folder, store = learned
    other = tmp_path / "other.json"
    other.write_text(
        json.dumps(
            synthetic_call(
                99, "Our promo codes are good for 30 days after they are sent."
            )
        )
    )
    code, scored = run(capsys, "score", other, "--company", COMPANY, "--store", store)
    assert (
        code == 0
        and scored["score"] == 0.0
        and scored["checked"][0]["rule_value"] == "7 days"
    )

    topic = json.loads((store / f"{COMPANY}.json").read_text())["rules"][0]["topic"][
        "topic_id"
    ]
    code, out = run(
        capsys, "override", "--company", COMPANY, "--store", store, "--topic", topic,
        "--value", "one month", "--by", "m", "--reason", "New policy",
    )  # fmt: skip
    assert (
        code == 1 and out["errors"][0]["code"] == "invalid_input"
    )  # "1 months" isn't days
    code, out = run(
        capsys, "override", "--company", COMPANY, "--store", store, "--topic", topic,
        "--value", "thirty days", "--by", "m", "--reason", "New policy",
    )  # fmt: skip
    assert code == 0 and out["value"] == "30 days"
    run(capsys, "infer", folder, "--company", COMPANY, "--store", store)
    code, scored = run(capsys, "score", other, "--company", COMPANY, "--store", store)
    assert scored["score"] == 1.0


@pytest.mark.parametrize(
    "args",
    [
        [
            "override",
            "--company",
            COMPANY,
            "--topic",
            "typo",
            "--value",
            "7 days",
            "--by",
            "m",
            "--reason",
            "r",
        ],
        [
            "override",
            "--company",
            COMPANY,
            "--topic",
            "t",
            "--value",
            "",
            "--by",
            "m",
            "--reason",
            "r",
        ],
        [
            "override",
            "--company",
            COMPANY,
            "--topic",
            "t",
            "--remove",
            "--by",
            "m",
            "--reason",
            " ",
        ],
        ["infer", "MISSING", "--company", COMPANY],
        ["infer", "CALLS", "--company", "acme corp"],
    ],
)
def test_command_line_errors_are_reported_not_raised(args, learned, capsys):
    folder, store = learned
    args = [str(folder) if a == "CALLS" else a for a in args] + ["--store", str(store)]
    code, out = run(capsys, *args)
    assert code == 1 and out["status"] == "error"


def test_scoring_before_learning_and_unreadable_calls_fail_cleanly(tmp_path, capsys):
    call = tmp_path / "call.json"
    call.write_text(json.dumps(synthetic_call(1, PROMO_ANSWER)))
    code, out = run(
        capsys, "score", call, "--company", COMPANY, "--store", tmp_path / "none"
    )
    assert code == 1 and out["status"] == "error"
    broken = tmp_path / "broken.json"
    broken.write_text(json.dumps({"id": "broken"}))
    code, out = run(
        capsys, "score", broken, "--company", COMPANY, "--store", tmp_path / "none"
    )
    assert code == 1 and out["failures"][0]["conversation"] == "broken"


def test_a_run_with_nothing_to_learn_keeps_the_old_knowledge_base(
    learned, tmp_path, capsys
):
    _, store = learned
    empty = tmp_path / "empty.json"
    empty.write_text(
        json.dumps(synthetic_call(50, "Let me look into that for you right away."))
    )
    code, out = run(capsys, "infer", empty, "--company", COMPANY, "--store", store)
    assert code == 1 and out["status"] == "error"
    assert json.loads((store / f"{COMPANY}.json").read_text())["version"] == 1


# ---------------------------------------------------------------- evaluation


def test_answer_key_reads_values_and_levels_from_guideline_passages():
    snapshot = {
        "passages": [
            {
                "reference_id": "a",
                "text": "Promotions only last 7 days.",
                "scope": {"subflow": "p"},
            },
            {"reference_id": "b", "text": "Say thanks.", "scope": {"subflow": "p"}},
            {
                "reference_id": "c",
                "text": "It costs $8.",
                "scope": {"subflow_prefix": "ship_"},
            },
            {
                "reference_id": "d",
                "text": "Gold members: 30 days",
                "scope": {"subflow": "p"},
            },
        ]
    }
    key = answer_key(snapshot, ["p", "ship_cost", "other"])
    assert {k: [(i["value"], i["levels"]) for i in v] for k, v in key.items()} == {
        "p": [("7 days", []), ("30 days", ["gold"])],
        "ship_cost": [("8 usd", [])],
    }


def evaluation_inputs():
    wrong = "Gift wrapping costs $4.99 per item, which is a flat fee."
    dump = {
        "train": [synthetic_call(n, PROMO_ANSWER) for n in range(10)]
        + [synthetic_call(100 + n, wrong) for n in range(10)],
        "dev": [],
        "test": [
            synthetic_call(500, PROMO_ANSWER),
            synthetic_call(
                501, "Promo codes are only valid for 30 days after they are issued."
            ),
        ],
    }
    snapshot = {
        "snapshot_id": "test",
        "passages": [
            {
                "reference_id": "a",
                "text": "Codes last 7 days.",
                "scope": {"subflow": "promo_code_invalid"},
            },
            {
                "reference_id": "b",
                "text": "The fee is $3.",
                "scope": {"subflow": "promo_code_invalid"},
            },
        ],
    }
    return dump, snapshot


def test_evaluation_measures_precision_recall_and_growth():
    dump, snapshot = evaluation_inputs()
    report = evaluate_inferred(dump, snapshot, sizes=(10,))
    final = report["final"]
    assert report["guidelines_used_for_learning"] is False
    assert (final["rules"], final["correct_rules"], final["checkable_rules"]) == (
        2,
        1,
        2,
    )
    assert final["precision"] == 0.5 and final["recall"] == 0.5
    assert final["values_said_in_train"] == 1 and final["recall_of_said"] == 1.0
    assert [row["rules"] for row in report["growth"]] == [1, 2]
    held = report["held_out"]
    assert (held["values_matching_a_rule"], held["values_differing_from_a_rule"]) == (
        1,
        1,
    )


def test_what_is_learned_does_not_change_when_the_guidelines_change():
    dump, snapshot = evaluation_inputs()
    changed = copy.deepcopy(snapshot)
    for passage in changed["passages"]:
        passage["text"] = "Promotions last 99 days and cost $1."
    learned = [
        [
            (r["category"], r["value"], r["share"])
            for r in evaluate_inferred(dump, s)["rules"]
        ]
        for s in (snapshot, changed)
    ]
    assert learned[0] == learned[1] and learned[0]
