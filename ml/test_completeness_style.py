"""Constructed pattern tests, not human-labelled language-quality evidence."""

import json
import unittest
from copy import deepcopy
from pathlib import Path
from unittest.mock import patch

from ml.abcd import prepare_conversation, transcript_version
from ml.audit import eligible_criteria
from ml.citations import validate_citations
from ml.completeness_style import check_completeness_style
from ml.references import eligible_references, reference_version
from ml.test_evidence import catalog, source_record

CONTEXT = {"as_of": "2026-10-29", "scope": "refund-initiation"}
HUMAN_CASES = (
    {
        "case": "multiple requests",
        "events": [
            ("customer", "I want a refund and please explain the next step."),
            ("agent", "I will process your refund."),
            ("agent", "The next step is to provide your order ID."),
        ],
        "expected": None,
        "reviewed_by": None,
        "reviewed_at": None,
    },
    {
        "case": "withdrawn request",
        "events": [
            ("customer", "I want to return an item."),
            ("customer", "Never mind."),
        ],
        "expected": None,
        "reviewed_by": None,
        "reviewed_at": None,
    },
    {
        "case": "informal equivalent",
        "events": [
            ("customer", "I want a refund."),
            ("agent", "Can you give me your username, email and order ID?"),
            ("agent", "I'll sort your refund."),
            ("agent", "Thank you."),
        ],
        "expected": None,
        "reviewed_by": None,
        "reviewed_at": None,
    },
    {
        "case": "quoted insult",
        "events": [
            ("customer", "I want a refund."),
            ("agent", 'The customer said "You are an idiot."'),
        ],
        "expected": None,
        "reviewed_by": None,
        "reviewed_at": None,
    },
)


def wording_criteria(approved=False):
    sections = json.loads((Path(__file__).parent / "rubric.json").read_text())[
        "references"
    ]
    if approved:
        for section in sections:
            section.update(
                status="approved",
                approved_by="Test reviewer",
                approved_at="2026-10-28",
                verified_at="2026-10-28",
                approved_version=section["version"],
                review_due="2027-10-28",
            )
    return sections


def conversation(*events, turn_ids=None):
    record = source_record()
    record["original"] = [list(event) for event in events]
    record.pop("delexed")
    return prepare_conversation(record, split="train", index=0, turn_ids=turn_ids)


def evaluate(source, criteria=None, **context):
    return check_completeness_style(
        source,
        catalog(),
        wording_criteria() if criteria is None else criteria,
        **(CONTEXT | context),
    )


def positive_conversation(
    promise="I will process your refund.",
    instruction="Please provide your username, email address and order ID.",
):
    return conversation(
        ("customer", "I want a refund."),
        ("agent", "I can help with your refund."),
        ("agent", instruction),
        ("agent", promise),
        ("agent", "Thank you."),
    )


