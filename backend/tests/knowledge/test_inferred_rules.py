"""Inferred knowledge (Layer 2): the 70% rule, conflicts, overrides and scoring.

These test the business rules and use cases only, with hand-made claims.
"""

from __future__ import annotations

import random

import pytest

from backend.entities.inferred_knowledge import (
    Conflict,
    FactClaim,
    InferenceSettings,
    InvalidKnowledgeInput,
    Override,
    apply_overrides,
    build_knowledge_base,
    check_override,
    decide,
    score_call,
)
from backend.use_cases.inferred_knowledge import (
    InferKnowledgeBase,
    KnowledgeBaseNotBuilt,
    NoCallsToLearnFrom,
    RecordOverride,
    ScoreCall,
)

COMPANY = "acme-test"
PROMO = frozenset({"promo", "cod", "valid"})
REFUND = frozenset({"refund", "arriv", "bank"})
WRAP = frozenset({"gift", "wrap", "cost", "item"})


def claim(call, value="7 days", subject=PROMO, category="promo_code_invalid", **extra):
    return FactClaim(
        company_id=extra.pop("company_id", COMPANY),
        call_id=f"call-{call}",
        category=category,
        value=value,
        subject=subject,
        quote=extra.pop("quote", f"It is {value}."),
        **extra,
    )


def calls(values, start=0, **extra):
    """One claim per call: values[i] is what call start+i said."""
    return [claim(start + i, value, **extra) for i, value in enumerate(values)]


def only_topic(kb):
    topics = list(kb.topics())
    assert len(topics) == 1, topics
    return topics[0]


# ------------------------------------------------------------------ the policy


def test_value_given_in_70_percent_of_calls_becomes_a_rule():
    kb = build_knowledge_base(COMPANY, calls(["7 days"] * 7 + ["30 days"] * 3))
    assert [(r.value, r.supporting_calls, r.share) for r in kb.rules] == [
        ("7 days", 7, 0.7)
    ]
    assert kb.rules[0].source == "inferred" and not kb.conflicts


def test_just_under_70_percent_is_not_a_rule():
    kb = build_knowledge_base(COMPANY, calls(["7 days"] * 13 + ["30 days"] * 7))  # 65%
    assert not kb.rules
    assert len(kb.conflicts) == 1  # both answers are in 5+ calls: a common conflict


def test_nothing_is_decided_below_the_minimum_calls():
    kb = build_knowledge_base(COMPANY, calls(["7 days"] * 9))
    assert not kb.rules and not kb.conflicts
    assert only_topic(kb).total_calls == 9


def test_split_without_a_common_second_answer_stays_undecided():
    values = (
        ["7 days"] * 6 + ["30 days"] * 2 + ["14 days"] * 2
    )  # 60%, others in 2 calls
    kb = build_knowledge_base(COMPANY, calls(values))
    assert not kb.rules and not kb.conflicts and len(kb.undecided) == 1


def test_minority_answer_does_not_reach_managers_once_a_rule_forms():
    # 75% agree; the other answer is common (5 calls) but a rule still forms.
    kb = build_knowledge_base(COMPANY, calls(["7 days"] * 15 + ["30 days"] * 5))
    assert len(kb.rules) == 1 and not kb.conflicts


def test_a_call_counts_once_however_often_it_repeats_a_value():
    repeated = [claim(0, "30 days")] * 5
    kb = build_knowledge_base(COMPANY, calls(["7 days"] * 9, start=1) + repeated)
    assert only_topic(kb).total_calls == 10
    assert kb.rules[0].supporting_calls == 9


def test_a_call_giving_several_values_for_one_topic_votes_for_none():
    # "Bronze is $500, silver $1000, gold $2000" said in 10 calls: no rule from it.
    levels = frozenset({"bronze", "silver", "gold"})
    subject = frozenset({"spend", "level"})
    claims = [
        claim(n, value, subject=subject, levels=levels)
        for n in range(10)
        for value in ("500 usd", "1000 usd", "2000 usd")
    ]
    kb = build_knowledge_base(COMPANY, claims)
    topic = only_topic(kb)
    assert (topic.total_calls, topic.unclear_calls, topic.answers) == (10, 10, ())
    assert not kb.rules and not kb.conflicts


