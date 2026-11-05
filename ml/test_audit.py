"""Contract/trust tests; constructed expectations are not human audit judgements."""

import json
import unittest
from copy import deepcopy
from pathlib import Path
from unittest.mock import patch

from ml.abcd import prepare_conversation
from ml.audit import (
    build_assessment,
    category_result,
    criteria_issues,
    eligible_criteria,
    validate_results,
    validate_rubric,
)
from ml.citations import validate_citations
from ml.references import (
    eligible_references,
    reference_issues,
    reference_passages,
    reference_version,
)
from ml.test_evidence import catalog, prepared, source_record

AS_OF = "2026-10-29"
SCOPE = "refund-initiation"
ML_ROOT = Path(__file__).resolve().parent


def criteria():
    return json.loads((ML_ROOT / "rubric.json").read_text())["references"]


def test_approved_criterion():
    """Only an in-memory test fixture; never approve the source catalog."""
    criterion = deepcopy(criteria()[0])
    criterion.update(
        status="approved",
        approved_by="Test reviewer",
        approved_version=criterion["version"],
        approved_at="2026-10-28",
        verified_at="2026-10-28",
        review_due="2027-10-28",
    )
    return criterion


def check(status="cannot-assess", citations=None):
    return {
        "rule_id": "constructed-format-v1",
        "result": status,
        "explanation": "A constructed check exercises the result contract.",
        "advice": "Inspect the cited source before making a decision.",
        "citations": citations or [],
    }


def results(conversation):
    return [
        category_result(conversation, category, [check()])
        for category in (
            "procedure",
            "answer-support",
            "completeness",
            "communication-style",
        )
    ]


def assessment(conversation, records, sources=None):
    return build_assessment(
        conversation,
        records,
        sources or [],
        as_of=AS_OF,
        scope=SCOPE,
        rule_versions={"constructed-test": "1"},
    )


class RubricTests(unittest.TestCase):
    def test_draft_sections_have_real_local_provenance_and_unset_approvals(self):
        document = json.loads((ML_ROOT / "rubric.json").read_text())
        validate_rubric(document)
        for section in document["references"]:
            self.assertEqual(section["version"], reference_version(section))
            self.assertEqual(section["status"], "unapproved")
            for field in (
                "approved_by",
                "approved_version",
                "approved_at",
                "verified_at",
                "review_due",
            ):
                self.assertIsNone(section[field])
            self.assertEqual(section["source"]["kind"], "memoria-authored-rubric")
            self.assertNotIn("dataset", section["source"])
            self.assertNotIn("commit", section["source"])
            value = document
            for segment in section["source"]["pointer"].split("/")[1:]:
                value = (
                    value[int(segment)] if isinstance(value, list) else value[segment]
                )
            self.assertEqual(value, section["text"])
        self.assertEqual(eligible_criteria(criteria(), as_of=AS_OF, scope=SCOPE), [])

    def test_review_binding_currentness_and_unchanged_ABCD_provenance_gate(self):
        criterion = test_approved_criterion()
        self.assertEqual(criteria_issues(criterion, as_of=AS_OF, scope=SCOPE), [])
        citation = reference_passages([criterion])[0]["citation"]
        self.assertEqual(validate_citations([citation], [], [criterion]), [])
        self.assertTrue(reference_issues(criterion, as_of=AS_OF, scope=SCOPE))
        for field, value in (
            ("status", "unapproved"),
            ("status", "disputed"),
            ("verified_at", None),
            ("approved_version", "wrong"),
            ("review_due", "2026-10-28"),
        ):
            changed = {**criterion, field: value}
            with self.subTest(field=field, value=value):
                self.assertTrue(criteria_issues(changed, as_of=AS_OF, scope=SCOPE))
        self.assertTrue(criteria_issues(criterion, as_of=AS_OF, scope="refund-status"))
        self.assertEqual(
            criteria_issues(criterion, as_of="2027-10-28", scope=SCOPE), []
        )
        self.assertTrue(criteria_issues(criterion, as_of="2027-10-29", scope=SCOPE))

    def test_content_and_interpretation_limits_are_approval_bound(self):
        for field in ("text", "interpretation_limits"):
            changed = test_approved_criterion()
            if field == "text":
                changed[field] += " Changed meaning."
            else:
                changed[field].append("A changed interpretation needs human review.")
            changed["version"] = reference_version(changed)
            self.assertNotEqual(changed["approved_version"], changed["version"])
            self.assertTrue(criteria_issues(changed, as_of=AS_OF, scope=SCOPE))

    def test_fake_provenance_and_nonexistent_sections_are_not_eligible(self):
        for source in (
            {"dataset": "ABCD", "commit": "0" * 40},
            {
                "kind": "memoria-authored-rubric",
                "path": "elsewhere.json",
                "pointer": "/text",
            },
            {
                "kind": "memoria-authored-rubric",
                "path": "ml/rubric.json",
                "pointer": "/references/999/text",
            },
        ):
            criterion = test_approved_criterion()
            criterion["source"] = source
            criterion["version"] = reference_version(criterion)
            criterion["approved_version"] = criterion["version"]
            self.assertTrue(criteria_issues(criterion, as_of=AS_OF, scope=SCOPE))
        with self.assertRaises(ValueError):
            eligible_criteria([test_approved_criterion()] * 2, as_of=AS_OF, scope=SCOPE)

    def test_rubric_rejects_malformed_or_mislocated_sections(self):
        malformed = [None, {"schema_version": 1, "references": [None]}]
        misplaced = criteria()
        misplaced.reverse()
        malformed.append({"schema_version": 1, "references": misplaced})
        changed = criteria()
        changed[0]["version"] = "changed"
        malformed.append({"schema_version": 1, "references": changed})
        for document in malformed:
            with self.subTest(document=document), self.assertRaises(ValueError):
                validate_rubric(document)