class CompletenessTests(unittest.TestCase):
    def test_promise_addresses_the_request_without_claiming_completion(self):
        completeness, style = evaluate(positive_conversation())
        self.assertEqual(completeness["result"], "meets-criteria")
        request = completeness["details"]["requests"][0]
        self.assertEqual(request["response_kind"], "promise")
        self.assertFalse(request["recorded_completion_observed"])
        self.assertEqual(style["result"], "cannot-assess")
        self.assertFalse(style["findings"])

    def test_capability_and_offer_wording_is_not_a_commitment(self):
        for wording in ("I can process your refund.", "I can help with your refund."):
            with self.subTest(wording=wording):
                completeness, _ = evaluate(
                    conversation(("customer", "I want a refund."), ("agent", wording))
                )
                self.assertEqual(completeness["result"], "cannot-assess")
                request = completeness["details"]["requests"][0]
                self.assertIsNone(request["response_kind"])
                self.assertFalse(request["recorded_completion_observed"])

    def test_multiple_requests_have_independent_response_links(self):
        source = conversation(
            ("customer", "I want a refund and please explain the next step."),
            ("agent", "I will process your refund."),
            ("agent", "The next step is to provide your order ID."),
        )
        completeness, _ = evaluate(source)
        self.assertEqual(completeness["result"], "meets-criteria")
        requests = completeness["details"]["requests"]
        self.assertEqual(
            [request["topic"] for request in requests], ["refund", "next-step"]
        )
        self.assertEqual(
            [request["response_kind"] for request in requests], ["promise", "answer"]
        )
        self.assertEqual(
            [request["response_citations"][0]["turn_id"] for request in requests],
            [2, 3],
        )

    def test_inline_quoted_clauses_do_not_create_requests(self):
        quoted = [
            f"The example sentence is {opening}Hello; I want a refund; goodbye.{closing}"
            for opening, closing in (
                ('"', '"'),
                ("'", "'"),
                ("“", "”"),
                ("‘", "’"),
                ("`", "`"),
                ('""', '""'),
                ("''", "''"),
                ("““", "””"),
                ("``", "``"),
                ("```", "```"),
            )
        ]
        quoted.extend(
            (
                'The example is "Hello and I want a refund and please explain the next step."',
                "The example is “He said 'Hello; I want a refund; goodbye.'”",
                'The example is "Hello \\"friend\\"; I want a refund; goodbye."',
                'The example is "Hello; I want a refund; goodbye.',
                "The example is ‘Hello; I want a refund; goodbye.",
                "The example is ”Hello; I want a refund; goodbye.",
            )
        )
        for text in quoted:
            with self.subTest(text=text):
                completeness, _ = evaluate(
                    conversation(
                        ("customer", text),
                        ("agent", "I will not address your refund request."),
                    )
                )
                self.assertEqual(completeness["result"], "cannot-assess")
                self.assertEqual(completeness["details"]["requests"], [])
                self.assertFalse(completeness["findings"])

    def test_inline_quotes_preserve_independent_unquoted_requests_and_faults(self):
        example = 'The example is "Hello; I want to return an item; goodbye."'
        for text in (
            f"I'd like a refund; {example}",
            f"{example}; I’d like a refund.",
            f"{example} and I want a refund.",
        ):
            with self.subTest(text=text):
                completeness, _ = evaluate(
                    conversation(
                        ("customer", text),
                        ("agent", "I will not address your refund request."),
                    )
                )
                self.assertEqual(completeness["result"], "needs-review")
                requests = completeness["details"]["requests"]
                self.assertEqual([request["topic"] for request in requests], ["refund"])
                self.assertEqual(
                    [
                        cite["turn_id"]
                        for cite in completeness["findings"][0]["citations"]
                    ],
                    [1, 2],
                )

    def test_inline_quoted_changes_do_not_mutate_an_actual_request(self):
        for phrase in ("Never mind", "Actually, I want to return an item instead"):
            with self.subTest(phrase=phrase):
                completeness, _ = evaluate(
                    conversation(
                        ("customer", "I want a refund."),
                        ("agent", "I will not address your refund request."),
                        ("customer", f'The example is "Hello; {phrase}; goodbye."'),
                    )
                )
                self.assertEqual(completeness["result"], "needs-review")
                request = completeness["details"]["requests"][0]
                self.assertEqual(request["state"], "active")
                self.assertEqual(request["change_citations"], [])

    def test_assertion_shaped_questions_do_not_address_or_refuse_requests(self):
        for text in (
            "Your refund is in progress?",
            "I will process your refund?",
            "I will not address your refund request?",
            "I have credited your card for $79?",
            "Your refund is $79?",
        ):
            with self.subTest(text=text):
                completeness, _ = evaluate(
                    conversation(("customer", "I want a refund."), ("agent", text))
                )
                self.assertEqual(completeness["result"], "cannot-assess")
                self.assertFalse(completeness["findings"])
                request = completeness["details"]["requests"][0]
                self.assertIsNone(request["response_kind"])
                self.assertFalse(request["response_citations"])
        completeness, _ = evaluate(
            conversation(
                ("customer", "I want a refund?"),
                ("agent", "I will not address your refund request."),
            )
        )
        self.assertEqual(completeness["details"]["requests"], [])
        self.assertFalse(completeness["findings"])

    def test_explicit_request_instruction_and_closing_questions_remain_supported(self):
        completeness, style = evaluate(
            conversation(
                ("customer", "Can you issue a refund?"),
                ("agent", "Can you give me your username, email and order ID?"),
                ("agent", "I'll sort your refund."),
                ("agent", "Is there anything else I can help you with?"),
            ),
            wording_criteria(True),
        )
        self.assertEqual(completeness["result"], "meets-criteria")
        self.assertEqual(style["result"], "meets-criteria")

    def test_question_uncertainty_preserves_independent_later_responses(self):
        for response, kind, result in (
            ("I will process your refund.", "promise", "cannot-assess"),
            ("I will not address your refund request.", "refusal", "needs-review"),
        ):
            with self.subTest(response=response):
                completeness, _ = evaluate(
                    conversation(
                        ("customer", "I want a refund."),
                        ("agent", "Your refund is in progress?"),
                        ("agent", response),
                    )
                )
                self.assertEqual(completeness["result"], result)
                request = completeness["details"]["requests"][0]
                self.assertEqual(request["response_kind"], kind)
                self.assertEqual(
                    [cite["turn_id"] for cite in request["response_citations"]], [3]
                )

    def test_promise_is_not_an_answer_to_a_different_question(self):
        source = conversation(
            ("customer", "I want a refund and please explain the next step."),
            ("agent", "I will process your refund."),
        )
        completeness, _ = evaluate(source)
        self.assertEqual(completeness["result"], "cannot-assess")
        self.assertFalse(completeness["findings"])
        self.assertFalse(completeness["details"]["requests"][1]["response_citations"])

    def test_unrecognised_additional_request_prevents_a_blanket_pass(self):
        source = conversation(
            ("customer", "I want a refund."),
            ("agent", "I will process your refund."),
            ("customer", "Please email me the receipt."),
        )
        completeness, _ = evaluate(source)
        self.assertEqual(completeness["result"], "cannot-assess")
        self.assertTrue(completeness["limitations"])
        self.assertFalse(completeness["findings"])

    def test_explicit_withdrawal_is_not_an_unanswered_request(self):
        source = conversation(
            ("customer", "I want a refund."), ("customer", "Never mind.")
        )
        completeness, _ = evaluate(source)
        self.assertEqual(completeness["result"], "meets-criteria")
        request = completeness["details"]["requests"][0]
        self.assertEqual(request["state"], "withdrawn")
        self.assertEqual(request["change_citations"][0]["turn_id"], 2)

    def test_ambiguous_withdrawal_never_guesses_which_request_changed(self):
        source = conversation(
            ("customer", "I want a refund and please explain the next step."),
            ("customer", "Never mind."),
        )
        completeness, _ = evaluate(source)
        self.assertEqual(completeness["result"], "cannot-assess")
        self.assertEqual(
            [request["state"] for request in completeness["details"]["requests"]],
            ["uncertain", "uncertain"],
        )

    def test_unsupported_changes_block_both_positive_and_negative_attachment(self):
        changes = (
            "Actually, please do not issue the refund.",
            "Actually, forget the refund.",
            "I mean do not refund it.",
            "Actually, the request needs a different outcome.",
        )
        for change in changes:
            for response in (
                "I will not address your refund request.",
                "I will process your refund.",
                "Your refund is in progress.",
            ):
                with self.subTest(change=change, response=response):
                    completeness, _ = evaluate(
                        conversation(
                            ("customer", "I want a refund."),
                            ("customer", change),
                            ("agent", response),
                        )
                    )
                    self.assertEqual(completeness["result"], "cannot-assess")
                    self.assertFalse(completeness["findings"])
                    request = completeness["details"]["requests"][0]
                    self.assertEqual(request["state"], "uncertain")
                    self.assertEqual(request["response_citations"], [])
                    self.assertEqual(request["change_citations"][0]["turn_id"], 2)
                    self.assertIn("unresolved", completeness["limitations"][0])

    def test_ambiguous_change_cannot_guess_among_multiple_active_requests(self):
        completeness, _ = evaluate(
            conversation(
                ("customer", "I want a refund and I want to return an item."),
                ("customer", "Actually, that needs a different outcome."),
                ("agent", "I will not address your refund request."),
                ("agent", "I will process your return."),
            )
        )
        self.assertEqual(completeness["result"], "cannot-assess")
        self.assertFalse(completeness["findings"])
        for request in completeness["details"]["requests"]:
            self.assertEqual(request["state"], "uncertain")
            self.assertFalse(request["response_citations"])

    def test_truncated_change_cues_are_uncertain_across_clause_boundaries(self):
        for cue in ("Actually.", "Actually,", "I mean...", "I mean"):
            for combined in (False, True):
                with self.subTest(cue=cue, combined=combined):
                    events = (
                        [("customer", "I want a refund; " + cue)]
                        if combined
                        else [("customer", "I want a refund."), ("customer", cue)]
                    )
                    completeness, _ = evaluate(
                        conversation(
                            *events,
                            ("agent", "I will not address your refund request."),
                        )
                    )
                    self.assertEqual(completeness["result"], "cannot-assess")
                    self.assertFalse(completeness["findings"])
                    request = completeness["details"]["requests"][0]
                    self.assertEqual(request["state"], "uncertain")
                    self.assertFalse(request["response_citations"])
                    self.assertEqual(
                        request["change_citations"][0]["turn_id"], 1 if combined else 2
                    )

    def test_change_cues_require_a_complete_word_boundary(self):
        for wording in (
            "Actuallyship the refund.",
            "I meaner a different answer.",
            "This actually matters.",
        ):
            with self.subTest(wording=wording):
                completeness, _ = evaluate(
                    conversation(
                        ("customer", "I want a refund."),
                        ("customer", wording),
                        ("agent", "I will not address your refund request."),
                    )
                )
                self.assertEqual(completeness["result"], "needs-review")
                self.assertEqual(
                    completeness["details"]["requests"][0]["state"], "active"
                )

    def test_customer_clause_boundaries_do_not_change_request_semantics(self):
        cases = (
            (
                ["I want a refund.", "Actually, please do not issue the refund."],
                "I will not address your refund request.",
                "cannot-assess",
            ),
            (
                ["I want a refund.", "I mean please hold off for now."],
                "I will process your refund.",
                "cannot-assess",
            ),
            (
                ["I want a refund.", "Actually, I want to return an item instead."],
                "I will not address your return request.",
                "needs-review",
            ),
            (
                ["I want a refund.", "Cancel the refund request."],
                "I will not address your refund request.",
                "meets-criteria",
            ),
            (
                ["I want a refund.", "I want to return an item.", "Never mind."],
                "I will not address your refund request.",
                "cannot-assess",
            ),
            (
                ["I want a refund.", "Please email me the receipt."],
                "I will not address your refund request.",
                "needs-review",
            ),
        )

        def outcomes(result):
            return (
                result["result"],
                len(result["findings"]),
                [
                    (
                        request["topic"],
                        request["state"],
                        request["response_kind"],
                        request["recorded_completion_observed"],
                    )
                    for request in result["details"]["requests"]
                ],
            )

        for clauses, response, expected in cases:
            separate = conversation(
                *[("customer", clause) for clause in clauses], ("agent", response)
            )
            baseline, _ = evaluate(separate)
            self.assertEqual(baseline["result"], expected)
            for delimiter in ("; ", ";", ";  "):
                with self.subTest(clauses=clauses, delimiter=delimiter):
                    source = conversation(
                        ("customer", delimiter.join(clauses)), ("agent", response)
                    )
                    combined, _ = evaluate(source)
                    self.assertEqual(outcomes(combined), outcomes(baseline))
                    citations = [
                        citation
                        for check in combined["details"]["checks"]
                        for citation in check["citations"]
                    ]
                    self.assertEqual(validate_citations(citations, [source], []), [])
                    for request in combined["details"]["requests"]:
                        self.assertEqual(request["request_citations"][0]["turn_id"], 1)
                        for citation in request["change_citations"]:
                            self.assertEqual(citation["turn_id"], 1)
                            self.assertEqual(
                                citation["quote"], source["events"][0]["text"]
                            )

    def test_quote_guard_precedes_customer_clause_processing(self):
        phrase = "I want a refund; cancel the refund request."
        source = conversation(
            ("customer", "I want a refund."),
            ("agent", "I will not address your refund request."),
            ("agent", "Please repeat the phrase " + phrase),
            ("customer", phrase),
        )
        completeness, _ = evaluate(source)
        self.assertEqual(completeness["result"], "needs-review")
        self.assertEqual(len(completeness["details"]["requests"]), 1)
        request = completeness["details"]["requests"][0]
        self.assertEqual(request["state"], "active")
        self.assertFalse(request["change_citations"])
        self.assertEqual(
            [cite["turn_id"] for cite in completeness["findings"][0]["citations"]],
            [1, 2],
        )

    def test_uncertainty_does_not_erase_an_already_supported_refusal(self):
        completeness, _ = evaluate(
            conversation(
                ("customer", "I want a refund."),
                ("agent", "I will not address your refund request."),
                ("customer", "Actually, this needs a different outcome."),
                ("agent", "I will process your refund."),
            )
        )
        self.assertEqual(completeness["result"], "needs-review")
        request = completeness["details"]["requests"][0]
        self.assertEqual(request["state"], "uncertain")
        self.assertEqual(request["response_kind"], "refusal")
        self.assertEqual(
            [cite["turn_id"] for cite in request["response_citations"]], [2]
        )

    def test_supported_clarification_resolves_uncertain_request_attachment(self):
        completeness, _ = evaluate(
            conversation(
                ("customer", "I want to return an item."),
                ("customer", "Actually, this needs a different outcome."),
                ("customer", "Actually, I want a refund instead."),
                ("agent", "I will process your refund."),
            )
        )
        old, current = completeness["details"]["requests"]
        self.assertEqual((old["state"], current["state"]), ("superseded", "active"))
        self.assertEqual([cite["turn_id"] for cite in old["change_citations"]], [2, 3])
        self.assertEqual(current["response_kind"], "promise")
        self.assertEqual(current["response_citations"][0]["turn_id"], 4)
        self.assertFalse(completeness["findings"])

    def test_separate_later_request_remains_assessable_after_uncertainty(self):
        completeness, _ = evaluate(
            conversation(
                ("customer", "I want a refund."),
                ("customer", "Actually, this needs a different outcome."),
                ("customer", "I want to return an item."),
                ("agent", "I will not address your return request."),
            )
        )
        self.assertEqual(completeness["result"], "needs-review")
        old, current = completeness["details"]["requests"]
        self.assertEqual(old["state"], "uncertain")
        self.assertFalse(old["response_citations"])
        self.assertEqual(current["response_kind"], "refusal")
        self.assertEqual(
            [cite["turn_id"] for cite in completeness["findings"][0]["citations"]],
            [3, 4],
        )

    def test_customer_repetition_cannot_create_withdraw_or_replace_requests(self):
        for phrase in (
            "I want a refund.",
            "Cancel the refund request.",
            "Actually, I want to return an item instead.",
        ):
            for prompt in (
                "Please repeat the phrase ",
                "Can you quote the words: ",
                "Please say this phrase: ",
            ):
                with self.subTest(phrase=phrase, prompt=prompt):
                    completeness, _ = evaluate(
                        conversation(
                            ("customer", "I want a refund."),
                            ("agent", "I will not address your refund request."),
                            ("agent", prompt + phrase),
                            ("customer", phrase),
                        )
                    )
                    self.assertEqual(completeness["result"], "needs-review")
                    requests = completeness["details"]["requests"]
                    self.assertEqual(len(requests), 1)
                    self.assertEqual(requests[0]["state"], "active")
                    self.assertFalse(requests[0]["change_citations"])
                    self.assertEqual(
                        [
                            cite["turn_id"]
                            for cite in completeness["findings"][0]["citations"]
                        ],
                        [1, 2],
                    )

    def test_repeated_customer_request_does_not_establish_actual_intent(self):
        completeness, _ = evaluate(
            conversation(
                ("agent", "Please repeat the phrase I want a refund."),
                ("customer", "I want a refund."),
                ("agent", "I will not address your refund request."),
            )
        )
        self.assertEqual(completeness["result"], "cannot-assess")
        self.assertEqual(completeness["details"]["requests"], [])
        self.assertFalse(completeness["findings"])

    def test_genuine_request_after_customer_repetition_keeps_its_own_evidence(self):
        completeness, _ = evaluate(
            conversation(
                ("agent", "Please repeat the phrase I want a refund."),
                ("customer", "I want a refund."),
                ("agent", "Thank you."),
                ("customer", "I want to return an item."),
                ("agent", "I will not address your return request."),
            )
        )
        self.assertEqual(completeness["result"], "needs-review")
        self.assertEqual(len(completeness["details"]["requests"]), 1)
        self.assertEqual(
            [cite["turn_id"] for cite in completeness["findings"][0]["citations"]],
            [4, 5],
        )

    def test_explicit_replacement_preserves_both_request_sources(self):
        source = conversation(
            ("customer", "I want to return an item."),
            ("customer", "Actually, I want a refund instead."),
            ("agent", "I will process your refund."),
        )
        completeness, _ = evaluate(source)
        self.assertEqual(completeness["result"], "meets-criteria")
        old, current = completeness["details"]["requests"]
        self.assertEqual((old["state"], current["state"]), ("superseded", "active"))
        self.assertEqual(old["change_citations"][0]["turn_id"], 2)
        self.assertEqual(current["request_citations"][0]["turn_id"], 2)

    def test_shipping_clarification_is_preserved_without_guessing_a_new_request(self):
        source = conversation(
            ("customer", "I want to return an item."),
            ("customer", "Actually, the item is not shipped yet."),
            ("agent", "I will process your refund."),
        )
        completeness, _ = evaluate(source)
        self.assertEqual(completeness["result"], "cannot-assess")
        request = completeness["details"]["requests"][0]
        self.assertEqual(request["topic"], "return")
        self.assertEqual(request["change_citations"][0]["turn_id"], 2)

    def test_direct_nonaddressing_finding_has_request_and_agent_evidence(self):
        source = conversation(
            ("customer", "I want a refund."),
            ("agent", "I will not address your refund request."),
        )
        completeness, _ = evaluate(source)
        self.assertEqual(completeness["result"], "needs-review")
        self.assertEqual(
            [cite["turn_id"] for cite in completeness["findings"][0]["citations"]],
            [1, 2],
        )

    def test_reported_or_repeated_refusal_does_not_attach_to_an_active_request(self):
        refusal = "I will not address your refund request."
        cases = (
            (("agent", "The customer said:"), ("agent", refusal)),
            (("agent", "The caller wrote:"), ("agent", refusal)),
            (("agent", refusal), ("agent", "I was quoting the customer.")),
            (
                ("customer", "Please repeat the phrase " + refusal),
                ("agent", refusal),
            ),
            (
                ("agent", "The customer said:"),
                ("action", "Purchase validation in progress ..."),
                ("agent", refusal),
            ),
        )
        for events in cases:
            with self.subTest(events=events):
                source = conversation(("customer", "I want a refund."), *events)
                completeness, _ = evaluate(source)
                self.assertEqual(completeness["result"], "cannot-assess")
                self.assertFalse(completeness["findings"])
                request = completeness["details"]["requests"][0]
                self.assertIsNone(request["response_kind"])
                self.assertEqual(request["response_citations"], [])
                inventory = completeness["details"]["checks"][-1]
                self.assertIn("reported/repeated", inventory["explanation"])
                self.assertEqual(
                    {cite["turn_id"] for cite in inventory["citations"]},
                    {
                        event["turn_id"]
                        for event in source["events"]
                        if event["kind"] != "action" and event["turn_id"] > 1
                    },
                )

    def test_reported_refusal_does_not_suppress_an_independent_later_refusal(self):
        source = conversation(
            ("customer", "I want a refund."),
            (
                "customer",
                "Please repeat the phrase I will not address your refund request.",
            ),
            ("agent", "I will not address your refund request."),
            ("agent", "Thank you."),
            ("agent", "I won't address your refund request."),
        )
        completeness, _ = evaluate(source)
        self.assertEqual(completeness["result"], "needs-review")
        request = completeness["details"]["requests"][0]
        self.assertEqual(request["response_kind"], "refusal")
        self.assertEqual(
            [cite["turn_id"] for cite in request["response_citations"]], [5]
        )
        self.assertEqual(
            [cite["turn_id"] for cite in completeness["findings"][0]["citations"]],
            [1, 5],
        )

    def test_reported_responses_cannot_address_a_request_or_clear_a_refusal(self):
        for wording in (
            "I will process your refund.",
            "I will refund it to your credit card.",
            "Your refund is in progress.",
            "I have credited your card for $79.",
        ):
            contexts = (
                (("agent", "The customer said:"), ("agent", wording)),
                (("agent", wording), ("agent", "I was quoting the customer.")),
                (
                    ("customer", "Please repeat the phrase " + wording),
                    ("agent", wording),
                ),
            )
            for events in contexts:
                for prior_refusal in (False, True):
                    with self.subTest(
                        wording=wording, events=events, prior_refusal=prior_refusal
                    ):
                        prefix = [("customer", "I want a refund.")]
                        if prior_refusal:
                            prefix.append(
                                ("agent", "I will not address your refund request.")
                            )
                        completeness, _ = evaluate(conversation(*prefix, *events))
                        request = completeness["details"]["requests"][0]
                        self.assertEqual(
                            completeness["result"],
                            "needs-review" if prior_refusal else "cannot-assess",
                        )
                        self.assertEqual(
                            request["response_kind"],
                            "refusal" if prior_refusal else None,
                        )
                        self.assertEqual(
                            [cite["turn_id"] for cite in request["response_citations"]],
                            [2] if prior_refusal else [],
                        )
                        if prior_refusal:
                            self.assertEqual(
                                [
                                    cite["turn_id"]
                                    for cite in completeness["findings"][0]["citations"]
                                ],
                                [1, 2],
                            )
                        else:
                            self.assertFalse(completeness["findings"])
                        self.assertIn(
                            "reported/repeated",
                            completeness["details"]["checks"][-1]["explanation"],
                        )

    def test_genuine_later_response_can_resolve_a_refusal_after_reported_speech(self):
        source = conversation(
            ("customer", "I want a refund."),
            ("agent", "I will not address your refund request."),
            ("agent", "The customer said:"),
            ("agent", "I will process your refund."),
            ("agent", "I was quoting the customer."),
            ("agent", "I will process your refund."),
        )
        completeness, _ = evaluate(source)
        request = completeness["details"]["requests"][0]
        self.assertEqual(request["response_kind"], "promise")
        self.assertEqual(
            [cite["turn_id"] for cite in request["response_citations"]], [2, 6]
        )
        self.assertEqual(
            completeness["details"]["checks"][0]["result"], "meets-criteria"
        )
        self.assertFalse(completeness["findings"])
        self.assertEqual(completeness["result"], "cannot-assess")

    def test_customer_quote_block_does_not_mutate_request_inventory(self):
        source = conversation(
            ("customer", "I want a refund."),
            ("agent", "I will not address your refund request."),
            ("customer", "The agent said:"),
            ("customer", "I want to return an item."),
            ("customer", "Cancel the refund request."),
            ("customer", "Actually, I want a refund instead."),
            ("customer", "Those were the agent's words."),
        )
        completeness, _ = evaluate(source)
        self.assertEqual(completeness["result"], "needs-review")
        requests = completeness["details"]["requests"]
        self.assertEqual(len(requests), 1)
        self.assertEqual(requests[0]["state"], "active")
        self.assertFalse(requests[0]["change_citations"])
        self.assertEqual(
            [cite["turn_id"] for cite in completeness["findings"][0]["citations"]],
            [1, 2],
        )

    def test_later_explicit_response_can_address_the_same_previously_refused_request(
        self,
    ):
        source = conversation(
            ("customer", "I want a refund."),
            ("agent", "I will not address your refund request."),
            ("agent", "I will process your refund."),
        )
        completeness, _ = evaluate(source)
        self.assertEqual(completeness["result"], "meets-criteria")
        self.assertEqual(
            len(completeness["details"]["requests"][0]["response_citations"]), 2
        )

    def test_recorded_outcome_differs_from_lookup_and_in_progress_actions(self):
        source = conversation(
            ("customer", "I want a refund."),
            ("action", "Account has been pulled up for Taylor Parker."),
            ("action", "Purchase validation in progress ..."),
            ("agent", "I will process your refund."),
        )
        completeness, _ = evaluate(source)
        self.assertFalse(
            completeness["details"]["requests"][0]["recorded_completion_observed"]
        )
        observed = conversation(
            ("customer", "I want a refund."),
            ("action", "A refund has been made for the amount of $79."),
        )
        completeness, _ = evaluate(observed)
        self.assertEqual(completeness["result"], "meets-criteria")
        request = completeness["details"]["requests"][0]
        self.assertEqual(request["response_kind"], "observed-action")
        self.assertTrue(request["recorded_completion_observed"])

    def test_partial_excerpt_and_missing_actions_are_not_failures(self):
        source = conversation(
            ("customer", "I want a refund."),
            ("agent", "I will process your refund."),
            ("agent", "Thank you."),
            turn_ids=[1, 2],
        )
        completeness, _ = evaluate(source)
        self.assertEqual(completeness["result"], "cannot-assess")
        self.assertFalse(completeness["findings"])
        self.assertEqual(source["coverage"]["actions"]["status"], "unknown")

    def test_amount_alone_does_not_answer_a_refund_method_request(self):
        source = conversation(
            ("customer", "I'd like it to be refunded to my credit card."),
            ("agent", "Your refund is $79."),
        )
        completeness, _ = evaluate(source)
        self.assertEqual(completeness["result"], "cannot-assess")
        self.assertFalse(completeness["details"]["requests"][0]["response_citations"])
        explicit = conversation(
            ("customer", "I'd like it to be refunded to my credit card."),
            ("agent", "I have credited your card for $79."),
        )
        completeness, _ = evaluate(explicit)
        self.assertEqual(completeness["result"], "meets-criteria")
        self.assertFalse(
            completeness["details"]["requests"][0]["recorded_completion_observed"]
        )

    def test_unsupported_scope_abstains_and_stale_transcript_is_rejected(self):
        source = positive_conversation()
        results = evaluate(source, wording_criteria(True), scope="refund-status")
        self.assertEqual(
            [result["result"] for result in results], ["cannot-assess"] * 2
        )
        source["events"][0]["text"] = "Edited without a new version."
        with self.assertRaises(ValueError):
            evaluate(source)


