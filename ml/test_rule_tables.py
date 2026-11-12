"""Data contracts and recognition boundaries; no dataset or model is loaded."""

import json
import re
import unittest
from copy import deepcopy
from pathlib import Path

from ml.abcd import ABCD_COMMIT, ABCD_SHA256
from ml.references import reference_version, review_issues
from ml.rule_assessment import assess_conversation
from ml.scoring import (
    REVIEW_FIELDS,
    content_version,
    eligible_sources,
    policy_issues,
    policy_version,
)
from ml.test_rule_scoring import approved, category, evidence, rebind_policy


class RuleTableTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        directory = Path(__file__).parent
        cls.tables = json.loads((directory / "rule_tables.json").read_text())
        cls.cohort = json.loads((directory / "rule_cohort.json").read_text())

    def test_frozen_training_cohort_and_unset_spotchecks(self):
        rows = self.cohort["conversations"]
        identifiers = {row["id"] for row in rows}
        self.assertEqual(len(rows), 117)
        self.assertEqual(len(identifiers), 117)
        self.assertEqual({row["split"] for row in rows}, {"train"})
        self.assertEqual(len({row["source_index"] for row in rows}), 117)
        self.assertEqual(self.cohort["source"]["commit"], ABCD_COMMIT)
        self.assertEqual(self.cohort["source"]["sha256"], ABCD_SHA256)
        self.assertEqual(len(self.cohort["development_ids"]), 15)
        self.assertLessEqual(set(self.cohort["development_ids"]), identifiers)
        review = self.cohort["human_spotcheck"]
        self.assertEqual(len(set(review["conversation_ids"])), 5)
        self.assertLessEqual(set(review["conversation_ids"]), identifiers)
        for field in ("reviewer", "reviewed_at", "judgements"):
            self.assertIsNone(review[field])
        content = {k: v for k, v in self.cohort.items() if k != "version"}
        self.assertEqual(self.cohort["version"], content_version(content))

    def test_reference_provenance_quotes_and_bounded_demo_approval(self):
        references = self.tables["references"]
        by_id = {row["id"]: row for row in references}
        approved_ids = {
            "abcd-rule-" + name
            for name in (
                "product-defect-update-refund",
                "product-defect-return-due-to-color",
                "product-defect-return-due-to-size",
                "shipping-issue-manage-shipping",
                "shipping-issue-shipping-cost",
                "subscription-inquiry-manage-extension",
                "subscription-inquiry-manage-dispute-bill",
            )
        } | {
            "memoria-rule-request-response",
            "memoria-rule-wording-clarity",
            "memoria-rule-wording-acknowledgement",
            "memoria-rule-wording-respect",
        }
        self.assertEqual(len(references), len(by_id))
        for index, reference in enumerate(references):
            with self.subTest(reference=reference["id"]):
                self.assertEqual(reference["version"], reference_version(reference))
                reviewed = reference["id"] in approved_ids
                self.assertEqual(
                    reference["status"], "approved" if reviewed else "draft"
                )
                issues = review_issues(
                    reference, as_of="2026-11-09", scope=reference["scope"][0]
                )
                self.assertEqual(not issues, reviewed)
                if reviewed:
                    self.assertIn(
                        "explicit local-demo approval", reference["approved_by"]
                    )
                    self.assertEqual(
                        reference["approved_version"], reference["version"]
                    )
                    self.assertEqual(reference["review_due"], "2026-11-09")
                    self.assertTrue(
                        review_issues(
                            reference, as_of="2026-11-10", scope=reference["scope"][0]
                        )
                    )
                else:
                    self.assertIsNone(reference["approved_by"])
                    self.assertIsNone(reference["approved_version"])
                source = reference["source"]
                if source.get("dataset") == "ABCD":
                    self.assertEqual(source["commit"], ABCD_COMMIT)
                    self.assertEqual(source["path"], "data/guidelines.json")
                else:
                    self.assertEqual(
                        source,
                        {
                            "kind": "memoria-authored-scoring",
                            "path": "ml/rule_tables.json",
                            "pointer": f"/references/{index}/text",
                        },
                    )
        for workflow in self.tables["workflows"]:
            for action in workflow["actions"]:
                reference = by_id[action["reference_id"]]
                for check in action["prerequisites"] + action["required_before"]:
                    self.assertIn(check["source_quote"], reference["text"])

    def test_profiles_and_policy_bind_only_the_approved_demo(self):
        # Historical approval is preserved; recognition changes cannot inherit it.
        self.assertNotEqual(
            self.tables["review_package"]["version"], policy_version(self.tables)
        )
        self.assertTrue(policy_issues(self.tables, as_of="2026-11-09"))
        self.assertEqual(
            self.tables["review_package"]["version"],
            self.tables["review_package"]["approved_version"],
        )
        for profile in self.tables["profiles"]:
            self.assertEqual(sum(profile["weights"].values()), 100)
            content = {k: v for k, v in profile.items() if k not in REVIEW_FIELDS}
            self.assertEqual(profile["version"], content_version(content))
            reviewed = profile["id"] in {"ordinary-support", "account-access"}
            self.assertEqual(profile["status"], "approved" if reviewed else "draft")
            self.assertEqual(
                profile["approved_version"], profile["version"] if reviewed else None
            )
            self.assertEqual(
                not review_issues(
                    profile, as_of="2026-11-09", scope="rule-assessment-scoring"
                ),
                reviewed,
            )
        fraud = next(p for p in self.tables["profiles"] if p["id"] == "fraud-future")
        self.assertTrue(fraud["unsupported"])
        self.assertEqual(fraud["workflows"], [])

    def test_unsafe_sources_cannot_be_enabled_by_approval_metadata(self):
        tables = deepcopy(self.tables)
        for reference in tables["references"]:
            approved(reference, reference["version"])
        workflows = [row["id"] for row in tables["workflows"]]
        eligible = {
            row["id"]
            for row in eligible_sources(
                [], {"references": []}, tables, as_of="2026-11-09", workflows=workflows
            )
        }
        for reference in tables["references"]:
            with self.subTest(reference=reference["id"]):
                self.assertEqual(
                    reference["id"] in eligible, not reference["safety_flags"]
                )
        for suffix in (
            "subscription-inquiry-manage-pay-bill",
            "shipping-issue-missing-item",
            "purchase-dispute-promo-code-invalid",
            "single-item-query-boots-faq",
        ):
            self.assertNotIn("abcd-rule-" + suffix, eligible)

    def test_factual_selections_only_use_exact_unblocked_source_passages(self):
        references = {row["id"]: row for row in self.tables["references"]}
        for workflow in self.tables["workflows"]:
            for selection in workflow["answer_statements"]:
                with self.subTest(workflow=workflow["id"]):
                    source = references[selection["reference_id"]]
                    self.assertIn(source["id"], workflow["reference_ids"])
                    self.assertEqual(selection["reference_version"], source["version"])
                    self.assertTrue(selection["quote"].strip())
                    self.assertIn(selection["quote"], source["text"])
                    self.assertFalse(source["safety_flags"])

    def test_selected_shipping_fact_supports_credit_and_evidenced_deduction(self):
        tables = deepcopy(self.tables)
        source = next(
            row
            for row in tables["references"]
            if row["id"] == "abcd-rule-shipping-issue-shipping-cost"
        )
        approved(source, source["version"])
        rebind_policy(tables)
        for amount, expected in (("8.00", 100), ("9.00", 0)):
            report = assess_conversation(
                evidence(
                    [
                        ["customer", "The cost of shipping is too high."],
                        ["agent", f"Standard shipping is ${amount}."],
                    ]
                ),
                [],
                {"references": []},
                tables,
                as_of="2026-11-09",
            )
            self.assertEqual(
                category(report, "answer-support")["scoring"]["score"], expected
            )
            self.assertIsNone(report["overall"]["score"])

    def test_purpose_pattern_equivalents_and_counterexamples(self):
        examples = [
            (
                "troubleshoot-site-invalid-credit-card",
                "My credit card was rejected.",
                "My credit card was accepted.",
            ),
            (
                "troubleshoot-site-search-not-working",
                "The search bar doesn't work.",
                "The search bar works now.",
            ),
            (
                "shipping-issue-shipping-cost",
                "The cost of shipping is too high.",
                "The cost of shipping is reasonable.",
            ),
            (
                "single-item-query-jeans-faq",
                "Any smaller sizes of these jeans?",
                "Any smaller sizes of these shoes?",
            ),
            (
                "single-item-query-jacket-faq",
                "I'm looking at a jacket. What materials are used?",
                "I'm looking at shoes. What materials are used?",
            ),
        ]
        workflows = {row["id"]: row for row in self.tables["workflows"]}
        for identifier, supported, other in examples:
            with self.subTest(workflow=identifier):
                patterns = workflows[identifier]["purpose_patterns"]
                self.assertTrue(
                    any(re.search(p, supported, re.IGNORECASE) for p in patterns)
                )
                self.assertFalse(
                    any(re.search(p, other, re.IGNORECASE) for p in patterns)
                )

    def test_started_operations_and_malformed_amounts_never_mean_success(self):
        forms = self.tables["action_forms"]
        for name in (
            "Verify Identity",
            "Validate Purchase",
            "Send Link",
            "Ask the Oracle",
        ):
            self.assertIn("started_pattern", forms[name])
            self.assertNotIn("completed_pattern", forms[name])
        refund = forms["Offer Refund"]["completed_pattern"]
        self.assertIsNotNone(
            re.fullmatch(refund, "A refund has been made for the amount of $12.50.")
        )
        for value in ("", "yesterday", "give credit", "$12"):
            self.assertIsNone(
                re.fullmatch(
                    refund, f"A refund has been made for the amount of ${value}."
                )
            )


if __name__ == "__main__":
    unittest.main()
