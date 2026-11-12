"""Constructed factual equivalents; these approvals never alter real sources."""

import unittest
from copy import deepcopy

from ml.references import reference_version
from ml.rule_assessment import assess_conversation
from ml.test_rule_scoring import (
    AS_OF,
    approved,
    category,
    decision_tables,
    evidence,
    rebind_policy,
)


def fact_tables(statement):
    tables = decision_tables()
    reference = tables["references"][0]
    reference["text"] = statement
    approved(reference, reference_version(reference))
    tables["workflows"][0]["answer_statements"] = [
        {
            "reference_id": reference["id"],
            "reference_version": reference["version"],
            "quote": statement,
        }
    ]
    rebind_policy(tables)
    return tables


def answer_checks(statement, claim, *, tables=None, identifier=7531):
    report = assess_conversation(
        evidence(
            [["customer", "Please explain this shipment."], ["agent", claim]],
            identifier=identifier,
        ),
        [],
        {"references": []},
        tables if tables is not None else fact_tables(statement),
        as_of=AS_OF,
    )
    return category(report, "answer-support")["scoring"]["checks"]


class FactualEquivalentTests(unittest.TestCase):
    def test_standard_shipping_cost_equivalents_keep_the_service_qualifier(self):
        source = "Standard shipping is $8.00."
        for claim in (
            "Standard shipping costs $8.",
            "The cost of standard shipping is $8.00.",
            "Standard shipping is $ 8.00.",
        ):
            with self.subTest(claim=claim):
                checks = answer_checks(source, claim)
                self.assertEqual(checks[0]["outcome"], "supported")
                self.assertEqual(
                    [
                        c["quote"]
                        for c in checks[0]["citations"]
                        if c["kind"] == "reference"
                    ],
                    [source],
                )

    def test_different_value_in_same_cost_frame_is_an_evidenced_breach(self):
        checks = answer_checks(
            "Standard shipping is $8.00.", "Standard shipping costs $11."
        )
        self.assertEqual(checks[0]["outcome"], "breach")
        self.assertEqual(
            {citation["kind"] for citation in checks[0]["citations"]},
            {"conversation", "reference"},
        )

    def test_wrong_currency_or_service_does_not_create_a_comparison(self):
        for claim in (
            "Standard shipping costs €8.",
            "Overnight shipping costs $8.",
            "Shipping costs $8.",
            "Standard shipping costs 8 dollars.",
        ):
            with self.subTest(claim=claim):
                checks = answer_checks("Standard shipping is $8.00.", claim)
                self.assertTrue(all(row["outcome"] == "unresolved" for row in checks))

    def test_membership_benefit_equivalents_preserve_tier_and_scope(self):
        source = "Gold members get unlimited returns."
        for claim in (
            "Gold members are allowed unlimited returns.",
            "Gold members are entitled to unlimited returns.",
        ):
            with self.subTest(claim=claim):
                self.assertEqual(
                    answer_checks(source, claim)[0]["outcome"], "supported"
                )

    def test_benefit_does_not_prove_personal_membership_or_refund_authority(self):
        source = "Gold members get unlimited returns."
        for claim in (
            "Silver members get unlimited returns.",
            "Members get unlimited returns.",
            "Gold members get unlimited refunds.",
            "You are a Gold member and can return anything.",
        ):
            with self.subTest(claim=claim):
                checks = answer_checks(source, claim)
                self.assertTrue(all(row["outcome"] == "unresolved" for row in checks))

    def test_personalized_benefit_retains_unresolved_membership_and_completion(self):
        source = "Gold members can always get an extension."
        checks = answer_checks(
            source,
            "As a Gold member, you qualify for an extension which I have just put into place.",
        )
        self.assertTrue(any(row["outcome"] == "unresolved" for row in checks))
        self.assertFalse(any(row["outcome"] == "breach" for row in checks))
        for row in checks:
            if row["outcome"] == "supported":
                self.assertTrue(any(c.get("quote") == source for c in row["citations"]))

    def test_one_tier_policy_does_not_establish_another_tiers_entitlement(self):
        checks = answer_checks(
            "Gold members get unlimited returns.",
            "Gold members get unlimited returns. Silver members get unlimited returns.",
        )
        self.assertEqual(
            [row["outcome"] for row in checks], ["supported", "unresolved"]
        )

    def test_extension_equivalent_retains_the_gold_condition(self):
        source = "Gold members can always get an extension."
        for claim in (
            "Gold members are always eligible for an extension.",
            "Gold members are eligible for an extension.",
        ):
            with self.subTest(claim=claim):
                self.assertEqual(
                    answer_checks(source, claim)[0]["outcome"], "supported"
                )
        for claim in (
            "Members are always eligible for an extension.",
            "Your extension has been completed.",
        ):
            with self.subTest(claim=claim):
                self.assertTrue(
                    all(
                        row["outcome"] == "unresolved"
                        for row in answer_checks(source, claim)
                    )
                )

    def test_weaker_entitlement_source_cannot_establish_always(self):
        source = "Gold members are eligible for an extension."
        checks = answer_checks(
            source, "Gold members are always eligible for an extension."
        )
        self.assertTrue(all(row["outcome"] == "unresolved" for row in checks))

    def test_literal_placeholders_never_become_numeric_values_or_deductions(self):
        source = "Shipping takes 3 business days after dispatch."
        for claim in (
            "Shipping takes {business day} after dispatch.",
            "Shipping takes [DURATION_1] business days after dispatch.",
            "Shipping takes three unknown days after dispatch.",
        ):
            with self.subTest(claim=claim):
                checks = answer_checks(source, claim)
                self.assertTrue(all(row["outcome"] == "unresolved" for row in checks))

    def test_prefix_conditions_cannot_be_discarded_to_match_a_fact(self):
        source = "Standard shipping is $8.00."
        for claim in (
            "If the package is small, standard shipping costs $8.",
            "Provided the package is small, standard shipping costs $8.",
            "Assuming the package is small, standard shipping costs $8.",
            "Standard shipping costs $8 only for small packages.",
            "Standard shipping costs $8. Provided the package is small.",
            "Standard shipping costs $8. Assuming the package is small.",
            "Standard shipping costs $8. Subject to a small-package limit.",
            "Standard shipping costs $8. Depending on weight.",
            "Standard shipping costs $8. Depending on what the weight is.",
            "Standard shipping costs $8. For small packages.",
            "Standard shipping costs $8. Under a promotion.",
            "Standard shipping costs $8. For small packages that are lightweight.",
            "Standard shipping costs $8. Under a promotion that is temporary.",
        ):
            with self.subTest(claim=claim):
                checks = answer_checks(source, claim)
                self.assertTrue(all(row["outcome"] == "unresolved" for row in checks))

    def test_duration_equivalent_preserves_business_days_and_dispatch_condition(self):
        source = "Shipping takes 3 business days after dispatch."
        checks = answer_checks(
            source, "Shipping takes three business days after dispatch."
        )
        self.assertEqual(checks[0]["outcome"], "supported")
        for claim in (
            "Shipping takes 3 days after dispatch.",
            "Shipping takes 72 hours after dispatch.",
            "Shipping takes three business days.",
            "Refunding takes three business days after dispatch.",
        ):
            with self.subTest(claim=claim):
                self.assertTrue(
                    all(
                        row["outcome"] == "unresolved"
                        for row in answer_checks(source, claim)
                    )
                )

    def test_qualifications_quotes_negation_and_corrections_remain_unresolved(self):
        source = "Standard shipping is $8.00."
        for claim in (
            'The customer said "Standard shipping costs $8."',
            "Standard shipping costs $8, unless the item is heavy.",
            "Standard shipping does not cost $8.",
            "Actually, standard shipping costs $8 instead.",
            "Standard shipping costs $8. Only if the order is small.",
        ):
            with self.subTest(claim=claim):
                self.assertTrue(
                    all(
                        row["outcome"] == "unresolved"
                        for row in answer_checks(source, claim)
                    )
                )

    def test_selected_statement_is_required_even_when_source_contains_matching_fact(
        self,
    ):
        statement = "Standard shipping is $8.00."
        tables = fact_tables(statement)
        tables["workflows"][0]["answer_statements"] = []
        rebind_policy(tables)
        checks = answer_checks(statement, "Standard shipping costs $8.", tables=tables)
        self.assertTrue(all(row["outcome"] == "unresolved" for row in checks))

    def test_changed_interpretation_limits_do_not_inherit_reference_approval(self):
        statement = "Standard shipping is $8.00."
        tables = fact_tables(statement)
        tables["references"][0]["interpretation_limits"].append("Changed limitation.")
        rebind_policy(tables)
        checks = answer_checks(statement, "Standard shipping costs $8.", tables=tables)
        self.assertTrue(all(row["outcome"] == "unresolved" for row in checks))

    def test_equivalent_repetition_cannot_manufacture_points(self):
        checks = answer_checks(
            "Standard shipping is $8.00.",
            "Standard shipping costs $8. The cost of standard shipping is $8.00.",
        )
        self.assertEqual(len(checks), 1)
        self.assertEqual(checks[0]["outcome"], "supported")

    def test_correct_and_contradictory_values_remain_separate_checks(self):
        checks = answer_checks(
            "Standard shipping is $8.00.",
            "Standard shipping costs $8. Standard shipping costs $11.",
        )
        self.assertEqual([row["outcome"] for row in checks], ["supported", "breach"])

    def test_supported_fact_does_not_hide_an_independent_unknown_assertion(self):
        checks = answer_checks(
            "Standard shipping is $8.00.",
            "Standard shipping costs $8. The jacket is made of cotton.",
        )
        self.assertEqual(
            [row["outcome"] for row in checks], ["supported", "unresolved"]
        )

    def test_id_changes_do_not_change_fact_results(self):
        source, claim = "Standard shipping is $8.00.", "Standard shipping costs $8."
        first = answer_checks(source, claim, identifier=7531)
        second = answer_checks(source, claim, identifier=8642)
        for left, right in zip(first, second, strict=True):
            self.assertEqual(left["outcome"], right["outcome"])
            self.assertEqual(left["earned"], right["earned"])
            self.assertEqual(left["requirement"], right["requirement"])

    def test_safety_flags_cannot_be_removed_by_reapproving_the_policy(self):
        statement = "Standard shipping is $8.00."
        tables = deepcopy(fact_tables(statement))
        tables["references"][0]["safety_flags"] = ["Unsafe proposed instruction."]
        approved(tables["references"][0], reference_version(tables["references"][0]))
        rebind_policy(tables)
        checks = answer_checks(statement, "Standard shipping costs $8.", tables=tables)
        self.assertTrue(all(row["outcome"] == "unresolved" for row in checks))