def test_the_same_value_can_answer_different_questions():
    promo = calls(["7 days"] * 10)
    refund_7 = calls(["7 days"] * 10, 100, subject=REFUND)
    refund_5 = calls(["5 days"] * 10, 200, subject=REFUND)
    kb = build_knowledge_base(COMPANY, promo + refund_7 + refund_5)
    assert [(r.topic.subject[:1], r.value) for r in kb.rules] == [(("cod",), "7 days")]
    assert len(kb.conflicts) == 1  # refunds: 7 vs 5 days
    assert {a.value for a in kb.conflicts[0].topic.answers} == {"5 days", "7 days"}


def test_result_does_not_depend_on_claim_order():
    claims = calls(["7 days"] * 8 + ["30 days"] * 2) + calls(
        ["4.99 usd"] * 10, 50, subject=WRAP
    )
    # The same call and value with different words, which used to depend on order.
    claims += [claim(90, "7 days", subject=REFUND), claim(90, "7 days", subject=PROMO)]
    claims += [claim(91, "7 days", levels=frozenset({"gold"})), claim(91, "7 days")]
    baseline = build_knowledge_base(COMPANY, claims)
    for seed in range(5):
        shuffled = claims[:]
        random.Random(seed).shuffle(shuffled)
        assert build_knowledge_base(COMPANY, shuffled) == baseline


def test_different_units_are_never_one_topic():
    claims = calls(["7 days"] * 10) + calls(["20 percent"] * 10, 200)  # same words
    kb = build_knowledge_base(COMPANY, claims)
    assert sorted(r.value for r in kb.rules) == ["20 percent", "7 days"]


def test_membership_levels_and_categories_are_kept_apart():
    gold = calls(["30 days"] * 10, levels=frozenset({"gold"}))
    guest = calls(["7 days"] * 10, 100, levels=frozenset({"guest"}))
    other = calls(["14 days"] * 10, 200, category="promo_code_out_of_date")
    kb = build_knowledge_base(COMPANY, gold + guest + other)
    assert len(kb.rules) == 3 and not kb.conflicts


def test_companies_never_mix():
    with pytest.raises(InvalidKnowledgeInput):
        build_knowledge_base(COMPANY, calls(["7 days"] * 10, company_id="other"))
    other = build_knowledge_base("other", calls(["7 days"] * 10, company_id="other"))
    with pytest.raises(InvalidKnowledgeInput):
        build_knowledge_base(COMPANY, calls(["7 days"] * 10), previous=other)


def test_thresholds_are_configurable():
    settings = InferenceSettings(agreement_share=0.8, min_calls=4, conflict_calls=2)
    topic = only_topic(
        build_knowledge_base(COMPANY, calls(["7 days"] * 3 + ["1 days"] * 2))
    )
    assert isinstance(decide(topic, settings), Conflict)
    assert decide(topic, InferenceSettings()) is None


@pytest.mark.parametrize(
    "bad",
    [
        {"agreement_share": 0.5},
        {"agreement_share": 1.2},
        {"min_calls": 0},
        {"conflict_calls": 0},
        {"topic_similarity": 0},
    ],
)
def test_settings_are_checked(bad):
    with pytest.raises(InvalidKnowledgeInput):
        InferenceSettings(**bad)


# --------------------------------------------------------------- topic ids


def test_topics_keep_their_ids_when_the_majority_flips():
    first = build_knowledge_base(COMPANY, calls(["7 days"] * 6 + ["30 days"] * 5))
    later = build_knowledge_base(
        COMPANY, calls(["7 days"] * 6 + ["30 days"] * 9), previous=first
    )
    assert only_topic(later).topic_id == only_topic(first).topic_id
    assert later.version == 2


