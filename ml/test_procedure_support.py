"""Constructed rule tests are not human labels or general-language evaluation."""

import unittest
from copy import deepcopy

from ml.abcd import prepare_conversation
from ml.audit import quotation_context
from ml.citations import validate_citations
from ml.procedure_support import RULE_VERSION, check_procedure_support
from ml.references import eligible_references, reference_version
from ml.test_evidence import catalog, source_record

CONTEXT = {"as_of": "2026-10-29", "scope": "refund-initiation"}


def conversation(events, *, turn_ids=None):
    record = source_record(99991)
    record["original"] = events
    record.pop("delexed")
    return prepare_conversation(record, split="train", index=0, turn_ids=turn_ids)


def supported_steps(method="credit card"):
    detail = (
        "12 Test St  Ottawa, ON A1A1A1"
        if method in {"gift card", "paper check"}
        else "AC98765432"
    )
    events = [
        ["customer", "The item is the wrong size."],
        ["customer", "Taylor Parker."],
        ["action", "Account has been pulled up for Taylor Parker."],
        ["customer", "tparker321 tparker321@example.test ORD1234567"],
        ["action", "Purchase validation succeeded."],
        ["customer", f"I'd like a {method} refund."],
        ["action", f"Details of {detail} have been entered."],
        ["agent", "Can I help with anything else?"],
    ]
    if method in {"gift card", "paper check"}:
        events.insert(6, ["customer", f"My full address is {detail}."])
    return events


HUMAN_CASES = tuple(
    {
        **case,
        "context": dict(CONTEXT),
        "expected": None,
        "reviewed_by": None,
        "reviewed_at": None,
    }
    for case in (
        {
            "case": "valid alternative and volunteered details",
            "events": supported_steps("gift card"),
        },
        {
            "case": "explicit order breach",
            "events": supported_steps()
            + [["agent", "I validated the purchase before the first account lookup."]],
        },
        {
            "case": "no recorded actions",
            "events": [event for event in supported_steps() if event[0] != "action"],
        },
        {
            "case": "direct contradiction and unrelated correction",
            "events": [
                ["agent", "Gift cards do not require an address."],
                [
                    "agent",
                    "Correction: For a paper check refund, we need your full address.",
                ],
            ],
        },
        {
            "case": "explicit correction of a mixed answer",
            "events": [
                ["agent", "Purchase validation requires only an email address."],
                [
                    "agent",
                    "Correction: Purchase validation requires a username, email address and order ID.",
                ],
            ],
        },
        {
            "case": "supported paraphrase and unknown wording",
            "events": [
                [
                    "agent",
                    "We need your username, email and order ID to validate the purchase.",
                ],
                ["agent", "An email alone should do the trick."],
            ],
        },
        {
            "case": "partial excerpt",
            "events": supported_steps(),
            "selected_turn_ids": [3, 4, 5],
        },
    )
)


