"""Authored mechanical cases; fixture approvals never approve real catalogues."""

import json
import unittest
from copy import deepcopy
from pathlib import Path
from unittest.mock import patch

from ml.abcd import prepare_dataset
from ml.audit import CATEGORIES
from ml.references import reference_version
from ml.rule_assessment import assess_conversation
from ml.rule_links import request_links
from ml.scoring import (
    REVIEW_FIELDS,
    SCOPE,
    content_version,
    eligible_sources,
    overall_score,
    policy_issues,
    policy_version,
    score_checks,
    validate_scored_report,
)
from ml.test_evidence import SOURCE, source_record

AS_OF = "2026-11-09"
WORKFLOW = "test-shipment"


def approved(value, version):
    value.update(
        version=version,
        status="approved",
        approved_by="Synthetic test reviewer",
        approved_version=version,
        approved_at="2026-10-28",
        verified_at="2026-10-28",
        review_due="2027-10-28",
    )
    return value


def rebind_policy(tables):
    tables["review_package"] = approved(
        {"scope": [SCOPE], "exclusions": [], "safety_flags": []},
        policy_version(tables),
    )


def profile():
    value = {
        "id": "test-equal-weights",
        "scope": [SCOPE],
        "workflows": [WORKFLOW],
        "weights": dict.fromkeys(CATEGORIES, 25),
        "unsupported": False,
        "exclusions": [],
        "safety_flags": [],
    }
    return approved(value, content_version(value))


def decision_tables():
    definitions = [
        ("test-shipping", "Shipping takes 3 business days after dispatch."),
        (
            "memoria-rule-request-response",
            "Link the response to the distinct requested action and its details.",
        ),
        (
            "memoria-rule-wording-respect",
            "Directly expressed courtesies are supported; direct customer insults breach respect.",
        ),
        (
            "memoria-rule-wording-clarity",
            "An instruction names a concrete requested field.",
        ),
        (
            "memoria-rule-wording-acknowledgement",
            "Acknowledgement must match the customer's current requested action.",
        ),
    ]
    references = []
    for index, (identifier, text) in enumerate(definitions):
        reference = {
            "id": identifier,
            "section_id": f"test-{index}",
            "title": "Authored test criterion",
            "text": text,
            "conditions": [],
            "exclusions": [],
            "scope": [WORKFLOW],
            "source": {
                "kind": "memoria-authored-scoring",
                "path": "ml/rule_tables.json",
                "pointer": f"/references/{index}/text",
            },
            "safety_flags": [],
            "interpretation_limits": [
                "A lookup records lookup; it does not establish verified identity."
            ],
        }
        references.append(approved(reference, reference_version(reference)))
    tables = {
        "references": references,
        "profiles": [profile()],
        "checks": [],
        "workflows": [
            {
                "id": WORKFLOW,
                "purpose_patterns": [r"\bshipment\b"],
                "answer_statements": [
                    {
                        "reference_id": references[0]["id"],
                        "reference_version": references[0]["version"],
                        "quote": definitions[0][1],
                    }
                ],
                "reference_ids": ["test-shipping"],
                "actions": [
                    {
                        "button": "Lookup Order",
                        "reference_id": "test-shipping",
                        "condition": None,
                        "prerequisites": [],
                        "required_before": [],
                    }
                ],
            }
        ],
        "action_forms": {
            "Lookup Order": {
                "completed_pattern": r"Order lookup complete\.",
                "started_pattern": r"Order lookup in progress\.",
                "limit": "Lookup does not establish identity or authority.",
            }
        },
    }
    rebind_policy(tables)
    return tables


def evidence(turns=None, identifier=1234):
    record = source_record(identifier)
    record["original"] = turns or [
        ["customer", "Where is my shipment?"],
        ["action", "Order lookup complete."],
        ["agent", "Thanks for waiting."],
        ["agent", "Shipping takes 3 business days after dispatch."],
    ]
    record["delexed"] = [
        {
            "speaker": speaker,
            "text": text.lower(),
            "turn_count": turn,
            "targets": ["TARGET_LABEL_CANARY"],
            "candidates": ["CANDIDATE_LABEL_CANARY"],
        }
        for turn, (speaker, text) in enumerate(record["original"], 1)
    ]
    return prepare_dataset(
        {"train": [record], "dev": [], "test": []}, SOURCE, (str(identifier),)
    )