class ResultContractTests(unittest.TestCase):
    def setUp(self):
        self.conversation = prepared()["conversations"][0]
        self.policies = eligible_references(catalog(), as_of=AS_OF, scope=SCOPE)

    def test_partial_validation_is_explicit_and_preserves_complete_requirement(self):
        partial = results(self.conversation)[:2]
        before = deepcopy((partial, self.policies))
        validate_results(
            self.conversation,
            partial,
            self.policies,
            as_of=AS_OF,
            scope=SCOPE,
            require_all=False,
        )
        self.assertEqual((partial, self.policies), before)
        with self.assertRaises(ValueError):
            assessment(self.conversation, partial, self.policies)
        for invalid in (
            [],
            [partial[0], partial[0]],
            [{**partial[0], "category": "other"}],
        ):
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                validate_results(
                    self.conversation,
                    invalid,
                    self.policies,
                    as_of=AS_OF,
                    scope=SCOPE,
                    require_all=False,
                )

    def test_partial_validation_keeps_source_and_nested_citation_gates(self):
        partial = results(self.conversation)[:1]
        with self.assertRaises(ValueError):
            validate_results(
                self.conversation,
                partial,
                criteria(),
                as_of=AS_OF,
                scope=SCOPE,
                require_all=False,
            )
        partial[0]["details"]["citations"] = [{"kind": "bad", "quote": "untrusted"}]
        with self.assertRaises(ValueError):
            validate_results(
                self.conversation,
                partial,
                self.policies,
                as_of=AS_OF,
                scope=SCOPE,
                require_all=False,
            )

    def test_partial_validation_rejects_duplicate_findings_across_categories(self):
        from ml.abcd import conversation_passages

        citations = [
            conversation_passages([self.conversation])[0]["citation"],
            reference_passages(self.policies)[0]["citation"],
        ]
        partial = [
            category_result(
                self.conversation, category, [check("needs-review", citations)]
            )
            for category in ("procedure", "answer-support")
        ]
        partial[1]["findings"][0]["id"] = partial[0]["findings"][0]["id"]
        for record in partial:
            validate_results(
                self.conversation,
                [record],
                self.policies,
                as_of=AS_OF,
                scope=SCOPE,
                require_all=False,
            )
        with self.assertRaisesRegex(ValueError, "unique"):
            validate_results(
                self.conversation,
                partial,
                self.policies,
                as_of=AS_OF,
                scope=SCOPE,
                require_all=False,
            )

    def test_result_precedence_and_explained_uncertainty(self):
        for statuses, expected in (
            ([], "cannot-assess"),
            (["meets-criteria"], "meets-criteria"),
            (["meets-criteria", "cannot-assess"], "cannot-assess"),
            (["cannot-assess", "needs-review"], "needs-review"),
        ):
            records = [check(status) for status in statuses]
            record = category_result(self.conversation, "procedure", records)
            self.assertEqual(record["result"], expected)
            if expected == "cannot-assess":
                self.assertTrue(record["limitations"])
            self.assertNotIn("score", record)
            self.assertNotIn("decision", record)

    def test_finding_identity_and_reference_limits_trace(self):
        from ml.abcd import conversation_passages

        citations = [
            conversation_passages([self.conversation])[0]["citation"],
            reference_passages(self.policies)[0]["citation"],
        ]
        first = category_result(
            self.conversation, "procedure", [check("needs-review", citations)]
        )
        reverse = category_result(
            self.conversation,
            "procedure",
            [check("needs-review", list(reversed(citations)))],
        )
        self.assertEqual(first["findings"][0]["id"], reverse["findings"][0]["id"])
        records = results(self.conversation)
        records[0] = first
        saved = assessment(self.conversation, records, self.policies)
        reference = self.policies[0]
        self.assertEqual(
            saved["reference_trace"],
            [
                {
                    "id": reference["id"],
                    "version": reference["version"],
                    "interpretation_limits": reference["interpretation_limits"],
                }
            ],
        )
        self.assertEqual(saved["assessment_type"], "automated")
        self.assertEqual(
            saved["rule_version"],
            assessment(self.conversation, records, list(reversed(self.policies)))[
                "rule_version"
            ],
        )

    def test_only_eligible_union_can_validate_findings(self):
        from ml.abcd import conversation_passages

        criterion = test_approved_criterion()
        citations = [
            conversation_passages([self.conversation])[0]["citation"],
            reference_passages([criterion])[0]["citation"],
        ]
        records = results(self.conversation)
        records[-1] = category_result(
            self.conversation, "communication-style", [check("needs-review", citations)]
        )
        self.assertEqual(
            assessment(self.conversation, records, self.policies + [criterion])[
                "results"
            ][-1]["result"],
            "needs-review",
        )
        with self.assertRaises(ValueError):
            assessment(self.conversation, records, self.policies)
        with self.assertRaises(ValueError):
            assessment(self.conversation, records, criteria())
        policy = deepcopy(self.policies[0])
        policy["id"] = criterion["id"]
        policy["version"] = reference_version(policy)
        policy["approved_version"] = policy["version"]
        with self.assertRaisesRegex(ValueError, "globally unique"):
            assessment(
                self.conversation, results(self.conversation), [policy, criterion]
            )

    def test_invalid_results_duplicate_findings_and_uncited_faults_fail(self):
        for field, value in (
            ("category", []),
            ("category", None),
            ("limitations", [None]),
            ("limitations", [{}]),
            ("findings", [{"id": "invalid"}]),
        ):
            records = results(self.conversation)
            records[0][field] = value
            with self.subTest(field=field, value=value), self.assertRaises(ValueError):
                assessment(self.conversation, records)
        records = results(self.conversation)
        records[0] = category_result(
            self.conversation, "procedure", [check("needs-review")]
        )
        with self.assertRaises(ValueError):
            assessment(self.conversation, records)
        from ml.abcd import conversation_passages

        citations = [
            conversation_passages([self.conversation])[0]["citation"],
            reference_passages(self.policies)[0]["citation"],
        ]
        records[0] = category_result(
            self.conversation, "procedure", [check("needs-review", citations)] * 2
        )
        with self.assertRaisesRegex(ValueError, "unique"):
            assessment(self.conversation, records, self.policies)

    def test_nested_request_citations_and_transcript_integrity_are_checked(self):
        records = results(self.conversation)
        records[2]["details"]["requests"] = [
            {"request_citations": [{"kind": "bad", "quote": "untrusted"}]}
        ]
        with self.assertRaises(ValueError):
            assessment(self.conversation, records)
        changed = deepcopy(self.conversation)
        changed["events"][0]["text"] += " Changed."
        with self.assertRaises(ValueError):
            assessment(changed, results(changed))

    def test_existing_approvals_expire_on_the_actual_human_deadline(self):
        references = catalog()
        self.assertEqual(
            len(eligible_references(references, as_of="2027-10-28", scope=SCOPE)), 5
        )
        self.assertEqual(
            eligible_references(references, as_of="2027-10-29", scope=SCOPE), []
        )
        self.assertEqual(
            len(eligible_references(references, as_of=AS_OF, scope=SCOPE)), 5
        )