if __name__ == "__main__":
    unittest.main()


class ConditionalReturnBenefitsTests(unittest.TestCase):
    def test_bounded_equivalents_separate_tier_fact_from_personal_claim(self):
        for claim in (
            "As a Gold member, you get unlimited returns.",
            "As one of our Gold members you are allowed unlimited returns.",
            "As a Gold member you have unlimted returns.",
        ):
            checks = answer_checks("Gold members get unlimited returns.", claim)
            self.assertEqual(
                [r["outcome"] for r in checks], ["supported", "unresolved"]
            )
            self.assertIn("Actual membership", checks[1]["explanation"])
            self.assertTrue(
                all(
                    c["quote"] == claim
                    for r in checks
                    for c in r["citations"]
                    if c["kind"] == "conversation"
                )
            )

    def test_negation_limited_returns_other_tier_and_quotes_never_match(self):
        for claim in (
            "As a Gold member you get limited returns.",
            "As a Gold member you do not get unlimited returns.",
            "As a Silver member you get unlimited returns.",
            'The customer said "As a Gold member you get unlimited returns."',
            "As a Gold member you get unlimited returns if the goods are faulty.",
        ):
            checks = answer_checks("Gold members get unlimited returns.", claim)
            self.assertTrue(all(r["outcome"] == "unresolved" for r in checks))
