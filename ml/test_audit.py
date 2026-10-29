"""Contract/trust tests; constructed expectations are not human audit judgements."""

import json
import unittest
from copy import deepcopy
from pathlib import Path

from ml.audit import (
    build_assessment,
    category_result,
    criteria_issues,
    eligible_criteria,
    validate_rubric,
)
from ml.citations import validate_citations
from ml.references import (
    eligible_references,
    reference_issues,
    reference_passages,
    reference_version,
)
from ml.test_evidence import catalog, prepared

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


if __name__ == "__main__":
    unittest.main()
