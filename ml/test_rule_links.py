"""Finite information-slot links; an answer is not proof of factual correctness."""

import unittest

from ml.rule_links import request_links


def links(*messages):
    return request_links(
        {
            "events": [
                {"turn_id": index, "kind": "message", "speaker": speaker, "text": text}
                for index, (speaker, text) in enumerate(messages, 1)
            ]
        }
    )


class InformationLinksTests(unittest.TestCase):
    def test_declared_question_equivalents_link_the_same_cost(self):
        for question in (
            "How much does standard shipping cost?",
            "What is the cost of standard shipping?",
            "Could you tell me how much standard shipping costs?",
            "I wanted to know what is the price of standard shipping?",
        ):
            with self.subTest(question=question):
                requests, _ = links(
                    ("customer", question), ("agent", "Standard shipping costs $8.")
                )
                self.assertEqual(len(requests), 1)
                self.assertEqual(requests[0]["state"], "answered")
                self.assertEqual(requests[0]["goal"], "explain")
                self.assertEqual(requests[0]["response_turns"], [2])

    def test_answering_does_not_assert_factual_truth(self):
        requests, _ = links(
            ("customer", "How much is shipping?"), ("agent", "Shipping costs $999.")
        )
        self.assertEqual(requests[0]["state"], "answered")
        self.assertIn(
            "factual correctness is assessed separately",
            requests[0]["history"][-1]["reason"],
        )

    def test_subject_attribute_and_qualifiers_must_match(self):
        for answer in (
            "Overnight shipping costs $8.",
            "Standard shipping takes 3 days.",
            "Standard shipping costs $8 if you are a member.",
            "Standard shipping might cost $8.",
            "Standard shipping does not cost $8.",
            "Standard shipping costs $8?",
        ):
            with self.subTest(answer=answer):
                requests, _ = links(
                    ("customer", "How much does standard shipping cost?"),
                    ("agent", answer),
                )
                self.assertEqual(requests[0]["state"], "active")

    def test_duration_and_date_slots_are_distinct(self):
        for question, answer in (
            (
                "How long does premium membership last?",
                "Premium membership lasts twelve months.",
            ),
            (
                "When is my subscription fee due?",
                "Your subscription fee is due on December 15th.",
            ),
        ):
            with self.subTest(question=question):
                requests, _ = links(("customer", question), ("agent", answer))
                self.assertEqual(requests[0]["state"], "answered")

    def test_short_answers_require_the_actual_preceding_question(self):
        for question, answer in (
            ("How much is shipping?", "$12"),
            ("How long is the extension?", "Three weeks."),
            ("Is the hood detachable?", "No."),
            ("Is the lining removable?", "Yes."),
        ):
            with self.subTest(question=question):
                requests, _ = links(("customer", question), ("agent", answer))
                self.assertEqual(requests[0]["state"], "answered")
                requests, _ = links(
                    ("customer", question),
                    ("agent", "What is your name?"),
                    ("customer", "A demo alias."),
                    ("agent", answer),
                )
                self.assertEqual(requests[0]["state"], "active")

    def test_short_answers_do_not_cover_multiple_questions(self):
        for question in (
            "Is the hood detachable? Is the lining removable?",
            "Is the hood detachable? Can you lower the price?",
        ):
            requests, _ = links(("customer", question), ("agent", "Yes."))
            self.assertTrue(requests)
            self.assertTrue(all(row["state"] == "active" for row in requests))

    def test_quoted_questions_and_answers_are_not_current_intentions(self):
        requests, _ = links(
            ("customer", 'The customer said "How much is shipping?"'), ("agent", "$8.")
        )
        self.assertEqual(requests, [])
        for answer in ('The agent said "Shipping costs $8."', '"Shipping costs $8."'):
            requests, _ = links(
                ("customer", "How much is shipping?"), ("agent", answer)
            )
            self.assertEqual(requests[0]["state"], "active")

    def test_quoted_qualifiers_and_unresolved_corrections_do_not_disappear(self):
        for question, answer in (
            ('How much is "standard" shipping?', "Shipping costs $8."),
            ("How much is shipping?", '"Standard" shipping costs $8.'),
            (
                "Is the hood detachable?",
                "The hood is detachable. Actually, that is wrong.",
            ),
            ("Is the hood detachable?", "The hood is detachable. Ignore that answer."),
        ):
            requests, _ = links(("customer", question), ("agent", answer))
            self.assertTrue(all(row["state"] != "answered" for row in requests))

    def test_property_negation_is_an_answer_not_a_fault(self):
        requests, _ = links(
            ("customer", "Is the hood detachable?"),
            ("agent", "The hood is not detachable."),
        )
        self.assertEqual(requests[0]["state"], "answered")
        requests, _ = links(
            ("customer", "Is the hood detachable?"),
            ("agent", "The lining is removable."),
        )
        self.assertEqual(requests[0]["state"], "active")

    def test_explicit_replacement_keeps_the_old_answer_history(self):
        requests, _ = links(
            ("customer", "How much is shipping?"),
            ("agent", "Shipping costs $8."),
            ("customer", "Instead, how long does shipping take?"),
            ("agent", "Shipping takes 5 days."),
        )
        self.assertEqual([row["state"] for row in requests], ["changed", "answered"])
        self.assertEqual(
            [row["state"] for row in requests[0]["history"]],
            ["active", "answered", "changed"],
        )
        self.assertEqual(requests[1]["replaces"], requests[0]["id"])

    def test_follow_up_is_not_automatically_a_replacement(self):
        requests, unknown = links(
            ("customer", "How much is shipping?"),
            ("customer", "Actually, how long does shipping take?"),
        )
        self.assertEqual(requests[0]["state"], "active")
        self.assertTrue(unknown)

    def test_prefixes_preserve_transactional_cancellations_and_changes(self):
        requests, _ = links(
            ("customer", "Yes, I would like to email me the receipt."),
            ("agent", "I'll email you the receipt."),
            ("customer", "Actually, don't email me the receipt."),
        )
        self.assertEqual(requests[0]["state"], "withdrawn")
        requests, _ = links(
            ("customer", "Please email me the receipt."),
            ("agent", "I've sent you the receipt email."),
            ("customer", "Actually, please email me the invoice instead."),
        )
        self.assertEqual([r["state"] for r in requests], ["changed", "active"])

    def test_aliases_and_conversation_ids_do_not_select_results(self):
        outputs = []
        for identifier, alias in (
            ("synthetic-alpha", "Robin"),
            ("synthetic-beta", "Taylor"),
        ):
            conversation = {
                "id": identifier,
                "events": [
                    {
                        "turn_id": 1,
                        "kind": "message",
                        "speaker": "agent",
                        "text": f"Hello, I am {alias}.",
                    },
                    {
                        "turn_id": 2,
                        "kind": "message",
                        "speaker": "customer",
                        "text": "How much is shipping?",
                    },
                    {
                        "turn_id": 3,
                        "kind": "message",
                        "speaker": "agent",
                        "text": "$11.",
                    },
                ],
            }
            outputs.append(request_links(conversation))
        self.assertEqual(outputs[0], outputs[1])
        self.assertEqual(outputs[0][0][0]["state"], "answered")

    def test_short_customer_no_still_is_not_a_blanket_withdrawal(self):
        requests, _ = links(
            ("customer", "Please email me the receipt."),
            ("agent", "I'll email you the receipt."),
            ("agent", "Have you received the email?"),
            ("customer", "No."),
        )
        self.assertEqual(requests[0]["state"], "promised")