def test_a_settled_conflict_stays_settled_after_agents_follow_it():
    store = MemoryStore()
    InferKnowledgeBase(
        FakeSource(calls(["7 days"] * 6 + ["30 days"] * 5)), store
    ).execute(COMPANY)
    topic_id = store.load(COMPANY).conflicts[0].topic.topic_id
    RecordOverride(store).execute(
        COMPANY, Override(topic_id, "30 days", "m", "New policy")
    )
    after = calls(["7 days"] * 6 + ["30 days"] * 9)  # agents switch to the new value
    kb = InferKnowledgeBase(FakeSource(after), store).execute(COMPANY)
    assert [(r.value, r.source) for r in kb.rules] == [("30 days", "manager")]
    assert not kb.conflicts and not kb.unmatched_overrides


# ----------------------------------------------------------------- overrides


def test_manager_can_settle_a_conflict():
    kb = build_knowledge_base(COMPANY, calls(["7 days"] * 6 + ["30 days"] * 5))
    topic_id = kb.conflicts[0].topic.topic_id
    settled = apply_overrides(
        kb, [Override(topic_id, "30 days", "manager-1", "New policy")]
    )
    rule = settled.rules[0]
    assert not settled.conflicts
    assert (rule.value, rule.source, rule.supporting_calls, rule.note) == (
        "30 days",
        "manager",
        5,
        "New policy",
    )


def test_manager_can_remove_a_rule_and_the_last_change_wins():
    kb = build_knowledge_base(COMPANY, calls(["7 days"] * 10))
    topic_id = kb.rules[0].topic.topic_id
    removed = apply_overrides(kb, [Override(topic_id, None, "m", "Wrong")])
    assert not removed.rules and len(removed.removed) == 1
    restored = apply_overrides(
        kb,
        [
            Override(topic_id, None, "m", "Wrong"),
            Override(topic_id, "7 days", "m", "Fine"),
        ],
    )
    assert restored.rules[0].source == "manager"


def test_overrides_for_missing_topics_are_kept_visible():
    kb = apply_overrides(
        build_knowledge_base(COMPANY, calls(["7 days"] * 10)),
        [Override("gone", "1 days", "m", "Old")],
    )
    assert [o.topic_id for o in kb.unmatched_overrides] == ["gone"]


@pytest.mark.parametrize(
    "override",
    [
        Override("missing-topic", "7 days", "m", "Typo"),
        Override("TOPIC", "20 percent", "m", "Wrong unit"),
    ],
)
def test_overrides_are_checked_before_they_are_recorded(override):
    kb = build_knowledge_base(COMPANY, calls(["7 days"] * 10))
    if override.topic_id == "TOPIC":
        override = Override(
            kb.rules[0].topic.topic_id, override.value, "m", override.reason
        )
    with pytest.raises(InvalidKnowledgeInput):
        check_override(kb, override)


@pytest.mark.parametrize(("value", "reason"), [("7 days", " "), (" ", "Reason")])
def test_override_needs_a_reason_and_a_real_value(value, reason):
    with pytest.raises(InvalidKnowledgeInput):
        Override("t", value, "m", reason)


# ------------------------------------------------------------------- scoring


def rules_kb():
    return build_knowledge_base(
        COMPANY, calls(["7 days"] * 10) + calls(["4.99 usd"] * 10, 100, subject=WRAP)
    )


def verdicts(result):
    return sorted((c.claim.value, c.verdict, c.rule_value) for c in result.checked)


def test_scoring_marks_matches_differences_and_values_without_a_rule():
    said = [
        claim(500, "7 days"),
        claim(500, "9 usd", subject=frozenset({"ship", "fee"})),
        claim(500, "5 usd", subject=WRAP),
    ]
    result = score_call(COMPANY, "call-500", said, rules_kb())
    assert verdicts(result) == [
        ("5 usd", "differs_from_rule", "4.99 usd"),
        ("7 days", "matches_rule", "7 days"),
        ("9 usd", "no_rule", None),
    ]
    assert result.score == 0.5