class ProcedureSupportTests(unittest.TestCase):
    def evaluate(self, events, references=None, **context):
        return check_procedure_support(
            conversation(events),
            catalog() if references is None else references,
            **(CONTEXT | context),
        )

    def test_supported_steps_and_explicit_factual_equivalents(self):
        events = supported_steps() + [
            ["agent", "For a credit card refund, we need your account ID."]
        ]
        before = deepcopy(events)
        results = self.evaluate(events)
        self.assertEqual(
            [result["result"] for result in results],
            ["meets-criteria", "meets-criteria"],
        )
        self.assertEqual(events, before)
        self.assertTrue(RULE_VERSION)
        self.assertIn("identity", results[0]["details"]["checks"][1]["explanation"])
        self.assertTrue(
            all(
                ref["interpretation_limits"]
                for ref in results[0]["details"]["reference_limits"]
            )
        )
        for equivalent in (
            "Purchase validation requires a username, email address and order ID.",
            "We need your username, email and order ID to validate the purchase.",
        ):
            with self.subTest(equivalent=equivalent):
                self.assertEqual(
                    self.evaluate([["agent", equivalent]])[1]["result"],
                    "meets-criteria",
                )

    def test_volunteered_reason_and_selected_address_branch(self):
        result = self.evaluate(supported_steps("gift card"))[0]
        self.assertEqual(result["result"], "meets-criteria")
        checks = {
            check["rule_id"].split(":")[-1]: check
            for check in result["details"]["checks"]
        }
        self.assertIn("no repeated question", checks["refund-reason"]["explanation"])
        self.assertIn("selected-method", checks["refund-details"]["explanation"])
        events = supported_steps("gift card")
        events[7][1] = "Details of AC98765432 have been entered."
        self.assertEqual(self.evaluate(events)[0]["result"], "cannot-assess")

    def test_in_progress_and_agent_success_claim_are_not_successful_validation(self):
        events = supported_steps()
        events[4][1] = "Purchase validation in progress ..."
        events.append(["agent", "I was able to validate your purchase."])
        procedure, answers = self.evaluate(events)
        self.assertEqual(procedure["result"], "cannot-assess")
        self.assertTrue(
            any("in progress" in reason for reason in procedure["limitations"])
        )
        self.assertEqual(answers["result"], "cannot-assess")
        self.assertFalse(procedure["findings"] or answers["findings"])
        events[4][1] = "Purchase validation complete."
        self.assertEqual(self.evaluate(events)[0]["result"], "cannot-assess")

    def test_reported_customer_choices_do_not_establish_a_refund_branch(self):
        for method in ("credit card", "gift card", "paper check", "add value"):
            choice = f"I'd like a {method} refund."
            for context in (
                [
                    ["agent", f"Please repeat the sentence: {choice}"],
                    ["customer", choice],
                ],
                [
                    ["customer", "The agent said:"],
                    ["customer", choice],
                    ["customer", "Those were the agent's words."],
                ],
                [["customer", choice], ["customer", "I was quoting the agent."]],
            ):
                with self.subTest(method=method, context=context):
                    skipped = [
                        "agent",
                        "I processed the refund without entering the required details.",
                    ]
                    procedure = self.evaluate(context + [skipped])[0]
                    self.assertEqual(procedure["result"], "cannot-assess")
                    self.assertFalse(procedure["findings"])
                    genuine = self.evaluate(context + [["customer", choice], skipped])[
                        0
                    ]
                    self.assertEqual(genuine["result"], "needs-review")
                    self.assertEqual(len(genuine["findings"]), 1)

    def test_reported_customer_facts_do_not_supply_procedure_evidence(self):
        for method, index, section in (
            ("credit card", 0, "refund-reason"),
            ("credit card", 3, "purchase-validation"),
            ("gift card", 6, "refund-details"),
        ):
            with self.subTest(section=section):
                events = supported_steps(method)
                original = events[index]
                events[index : index + 1] = [
                    ["agent", f"Please repeat the sentence: {original[1]}"],
                    original,
                ]
                procedure = self.evaluate(events)[0]
                step = next(
                    step
                    for step in procedure["details"]["steps"]
                    if step["step"] == section
                )
                self.assertEqual(step["result"], "cannot-assess")
                self.assertFalse(procedure["findings"])
        events = supported_steps()
        events[3:3] = [
            ["agent", "Please repeat the phrase I forgot my username."],
            ["customer", "I forgot my username."],
        ]
        self.assertEqual(self.evaluate(events)[0]["result"], "meets-criteria")

    def test_validation_fields_require_positive_submission_forms(self):
        values = "tparker321, tparker321@example.test and ORD1234567"
        for statement in (
            f"Do not use {values}; those are someone else's details.",
            f"Are {values} correct?",
            f'The example values are "{values}".',
            f"These details are incorrect: {values}.",
        ):
            with self.subTest(statement=statement):
                events = supported_steps()
                events[3][1] = statement
                procedure = self.evaluate(events)[0]
                self.assertEqual(procedure["result"], "cannot-assess")
                self.assertFalse(procedure["findings"])
                independent = self.evaluate(
                    [["agent", "I skipped account lookup."], *events]
                )[0]
                self.assertEqual(independent["result"], "needs-review")
                self.assertEqual(len(independent["findings"]), 1)

    def test_validation_accepts_supported_positive_submissions_after_uncertainty(self):
        for submissions in (
            ["tparker321 tparker321@example.test ORD1234567"],
            ["tparker321, tparker321@example.test, and ORD1234567."],
            ["tparker321", "tparker321@example.test", "ORD1234567"],
            [
                "My username is tparker321, my email address is tparker321@example.test and my order ID is ORD1234567."
            ],
            [
                "Username: tparker321; email: tparker321@example.test; order ID: ORD1234567."
            ],
            [
                "My username is tparker321.",
                "My email is tparker321@example.test.",
                "My order ID is ORD1234567.",
            ],
        ):
            with self.subTest(submissions=submissions):
                events = supported_steps()
                events[3:4] = [
                    [
                        "customer",
                        "Do not use tparker321, tparker321@example.test or ORD1234567; those are someone else's details.",
                    ],
                    *[["customer", text] for text in submissions],
                ]
                self.assertEqual(self.evaluate(events)[0]["result"], "meets-criteria")

    def test_disavowed_fields_invalidate_prior_submissions_until_replaced(self):
        for statement, replacement in (
            (
                "Do not use tparker321, tparker321@example.test or ORD1234567; those are someone else's details.",
                "tparker321 tparker321@example.test ORD1234567",
            ),
            (
                "My order ID is not ORD1234567.",
                "My order ID is ORD1234567.",
            ),
            ("My order ID is wrong.", "My order ID is ORD1234567."),
            ("Do not use my email address.", "My email is tparker321@example.test."),
            ("My username is incorrect.", "My username is tparker321."),
        ):
            with self.subTest(statement=statement):
                events = supported_steps()
                events.insert(4, ["customer", statement])
                self.assertEqual(self.evaluate(events)[0]["result"], "cannot-assess")
                events.insert(5, ["customer", replacement])
                source = conversation(events)
                procedure = check_procedure_support(source, catalog(), **CONTEXT)[0]
                self.assertEqual(procedure["result"], "meets-criteria")
                validation = next(
                    check
                    for check in procedure["details"]["checks"]
                    if check["rule_id"].endswith(":purchase-validation")
                )
                self.assertNotIn(
                    5,
                    [
                        c["turn_id"]
                        for c in validation["citations"]
                        if c["kind"] == "conversation"
                    ],
                )
                self.assertEqual(
                    validate_citations(
                        validation["citations"],
                        [source],
                        eligible_references(catalog(), **CONTEXT),
                    ),
                    [],
                )
        events = supported_steps()
        events.insert(4, ["customer", "The item was damaged."])
        self.assertEqual(self.evaluate(events)[0]["result"], "meets-criteria")

    def test_missing_and_partial_evidence_never_establish_skipping(self):
        events = supported_steps()
        for reduced in (
            [event for event in events if event[0] != "action"],
            events[:2],
        ):
            with self.subTest(event_count=len(reduced)):
                self.assertEqual(self.evaluate(reduced)[0]["result"], "cannot-assess")
                self.assertFalse(self.evaluate(reduced)[0]["findings"])
        partial = conversation(events, turn_ids=[3, 4, 5, 6, 7, 8])
        results = check_procedure_support(partial, catalog(), **CONTEXT)
        self.assertEqual(results[0]["result"], "cannot-assess")
        self.assertEqual(partial["events"][0]["turn_id"], 3)

    def test_missing_recovery_reference_is_not_agent_failure(self):
        events = supported_steps()
        events.insert(3, ["customer", "I don't remember my username."])
        procedure = self.evaluate(events)[0]
        self.assertEqual(procedure["result"], "cannot-assess")
        self.assertTrue(
            any("recovery" in reason for reason in procedure["limitations"])
        )
        self.assertFalse(procedure["findings"])
        events.append(["agent", "Purchase validation requires only an email address."])
        answers = self.evaluate(events)[1]
        self.assertEqual(answers["result"], "cannot-assess")
        self.assertFalse(answers["findings"])

    def test_explicit_breach_has_requirement_and_event_citations_and_stable_id(self):
        events = [["agent", "I skipped purchase validation."], *supported_steps()]
        first = self.evaluate(events)[0]
        second = self.evaluate(events)[0]
        self.assertEqual(first["result"], "needs-review")
        finding = first["findings"][0]
        self.assertEqual(finding["id"], second["findings"][0]["id"])
        self.assertEqual(
            {citation["kind"] for citation in finding["citations"]},
            {"reference", "conversation"},
        )
        self.assertEqual(
            validate_citations(
                finding["citations"],
                [conversation(events)],
                eligible_references(catalog(), **CONTEXT),
            ),
            [],
        )
        self.assertTrue(finding["advice"])

    def test_recovery_limit_precedes_direct_skips_standard_claims_and_order(self):
        recovery = ["customer", "I forgot my username."]
        for statement in (
            "I skipped purchase validation.",
            "I processed the refund without validating the purchase.",
            "I validated the purchase before the first account lookup.",
            "Purchase validation requires only an email address.",
        ):
            with self.subTest(statement=statement):
                results = self.evaluate(
                    supported_steps() + [recovery, ["agent", statement]]
                )
                self.assertTrue(
                    all(result["result"] == "cannot-assess" for result in results)
                )
                self.assertFalse(any(result["findings"] for result in results))
        procedure, answers = self.evaluate(
            [
                ["agent", "I skipped account lookup."],
                *supported_steps(),
                recovery,
                ["agent", "Purchase validation requires only an email address."],
            ]
        )
        self.assertEqual(procedure["result"], "needs-review")
        self.assertEqual(len(procedure["findings"]), 1)
        self.assertTrue(procedure["findings"][0]["rule_id"].endswith(":account-lookup"))
        self.assertEqual(answers["result"], "cannot-assess")
        self.assertFalse(answers["findings"])

    def test_recorded_reverse_order_is_uncertain_but_explicit_breach_remains(self):
        events = supported_steps()
        events[2], events[4] = events[4], events[2]
        procedure = self.evaluate(events)[0]
        self.assertEqual(procedure["result"], "cannot-assess")
        self.assertFalse(procedure["findings"])
        events += [
            ["agent", "I validated the purchase before the first account lookup."]
        ]
        self.assertEqual(self.evaluate(events)[0]["result"], "needs-review")
        events += [["action", "Account has been pulled up for Taylor Parker."]]
        self.assertEqual(self.evaluate(events)[0]["result"], "needs-review")

    def test_direct_policy_contradictions_and_mixed_answers(self):
        for statement in (
            "Purchase validation requires only an email address.",
            "We do not need an order ID to validate your purchase.",
            "Gift cards do not require an address.",
        ):
            with self.subTest(statement=statement):
                answers = self.evaluate([["agent", statement]])[1]
                self.assertEqual(answers["result"], "needs-review")
                self.assertTrue(answers["findings"])
        events = [
            ["agent", "Purchase validation requires only an email address."],
            ["agent", "For a credit card refund, we need your account ID."],
        ]
        self.assertEqual(self.evaluate(events)[1]["result"], "needs-review")

    def test_only_an_explicit_linked_correction_resolves_a_claim(self):
        first = ["agent", "Purchase validation requires only an email address."]
        correction = [
            "agent",
            "Correction: Purchase validation requires a username, email address and order ID.",
        ]
        answers = self.evaluate([first, correction])[1]
        self.assertEqual(answers["result"], "meets-criteria")
        self.assertEqual(answers["details"]["claims"][0]["state"], "corrected")
        self.assertFalse(answers["findings"])
        self.assertEqual(
            self.evaluate([first, ["agent", "Actually, that's not correct."]])[1][
                "result"
            ],
            "needs-review",
        )
        self.assertEqual(
            self.evaluate(
                [
                    first,
                    [
                        "agent",
                        "Purchase validation requires a username, email address and order ID.",
                    ],
                ]
            )[1]["result"],
            "needs-review",
        )
        self.assertEqual(
            self.evaluate(
                [
                    first,
                    [
                        "agent",
                        "Correction: For a credit card refund, we need your account ID.",
                    ],
                ]
            )[1]["result"],
            "needs-review",
        )

    def test_unknown_quoted_and_negated_language_is_not_confidently_interpreted(self):
        for statement in (
            "An email alone should do the trick.",
            'The earlier agent said "Purchase validation requires only an email address."',
            "I did not skip purchase validation.",
            "A service fee will apply.",
            "I have credited your card for $79.",
            "Finding your account proves your identity.",
        ):
            with self.subTest(statement=statement):
                results = self.evaluate([["agent", statement]])
                self.assertFalse(any(result["findings"] for result in results))
                self.assertEqual(results[1]["result"], "cannot-assess")
        events = [
            ["agent", "For a credit card refund, we need your account ID."],
            ["agent", "A service fee will apply."],
        ]
        self.assertEqual(self.evaluate(events)[1]["result"], "cannot-assess")

    def test_adjacent_report_and_repetition_do_not_establish_agent_fault(self):
        for statement, category in (
            ("I skipped purchase validation.", 0),
            ("I validated the purchase before the first account lookup.", 0),
            ("Purchase validation requires only an email address.", 1),
        ):
            contexts = (
                [["agent", "The customer said:"], ["agent", statement]],
                [["agent", statement], ["agent", "I was quoting the customer."]],
                [
                    ["customer", f"Please repeat the phrase {statement}"],
                    ["agent", statement],
                ],
                [
                    ["agent", "The customer said:"],
                    ["action", "Purchase validation in progress ..."],
                    ["agent", statement],
                ],
            )
            for events in contexts:
                with self.subTest(statement=statement, events=events):
                    source = conversation(events)
                    result = check_procedure_support(source, catalog(), **CONTEXT)[
                        category
                    ]
                    self.assertEqual(result["result"], "cannot-assess")
                    self.assertFalse(result["findings"])
                    reported = next(
                        check
                        for check in result["details"]["checks"]
                        if "quotation" in check["explanation"]
                    )
                    self.assertEqual(
                        {citation["quote"] for citation in reported["citations"]},
                        {
                            event["text"]
                            for event in source["events"]
                            if event["speaker"] != "action"
                        },
                    )
                    self.assertEqual(
                        validate_citations(
                            reported["citations"],
                            [source],
                            eligible_references(catalog(), **CONTEXT),
                        ),
                        [],
                    )

    def test_reported_statement_does_not_suppress_later_genuine_fault(self):
        for statement, category in (
            ("I skipped purchase validation.", 0),
            ("I validated the purchase before the first account lookup.", 0),
            ("Purchase validation requires only an email address.", 1),
        ):
            with self.subTest(statement=statement):
                source = conversation(
                    [
                        ["agent", "The customer said:"],
                        ["agent", statement],
                        ["agent", "Those were the customer's words."],
                        ["agent", "Thanks."],
                        ["agent", statement],
                    ]
                )
                result = check_procedure_support(source, catalog(), **CONTEXT)[category]
                self.assertEqual(result["result"], "needs-review")
                self.assertEqual(len(result["findings"]), 1)
                self.assertTrue(result["limitations"])
                evidence = [
                    citation["turn_id"]
                    for citation in result["findings"][0]["citations"]
                    if citation["kind"] == "conversation"
                ]
                self.assertEqual(evidence, [5])

    def test_reported_correction_cannot_erase_an_independent_contradiction(self):
        statement = "Purchase validation requires only an email address."
        correction = "Correction: Purchase validation requires a username, email address and order ID."
        for context in (
            ["agent", "The customer said:"],
            ["customer", f"Please repeat the phrase {correction}"],
        ):
            with self.subTest(context=context):
                answers = self.evaluate(
                    [["agent", statement], context, ["agent", correction]]
                )[1]
                self.assertEqual(answers["result"], "needs-review")
                self.assertEqual(len(answers["findings"]), 1)
                self.assertEqual(
                    answers["details"]["claims"][0]["state"], "needs-review"
                )
                self.assertTrue(answers["limitations"])

    def test_reported_supported_policy_is_not_an_agent_answer(self):
        answers = self.evaluate(
            [
                ["agent", "The customer said:"],
                [
                    "agent",
                    "Purchase validation requires a username, email address and order ID.",
                ],
            ]
        )[1]
        self.assertEqual(answers["result"], "cannot-assess")
        self.assertEqual(answers["details"]["claims"], [])
        self.assertFalse(answers["findings"])

    def test_reported_and_repeated_closings_do_not_establish_an_agent_offer(self):
        phrase = "Can I help with anything else?"
        for context in (
            [["agent", "The customer said:"], ["agent", phrase]],
            [["agent", phrase], ["agent", "I was quoting the customer."]],
            [
                ["customer", f"Please repeat the phrase {phrase}"],
                ["agent", phrase],
            ],
        ):
            with self.subTest(context=context):
                source = conversation(supported_steps()[:-1] + context)
                procedure = check_procedure_support(source, catalog(), **CONTEXT)[0]
                self.assertEqual(procedure["result"], "cannot-assess")
                self.assertFalse(procedure["findings"])
                closing = next(
                    check
                    for check in procedure["details"]["checks"]
                    if check["rule_id"].endswith(":closing")
                )
                self.assertEqual(closing["result"], "cannot-assess")
                self.assertIn("reported or repeated", closing["explanation"])
                evidence = [
                    citation["quote"]
                    for citation in closing["citations"]
                    if citation["kind"] == "conversation"
                ]
                self.assertCountEqual(evidence, [text for _, text in context])
                self.assertEqual(
                    [
                        citation["section_id"]
                        for citation in closing["citations"]
                        if citation["kind"] == "reference"
                    ],
                    ["closing"],
                )
                self.assertEqual(
                    validate_citations(
                        closing["citations"],
                        [source],
                        eligible_references(catalog(), **CONTEXT),
                    ),
                    [],
                )

    def test_reported_closing_does_not_hide_a_later_genuine_offer(self):
        for context in (
            [
                ["agent", "The customer said:"],
                ["agent", "Can I help with anything else?"],
                ["agent", "Those were the customer's words."],
            ],
            [
                ["agent", "Can I help with anything else?"],
                ["agent", "I was quoting the customer."],
            ],
            [
                ["customer", "Please repeat the phrase Can I help with anything else?"],
                ["agent", "Can I help with anything else?"],
            ],
        ):
            with self.subTest(context=context):
                source = conversation(
                    supported_steps()[:-1]
                    + context
                    + [
                        ["agent", "Thanks."],
                        ["agent", "Do you need any further assistance?"],
                    ]
                )
                procedure = check_procedure_support(source, catalog(), **CONTEXT)[0]
                self.assertEqual(procedure["result"], "meets-criteria")
                closing = next(
                    check
                    for check in procedure["details"]["checks"]
                    if check["rule_id"].endswith(":closing")
                )
                evidence = [
                    citation
                    for citation in closing["citations"]
                    if citation["kind"] == "conversation"
                ]
                self.assertEqual(len(evidence), 1)
                self.assertEqual(
                    evidence[0]["turn_id"], source["events"][-1]["turn_id"]
                )
                self.assertEqual(
                    evidence[0]["quote"], "Do you need any further assistance?"
                )

    def test_reporting_scope_covers_middle_statements_and_ends_explicitly(self):
        for opening, closing in (
            ("The customer said:", "Those were the customer's words."),
            ("The caller wrote:", "I was quoting the caller."),
            ("I quote:", "That is what the customer said."),
        ):
            with self.subTest(opening=opening):
                source = conversation(
                    [
                        ["agent", opening],
                        ["agent", "I skipped account lookup."],
                        ["action", "Purchase validation in progress ..."],
                        ["agent", "I skipped purchase validation."],
                        [
                            "agent",
                            "Purchase validation requires only an email address.",
                        ],
                        ["agent", closing],
                    ]
                )
                results = check_procedure_support(source, catalog(), **CONTEXT)
                self.assertTrue(
                    all(result["result"] == "cannot-assess" for result in results)
                )
                self.assertFalse(any(result["findings"] for result in results))
                self.assertEqual(
                    [cue["turn_id"] for cue in quotation_context(source["events"], 3)],
                    [1, 6],
                )
                source = conversation(
                    [[event["speaker"], event["text"]] for event in source["events"]]
                    + [["agent", "I skipped purchase validation."]]
                )
                procedure = check_procedure_support(source, catalog(), **CONTEXT)[0]
                self.assertEqual(procedure["result"], "needs-review")
                self.assertEqual(
                    [
                        citation["turn_id"]
                        for citation in procedure["findings"][0]["citations"]
                        if citation["kind"] == "conversation"
                    ],
                    [7],
                )

    def test_reported_correction_inside_a_block_cannot_clear_a_real_claim(self):
        source = conversation(
            [
                ["agent", "Purchase validation requires only an email address."],
                ["agent", "The customer said:"],
                ["agent", "Hello."],
                [
                    "agent",
                    "Correction: Purchase validation requires a username, email address and order ID.",
                ],
                ["agent", "Thank you."],
                ["agent", "Those were the customer's words."],
            ]
        )
        answers = check_procedure_support(source, catalog(), **CONTEXT)[1]
        self.assertEqual(answers["result"], "needs-review")
        self.assertEqual(len(answers["findings"]), 1)
        self.assertEqual(
            [
                citation["turn_id"]
                for citation in answers["findings"][0]["citations"]
                if citation["kind"] == "conversation"
            ],
            [1],
        )
        self.assertTrue(answers["limitations"])

    def test_nested_reports_keep_outer_scope_after_inner_attribution(self):
        markers = (
            ("The customer said:", "Those were the customer's words."),
            ("The agent said:", "I was quoting the agent."),
            ("The caller wrote:", "That is what the caller said."),
        )
        for depth in (2, 3):
            with self.subTest(depth=depth):
                selected = markers[:depth]
                events = [["agent", opening] for opening, _ in selected]
                events.append(["agent", "I skipped account lookup."])
                middle_positions = []
                for _, closing in reversed(selected[1:]):
                    events.append(["agent", closing])
                    middle_positions.append(len(events))
                    events.append(["agent", "I skipped purchase validation."])
                    events.append(["agent", "Hello."])
                events.append(["agent", selected[0][1]])
                source = conversation(events)
                procedure = check_procedure_support(source, catalog(), **CONTEXT)[0]
                self.assertEqual(procedure["result"], "cannot-assess")
                self.assertFalse(procedure["findings"])
                for position in middle_positions:
                    self.assertIn(
                        1,
                        [
                            cue["turn_id"]
                            for cue in quotation_context(source["events"], position)
                        ],
                    )
                source = conversation(
                    events + [["agent", "I skipped purchase validation."]]
                )
                self.assertEqual(quotation_context(source["events"], len(events)), [])
                procedure = check_procedure_support(source, catalog(), **CONTEXT)[0]
                self.assertEqual(procedure["result"], "needs-review")
                self.assertEqual(
                    [
                        citation["turn_id"]
                        for citation in procedure["findings"][0]["citations"]
                        if citation["kind"] == "conversation"
                    ],
                    [len(events) + 1],
                )

    def test_unclosed_outer_report_survives_a_closed_inner_report(self):
        source = conversation(
            [
                ["agent", "The customer said:"],
                ["agent", "The agent said:"],
                ["agent", "I skipped account lookup."],
                ["agent", "I was quoting the agent."],
                ["agent", "I skipped purchase validation."],
                ["agent", "Hello."],
            ]
        )
        self.assertEqual(
            [cue["turn_id"] for cue in quotation_context(source["events"], 4)],
            [1],
        )
        self.assertFalse(
            check_procedure_support(source, catalog(), **CONTEXT)[0]["findings"]
        )

    def test_mismatched_attribution_does_not_release_report_scope(self):
        for opening, wrong_end, right_end in (
            (
                "The customer said:",
                "I was quoting the agent.",
                "I was quoting the caller.",
            ),
            (
                "The agent said:",
                "Those were the customer's words.",
                "Those were the representative's words.",
            ),
        ):
            with self.subTest(opening=opening):
                events = [
                    ["agent", opening],
                    ["agent", "Hello."],
                    ["agent", wrong_end],
                    ["agent", "I skipped purchase validation."],
                    ["agent", "Hello."],
                ]
                source = conversation(events)
                self.assertEqual(
                    check_procedure_support(source, catalog(), **CONTEXT)[0]["result"],
                    "cannot-assess",
                )
                source = conversation(
                    events
                    + [
                        ["agent", right_end],
                        ["agent", "I skipped purchase validation."],
                    ]
                )
                self.assertEqual(
                    [cue["turn_id"] for cue in quotation_context(source["events"], 3)],
                    [1, 6],
                )
                procedure = check_procedure_support(source, catalog(), **CONTEXT)[0]
                self.assertEqual(procedure["result"], "needs-review")
                self.assertEqual(
                    [
                        citation["turn_id"]
                        for citation in procedure["findings"][0]["citations"]
                        if citation["kind"] == "conversation"
                    ],
                    [7],
                )

    def test_generic_report_marker_can_end_with_either_known_party(self):
        for ending in (
            "Those were the customer's words.",
            "I was quoting the representative.",
        ):
            with self.subTest(ending=ending):
                source = conversation(
                    [
                        ["agent", "I quote:"],
                        ["agent", "Hello."],
                        ["agent", ending],
                        ["agent", "I skipped purchase validation."],
                    ]
                )
                self.assertEqual(quotation_context(source["events"], 3), [])
                self.assertEqual(
                    check_procedure_support(source, catalog(), **CONTEXT)[0]["result"],
                    "needs-review",
                )

    def test_unclosed_report_is_uncertain_until_another_speaker_takes_over(self):
        source = conversation(
            [
                ["agent", "The customer said:"],
                ["agent", "I skipped account lookup."],
                ["agent", "Thanks."],
                ["action", "Purchase validation in progress ..."],
                ["agent", "I skipped purchase validation."],
            ]
        )
        procedure = check_procedure_support(source, catalog(), **CONTEXT)[0]
        self.assertEqual(procedure["result"], "cannot-assess")
        self.assertFalse(procedure["findings"])
        self.assertEqual(
            [cue["turn_id"] for cue in quotation_context(source["events"], 4)], [1]
        )
        source = conversation(
            [[event["speaker"], event["text"]] for event in source["events"]]
            + [["customer", "Thank you."], ["agent", "I skipped purchase validation."]]
        )
        self.assertEqual(quotation_context(source["events"], 6), [])
        self.assertEqual(
            check_procedure_support(source, catalog(), **CONTEXT)[0]["result"],
            "needs-review",
        )

    def test_repetition_requests_work_in_both_directions_without_sticky_scope(self):
        phrase = "I want a refund."
        for asking, repeating in (("agent", "customer"), ("customer", "agent")):
            for prompt in (
                "Please repeat the phrase I want a refund.",
                "Can you quote the words: I want a refund.",
                "Please say this sentence: “I want a refund.”",
            ):
                with self.subTest(asking=asking, prompt=prompt):
                    source = conversation(
                        [
                            [asking, prompt],
                            [repeating, phrase],
                            [asking, "Thank you."],
                            [repeating, phrase],
                        ]
                    )
                    self.assertEqual(
                        [
                            cue["turn_id"]
                            for cue in quotation_context(source["events"], 1)
                        ],
                        [1],
                    )
                    self.assertEqual(quotation_context(source["events"], 3), [])

    def test_closing_must_follow_work_and_substantive_customer_input(self):
        for phrase in (
            "Can I help with anything else?",
            "Do you need any further assistance?",
            "Is there anything else I can help you with today?",
        ):
            with self.subTest(phrase=phrase):
                procedure = self.evaluate([["agent", phrase]] + supported_steps()[:-1])[
                    0
                ]
                self.assertEqual(procedure["result"], "cannot-assess")
                self.assertFalse(procedure["findings"])
                self.assertIn(
                    "wrap-up", procedure["details"]["steps"][-1]["explanation"]
                )
                events = supported_steps() + [
                    ["customer", "Please explain the next step."]
                ]
                self.assertEqual(self.evaluate(events)[0]["result"], "cannot-assess")
                events += [["agent", phrase]]
                self.assertEqual(self.evaluate(events)[0]["result"], "meets-criteria")

    def test_closing_allows_known_courtesy_replies_but_not_later_work(self):
        for reply in ("Thanks!", "No, thank you.", "That’s all.", "Goodbye."):
            with self.subTest(reply=reply):
                self.assertEqual(
                    self.evaluate(supported_steps() + [["customer", reply]])[0][
                        "result"
                    ],
                    "meets-criteria",
                )
        events = supported_steps() + [["action", "Purchase validation in progress ..."]]
        self.assertEqual(self.evaluate(events)[0]["result"], "cannot-assess")
        events += [["agent", "Can I help with anything else?"]]
        self.assertEqual(self.evaluate(events)[0]["result"], "meets-criteria")

    def test_corrections_must_match_the_method_condition(self):
        cases = (
            (
                "Gift cards do not require an address.",
                "Correction: For a paper check refund, we need your full address.",
            ),
            (
                "For a credit card refund, we do not need your account ID.",
                "Correction: For an add value refund, we need your account ID.",
            ),
        )
        for incorrect, correction in cases:
            with self.subTest(incorrect=incorrect):
                answers = self.evaluate([["agent", incorrect], ["agent", correction]])[
                    1
                ]
                self.assertEqual(answers["result"], "needs-review")
                self.assertEqual(
                    answers["details"]["claims"][0]["state"], "needs-review"
                )
        correct = self.evaluate(
            [
                ["agent", "Gift cards do not require an address."],
                [
                    "agent",
                    "Correction: For a gift card refund, we need your full address.",
                ],
            ]
        )[1]
        self.assertEqual(correct["result"], "meets-criteria")

    def test_unclear_correction_keeps_independently_supported_findings(self):
        answers = self.evaluate(
            [
                ["agent", "Gift cards do not require an address."],
                ["agent", "Purchase validation requires only an email address."],
                ["agent", "Actually, that's not correct."],
            ]
        )[1]
        self.assertEqual(answers["result"], "needs-review")
        self.assertEqual(len(answers["findings"]), 2)
        self.assertTrue(answers["limitations"])

    def test_reason_patterns_do_not_accept_arbitrary_negation_or_questions(self):
        for text in ("The item is not damaged.", "Because why?", "The item is where?"):
            events = supported_steps()
            events[0][1] = text
            with self.subTest(text=text):
                result = self.evaluate(events)[0]
                reason = next(
                    step
                    for step in result["details"]["steps"]
                    if step["step"] == "refund-reason"
                )
                self.assertEqual(reason["result"], "cannot-assess")
                self.assertFalse(result["findings"])

    def test_unknown_or_negated_method_changes_do_not_reuse_the_first_method(self):
        for text in (
            "Actually, use another method instead.",
            "I don't want a credit card refund anymore.",
            "Maybe a gift card would be better.",
        ):
            events = supported_steps()
            events.insert(6, ["customer", text])
            with self.subTest(text=text):
                result = self.evaluate(events)[0]
                details = next(
                    step
                    for step in result["details"]["steps"]
                    if step["step"] == "refund-details"
                )
                self.assertEqual(details["result"], "cannot-assess")
                self.assertFalse(result["findings"])

    def test_address_token_ordinal_does_not_establish_full_address(self):
        events = supported_steps("gift card")
        events = [
            event for event in events if not event[1].startswith("My full address is")
        ]
        result = self.evaluate(events)[0]
        self.assertEqual(result["result"], "cannot-assess")
        context = ["customer", "My full address is 12 Test St."]
        events.insert(6, context)
        # The street-only context and full-address action mask to different tokens.
        self.assertEqual(self.evaluate(events)[0]["result"], "cannot-assess")

    def test_approval_expiry_and_interpretation_versions_fail_closed(self):
        events = supported_steps()
        self.assertEqual(
            self.evaluate(events, as_of="2027-10-28")[0]["result"], "meets-criteria"
        )
        expired = self.evaluate(events, as_of="2027-10-29")
        self.assertTrue(all(result["result"] == "cannot-assess" for result in expired))
        references = catalog()
        changed = next(
            reference
            for reference in references
            if reference["section_id"] == "account-lookup"
        )
        changed["interpretation_limits"].append("A different interpretation.")
        changed["version"] = reference_version(changed)
        changed["approved_version"] = changed["version"]
        result = self.evaluate(events, references)[0]
        self.assertEqual(result["result"], "cannot-assess")
        self.assertTrue(
            any("interpretation version" in reason for reason in result["limitations"])
        )
        self.assertEqual(result["details"]["steps"][-1]["result"], "meets-criteria")

    def test_new_human_judgements_remain_pending(self):
        self.assertTrue(
            all(
                case["expected"] is None
                and case["reviewed_by"] is None
                and case["reviewed_at"] is None
                for case in HUMAN_CASES
            )
        )
        self.assertTrue(
            all(case["events"] and case["context"] == CONTEXT for case in HUMAN_CASES)
        )

    def test_applicability_and_prior_satisfaction_precede_negative_patterns(self):
        events = supported_steps()
        events[5][1] = "Actually, use another method instead."
        events.append(
            ["agent", "I processed the refund without entering the required details."]
        )
        result = self.evaluate(events)[0]
        self.assertEqual(result["result"], "cannot-assess")
        self.assertFalse(result["findings"])
        events = supported_steps() + [
            ["agent", "I did not ask for or receive a refund reason."]
        ]
        result = self.evaluate(events)[0]
        self.assertEqual(result["result"], "cannot-assess")
        self.assertFalse(result["findings"])
        self.assertTrue(
            any("earlier evidence" in reason for reason in result["limitations"])
        )
        self.assertEqual(
            self.evaluate(
                supported_steps() + [["agent", "I skipped purchase validation."]]
            )[0]["result"],
            "cannot-assess",
        )

    def test_future_closing_intention_is_not_a_completed_omission(self):
        events = supported_steps()
        events.insert(0, ["agent", "I will not offer any further assistance."])
        procedure = self.evaluate(events)[0]
        self.assertEqual(procedure["result"], "meets-criteria")
        self.assertFalse(procedure["findings"])
        events.pop()
        self.assertEqual(self.evaluate(events)[0]["result"], "cannot-assess")


if __name__ == "__main__":
    unittest.main()