class ExpandedInformationTests(unittest.TestCase):
    def test_named_material_color_warranty_status_and_date_answers(self):
        cases = [
            ("What is the jacket made of?", "The jacket is made of cotton and nylon."),
            ("What color are the laces?", "The laces are dark brown."),
            (
                "Do boots come with a warranty?",
                "Our boots come with a 9 month warranty.",
            ),
            ("What is my refund status?", "Your refund is still processing."),
            (
                "Could you tell me when the annual sale ends?",
                "The annual sale ends on Feb. 15th.",
            ),
            ("When my annual fee is due?", "Your annual fee is due tomorrow."),
            (
                "How should I wash the shirt?",
                "You should wash the shirt in cold water.",
            ),
            (
                "What is your return policy?",
                "The return policy depends on your membership level.",
            ),
        ]
        for question, answer in cases:
            with self.subTest(question=question):
                requests, _ = links(("customer", question), ("agent", answer))
                self.assertEqual(requests[0]["state"], "answered")

    def test_named_qualifying_warranty_response_still_only_addresses_question(self):
        requests, _ = links(
            ("customer", "Do boots come with a warranty?"),
            (
                "agent",
                "Our boots come with a 9 month warranty that covers manufacturing defects.",
            ),
        )
        self.assertEqual(requests[0]["state"], "answered")
        self.assertIn("factual correctness", requests[0]["history"][-1]["reason"])

    def test_product_pronoun_uses_only_an_explicit_customer_product(self):
        requests, _ = links(
            ("customer", "I am looking at a Rowan jacket."),
            (
                "customer",
                "Could you tell me the type of materials used in its construction?",
            ),
            ("agent", "Our Rowan jacket is made of cotton and nylon."),
        )
        self.assertEqual(requests[0]["question"]["subject"], "rowan jacket")
        self.assertEqual(requests[0]["state"], "answered")
        for preface in (
            "I am looking at a Rowan jacket and a Cedar shirt.",
            "I am looking at Rowan boots or Cedar boots.",
            'The customer said "I am looking at a Rowan jacket".',
        ):
            requests, _ = links(
                ("customer", preface),
                ("customer", "What is it made of?"),
                ("agent", "Our Rowan jacket is made of cotton."),
            )
            self.assertFalse(any(r["state"] == "answered" for r in requests))

    def test_named_brand_and_attribute_mismatches_remain_unresolved(self):
        for answer in (
            "Our Cedar jacket is made of cotton.",
            "Our Rowan jacket costs $30.",
            "Our Rowan jacket is made of cotton unless it is on sale.",
            "Our Rowan jacket is not made of cotton.",
            'The agent said "Our Rowan jacket is made of cotton."',
        ):
            requests, _ = links(
                ("customer", "I am looking at a Rowan jacket."),
                ("customer", "What is it made of?"),
                ("agent", answer),
            )
            self.assertFalse(any(r["state"] == "answered" for r in requests))

    def test_generic_policy_and_care_words_are_not_an_answer(self):
        for question, answer in (
            ("What is the return policy?", "The return policy is interesting."),
            ("How should I wash the shirt?", "Wash the shirt with care."),
            ("What is my refund status?", "Refunds are very important."),
        ):
            requests, _ = links(("customer", question), ("agent", answer))
            self.assertEqual(requests[0]["state"], "active")

    def test_following_feedback_question_does_not_hide_prior_named_answer(self):
        requests, _ = links(
            ("customer", "What is my refund status?"),
            (
                "agent",
                "Your refund is processing. Is there anything else I can help with?",
            ),
        )
        self.assertEqual(requests[0]["state"], "answered")
        requests, _ = links(
            ("customer", "What is my refund status?"),
            ("agent", "Your refund is processing?"),
        )
        self.assertEqual(requests[0]["state"], "active")

    def test_one_answer_does_not_resolve_two_independent_attributes(self):
        requests, _ = links(
            ("customer", "What is the jacket made of? What color is the jacket?"),
            ("agent", "The jacket is made of cotton."),
        )
        self.assertEqual([r["state"] for r in requests], ["answered", "active"])

    def test_information_short_reply_remains_ambiguous_after_other_question(self):
        requests, _ = links(
            ("customer", "What color are the laces?"),
            ("agent", "Do you want the wider boots?"),
            ("customer", "Yes."),
            ("agent", "Brown."),
        )
        self.assertEqual(requests[0]["state"], "active")

    def test_passive_action_claim_is_addressing_only(self):
        requests, _ = links(
            ("customer", "Please return my jacket."),
            ("agent", "The return has been initiated. Is there anything else?"),
        )
        self.assertEqual(requests[0]["state"], "answered")
        self.assertIn(
            "not proof of completed action", requests[0]["history"][-1]["reason"]
        )

    def test_mixed_cancel_and_refund_requests_do_not_share_completion(self):
        requests, _ = links(
            ("customer", "I would like to cancel the order and get a refund."),
            ("agent", "I went ahead and canceled your order."),
        )
        self.assertEqual([r["goal"] for r in requests], ["cancel", "refund"])
        self.assertEqual([r["state"] for r in requests], ["answered", "active"])

    def test_question_about_cancellation_does_not_execute_it(self):
        requests, _ = links(
            (
                "customer",
                "Please tell me whether I should cancel the order and get a refund.",
            ),
            ("agent", "I went ahead and canceled your order."),
        )
        self.assertFalse(any(r["state"] == "answered" for r in requests))

    def test_refusal_must_match_the_explicit_product_target(self):
        for answer, expected in (
            ("I cannot return your jacket.", "refused"),
            ("I cannot return your boots.", "active"),
            ('The agent said "I cannot return your jacket."', "active"),
            ("I cannot return your jacket if it is damaged.", "active"),
        ):
            requests, _ = links(
                ("customer", "Please return my jacket."), ("agent", answer)
            )
            self.assertEqual(requests[0]["state"], expected)

    def test_quoted_product_cannot_retarget_a_pronoun_after_existing_context(self):
        requests, _ = links(
            ("customer", "I am buying Cedar boots."),
            ("customer", 'The other customer said "I bought a Rowan jacket."'),
            ("customer", "What is it made of?"),
            ("agent", "The Rowan jacket is made of cotton."),
        )
        self.assertFalse(any(r["state"] == "answered" for r in requests))
        self.assertFalse(
            any(
                r.get("question", {}).get("subject") == "rowan jacket"
                for r in requests
                if r.get("question")
            )
        )

    def test_inherited_product_subject_retains_its_canonical_antecedent(self):
        requests, _ = links(
            ("customer", "I am buying a Cedar jacket."),
            ("customer", "What is it made of?"),
            ("agent", "The Cedar jacket is made of cotton."),
        )
        answered = next(row for row in requests if row["state"] == "answered")
        self.assertEqual(answered["context_turn_ids"], [1])