def links(*messages):
    conversation = {
        "events": [
            {"turn_id": number, "kind": "message", "speaker": speaker, "text": text}
            for number, (speaker, text) in enumerate(messages, 1)
        ]
    }
    return request_links(conversation)


def atomic(identifier, outcome):
    return {
        "id": identifier,
        "ruleId": identifier,
        "requirement": "Constructed atomic check",
        "outcome": outcome,
        "earned": {"supported": 1, "breach": 0}.get(outcome),
        "maximum": 1,
        "explanation": "Constructed calculation input.",
        "advice": "Inspect the supporting evidence.",
        "citations": [],
        "critical": False,
    }


def category(report, name):
    return next(row for row in report["categories"] if row["category"] == name)


class PointCalculationTests(unittest.TestCase):
    def test_assessable_points_and_coverage_have_different_denominators(self):
        checks = [atomic(f"pass-{n}", "supported") for n in range(18)]
        checks += [atomic(f"breach-{n}", "breach") for n in range(2)]
        checks += [atomic(f"unknown-{n}", "unresolved") for n in range(80)]
        checks.append(atomic("excluded", "not-applicable"))
        result = score_checks(checks)
        self.assertEqual((result["score"], result["coverage"]), (90, 20))
        self.assertEqual(
            (result["earned"], result["assessable"], result["possible"]), (18, 20, 100)
        )

    def test_partial_credit_is_separate_atomic_checks_and_unknown_is_not_a_deduction(
        self,
    ):
        checks = [
            atomic("a", "supported"),
            atomic("b", "supported"),
            atomic("c", "breach"),
        ]
        self.assertAlmostEqual(score_checks(checks)["score"], 200 / 3)
        checks[-1] = atomic("c", "unresolved")
        result = score_checks(checks)
        self.assertEqual(result["score"], 100)
        self.assertAlmostEqual(result["coverage"], 200 / 3)

    def test_unknown_inventory_zero_evidence_and_errors_never_invent_performance(self):
        self.assertIsNone(score_checks([atomic("unknown", "unresolved")])["score"])
        self.assertIsNone(score_checks([])["score"])
        result = score_checks(
            [atomic("supported", "supported")], inventory_complete=False
        )
        self.assertIsNone(result["possible"])
        self.assertIsNone(result["coverage"])
        result = score_checks(
            [atomic("supported", "supported")], error="Evaluator unavailable"
        )
        self.assertIsNone(result["score"])
        self.assertEqual(result["earned"], 1)

    def test_duplicate_and_fabricated_points_are_rejected(self):
        for change in (
            {"maximum": 2},
            {"maximum": True},
            {"earned": True},
            {"earned": 0},
            {"outcome": "guessed"},
        ):
            with self.subTest(change=change), self.assertRaises(ValueError):
                score_checks([{**atomic("one", "supported"), **change}])
        with self.assertRaises(ValueError):
            score_checks([atomic("same", "supported")] * 2)

    def test_weighted_example_and_no_redistribution(self):
        categories = [
            {
                "category": name,
                "status": "completed",
                "scoring": {"score": value, "coverage": 50},
            }
            for name, value in zip(CATEGORIES, [90, 90, 92, 92])
        ]
        self.assertEqual(
            overall_score(categories, [profile()], [WORKFLOW], as_of=AS_OF)["score"], 91
        )
        categories[0]["scoring"]["score"] = None
        self.assertIsNone(
            overall_score(categories, [profile()], [WORKFLOW], as_of=AS_OF)["score"]
        )
        categories[0]["scoring"]["score"] = 90
        self.assertIsNone(
            overall_score(categories, [profile()], [WORKFLOW, "other"], as_of=AS_OF)[
                "score"
            ]
        )
        self.assertIsNone(
            overall_score(categories, [profile(), profile()], [WORKFLOW], as_of=AS_OF)[
                "score"
            ]
        )

    def test_weights_must_be_current_version_bound_and_sum_to_one_hundred(self):
        categories = [
            {
                "category": name,
                "status": "completed",
                "scoring": {"score": 90, "coverage": 50},
            }
            for name in CATEGORIES
        ]
        proposed = profile()
        self.assertEqual(
            overall_score(categories, [proposed], [WORKFLOW], as_of="2027-10-28")[
                "score"
            ],
            90,
        )
        self.assertIsNone(
            overall_score(categories, [proposed], [WORKFLOW], as_of="2027-10-29")[
                "score"
            ]
        )
        proposed["weights"]["procedure"] = 40
        self.assertIsNone(
            overall_score(categories, [proposed], [WORKFLOW], as_of=AS_OF)["score"]
        )
        content = {
            key: value for key, value in proposed.items() if key not in REVIEW_FIELDS
        }
        approved(proposed, content_version(content))
        with self.assertRaises(ValueError):
            overall_score(categories, [proposed], [WORKFLOW], as_of=AS_OF)


