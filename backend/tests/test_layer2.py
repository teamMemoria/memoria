"""Layer 2: the 70% rule, conflicts and reading values from calls."""

import random

import backend.data.layer2_evaluation as evaluation
from backend.data.layer2_evaluation import answer_key, evaluate
from backend.data.value_claims import claims, values
from backend.entities.inferred_knowledge import Claim, Settings, learn

SCOPE = ("promo_code_invalid", (), "days")
PROMO = frozenset({"promo", "cod", "valid"})
REFUND = frozenset({"refund", "arriv", "bank"})


def calls(said, start=0, subject=PROMO, scope=SCOPE):
    return [Claim(f"c{start + i}", scope, v, subject) for i, v in enumerate(said)]


def outcomes(claims_):
    return sorted(
        (t.decide(Settings()), t.rule if t.votes() else None) for t in learn(claims_)
    )


def test_70_percent_agreement_makes_a_rule():
    assert outcomes(calls(["7 days"] * 7 + ["30 days"] * 3)) == [("rule", "7 days")]


def test_a_common_split_is_a_conflict_but_a_rare_one_is_not():
    assert outcomes(calls(["7 days"] * 13 + ["30 days"] * 7)) == [
        ("conflict", "7 days")
    ]
    assert outcomes(calls(["7 days"] * 6 + ["30 days"] * 2 + ["14 days"] * 2)) == [
        ("undecided", "7 days")
    ]


def test_minority_answers_dont_make_a_conflict_once_there_is_a_rule():
    assert outcomes(calls(["7 days"] * 15 + ["30 days"] * 5)) == [("rule", "7 days")]


def test_nothing_is_decided_under_10_calls():
    assert outcomes(calls(["7 days"] * 9)) == [("undecided", "7 days")]


def test_a_call_counts_once_and_a_list_of_values_does_not_vote():
    repeated = [Claim("c0", SCOPE, "30 days", PROMO)] * 5
    (topic,) = learn(calls(["7 days"] * 9, start=1) + repeated)
    assert topic.votes() == [("7 days", 9), ("30 days", 1)]
    (listed,) = learn(
        calls(["7 days"] * 10) + calls(["30 days"] * 10)
    )  # same calls, two values
    assert listed.votes() == [] and listed.decide(Settings()) == "undecided"


def test_same_value_can_answer_different_questions_and_scopes_stay_apart():
    refunds = calls(["7 days"] * 10, 100, REFUND) + calls(["5 days"] * 10, 200, REFUND)
    gold = calls(["30 days"] * 10, 300, scope=("promo_code_invalid", ("gold",), "days"))
    assert outcomes(calls(["7 days"] * 10) + refunds + gold) == [
        ("conflict", "5 days"),
        ("rule", "30 days"),
        ("rule", "7 days"),
    ]


def test_each_topic_keeps_its_own_example():
    promo = [Claim(f"p{i}", SCOPE, "7 days", PROMO, "promo") for i in range(10)]
    refund = [Claim(f"r{i}", SCOPE, "7 days", REFUND, "refund") for i in range(10)]
    assert sorted(t.example["7 days"] for t in learn(promo + refund)) == [
        "promo",
        "refund",
    ]


def test_order_of_claims_does_not_matter():
    claims_ = calls(["7 days"] * 8 + ["30 days"] * 2) + calls(
        ["5 days"] * 10, 50, REFUND
    )
    shuffled = random.Random(1).sample(claims_, len(claims_))
    assert outcomes(shuffled) == outcomes(claims_)


def test_reading_values():
    assert values("Promo codes last one week.") == ["7 days"]
    assert values("Gift wrapping is $4.99, or $5.00 for two.") == ["4.99 usd", "5 usd"]
    assert values("It's 20% off, and refunds take 5 business days.") == [
        "20 percent",
        "5 business days",
    ]
    assert values("Let me check that for you.") == []
    assert (
        values("Soak it for half an hour, once a week.") == []
    )  # "a" and "an" aren't numbers


def abcd_call(n, agent_says, action="[Offer promo code]: 20% off for 7 days"):
    return {
        "convo_id": n,
        "scenario": {
            "flow": "purchase_dispute",
            "subflow": "promo_code_invalid",
            "personal": {"customer_name": "joseph banter", "member_level": "gold"},
        },
        "original": [
            ["customer", "My promo code doesn't work."],
            ["agent", agent_says],
            ["action", action],
        ],
    }


def test_only_masked_agent_speech_is_read():
    (claim,) = claims(abcd_call(1, "Sorry Joseph, promo codes only last 7 days."))
    assert claim.value == "7 days" and claim.scope == SCOPE
    assert "Joseph" not in claim.quote and "promo" in claim.subject
    assert (
        claims(abcd_call(2, "I have made you a new code.")) == []
    )  # the action has values


def test_hidden_guidelines_evaluation():
    dump = {"train": [abcd_call(n, "Promo codes only last 7 days.") for n in range(10)]}
    guidelines = {
        "Purchase Dispute": {
            "subflows": {
                "Promo Code Invalid": {
                    "instructions": ["Codes last 7 days."],
                    "actions": [],
                }
            }
        }
    }
    assert answer_key(guidelines) == {"purchase_dispute": [("7 days", set())]}
    report = evaluate(dump, guidelines, sizes=())
    assert "| 10 | 1 | 0 | 1 | 1 |" in report


def test_abcd_files_are_downloaded_once(tmp_path, monkeypatch):
    downloads = []

    def download(url, path):
        downloads.append(url)
        path.write_text("{}")

    monkeypatch.setattr(evaluation, "CACHE", tmp_path)
    monkeypatch.setattr(evaluation.urllib.request, "urlretrieve", download)
    assert evaluation.fetch("guidelines.json").read_text() == "{}"
    evaluation.fetch("guidelines.json")
    assert downloads == [evaluation.ABCD + "guidelines.json"]
