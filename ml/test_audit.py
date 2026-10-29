"""Contract/trust tests; constructed expectations are not human audit judgements."""

import json
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from copy import deepcopy
from io import StringIO
from pathlib import Path
from unittest.mock import patch

from ml.abcd import main, prepare_conversation
from ml.audit import (
    build_assessment,
    category_result,
    criteria_issues,
    eligible_criteria,
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


class ResultContractTests(unittest.TestCase):
    def setUp(self):
        self.conversation = prepared()["conversations"][0]
        self.policies = eligible_references(catalog(), as_of=AS_OF, scope=SCOPE)

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
                        ["agent", "Thank you."],
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

                events += [["agent", "Thank you."], ["agent", statement]]
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

                    events += [["agent", "Thank you."], ["agent", statement]]
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

    def test_cli_rejects_malformed_or_mislocated_rubric_without_export(self):
        output_root = ML_ROOT / "output"
        output_root.mkdir(exist_ok=True)
        malformed = [None, {"schema_version": 1, "references": [None]}]
        misplaced = criteria()
        misplaced.reverse()
        malformed.append({"schema_version": 1, "references": misplaced})
        with tempfile.TemporaryDirectory(dir=output_root) as directory:
            root = Path(directory)
            evidence, rubric, output = (
                root / "evidence.json",
                root / "rubric.json",
                root / "audit.json",
            )
            evidence.write_text(json.dumps(prepared()))
            for document in malformed:
                rubric.write_text(json.dumps(document))
                stdout, stderr = StringIO(), StringIO()
                with redirect_stdout(stdout), redirect_stderr(stderr):
                    code = main(
                        [
                            "audit",
                            "--evidence",
                            str(evidence),
                            "--criteria",
                            str(rubric),
                            "--as-of",
                            AS_OF,
                            "--output",
                            str(output),
                        ]
                    )
                self.assertEqual(code, 1)
                self.assertIn("error", json.loads(stderr.getvalue()))
                self.assertNotIn("Traceback", stderr.getvalue())
                self.assertFalse(output.exists())

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
        self.assertEqual((evidence, references, rubric), before)
        self.assertEqual(saved["results"][-1]["result"], "cannot-assess")

    def test_cli_audit_is_local_versioned_and_does_not_publish_human_metrics(self):
        output_root = ML_ROOT / "output"
        output_root.mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(dir=output_root) as directory:
            root = Path(directory)
            source, output = root / "evidence.json", root / "audit.json"
            source.write_text(json.dumps(prepared()))
            stdout, stderr = StringIO(), StringIO()
            with redirect_stdout(stdout), redirect_stderr(stderr):
                code = main(
                    [
                        "audit",
                        "--evidence",
                        str(source),
                        "--as-of",
                        AS_OF,
                        "--output",
                        str(output),
                    ]
                )
            self.assertEqual((code, stderr.getvalue()), (0, ""))
            saved = json.loads(output.read_text())
            self.assertEqual(saved["assessment_type"], "automated")
            self.assertEqual(
                saved["human_evaluation"],
                {
                    "status": "not-evaluated",
                    "label_agreement": None,
                    "citation_support": None,
                    "unsupported_fault_rate": None,
                },
            )
            self.assertTrue(saved["criteria_exclusions"])
            self.assertEqual(len(saved["assessments"][0]["results"]), 4)
            self.assertNotIn("LABEL_CANARY", json.dumps(saved))
            self.assertEqual(saved["licence"], prepared()["licence"])


if __name__ == "__main__":
    unittest.main()