if __name__ == "__main__":
    unittest.main()


class ContextualEquivalentTests(unittest.TestCase):
    def test_declarative_questions_and_immediate_pronoun_answers(self):
        for question, answer in (
            (
                "Could you tell me when the annual sale expires?",
                "The annual sale expires tomorrow.",
            ),
            (
                "What is the return policy you offer?",
                "The policy on returns requires a valid receipt.",
            ),
            ("How much shipping costs?", "It costs $17."),
            ("Is the lining removable?", "It is not removable."),
            ("What the boots are made from?", "They are made from leather."),
        ):
            with self.subTest(question=question):
                requests, _ = links(("customer", question), ("agent", answer))
                self.assertEqual(requests[0]["state"], "answered")
                self.assertEqual(requests[0]["response_turns"], [2])

    def test_pronoun_does_not_jump_a_different_question_or_quote(self):
        for intervening in (
            ("customer", "What is the status of my order?"),
            ("agent", "What is your name?"),
            ("customer", 'My friend said "Is the lining removable?"'),
        ):
            requests, _ = links(
                ("customer", "Is the lining removable?"),
                intervening,
                ("agent", "It is removable."),
            )
            self.assertEqual(requests[0]["state"], "active")

    def test_product_context_and_canonical_positions(self):
        requests, _ = links(
            ("customer", "I am looking at a jacket."),
            (
                "customer",
                "Could you tell me the type of materials used in its construction?",
            ),
            ("agent", "The jacket is made from wool."),
        )
        request = next(r for r in requests if r.get("question"))
        self.assertEqual(request["context_turn_ids"], [1])
        self.assertEqual(request["response_turns"], [3])

    def test_reply_no_is_answer_not_customer_withdrawal(self):
        requests, _ = links(("customer", "Is the hood removable?"), ("agent", "No."))
        self.assertEqual(requests[0]["state"], "answered")
        for question in (
            "Do you still want me to email you the invoice?",
            "Do you have your account number?",
        ):
            requests, _ = links(
                ("customer", "Please email me the invoice."),
                ("agent", "I'll email you the invoice."),
                ("agent", question),
                ("customer", "No."),
            )
            self.assertEqual(
                requests[0]["state"],
                "withdrawn" if "still want" in question else "promised",
            )

    def test_changes_and_withdrawals_after_answer(self):
        for change, state in (
            ("Actually, please email me the receipt instead.", "changed"),
            ("Please don't email me the invoice.", "withdrawn"),
        ):
            requests, _ = links(
                ("customer", "Please email me the invoice."),
                ("agent", "I've sent the invoice to you by email."),
                ("customer", change),
            )
            self.assertEqual(requests[0]["state"], state)
        requests, _ = links(
            ("customer", "Please email me the invoice."),
            ("customer", 'My friend said "Please don\'t email me the invoice."'),
        )
        self.assertEqual(requests[0]["state"], "active")