class ContextualLinkTests(unittest.TestCase):
    def test_short_no_answers_the_actual_preceding_question(self):
        for question, expected in [
            ("Is there anything else?", "promised"),
            ("Have you received the email?", "promised"),
            ("Do you still want the email?", "withdrawn"),
        ]:
            with self.subTest(question=question):
                requests, _ = links(
                    ("customer", "Please email me."),
                    ("agent", "I'll email you."),
                    ("agent", question),
                    ("customer", "No."),
                )
                self.assertEqual(requests[0]["state"], expected)
                if expected == "withdrawn":
                    self.assertEqual(requests[0]["history"][-1]["turn_ids"], [3, 4])

    def test_short_reply_cannot_withdraw_a_different_operation_or_object(self):
        for request, question in [
            ("Can you explain the refund process?", "Do you still want the refund?"),
            ("Please email me the invoice.", "Do you still want the receipt by email?"),
        ]:
            with self.subTest(request=request):
                requests, unknown = links(
                    ("customer", request), ("agent", question), ("customer", "No.")
                )
                self.assertEqual(requests[0]["state"], "active")
                self.assertTrue(unknown)

    def test_withdrawals_and_changes_work_after_promises_and_answers(self):
        for response in ("I'll email you.", "I have sent the email to you."):
            with self.subTest(response=response):
                requests, _ = links(
                    ("customer", "Please email me."),
                    ("agent", response),
                    ("customer", "Actually, don't email me."),
                )
                self.assertEqual(requests[0]["state"], "withdrawn")
                self.assertEqual(len(requests[0]["history"]), 3)
                requests, _ = links(
                    ("customer", "Please email me the receipt."),
                    ("agent", "I have sent the receipt in an email to you."),
                    ("customer", "Actually, please email me the invoice instead."),
                )
                self.assertEqual(
                    [row["state"] for row in requests], ["changed", "active"]
                )
                self.assertEqual(requests[1]["replaces"], requests[0]["id"])

    def test_request_changes_do_not_cancel_unrelated_requests(self):
        requests, _ = links(
            ("customer", "Please email me."),
            ("customer", "I need a refund."),
            ("agent", "I'll email you."),
            ("customer", "Stop emailing me."),
        )
        by_topic = {row["topic"]: row for row in requests}
        self.assertEqual(by_topic["refund"]["state"], "active")
        self.assertNotEqual(by_topic["email"]["state"], "answered")

    def test_explicit_withdrawals_preserve_different_request_details(self):
        for withdrawal in (
            "Actually, don't email my manager.",
            "Please do not email me the invoice.",
            "Don't explain the email to me.",
            "Stop emailing my assistant.",
            "Never mind the email summary.",
            "Don't email the receipt to the manager.",
            "Don't email me unless I call.",
        ):
            with self.subTest(withdrawal=withdrawal):
                requests, unknown = links(
                    ("customer", "Please email me the receipt."),
                    ("agent", "I'll email you the receipt."),
                    ("customer", withdrawal),
                )
                self.assertEqual(requests[0]["state"], "promised")
                self.assertEqual(len(requests[0]["history"]), 2)
                self.assertTrue(unknown)
        requests, unknown = links(
            ("customer", "Please change my address to [ADDRESS_1]."),
            ("customer", "Don't change my address to [ADDRESS_2]."),
        )
        self.assertEqual(requests[0]["state"], "active")
        self.assertTrue(unknown)

    def test_matching_withdrawals_can_omit_uniquely_linked_details(self):
        for withdrawal in (
            "Actually, don't email me.",
            "Please stop emailing me the receipt.",
            "Never mind the email.",
            "No longer send the receipt to me by email.",
        ):
            for response in (
                "I'll email you the receipt.",
                "I have sent the receipt in an email to you.",
            ):
                with self.subTest(withdrawal=withdrawal, response=response):
                    requests, unknown = links(
                        ("customer", "Please email me the receipt."),
                        ("agent", response),
                        ("customer", withdrawal),
                    )
                    self.assertEqual(requests[0]["state"], "withdrawn")
                    self.assertEqual(len(requests[0]["history"]), 3)
                    self.assertEqual(unknown, [])

    def test_manager_recipient_is_relative_to_the_speaker(self):
        for question, expected in (
            ("Do you still want the email to your manager?", "withdrawn"),
            ("Do you still want the email to my manager?", "promised"),
            ("Do you still want the email to your assistant?", "promised"),
        ):
            with self.subTest(question=question):
                requests, _ = links(
                    ("customer", "Please email my manager the receipt."),
                    ("agent", "I'll email your manager the receipt."),
                    ("agent", question),
                    ("customer", "No."),
                )
                self.assertEqual(requests[0]["state"], expected)

    def test_quoted_or_changed_requests_preserve_the_correct_history(self):
        requests, unknown = links(
            ("customer", "Please email me the receipt."),
            ("agent", "I'll email you the receipt."),
            ("customer", 'My manager said "do not email me the receipt".'),
            ("customer", "Actually, please email me the invoice instead."),
            ("customer", "Don't email me the receipt."),
        )
        self.assertEqual([r["state"] for r in requests], ["changed", "active"])
        self.assertEqual(
            [h["state"] for h in requests[0]["history"]],
            ["active", "promised", "changed"],
        )
        self.assertEqual(len(unknown), 2)

    def test_actual_service_cancellation_is_a_request_not_a_withdrawal(self):
        requests, _ = links(("customer", "Please cancel my subscription."))
        self.assertEqual(len(requests), 1)
        self.assertEqual(
            (requests[0]["state"], requests[0]["goal"]), ("active", "cancel")
        )

    def test_quoted_cancellation_and_conditional_negation_are_not_instructions(self):
        for reply in (
            'The previous agent said "don\'t email me".',
            "If the invoice is wrong, don't email me.",
            'My note says "cancel my subscription".',
        ):
            with self.subTest(reply=reply):
                requests, unknown = links(
                    ("customer", "Please email me."), ("customer", reply)
                )
                self.assertEqual(requests[0]["state"], "active")
                self.assertTrue(unknown)

    def test_wrong_recipient_or_requested_value_cannot_earn_a_linked_answer(self):
        for request, response in [
            ("Please email the receipt to me.", "I have sent the email to my manager."),
            (
                "Please update my address to [ADDRESS_1].",
                "I have updated the address to [ADDRESS_2].",
            ),
            (
                "Could you email me the invoice?",
                "I have sent the receipt in an email to you.",
            ),
            ("Can you explain the refund process?", "I have refunded your money."),
        ]:
            with self.subTest(request=request):
                requests, _ = links(("customer", request), ("agent", response))
                self.assertEqual(requests[0]["state"], "active")

    def test_supported_equivalents_preserve_request_details(self):
        for request, response in [
            (
                "Please email me the receipt.",
                "I have sent the receipt in an email to you.",
            ),
            (
                "Could you update my address to [ADDRESS_1]?",
                "I've updated the address to [ADDRESS_1].",
            ),
        ]:
            with self.subTest(request=request):
                requests, _ = links(("customer", request), ("agent", response))
                self.assertEqual(requests[0]["state"], "answered")