class AuditIntegrationTests(unittest.TestCase):
    def assess_events(self, events):
        from ml.completeness_style import RULE_VERSION as wording_version
        from ml.completeness_style import check_completeness_style
        from ml.procedure_support import RULE_VERSION as procedure_version
        from ml.procedure_support import check_procedure_support

        record = source_record()
        record["original"] = events
        record.pop("delexed")
        conversation = prepare_conversation(record, split="train", index=0)
        references, rubric = catalog(), criteria()
        records = check_procedure_support(
            conversation, references, as_of=AS_OF, scope=SCOPE
        ) + check_completeness_style(
            conversation, references, rubric, as_of=AS_OF, scope=SCOPE
        )
        return build_assessment(
            conversation,
            records,
            eligible_references(references, as_of=AS_OF, scope=SCOPE),
            as_of=AS_OF,
            scope=SCOPE,
            rule_versions={
                "procedure-support": procedure_version,
                "completeness-style": wording_version,
            },
        )

    def test_uncertain_customer_prerequisites_do_not_pass_or_fault_in_export(self):
        from ml.test_procedure_support import supported_steps

        negated_inputs = supported_steps()
        negated_inputs[3][1] = (
            "Do not use tparker321, tparker321@example.test or ORD1234567; "
            "those are someone else's details."
        )
        cases = (
            [
                ["agent", "Please repeat the sentence: I'd like a gift card refund."],
                ["customer", "I'd like a gift card refund."],
                [
                    "agent",
                    "I processed the refund without entering the required details.",
                ],
            ],
            negated_inputs,
        )
        for events in cases:
            with self.subTest(events=events):
                result = self.assess_events(events)["results"][0]
                self.assertEqual(result["result"], "cannot-assess")
                self.assertFalse(result["findings"])
                self.assertTrue(result["limitations"])

    def test_quoted_requests_and_assertion_questions_remain_uncertain_in_export(self):
        cases = (
            [
                [
                    "customer",
                    'The example sentence is "Hello; I want a refund; goodbye."',
                ],
                ["agent", "I will not address your refund request."],
            ],
            [
                ["customer", "I want a refund."],
                ["agent", "Your refund is in progress?"],
            ],
            [
                ["customer", "I want a refund."],
                ["agent", "I will not address your refund request?"],
            ],
        )
        for events in cases:
            with self.subTest(events=events):
                result = self.assess_events(events)["results"][2]
                self.assertEqual(result["result"], "cannot-assess")
                self.assertFalse(result["findings"])
                self.assertTrue(result["limitations"])

    def test_quoted_examples_do_not_hide_a_separate_supported_refusal_in_export(self):
        result = self.assess_events(
            [
                [
                    "customer",
                    'The example sentence is "Hello; I want a refund; goodbye."',
                ],
                ["customer", "I want a refund."],
                ["agent", "I will not address your refund request."],
            ]
        )["results"][2]
        self.assertEqual(result["result"], "needs-review")
        self.assertEqual(len(result["findings"]), 1)
        self.assertEqual(
            [citation["turn_id"] for citation in result["findings"][0]["citations"]],
            [2, 3],
        )
        self.assertTrue(result["limitations"])

    def test_reported_and_repeated_faults_remain_neutral_in_export(self):
        candidates = (
            ("procedure", "I skipped purchase validation."),
            (
                "procedure",
                "I validated the purchase before the first account lookup.",
            ),
            (
                "answer-support",
                "Purchase validation requires only an email address.",
            ),
            ("completeness", "I will not address your refund request."),
        )
        for category, statement in candidates:
            contexts = (
                [["agent", "The customer said:"], ["agent", statement]],
                [["agent", statement], ["agent", "I was quoting the customer."]],
                [
                    ["customer", "Please repeat the phrase " + statement],
                    ["agent", statement],
                ],
                [
                    ["customer", f'Can you quote the words: "{statement}"'],
                    ["agent", statement],
                ],
            )
            for context in contexts:
                with self.subTest(category=category, context=context):
                    saved = self.assess_events(
                        [["customer", "I want a refund."], *context]
                    )
                    result = next(
                        item
                        for item in saved["results"]
                        if item["category"] == category
                    )
                    self.assertEqual(result["result"], "cannot-assess")
                    self.assertFalse(result["findings"])
                    self.assertTrue(result["limitations"])
                    self.assertTrue(
                        any(
                            "quot" in limitation or "reported/repeated" in limitation
                            for limitation in result["limitations"]
                        )
                    )

    def test_later_independent_faults_keep_their_own_citations_in_export(self):
        for category, statement in (
            ("procedure", "I skipped purchase validation."),
            (
                "answer-support",
                "Purchase validation requires only an email address.",
            ),
            ("completeness", "I will not address your refund request."),
        ):
            with self.subTest(category=category):
                saved = self.assess_events(
                    [
                        ["customer", "I want a refund."],
                        ["agent", "The customer said:"],
                        ["agent", statement],
                        ["agent", "I was quoting the customer."],
                        ["agent", statement],
                    ]
                )
                result = next(
                    item for item in saved["results"] if item["category"] == category
                )
                self.assertEqual(result["result"], "needs-review")
                evidence = [
                    citation
                    for finding in result["findings"]
                    for citation in finding["citations"]
                    if citation["kind"] == "conversation"
                ]
                self.assertIn(5, [citation["turn_id"] for citation in evidence])
                self.assertNotIn(3, [citation["turn_id"] for citation in evidence])
                self.assertTrue(result["limitations"])

    def test_reported_correction_cannot_clear_a_supported_exported_finding(self):
        saved = self.assess_events(
            [
                ["agent", "Purchase validation requires only an email address."],
                ["agent", "The customer said:"],
                [
                    "agent",
                    "Correction: Purchase validation requires a username, email address and order ID.",
                ],
            ]
        )
        result = saved["results"][1]
        self.assertEqual(result["result"], "needs-review")
        self.assertEqual(
            [
                citation["turn_id"]
                for citation in result["findings"][0]["citations"]
                if citation["kind"] == "conversation"
            ],
            [1],
        )
        self.assertTrue(result["limitations"])

    def test_only_a_genuine_closing_satisfies_the_exported_procedure(self):
        from ml.test_procedure_support import supported_steps

        statement = "Can I help with anything else?"
        contexts = (
            [["agent", "The customer said:"], ["agent", statement]],
            [["agent", statement], ["agent", "I was quoting the customer."]],
            [
                ["customer", "Please repeat the phrase " + statement],
                ["agent", statement],
            ],
        )
        for context in contexts:
            with self.subTest(context=context):
                events = supported_steps()[:-1] + context
                result = self.assess_events(events)["results"][0]
                self.assertEqual(result["result"], "cannot-assess")
                self.assertFalse(result["findings"])
                self.assertTrue(result["limitations"])

                events += [
                    ["agent", "I was quoting the customer."],
                    ["agent", "Thank you."],
                    ["agent", statement],
                ]
                result = self.assess_events(events)["results"][0]
                self.assertEqual(result["result"], "meets-criteria")
                closing = next(
                    check
                    for check in result["details"]["checks"]
                    if check["rule_id"].endswith(":closing")
                )
                self.assertEqual(
                    [
                        citation["turn_id"]
                        for citation in closing["citations"]
                        if citation["kind"] == "conversation"
                    ],
                    [len(events)],
                )

    def test_only_genuine_responses_can_resolve_an_exported_refusal(self):
        for statement in (
            "I will process your refund.",
            "I will refund it to your credit card.",
            "Your refund is in progress.",
            "I have credited your card for $79.",
        ):
            contexts = (
                [["agent", "The customer said:"], ["agent", statement]],
                [["agent", statement], ["agent", "I was quoting the customer."]],
                [
                    ["customer", "Please repeat the phrase " + statement],
                    ["agent", statement],
                ],
            )
            for context in contexts:
                with self.subTest(statement=statement, context=context):
                    events = [
                        ["customer", "I want a refund."],
                        ["agent", "I will not address your refund request."],
                        *context,
                    ]
                    result = self.assess_events(events)["results"][2]
                    self.assertEqual(result["result"], "needs-review")
                    request = result["details"]["requests"][0]
                    self.assertEqual(request["response_kind"], "refusal")
                    self.assertEqual(
                        [cite["turn_id"] for cite in request["response_citations"]],
                        [2],
                    )
                    self.assertEqual(
                        [
                            cite["turn_id"]
                            for cite in result["findings"][0]["citations"]
                        ],
                        [1, 2],
                    )

                    events += [
                        ["agent", "I was quoting the customer."],
                        ["agent", "Thank you."],
                        ["agent", statement],
                    ]
                    result = self.assess_events(events)["results"][2]
                    self.assertFalse(result["findings"])
                    self.assertEqual(
                        [
                            cite["turn_id"]
                            for cite in result["details"]["requests"][0][
                                "response_citations"
                            ]
                        ],
                        [2, len(events)],
                    )

    def test_quotation_scope_keeps_middle_passages_neutral_in_export(self):
        for category, statement in (
            ("procedure", "I skipped purchase validation."),
            (
                "answer-support",
                "Purchase validation requires only an email address.",
            ),
            ("completeness", "I will not address your refund request."),
        ):
            for opener, closer in (
                ("The customer said:", "Those were the customer's words."),
                ("The caller wrote:", "That is what the customer said."),
                ("I quote:", "I was quoting the customer."),
            ):
                for closed in (False, True):
                    with self.subTest(category=category, opener=opener, closed=closed):
                        events = [
                            ["customer", "I want a refund."],
                            ["agent", opener],
                            ["agent", "Hello."],
                            ["agent", statement],
                            ["agent", "Thank you."],
                        ]
                        if closed:
                            events.append(["agent", closer])
                        result = next(
                            item
                            for item in self.assess_events(events)["results"]
                            if item["category"] == category
                        )
                        self.assertEqual(result["result"], "cannot-assess")
                        self.assertFalse(result["findings"])
                        self.assertTrue(result["limitations"])

                        if not closed:
                            events.append(["agent", closer])
                        events.append(["agent", statement])
                        result = next(
                            item
                            for item in self.assess_events(events)["results"]
                            if item["category"] == category
                        )
                        self.assertEqual(result["result"], "needs-review")
                        turns = [
                            citation["turn_id"]
                            for finding in result["findings"]
                            for citation in finding["citations"]
                            if citation["kind"] == "conversation"
                        ]
                        self.assertIn(len(events), turns)
                        self.assertNotIn(4, turns)

    def test_closing_requires_wrap_up_context_in_export(self):
        from ml.test_procedure_support import supported_steps

        work = supported_steps()[:-1]
        for position in (0, 3, len(work) - 1):
            with self.subTest(position=position):
                events = [list(event) for event in work]
                events.insert(position, ["agent", "Can I help with anything else?"])
                result = self.assess_events(events)["results"][0]
                self.assertEqual(result["result"], "cannot-assess")
                self.assertFalse(result["findings"])
                events += [
                    ["agent", "Do you need any further assistance?"],
                    ["customer", "Thank you."],
                ]
                result = self.assess_events(events)["results"][0]
                self.assertEqual(result["result"], "meets-criteria")

    def test_nested_reports_keep_outer_attribution_until_its_end(self):
        for category, statement in (
            ("procedure", "I skipped purchase validation."),
            (
                "answer-support",
                "Purchase validation requires only an email address.",
            ),
            ("completeness", "I will not address your refund request."),
        ):
            for depth in (2, 3):
                with self.subTest(category=category, depth=depth):
                    events = [["customer", "I want a refund."]]
                    events += [["agent", "The customer said:"]] * depth
                    events += [
                        ["agent", "Hello."],
                        ["agent", "I was quoting the customer."],
                        ["agent", statement],
                        ["agent", "Thank you."],
                    ]
                    result = next(
                        item
                        for item in self.assess_events(events)["results"]
                        if item["category"] == category
                    )
                    self.assertEqual(result["result"], "cannot-assess")
                    self.assertFalse(result["findings"])
                    events += [["agent", "I was quoting the customer."]] * (depth - 1)
                    events.append(["agent", statement])
                    result = next(
                        item
                        for item in self.assess_events(events)["results"]
                        if item["category"] == category
                    )
                    self.assertEqual(result["result"], "needs-review")
                    turns = [
                        citation["turn_id"]
                        for finding in result["findings"]
                        for citation in finding["citations"]
                        if citation["kind"] == "conversation"
                    ]
                    self.assertIn(len(events), turns)
                    self.assertNotIn(depth + 4, turns)

    def test_unclear_changes_prevent_new_faults_and_passes_in_export(self):
        for change in (
            "Actually, please do not issue the refund.",
            "I mean please hold off for now.",
            "Actually, could we deal with a different thing instead?",
        ):
            for response in (
                "I will not address your refund request.",
                "I will process your refund.",
            ):
                with self.subTest(change=change, response=response):
                    result = self.assess_events(
                        [
                            ["customer", "I want a refund."],
                            ["customer", change],
                            ["agent", response],
                        ]
                    )["results"][2]
                    self.assertEqual(result["result"], "cannot-assess")
                    self.assertFalse(result["findings"])
                    self.assertTrue(result["limitations"])
                    request = result["details"]["requests"][0]
                    self.assertEqual(request["state"], "uncertain")
                    self.assertEqual(request["response_citations"], [])

    def test_request_clauses_have_the_same_meaning_across_turn_boundaries(self):
        for clauses, response in (
            (
                ["I want a refund", "actually, please do not issue the refund"],
                "I will not address your refund request.",
            ),
            (
                ["I want a refund", "I mean please hold off for now"],
                "I will process your refund.",
            ),
            (
                ["I want a refund", "actually, I want to return an item instead"],
                "I will not address your return request.",
            ),
            (
                ["I want a refund", "cancel the refund request"],
                "I will not address your refund request.",
            ),
            (
                ["I want a refund", "I want to return an item", "never mind"],
                "I will not address your refund request.",
            ),
        ):
            with self.subTest(clauses=clauses, response=response):
                separate_events = [["customer", part + "."] for part in clauses]
                separate = self.assess_events([*separate_events, ["agent", response]])[
                    "results"
                ][2]
                combined = self.assess_events(
                    [["customer", "; ".join(clauses) + "."], ["agent", response]]
                )["results"][2]
                self.assertEqual(combined["result"], separate["result"])
                self.assertEqual(len(combined["findings"]), len(separate["findings"]))
                self.assertEqual(
                    [
                        (request["topic"], request["state"], request["response_kind"])
                        for request in combined["details"]["requests"]
                    ],
                    [
                        (request["topic"], request["state"], request["response_kind"])
                        for request in separate["details"]["requests"]
                    ],
                )

    def test_customer_repetition_cannot_change_exported_requests(self):
        for phrase in (
            "I want a refund.",
            "Cancel the refund request.",
            "Actually, I want to return an item instead.",
        ):
            with self.subTest(phrase=phrase):
                result = self.assess_events(
                    [
                        ["customer", "I want a refund."],
                        ["agent", "I will not address your refund request."],
                        ["agent", "Please repeat the phrase " + phrase],
                        ["customer", phrase],
                    ]
                )["results"][2]
                self.assertEqual(result["result"], "needs-review")
                self.assertEqual(len(result["details"]["requests"]), 1)
                self.assertEqual(result["details"]["requests"][0]["state"], "active")
                self.assertEqual(
                    [
                        citation["turn_id"]
                        for citation in result["findings"][0]["citations"]
                    ],
                    [1, 2],
                )
        result = self.assess_events(
            [
                ["agent", "Please repeat the phrase I want a refund."],
                ["customer", "I want a refund."],
                ["agent", "I will not address your refund request."],
            ]
        )["results"][2]
        self.assertEqual(result["result"], "cannot-assess")
        self.assertEqual(result["details"]["requests"], [])
        self.assertFalse(result["findings"])

    def test_both_rule_modules_are_pure_and_use_the_same_contract(self):
        from ml.completeness_style import check_completeness_style
        from ml.procedure_support import check_procedure_support

        evidence, references, rubric = prepared(), catalog(), criteria()
        before = deepcopy((evidence, references, rubric))
        conversation = evidence["conversations"][0]
        with (
            patch.object(
                Path, "read_text", side_effect=AssertionError("File I/O in rule")
            ),
            patch.object(
                Path, "read_bytes", side_effect=AssertionError("File I/O in rule")
            ),
            patch("socket.socket", side_effect=AssertionError("Network in rule")),
        ):
            records = check_procedure_support(
                conversation, references, as_of=AS_OF, scope=SCOPE
            )
            records += check_completeness_style(
                conversation, references, rubric, as_of=AS_OF, scope=SCOPE
            )
        saved = assessment(
            conversation,
            records,
            eligible_references(references, as_of=AS_OF, scope=SCOPE),
        )
        self.assertEqual(len(saved["results"]), 4)
        self.assertEqual(saved["assessment_type"], "automated")
        self.assertEqual(saved["conversation_id"], conversation["id"])
        self.assertEqual(
            saved["transcript_version"], conversation["transcript_version"]
        )
        self.assertNotIn("decision", saved)
        self.assertNotIn("LABEL_CANARY", json.dumps(saved))
        self.assertEqual((evidence, references, rubric), before)
        self.assertEqual(saved["results"][-1]["result"], "cannot-assess")


if __name__ == "__main__":
    unittest.main()