class ExtensionDispositionTests(unittest.TestCase):
    def test_explicit_extension_refusal_addresses_but_does_not_justify(self):
        for answer in (
            "Your account does not qualify for an extension at this time.",
            "I cannot extend your subscription.",
            "I am sorry Mr. [PERSON_4], but your account does not qualify for an extension.",
        ):
            requests, _ = links(
                ("customer", "Could I get an extension on my subscription?"),
                ("agent", answer),
            )
            self.assertEqual(requests[0]["state"], "refused")
        for answer in (
            'The guide says "I cannot extend your subscription."',
            "I cannot cancel your subscription.",
        ):
            requests, _ = links(
                ("customer", "Can I have an extension on my subscription?"),
                ("agent", answer),
            )
            self.assertEqual(requests[0]["state"], "active")


class PolicyAndUnavailableLinkTests(unittest.TestCase):
    def test_conditional_question_is_not_an_instruction_to_cancel(self):
        for request in (
            "What happens if I cancel my subscription?",
            "I want to buy a coat but what happens if I cancel my subscription?",
        ):
            requests, _ = links(
                ("customer", request),
                (
                    "agent",
                    "If you cancel your subscription, you retain access. Your subscription ends on the end of next month.",
                ),
            )
            policy = next(r for r in requests if r.get("question"))
            self.assertEqual(policy["goal"], "explain")
            self.assertEqual(policy["question"]["attribute"], "cancellation")
            self.assertEqual(policy["state"], "answered")

    def test_policy_conditions_cannot_attach_to_a_different_question(self):
        for answer in (
            "If you upgrade your subscription, you gain access. Your subscription ends on tomorrow.",
            "When you upgrade, you gain access. Your subscription ends on tomorrow.",
            "If you do not cancel your subscription, you retain access. Your subscription ends on tomorrow.",
            'The customer said "Your subscription ends on tomorrow."',
            "The late payment fee is $7 per day.",
        ):
            with self.subTest(answer=answer):
                requests, _ = links(
                    ("customer", "What happens if I cancel my subscription?"),
                    ("agent", answer),
                )
                self.assertEqual(requests[0]["state"], "active")

    def test_late_payment_consequence_keeps_exact_units_and_scope(self):
        for answer in (
            "The late payment fee is €4 per day.",
            "If you are a Bronze member you get a grace period. The late payment fee costs £3 a day.",
        ):
            requests, _ = links(
                (
                    "customer",
                    "Could you tell me what happens if I am late on my subscription payment?",
                ),
                ("agent", answer),
            )
            self.assertEqual(requests[0]["state"], "answered")
            self.assertEqual(requests[0]["response_turns"], [2])
        for answer in (
            "The late payment fee is reasonable.",
            "The late payment fee is $7 per item.",
            "If you order a jacket, you pay a surcharge. The late payment fee is $7 a day.",
        ):
            requests, _ = links(
                ("customer", "What happens if I am late on my subscription payment?"),
                ("agent", answer),
            )
            self.assertEqual(requests[0]["state"], "active")

    def test_inability_requires_the_immediate_unambiguous_question(self):
        for answer in (
            "I cannot find that information.",
            "I can't confirm this information.",
            "That information is not available in the FAQ.",
        ):
            requests, _ = links(
                ("customer", "What is the warranty on boots?"), ("agent", answer)
            )
            self.assertEqual(requests[0]["state"], "refused")
        for messages in (
            [
                ("customer", "What is the warranty on boots?"),
                ("agent", "What is your name?"),
                ("agent", "I cannot find that information."),
            ],
            [
                ("customer", "What is the warranty on boots? How much is shipping?"),
                ("agent", "I cannot find that information."),
            ],
            [
                ("customer", "What is the warranty on boots?"),
                ("agent", 'Someone said "I cannot find that information."'),
            ],
        ):
            requests, _ = links(*messages)
            self.assertTrue(all(r["state"] == "active" for r in requests))

    def test_information_prefixes_preserve_the_requested_subject(self):
        for question in (
            "I'm trying to see when my annual fee is due?",
            "What I want to know is when my annual fee is due?",
        ):
            requests, _ = links(
                ("customer", question),
                ("agent", "Your annual fee is due on February 12th."),
            )
            self.assertEqual(requests[0]["state"], "answered")
        requests, _ = links(
            ("customer", "What I want to know is when my annual fee is due?"),
            ("agent", "Your shipment is due tomorrow."),
        )
        self.assertEqual(requests[0]["state"], "active")

    def test_new_prefix_does_not_turn_no_into_cancellation(self):
        requests, _ = links(
            (
                "customer",
                "What I want to know is is the hood detachable?",
            ),
            ("agent", "No."),
        )
        self.assertEqual(requests[0]["state"], "answered")