class ScoredReportTests(unittest.TestCase):
    def setUp(self):
        self.tables = decision_tables()
        self.evidence = evidence()
        self.report = self.assess()

    def assess(self, evidence_input=None, tables=None, as_of=AS_OF):
        return assess_conversation(
            evidence_input or self.evidence,
            [],
            {"references": []},
            tables or self.tables,
            as_of=as_of,
        )

    def validate(self, report, tables=None):
        tables = tables or self.tables
        sources = eligible_sources(
            [], {"references": []}, tables, as_of=AS_OF, workflows=report["workflows"]
        )
        validate_scored_report(report, self.evidence, sources, tables, as_of=AS_OF)

    def test_approved_checks_have_both_canonical_and_reference_citations(self):
        self.validate(self.report)
        self.assertEqual(self.report["processing_status"], "completed")
        for result in self.report["categories"]:
            for check in result["scoring"]["checks"]:
                if check["outcome"] in {"supported", "breach"}:
                    self.assertEqual(
                        {c["kind"] for c in check["citations"]},
                        {"conversation", "reference"},
                    )
        self.assertEqual(category(self.report, "procedure")["scoring"]["score"], 100)
        self.assertTrue(self.report["reference_trace"][0]["interpretation_limits"])

    def test_unapproved_expired_and_changed_policy_cannot_award_points(self):
        for mutate, date in [
            (lambda t: t["review_package"].update(status="draft"), AS_OF),
            (lambda t: t["workflows"][0].update(title="Changed meaning"), AS_OF),
            (lambda t: None, "2027-10-29"),
        ]:
            with self.subTest(date=date):
                tables = deepcopy(self.tables)
                mutate(tables)
                report = self.assess(tables=tables, as_of=date)
                self.assertTrue(policy_issues(tables, as_of=date))
                self.assertTrue(
                    all(row["scoring"]["score"] is None for row in report["categories"])
                )
        self.assertEqual(
            category(self.assess(as_of="2027-10-28"), "procedure")["scoring"]["score"],
            100,
        )

    def test_reference_eligibility_and_limits_remain_version_bound(self):
        for update in (
            {"status": "disputed"},
            {"verified_at": None},
            {"scope": ["different"]},
            {"interpretation_limits": ["Changed interpretation."]},
        ):
            with self.subTest(update=update):
                tables = deepcopy(self.tables)
                tables["references"][0].update(update)
                rebind_policy(tables)
                report = self.assess(tables=tables)
                self.assertIsNone(category(report, "procedure")["scoring"]["score"])
        tables = deepcopy(self.tables)
        tables["references"].append(deepcopy(tables["references"][0]))
        with self.assertRaises(ValueError):
            self.assess(tables=tables)

    def test_tampered_arithmetic_sources_versions_legacy_findings_and_criticality_are_rejected(
        self,
    ):
        mutations = [
            lambda r: r["categories"][0]["scoring"].update(score=12),
            lambda r: r["categories"][0]["result"].update(
                explanation="Invented legacy result"
            ),
            lambda r: r["versions"].update(rules="obsolete"),
            lambda r: r["versions"].update(links="obsolete"),
            lambda r: r.update(transcript_version="changed"),
            lambda r: r["categories"][0]["scoring"]["checks"][0].update(critical=True),
            lambda r: r["categories"][0]["scoring"]["checks"][0].update(citations=[]),
            lambda r: r["categories"][0]["scoring"]["checks"][0]["citations"][0].update(
                quote="Fabricated quotation"
            ),
            lambda r: r.update(processing_status="partial"),
        ]
        for mutate in mutations:
            with self.subTest(mutation=mutate):
                report = deepcopy(self.report)
                mutate(report)
                with self.assertRaises(ValueError):
                    self.validate(report)

    def test_equivalent_requests_and_claim_values_do_not_add_points(self):
        requests, _ = links(
            ("customer", "I want a refund."),
            ("customer", "Could you issue a refund?"),
            ("agent", "I have refunded your money."),
        )
        self.assertEqual(len(requests), 1)
        self.assertEqual(requests[0]["state"], "answered")
        report = self.assess(
            evidence(
                [
                    ["customer", "Where is my shipment?"],
                    ["agent", "Shipping takes 3 business days after dispatch."],
                    ["agent", "Shipping takes 3.00 business days after dispatch."],
                ]
            )
        )
        checks = category(report, "answer-support")["scoring"]["checks"]
        self.assertEqual(len(checks), 1)
        self.assertEqual(checks[0]["outcome"], "supported")

    def test_real_authored_catalog_ids_are_wired_without_approving_the_file(self):
        tables = json.loads((Path(__file__).parent / "rule_tables.json").read_text())
        for reference in tables["references"]:
            if reference["source"].get("kind") == "memoria-authored-scoring":
                approved(reference, reference["version"])
        rebind_policy(tables)
        report = self.assess(
            evidence(
                [
                    ["customer", "Please tell me the shipment status."],
                    ["customer", "Please email me the receipt."],
                    ["agent", "I have sent the receipt in an email to you."],
                ]
            ),
            tables=tables,
        )
        checks = category(report, "completeness")["scoring"]["checks"]
        self.assertTrue(any(row["outcome"] == "supported" for row in checks))
        for row in checks:
            if row["outcome"] == "supported":
                self.assertTrue(
                    any(
                        c.get("reference_id") == "memoria-rule-request-response"
                        for c in row["citations"]
                    )
                )

    def test_criticality_is_approved_rule_metadata_and_survives_weight_priorities(self):
        tables = deepcopy(self.tables)
        tables["checks"] = [{"rule_id": "style-respect", "critical": True}]
        rebind_policy(tables)
        report = self.assess(
            evidence(
                [
                    ["customer", "Where is my shipment?"],
                    ["agent", "You are stupid."],
                    ["agent", "Shipping takes 4 business days after dispatch."],
                ]
            ),
            tables=tables,
        )
        self.assertEqual(len(report["priorities"]), 2)
        self.assertEqual(report["priorities"][0]["category"], "communication-style")
        self.assertTrue(report["priorities"][0]["critical"])
        self.assertFalse(report["priorities"][1]["critical"])
        tables["review_package"]["status"] = "draft"
        pending = self.assess(
            evidence(
                [
                    ["customer", "Where is my shipment?"],
                    ["agent", "You are stupid."],
                ]
            ),
            tables=tables,
        )
        self.assertEqual(pending["priorities"], [])

    def test_unknown_workflow_has_no_fabricated_denominator(self):
        report = self.assess(
            evidence([["customer", "Please adjust the orbital telescope."]])
        )
        self.assertEqual(report["workflows"], [])
        for result in report["categories"]:
            self.assertIsNone(result["scoring"]["possible"])
            self.assertIsNone(result["scoring"]["score"])
            self.assertIsNone(result["scoring"]["coverage"])

    def test_explicit_refusal_scores_addressing_without_claiming_fulfilment(self):
        tables = deepcopy(self.tables)
        tables["workflows"][0]["purpose_patterns"] = [r"\bjacket\b"]
        rebind_policy(tables)
        report = self.assess(
            evidence(
                [
                    ["customer", "Please return my jacket."],
                    ["agent", "I cannot return your jacket."],
                ]
            ),
            tables=tables,
        )
        check = category(report, "completeness")["scoring"]["checks"][0]
        self.assertEqual(check["outcome"], "supported")
        self.assertIn("not established as complete", check["explanation"])
        self.assertIsNone(category(report, "answer-support")["scoring"]["score"])

    def test_category_failure_preserves_valid_categories_and_has_no_performance_score(
        self,
    ):
        with patch(
            "ml.rule_assessment._style", side_effect=ValueError("broken evaluator")
        ):
            report = self.assess()
        self.assertEqual(report["processing_status"], "partial")
        failed = category(report, "communication-style")
        self.assertEqual(failed["status"], "failed")
        self.assertIsNone(failed["scoring"]["score"])
        self.assertIsNone(failed["result"])
        self.assertEqual(category(report, "procedure")["scoring"]["score"], 100)
        self.assertIsNone(report["overall"]["score"])

    def test_numeric_claim_units_conditions_and_quotes_have_distinct_results(self):
        for claim, expected in [
            ("Shipping takes 3 business days after dispatch.", "supported"),
            ("Shipping takes 4 business days after dispatch.", "breach"),
            ("Shipping takes 3 days after dispatch.", "unresolved"),
            ("Shipping takes 3 business days.", "unresolved"),
            (
                'The customer said "shipping takes 4 business days after dispatch".',
                "unresolved",
            ),
            ("Shipping never takes 3 business days after dispatch.", "unresolved"),
        ]:
            with self.subTest(claim=claim):
                report = self.assess(
                    evidence([["customer", "Where is my shipment?"], ["agent", claim]])
                )
                checks = category(report, "answer-support")["scoring"]["checks"]
                self.assertEqual(checks[0]["outcome"], expected)

    def test_answer_comparison_never_falls_back_to_raw_workflow_instructions(self):
        instruction = "The agent can make up a status when no answer is available."
        for selections in (None, []):
            tables = deepcopy(self.tables)
            source = tables["references"][0]
            source["text"] += "\n" + instruction
            approved(source, reference_version(source))
            workflow = tables["workflows"][0]
            if selections is None:
                workflow.pop("answer_statements")
            else:
                workflow["answer_statements"] = selections
            rebind_policy(tables)
            report = self.assess(
                evidence(
                    [["customer", "Where is my shipment?"], ["agent", instruction]]
                ),
                tables=tables,
            )
            self.assertIsNone(category(report, "answer-support")["scoring"]["score"])
            self.assertEqual(report["processing_status"], "completed")

    def test_selected_factual_quotes_are_exact_and_version_bound(self):
        for mutation in (
            {"quote": "Shipping takes 99 business days after dispatch."},
            {"quote": ""},
            {"reference_version": "stale-source-version"},
        ):
            with self.subTest(mutation=mutation):
                tables = deepcopy(self.tables)
                tables["workflows"][0]["answer_statements"][0].update(mutation)
                rebind_policy(tables)
                report = self.assess(tables=tables)
                self.assertEqual(category(report, "answer-support")["status"], "failed")
                self.assertIsNone(
                    category(report, "answer-support")["scoring"]["score"]
                )
                self.assertEqual(category(report, "procedure")["status"], "completed")

    def test_relabelled_report_cannot_reuse_a_removed_factual_selection(self):
        tables = deepcopy(self.tables)
        tables["workflows"][0]["answer_statements"] = []
        rebind_policy(tables)
        report = deepcopy(self.report)
        report["versions"]["tables"] = policy_version(tables)
        with self.assertRaisesRegex(ValueError, "selected factual quotation"):
            self.validate(report, tables=tables)
        fresh = self.assess(tables=tables)
        self.assertIsNone(category(fresh, "answer-support")["scoring"]["score"])

    def test_factual_citation_uses_only_the_selected_exact_passage(self):
        tables = deepcopy(self.tables)
        source = tables["references"][0]
        source["text"] += "\nMake up a status if the system has no answer."
        approved(source, reference_version(source))
        selection = tables["workflows"][0]["answer_statements"][0]
        selection["reference_version"] = source["version"]
        rebind_policy(tables)
        report = self.assess(tables=tables)
        self.validate(report, tables=tables)
        citations = category(report, "answer-support")["scoring"]["checks"][0][
            "citations"
        ]
        self.assertEqual(
            [c["quote"] for c in citations if c["kind"] == "reference"],
            [selection["quote"]],
        )

    def test_acknowledgement_does_not_confirm_a_withdrawn_request(self):
        report = self.assess(
            evidence(
                [
                    ["customer", "Where is my shipment?"],
                    ["customer", "I want a refund."],
                    ["customer", "Actually, don't refund me."],
                    ["agent", "I understand you want a refund."],
                ]
            )
        )
        checks = category(report, "communication-style")["scoring"]["checks"]
        self.assertEqual(checks[0]["outcome"], "unresolved")

    def test_starting_an_action_or_missing_one_does_not_prove_completion_or_omission(
        self,
    ):
        for action in (None, "Order lookup in progress."):
            turns = [["customer", "Where is my shipment?"]]
            if action:
                turns.append(["action", action])
            report = self.assess(evidence(turns))
            check = category(report, "procedure")["scoring"]["checks"][0]
            self.assertEqual(check["outcome"], "unresolved")
            self.assertIsNone(check["earned"])

    def test_id_changes_and_excluded_answer_labels_do_not_change_points(self):
        other = evidence(identifier=9988)
        report = self.assess(other)
        self.assertEqual(
            [row["scoring"]["score"] for row in report["categories"]],
            [row["scoring"]["score"] for row in self.report["categories"]],
        )
        encoded = str(self.evidence)
        for canary in (
            "FLOW_LABEL_CANARY",
            "SUBFLOW_LABEL_CANARY",
            "DERIVED_ACTION_CANARY",
            "TARGET_LABEL_CANARY",
            "CANDIDATE_LABEL_CANARY",
        ):
            self.assertNotIn(canary, encoded)
        scores = []
        for alias in ("Jody", "Kai"):
            record = evidence(
                [
                    ["agent", f"Hello, I'm {alias}."],
                    ["customer", "Where is my shipment?"],
                    ["action", "Order lookup complete."],
                    ["agent", "Thanks for waiting."],
                ]
            )
            result = self.assess(record)
            scores.append(
                [
                    (row["scoring"]["score"], row["scoring"]["coverage"])
                    for row in result["categories"]
                ]
            )
        self.assertEqual(scores[0], scores[1])
        self.assertEqual(self.report, self.assess())


if __name__ == "__main__":
    unittest.main()