def test_repeating_a_value_counts_once():
    said = [claim(500, "5 usd", subject=WRAP)] * 2 + [claim(500, "7 days")]
    assert score_call(COMPANY, "call-500", said, rules_kb()).score == 0.5


def test_several_values_for_one_rule_are_not_scored():
    said = [claim(500, "7 days"), claim(500, "30 days")]
    result = score_call(COMPANY, "call-500", said, rules_kb())
    assert {c.verdict for c in result.checked} == {"several_values"}
    assert result.score is None


def test_a_value_is_matched_by_what_it_is_about_not_the_number():
    # The promo topic once heard "30 days", but this claim is about refunds.
    kb = build_knowledge_base(COMPANY, calls(["7 days"] * 9 + ["30 days"]))
    result = score_call(COMPANY, "call-9", [claim(9, "30 days", subject=REFUND)], kb)
    assert verdicts(result) == [("30 days", "no_rule", None)]


def test_a_value_on_an_unsettled_topic_is_not_pinned_to_a_nearby_rule():
    promo = calls(["7 days"] * 10)
    refund_words = REFUND | {"cod"}  # a refund topic that shares one word with promos
    refunds = calls(["5 days"] * 6 + ["10 days"] * 5, 100, subject=refund_words)
    kb = build_knowledge_base(COMPANY, promo + refunds)
    assert len(kb.rules) == 1 and len(kb.conflicts) == 1
    # Close enough to the promo rule to match it, but closer still to the refund topic.
    said = frozenset({"refund", "arriv", "cod", "valid"})
    result = score_call(COMPANY, "call-9", [claim(9, "10 days", subject=said)], kb)
    assert verdicts(result) == [("10 days", "no_rule", None)]


def test_scoring_stays_within_one_company_and_one_call():
    kb = rules_kb()
    with pytest.raises(InvalidKnowledgeInput):
        score_call("other", "call-1", [], kb)
    with pytest.raises(InvalidKnowledgeInput):
        score_call(COMPANY, "call-1", [claim(2)], kb)


# ------------------------------------------------------------------ use cases


class FakeSource:
    def __init__(self, claims):
        self.items = claims

    def claims(self, company_id):
        return self.items


class MemoryStore:
    def __init__(self):
        self.saved = {}
        self.changes = []

    def load(self, company_id):
        return self.saved.get(company_id)

    def save(self, knowledge_base):
        self.saved[knowledge_base.company_id] = knowledge_base

    def overrides(self, company_id):
        return self.changes

    def add_override(self, company_id, override):
        self.changes.append(override)


def test_relearning_bumps_the_version_and_keeps_manager_changes():
    store = MemoryStore()
    infer = InferKnowledgeBase(FakeSource(calls(["7 days"] * 10)), store)
    first = infer.execute(COMPANY)
    RecordOverride(store).execute(
        COMPANY,
        Override(first.rules[0].topic.topic_id, "14 days", "m", "Policy changed"),
    )
    second = infer.execute(COMPANY)
    assert (first.version, second.version) == (1, 2)
    assert second.rules[0].value == "14 days" and store.load(COMPANY) is second


def test_an_empty_run_never_replaces_a_knowledge_base():
    store = MemoryStore()
    InferKnowledgeBase(FakeSource(calls(["7 days"] * 10)), store).execute(COMPANY)
    with pytest.raises(NoCallsToLearnFrom):
        InferKnowledgeBase(FakeSource([]), store).execute(COMPANY)
    assert store.load(COMPANY).version == 1


def test_scoring_and_overrides_need_a_knowledge_base():
    with pytest.raises(KnowledgeBaseNotBuilt):
        ScoreCall(MemoryStore()).execute(COMPANY, "call-1", [])
    with pytest.raises(KnowledgeBaseNotBuilt):
        RecordOverride(MemoryStore()).execute(COMPANY, Override("t", None, "m", "r"))
