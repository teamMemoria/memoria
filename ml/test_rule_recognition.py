"""Authored clause/context regressions; synthetic approvals authorize no real data."""

import unittest
from collections import Counter

from ml.references import reference_version
from ml.rule_assessment import assess_conversation, workflow_candidates
from ml.test_rule_scoring import (
    AS_OF,
    WORKFLOW,
    approved,
    category,
    decision_tables,
    evidence,
    rebind_policy,
)


class ClauseRecognitionTests(unittest.TestCase):
    def setUp(self):
        self.tables = decision_tables()

    def assess(self, text, *, metric="answer-support", identifier=1234):
        report = assess_conversation(
            evidence(
                [["customer", "Where is my shipment?"], ["agent", text]],
                identifier=identifier,
            ),
            [],
            {"references": []},
            self.tables,
            as_of=AS_OF,
        )
        result = category(report, metric)
        self.assertEqual(result["status"], "completed")
        return result["scoring"]

    def test_exact_fact_after_ordinary_sentence_is_assessed(self):
        result = self.assess(
            "Sounds great. Shipping takes 3 business days after dispatch."
        )
        self.assertEqual(result["score"], 100)
        self.assertEqual(result["assessable"], 1)
        supported = next(c for c in result["checks"] if c["outcome"] == "supported")
        citations = supported["citations"]
        self.assertEqual(
            next(c["quote"] for c in citations if c["kind"] == "reference"),
            "Shipping takes 3 business days after dispatch.",
        )
        self.assertTrue(any(c["kind"] == "conversation" for c in citations))

    def test_decimal_amount_is_not_split_into_sentences(self):
        reference = self.tables["references"][0]
        reference["text"] = "Standard shipping is $8.50."
        approved(reference, reference_version(reference))
        self.tables["workflows"][0]["answer_statements"] = [
            {
                "reference_id": reference["id"],
                "reference_version": reference["version"],
                "quote": reference["text"],
            }
        ]
        rebind_policy(self.tables)
        for amount, score in (("8.50", 100), ("8.75", 0)):
            with self.subTest(amount=amount):
                result = self.assess(
                    f"Here is the price. Standard shipping is ${amount}."
                )
                self.assertEqual(result["score"], score)
                self.assertEqual(result["assessable"], 1)

    def test_two_distinct_claims_keep_supported_and_contradicted_values(self):
        result = self.assess(
            "Shipping takes 3 business days after dispatch. "
            "Shipping takes 8 business days after dispatch."
        )
        self.assertEqual(result["score"], 50)
        self.assertEqual(result["assessable"], 2)
        self.assertCountEqual(
            [c["outcome"] for c in result["checks"]], ["supported", "breach"]
        )
        self.assertEqual(len({c["id"] for c in result["checks"]}), 2)
        for check in result["checks"]:
            self.assertEqual(
                {c["kind"] for c in check["citations"]}, {"conversation", "reference"}
            )

    def test_equivalent_repeated_claim_does_not_earn_extra_points(self):
        result = self.assess(
            "Shipping takes 3 business days after dispatch. "
            "Shipping takes 03 business days after dispatch."
        )
        self.assertEqual(result["assessable"], 1)
        self.assertEqual(result["earned"], 1)

    def test_qualifications_and_corrections_cannot_be_dropped(self):
        statements = [
            "Shipping takes 3 business days after dispatch, unless stock runs out.",
            "Shipping takes 3 business days after dispatch. Except during holidays.",
            "Shipping takes 3 business days after dispatch. Actually, that was wrong.",
            "Shipping takes 3 business days after dispatch. Correction: it takes 8.",
            "Shipping does not take 3 business days after dispatch.",
            "Does shipping take 3 business days after dispatch?",
        ]
        for text in statements:
            with self.subTest(text=text):
                result = self.assess(text)
                self.assertIsNone(result["score"])
                self.assertEqual(result["assessable"], 0)

    def test_quoted_and_reported_assertions_are_not_new_facts(self):
        statements = [
            '"Shipping takes 3 business days after dispatch."',
            'The customer wrote: "Shipping takes 3 business days after dispatch."',
            "The caller said this. Shipping takes 3 business days after dispatch.",
        ]
        for text in statements:
            with self.subTest(text=text):
                self.assertIsNone(self.assess(text)["score"])

    def test_unsupported_neighboring_claim_stays_unresolved(self):
        result = self.assess(
            "Shipping takes 3 business days after dispatch. All deliveries are guaranteed."
        )
        self.assertEqual(result["assessable"], 1)
        self.assertTrue(any(c["outcome"] == "unresolved" for c in result["checks"]))
        self.assertLess(result["coverage"], 100)

    def test_courtesy_and_specific_instruction_are_recognized_as_clauses(self):
        result = self.assess(
            "Thanks for waiting. Please provide your order id.",
            metric="communication-style",
        )
        self.assertEqual(result["earned"], 2)
        self.assertEqual(result["assessable"], 2)

    def test_style_unknown_sentence_is_not_erased_by_courtesy(self):
        result = self.assess(
            "Thanks for your patience. This puzzle has purple corners.",
            metric="communication-style",
        )
        self.assertEqual(result["earned"], 1)
        self.assertTrue(any(c["outcome"] == "unresolved" for c in result["checks"]))
        self.assertLess(result["coverage"], 100)

    def test_quoted_courtesy_and_negated_insult_are_not_awarded_or_penalized(self):
        for text in ('The caller said: "Thanks for waiting."', "You are not stupid."):
            with self.subTest(text=text):
                result = self.assess(text, metric="communication-style")
                self.assertEqual(result["assessable"], 0)

    def test_customer_clause_negation_does_not_erase_a_different_request(self):
        for text in (
            "Please locate my shipment. I no longer need the invoice.",
            "Please locate my shipment because I no longer need the item.",
        ):
            with self.subTest(text=text):
                conversation = evidence([["customer", text]])["conversations"][0]
                self.assertEqual(
                    list(workflow_candidates(conversation, self.tables)), [WORKFLOW]
                )

    def test_negated_or_quoted_purpose_is_not_selected(self):
        for text in (
            "I no longer want a shipment.",
            "I don't want another shipment.",
            'The customer said: "Please locate my shipment."',
        ):
            with self.subTest(text=text):
                conversation = evidence([["customer", text]])["conversations"][0]
                self.assertEqual(workflow_candidates(conversation, self.tables), {})

    def test_bounded_courtesy_equivalents_are_observed_wording_only(self):
        for text in (
            "Thank you very much.",
            "Thanks so much for waiting.",
            "Have a wonderful day.",
        ):
            with self.subTest(text=text):
                result = self.assess(text, metric="communication-style")
                self.assertEqual(result["earned"], 1)
                self.assertEqual(result["assessable"], 1)

    def test_explicit_field_request_equivalents_have_a_concrete_target(self):
        for text in (
            "May I have your order number?",
            "Could you please provide your email address?",
            "Can I get your username and your order id please?",
        ):
            with self.subTest(text=text):
                result = self.assess(text, metric="communication-style")
                self.assertEqual(result["earned"], 1)
                self.assertEqual(result["assessable"], 1)

    def test_unspecified_instruction_and_unrecognized_courtesy_stay_unresolved(self):
        for text in ("Please provide it.", "Thanks for nothing."):
            with self.subTest(text=text):
                result = self.assess(text, metric="communication-style")
                self.assertIsNone(result["score"])
                self.assertEqual(result["assessable"], 0)

    def test_changing_id_or_alias_cannot_change_scoring_outcomes(self):
        signatures = []
        for identifier, alias in ((91001, "Rowan"), (91002, "Taylor")):
            report = assess_conversation(
                evidence(
                    [
                        ["customer", "Where is my shipment?"],
                        ["agent", f"Hello, I'm {alias}. Thanks for waiting."],
                        [
                            "agent",
                            "Sounds good. Shipping takes 3 business days after dispatch.",
                        ],
                    ],
                    identifier=identifier,
                ),
                [],
                {"references": []},
                self.tables,
                as_of=AS_OF,
            )
            signatures.append(
                [
                    (
                        row["category"],
                        row["scoring"]["score"],
                        row["scoring"]["earned"],
                        row["scoring"]["assessable"],
                        Counter(c["outcome"] for c in row["scoring"]["checks"]),
                    )
                    for row in report["categories"]
                ]
            )
        self.assertEqual(signatures[0], signatures[1])

    def test_expanded_courtesy_is_not_acknowledgement_or_an_extra_point(self):
        for text in (
            "You're very welcome.",
            "It is my pleasure.",
            "Good morning.",
            "Have a pleasant weekend.",
        ):
            with self.subTest(text=text):
                result = self.assess(text, metric="communication-style")
                self.assertEqual(result["assessable"], 1)
                self.assertEqual(
                    result["checks"][0]["requirement"], "Express a respectful courtesy"
                )
        result = self.assess(
            "Good morning. You're welcome. Have a pleasant weekend. The purple puzzle continues.",
            metric="communication-style",
        )
        self.assertEqual(result["assessable"], 1)
        self.assertTrue(any(r["outcome"] == "unresolved" for r in result["checks"]))

    def test_field_lists_name_targets_but_do_not_validate_identity(self):
        for text in (
            "Could I also get your username, email and order number please?",
            "What is your membership level?",
            "I'll need your first name or account number.",
        ):
            with self.subTest(text=text):
                result = self.assess(text, metric="communication-style")
                self.assertEqual(result["assessable"], 1)
                self.assertIn(
                    "separate Procedure check", result["checks"][0]["explanation"]
                )
                self.assertEqual(
                    [
                        c["quote"]
                        for c in result["checks"][0]["citations"]
                        if c["kind"] == "conversation"
                    ],
                    [text],
                )

    def test_qualifications_quotes_negation_and_unclear_fields_stay_unresolved(self):
        for text in (
            "Good morning, idiot.",
            "You're welcome for nothing.",
            "I'll need your name and whatever else.",
            "Do not give me your account number.",
            'Repeat "What is your membership level?"',
            "I need your account ID only if you want to pay.",
            "I need your name username.",
        ):
            with self.subTest(text=text):
                result = self.assess(text, metric="communication-style")
                self.assertEqual(result["assessable"], 0)


class ProductContextTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import json
        from pathlib import Path

        cls.tables = json.loads(
            Path(__file__).with_name("rule_tables.json").read_text()
        )

    def signals(self, messages):
        conversation = evidence(messages)["conversations"][0]
        return workflow_candidates(conversation, self.tables)

    def test_product_declaration_and_following_question_keep_both_source_turns(self):
        messages = [
            ["customer", "I am thinking about buying a jacket."],
            ["agent", "What would you like to know?"],
            ["customer", "Is the hood detachable?"],
        ]
        self.assertEqual(
            self.signals(messages), {"single-item-query-jacket-faq": [1, 3]}
        )
        source = evidence(messages)
        report = assess_conversation(
            source, [], {"references": []}, self.tables, as_of=AS_OF
        )
        citations = report["workflow_evidence"]["single-item-query-jacket-faq"]
        self.assertEqual([c["turn_id"] for c in citations], [1, 3])
        self.assertEqual(
            [c["quote"] for c in citations], [messages[0][1], messages[2][1]]
        )
        self.assertEqual(
            {c["transcript_version"] for c in citations},
            {source["conversations"][0]["transcript_version"]},
        )

    def test_product_context_expires_after_an_intervening_customer_topic(self):
        signals = self.signals(
            [
                ["customer", "I am buying a jacket."],
                ["customer", "I need help changing my subscription."],
                ["customer", "Is the hood detachable?"],
            ]
        )
        self.assertNotIn("single-item-query-jacket-faq", signals)

    def test_different_explicit_subject_cannot_inherit_the_previous_product(self):
        for question in (
            "Are these boots waterproof?",
            "Is the car hood detachable?",
        ):
            with self.subTest(question=question):
                signals = self.signals(
                    [["customer", "I am buying a jacket."], ["customer", question]]
                )
                self.assertNotIn("single-item-query-jacket-faq", signals)

    def test_agent_introducing_a_different_product_invalidates_implicit_context(self):
        signals = self.signals(
            [
                ["customer", "I am buying a jacket."],
                ["agent", "Do you want to know whether boots are waterproof?"],
                ["customer", "Is it waterproof?"],
            ]
        )
        self.assertNotIn("single-item-query-jacket-faq", signals)

    def test_negated_conditional_and_quoted_declarations_are_not_antecedents(self):
        declarations = [
            "I am not buying a jacket.",
            "I am no longer buying a jacket.",
            "If I were buying a jacket.",
            'The caller said: "I am buying a jacket."',
        ]
        for declaration in declarations:
            with self.subTest(declaration=declaration):
                signals = self.signals(
                    [["customer", declaration], ["customer", "Is the hood detachable?"]]
                )
                self.assertNotIn("single-item-query-jacket-faq", signals)

    def test_negated_or_reported_property_question_stays_unresolved(self):
        for question in (
            "I do not want to know if the hood is detachable.",
            'The caller said: "Is the hood detachable?"',
        ):
            with self.subTest(question=question):
                self.assertNotIn(
                    "single-item-query-jacket-faq",
                    self.signals(
                        [["customer", "I am buying a jacket."], ["customer", question]]
                    ),
                )

    def test_request_and_reason_or_indirect_question_preserve_workflow(self):
        cases = (
            (
                "I want to return an item because it is the wrong color.",
                "product-defect-return-due-to-color",
            ),
            (
                "I want to check the cost of shipping. It seems too high.",
                "shipping-issue-shipping-cost",
            ),
            (
                "I am wondering if I can get an extension on my subscription.",
                "subscription-inquiry-manage-extension",
            ),
        )
        for message, workflow in cases:
            with self.subTest(message=message):
                self.assertIn(workflow, self.signals([["customer", message]]))

    def test_hypothetical_or_withdrawn_request_cannot_establish_workflow(self):
        for message in (
            "If I wanted to return an item because of the wrong color, what then?",
            "I will return the item if it is the wrong color.",
            "I no longer want to return the item because of the wrong color.",
        ):
            with self.subTest(message=message):
                self.assertNotIn(
                    "product-defect-return-due-to-color",
                    self.signals([["customer", message]]),
                )
        self.assertNotIn(
            "product-defect-initiate-refund",
            self.signals(
                [
                    [
                        "customer",
                        "I would like to get a refund if the shipment does not arrive.",
                    ]
                ]
            ),
        )