class WordingTests(unittest.TestCase):
    def test_assertion_shaped_questions_do_not_establish_wording_faults(self):
        for text in (
            "You are an idiot?",
            "You're stupid?",
            "Provide your order ID and do not provide your order ID?",
        ):
            with self.subTest(text=text):
                _, style = evaluate(
                    conversation(("customer", "I want a refund."), ("agent", text)),
                    wording_criteria(True),
                )
                self.assertEqual(style["result"], "cannot-assess")
                self.assertFalse(style["findings"])

    def test_approved_test_rubric_supports_only_recognised_positive_wording(self):
        completeness, style = evaluate(positive_conversation(), wording_criteria(True))
        self.assertEqual(completeness["result"], "meets-criteria")
        self.assertEqual(style["result"], "meets-criteria")
        self.assertFalse(style["findings"])

    def test_tested_informal_equivalents_have_the_same_results(self):
        criteria = wording_criteria(True)
        first = evaluate(positive_conversation(), criteria)
        second = evaluate(
            positive_conversation(
                "I'll sort your refund.",
                "Can you give me your username, email and order ID?",
            ),
            criteria,
        )
        self.assertEqual(
            [result["result"] for result in first],
            [result["result"] for result in second],
        )

    def test_direct_insult_is_cited_and_an_apology_does_not_erase_it(self):
        criteria = wording_criteria(True)
        for wording in ("You are an idiot.", "You're stupid."):
            with self.subTest(wording=wording):
                source = conversation(
                    ("customer", "I want a refund."),
                    ("agent", wording),
                    ("agent", "I'm sorry."),
                )
                _, style = evaluate(source, criteria)
                self.assertEqual(style["result"], "needs-review")
                cites = style["findings"][0]["citations"]
                self.assertEqual(
                    {cite["kind"] for cite in cites}, {"reference", "conversation"}
                )
                self.assertTrue(any(cite.get("turn_id") == 2 for cite in cites))

    def test_quotes_reports_and_negation_are_not_direct_insults(self):
        criteria = wording_criteria(True)
        for wording in (
            'The customer said "You are an idiot."',
            '"You are an idiot."',
            "You are not an idiot.",
            "You're not stupid.",
            "I ain't got that.",
        ):
            with self.subTest(wording=wording):
                _, style = evaluate(
                    conversation(("customer", "I want a refund."), ("agent", wording)),
                    criteria,
                )
                self.assertEqual(style["result"], "cannot-assess")
                self.assertFalse(style["findings"])

    def test_adjacent_quotation_requests_and_reports_are_not_agent_assertions(self):
        criteria = wording_criteria(True)
        cases = (
            (
                ("customer", "Please repeat the phrase you are stupid."),
                ("agent", "You are stupid."),
            ),
            (
                ("customer", "I want a refund."),
                ("agent", "The customer said:"),
                ("agent", "You are an idiot."),
            ),
            (
                ("customer", "I want a refund."),
                ("agent", "You are stupid."),
                ("agent", "I was quoting the customer."),
            ),
            (
                ("customer", "I want a refund."),
                ("agent", "The caller wrote:"),
                ("agent", "Provide your order ID and do not provide your order ID."),
            ),
        )
        for events in cases:
            with self.subTest(events=events):
                _, style = evaluate(conversation(*events), criteria)
                self.assertEqual(style["result"], "cannot-assess")
                self.assertFalse(style["findings"])

    def test_quote_context_does_not_suppress_an_independent_later_insult(self):
        source = conversation(
            ("customer", "Please repeat the phrase you are stupid."),
            ("agent", "You are stupid."),
            ("agent", "Thank you."),
            ("agent", "You are an idiot."),
            ("agent", "I'm sorry."),
        )
        _, style = evaluate(source, wording_criteria(True))
        self.assertEqual(style["result"], "needs-review")
        evidence = [
            cite["turn_id"]
            for finding in style["findings"]
            for cite in finding["citations"]
            if cite["kind"] == "conversation"
        ]
        self.assertEqual(evidence, [4])

    def test_quote_context_does_not_suppress_a_later_contradictory_instruction(self):
        instruction = "Provide your order ID and do not provide your order ID."
        source = conversation(
            ("customer", "I want a refund."),
            ("customer", "Please repeat the phrase " + instruction),
            ("agent", instruction),
            ("agent", "Thank you."),
            ("agent", instruction),
        )
        _, style = evaluate(source, wording_criteria(True))
        self.assertEqual(style["result"], "needs-review")
        clarity = next(
            finding
            for finding in style["findings"]
            if finding["rule_id"].endswith(":clarity")
        )
        self.assertEqual(
            [
                cite["turn_id"]
                for cite in clarity["citations"]
                if cite["kind"] == "conversation"
            ],
            [5],
        )

    def test_explicit_contradictory_instruction_is_not_inferred_from_keywords(self):
        criteria = wording_criteria(True)
        source = conversation(
            ("customer", "I want a refund."),
            ("agent", "Provide your order ID and do not provide your order ID."),
        )
        _, style = evaluate(source, criteria)
        self.assertEqual(style["result"], "needs-review")
        self.assertIn(":clarity", style["findings"][0]["rule_id"])

    def test_partial_or_unrecognised_context_prevents_style_blanket_pass(self):
        criteria = wording_criteria(True)
        source = positive_conversation()
        source["coverage"]["transcript"]["status"] = "partial"
        source["transcript_version"] = transcript_version(source)
        _, style = evaluate(source, criteria)
        self.assertEqual(style["result"], "cannot-assess")
        source = positive_conversation()
        source["events"][-1]["text"] = "A novel but possibly respectful expression."
        source["transcript_version"] = transcript_version(source)
        _, style = evaluate(source, criteria)
        self.assertEqual(style["result"], "cannot-assess")
        self.assertFalse(style["findings"])

    def test_acknowledgement_requires_a_request_active_at_that_turn(self):
        criteria = wording_criteria(True)
        source = conversation(
            ("customer", "I want a refund."),
            ("customer", "Never mind."),
            ("agent", "I can help with your refund."),
            ("agent", "Please provide your username, email and order ID."),
            ("agent", "Thank you."),
        )
        _, style = evaluate(source, criteria)
        acknowledgement = next(
            check
            for check in style["details"]["checks"]
            if check["rule_id"].endswith(":acknowledgement")
        )
        self.assertEqual(acknowledgement["result"], "cannot-assess")
        prior = conversation(
            ("customer", "I want a refund."),
            ("agent", "I can help with your refund."),
            ("agent", "Please provide your username, email and order ID."),
            ("agent", "Thank you."),
            ("customer", "Never mind."),
        )
        _, style = evaluate(prior, criteria)
        acknowledgement = next(
            check
            for check in style["details"]["checks"]
            if check["rule_id"].endswith(":acknowledgement")
        )
        self.assertEqual(acknowledgement["result"], "meets-criteria")

    def test_changed_interpretation_limits_need_a_supported_new_rule_binding(self):
        criteria = wording_criteria(True)
        criteria[1]["interpretation_limits"].append("Additional wording constraint.")
        criteria[1]["version"] = reference_version(criteria[1])
        criteria[1]["approved_version"] = criteria[1]["version"]
        _, style = evaluate(positive_conversation(), criteria)
        self.assertEqual(style["result"], "cannot-assess")
        self.assertTrue(
            any(
                "not supported" in reason
                for state in style["details"]["rubric_states"]
                for reason in state["limitations"]
            )
        )

    def test_expired_missing_and_unapproved_criteria_never_support_findings(self):
        source = conversation(
            ("customer", "I want a refund."), ("agent", "You are an idiot.")
        )
        for criteria, context in (
            ([], {}),
            (wording_criteria(), {}),
            (wording_criteria(True), {"as_of": "2027-10-29"}),
        ):
            with self.subTest(criteria_count=len(criteria), context=context):
                _, style = evaluate(source, criteria, **context)
                self.assertEqual(style["result"], "cannot-assess")
                self.assertFalse(style["findings"])

    def test_all_emitted_citations_use_only_the_eligible_explicit_union(self):
        criteria = wording_criteria(True)
        source = conversation(
            ("customer", "I want a refund."), ("agent", "You are an idiot.")
        )
        results = evaluate(source, criteria)
        sources = eligible_references(catalog(), **CONTEXT) + eligible_criteria(
            criteria, **CONTEXT
        )
        citations = [
            cite
            for result in results
            for check in result["details"]["checks"]
            for cite in check["citations"]
        ]
        self.assertEqual(validate_citations(citations, [source], sources), [])
        reference = next(cite for cite in citations if cite["kind"] == "reference")
        self.assertEqual(
            set(reference),
            {"kind", "reference_id", "reference_version", "section_id", "quote"},
        )
        self.assertTrue(reference["reference_id"].startswith("memoria-"))

    def test_pure_rules_do_not_read_files_or_use_network_and_preserve_inputs(self):
        source, criteria, references = (
            positive_conversation(),
            wording_criteria(True),
            catalog(),
        )
        before = deepcopy((source, criteria, references))
        with (
            patch(
                "pathlib.Path.read_text", side_effect=AssertionError("I/O forbidden")
            ),
            patch("socket.socket", side_effect=AssertionError("Network forbidden")),
        ):
            check_completeness_style(source, references, criteria, **CONTEXT)
        self.assertEqual((source, criteria, references), before)

    def test_new_human_language_judgements_remain_unset(self):
        self.assertTrue(
            all(
                case["expected"] is None
                and case["reviewed_by"] is None
                and case["reviewed_at"] is None
                for case in HUMAN_CASES
            )
        )

    def test_human_language_agreement(self):
        if any(
            case["expected"] is None
            or not case["reviewed_by"]
            or not case["reviewed_at"]
            for case in HUMAN_CASES
        ):
            self.skipTest(
                "New request/wording cases await human judgement; language quality is not evaluated."
            )
        for case in HUMAN_CASES:
            with self.subTest(case=case["case"]):
                results = evaluate(
                    conversation(*case["events"]), wording_criteria(True)
                )
                observed = {result["category"]: result["result"] for result in results}
                self.assertEqual(observed, case["expected"])


if __name__ == "__main__":
    unittest.main()
