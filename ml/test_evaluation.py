"""Authored evaluation mechanics; these are not held-out human judgements."""

import gzip
import json
import unittest
from copy import deepcopy
from hashlib import sha256
from pathlib import Path
from unittest.mock import patch

from ml.abcd import ABCD_SHA256, conversation_passages, prepare_dataset
from ml.audit import CATEGORIES, _result_citations, category_result
from ml.evaluation import (
    HUMAN_FIELDS,
    QUALITY_METRICS,
    build_cohort,
    evaluate_reports,
    evaluate_retrieval,
    report_content_version,
    validate_cohort,
)
from ml.references import eligible_references
from ml.test_audit import criteria
from ml.test_evidence import SOURCE, catalog, source_record

AS_OF = "2026-10-30"


def dataset():
    result = {"train": [], "dev": [], "test": []}
    for split, identifiers in (
        ("train", [7921, 8570, *range(100001, 100025)]),
        ("test", range(200001, 200020)),
    ):
        for identifier in identifiers:
            record = source_record(identifier)
            record["scenario"]["subflow"] = "refund_initiate"
            result[split].append(record)
    return result


def fixture(partition="development"):
    raw = dataset()
    manifest = build_cohort(raw, SOURCE)
    ids = tuple(
        case["id"] for case in manifest["cases"] if case["partition"] == partition
    )
    evidence = prepare_dataset(raw, SOURCE, ids)
    references, rubric = catalog(), {"schema_version": 1, "references": criteria()}
    reports = {}
    for conversation in evidence["conversations"]:
        citation = conversation_passages([conversation])[0]["citation"]
        check = {
            "rule_id": "constructed-v1",
            "result": "cannot-assess",
            "explanation": "Constructed insufficient evidence.",
            "advice": "Review evidence.",
            "citations": [citation],
        }
        reports[conversation["id"]] = {
            "schema_version": 1,
            "processing_status": "complete",
            "conversation_id": conversation["id"],
            "transcript_version": conversation["transcript_version"],
            "as_of": AS_OF,
            "scope": "refund-initiation",
            "source": deepcopy(evidence["source"]),
            "masking_version": evidence["masking_version"],
            "licence": deepcopy(evidence["licence"]),
            "categories": [
                {
                    "category": name,
                    "status": "completed",
                    "result": category_result(conversation, name, [check]),
                    "error": None,
                }
                for name in CATEGORIES
            ],
            "topic": {"labels": [], "citations": [], "limitations": ["Unknown topic."]},
            "summary": {
                "claims": [
                    {
                        "kind": "agent-claim",
                        "text": citation["quote"],
                        "citations": [citation],
                    }
                ],
                "limitations": [],
            },
            "versions": {
                "report": "local-feedback-v1",
                "limits": {
                    "max_events": 200,
                    "max_input_bytes": 256 * 1024,
                    "max_output_bytes": 256 * 1024,
                    "timeout_seconds": 2.0,
                },
                "rules": {"constructed": "1"},
                "references": [
                    {"id": ref["id"], "version": ref["version"]} for ref in references
                ],
                "rubric": [
                    {"id": ref["id"], "version": ref["version"]}
                    for ref in rubric["references"]
                ],
            },
            "metrics": {
                "engine": "local-rules",
                "elapsed_ms": 5.0,
                "model": None,
                "prompt": None,
                "token_usage": None,
                "model_call_cost_usd": 0.0,
            },
            "errors": [],
        }
    return manifest, reports, evidence, references, rubric


def evaluate(values, *, partition="development"):
    manifest, reports, evidence, references, rubric = values
    return evaluate_reports(
        manifest,
        reports,
        evidence=evidence,
        references=references,
        rubric=rubric,
        as_of=AS_OF,
        partition=partition,
    )


def review(case, report):
    citations = len(
        list(
            _result_citations(
                [report["categories"], report["topic"], report["summary"]]
            )
        )
    )
    case["annotation"].update(
        transcript_version=report["transcript_version"],
        versions=deepcopy(report["versions"]),
        report_version=report_content_version(report),
        expected_results={name: "cannot-assess" for name in CATEGORIES},
        unsupported_findings=0,
        citation_support=[True] * citations,
        summary_faithfulness=[True],
        topic_faithfulness=True,
        reviewed_by="Test reviewer",
        reviewed_at=AS_OF,
        second_reviewed_by="Independent test reviewer",
        second_reviewed_at=AS_OF,
        reasons={name: "Constructed evidence gap." for name in CATEGORIES},
        evidence_gaps=[],
        disagreements=[],
        second_review_agreement=True,
    )


def freeze(manifest, reports):
    manifest["freeze"] = {
        "cohort_version": manifest["version"],
        "versions": deepcopy(next(iter(reports.values()))["versions"]),
        "reviewed_by": "Test owner",
        "reviewed_at": AS_OF,
    }
    manifest["release_checks"] = {
        "reviewed_by": "Test owner",
        "reviewed_at": AS_OF,
        "thresholds": dict.fromkeys(QUALITY_METRICS, 1.0),
    }


class CohortTests(unittest.TestCase):
    def test_selection_is_fixed_metadata_only_and_preserves_official_splits(self):
        raw = dataset()
        for record in raw["test"]:
            record["original"] = object()
        before = deepcopy(raw)
        manifest = build_cohort(raw, SOURCE)
        self.assertEqual(manifest, build_cohort(raw, SOURCE))
        self.assertEqual(len(manifest["cases"]), 39)
        self.assertEqual(
            [case["id"] for case in manifest["cases"][:2]], ["7921", "8570"]
        )
        self.assertEqual(
            sum(case["partition"] == "development" for case in manifest["cases"]), 20
        )
        self.assertEqual({case["split"] for case in manifest["cases"][20:]}, {"test"})
        self.assertTrue(
            all(
                set(case["annotation"]) == set(HUMAN_FIELDS)
                and all(v is None for v in case["annotation"].values())
                for case in manifest["cases"]
            )
        )
        self.assertIsNone(manifest["freeze"])
        self.assertIsNone(manifest["release_checks"])
        self.assertNotIn("FLOW_LABEL_CANARY", json.dumps(manifest))
        self.assertEqual(raw["train"], before["train"])
        validate_cohort(manifest)

    def test_source_duplicates_insufficient_cohorts_and_invalid_pins_fail(self):
        for mutation in ("duplicate", "missing-known", "short-test", "invalid-split"):
            raw = dataset()
            if mutation == "duplicate":
                raw["test"][0]["convo_id"] = 7921
            elif mutation == "missing-known":
                raw["train"].pop(0)
            elif mutation == "short-test":
                raw["test"].pop()
            else:
                raw["test"] = None
            with (
                self.subTest(mutation=mutation),
                self.assertRaises((ValueError, TypeError)),
            ):
                build_cohort(raw, SOURCE)
        with self.assertRaises(ValueError):
            build_cohort(dataset(), {**SOURCE, "sha256": "0" * 64})

    def test_changed_split_identity_annotation_or_version_is_rejected(self):
        original = build_cohort(dataset(), SOURCE)
        for mutation in ("id", "split", "source_pointer", "annotation", "version"):
            value = deepcopy(original)
            if mutation == "version":
                value[mutation] = "stale"
            else:
                value["cases"][0][mutation] = (
                    {} if mutation == "annotation" else "wrong"
                )
            with (
                self.subTest(mutation=mutation),
                self.assertRaises((ValueError, TypeError)),
            ):
                validate_cohort(value)

    def test_local_manifest_matches_pinned_metadata_without_preparing_holdout(self):
        raw_path = Path(__file__).parent / "raw" / "abcd_v1.1.json.gz"
        if not raw_path.exists():
            self.skipTest("Pinned local metadata is unavailable.")
        raw = gzip.decompress(raw_path.read_bytes())
        self.assertEqual(sha256(raw).hexdigest(), ABCD_SHA256)
        expected = build_cohort(json.loads(raw), SOURCE)
        stored = json.loads((Path(__file__).parent / "evaluation.json").read_text())
        self.assertEqual(stored, expected)


class EvaluationTests(unittest.TestCase):
    def test_unreviewed_metrics_remain_unavailable_and_inputs_are_pure(self):
        values = fixture()
        before = deepcopy(values)
        with (
            patch.object(Path, "read_text", side_effect=AssertionError("I/O")),
            patch("socket.socket", side_effect=AssertionError("Network")),
        ):
            result = evaluate(values)
        self.assertEqual(values, before)
        self.assertEqual(result["counts"]["completed_categories"], 80)
        self.assertEqual(result["counts"]["unreviewed_cases"], 20)
        self.assertEqual(result["metrics"]["citation_validity"]["value"], 1)
        for name in (
            "label_agreement",
            "citation_support",
            "unsupported_fault_rate",
            "summary_faithfulness",
            "topic_faithfulness",
            "appropriate_cannot_assess",
        ):
            self.assertIsNone(result["metrics"][name]["value"])
            self.assertEqual(result["metrics"][name]["denominator"], 0)
        self.assertEqual(result["release"]["status"], "pending")
        self.assertEqual(result["execution"]["elapsed_ms_total"], 100)

    def test_reviewed_metrics_use_only_bound_human_labels(self):
        values = fixture()
        case = values[0]["cases"][0]
        review(case, values[1][case["id"]])
        result = evaluate(values)
        self.assertEqual(
            result["metrics"]["label_agreement"],
            {"value": 1, "numerator": 4, "denominator": 4},
        )
        self.assertEqual(
            result["metrics"]["appropriate_cannot_assess"]["denominator"], 4
        )
        self.assertIsNone(result["metrics"]["unsupported_fault_rate"]["value"])
        case["annotation"]["transcript_version"] = "old"
        self.assertIsNone(evaluate(values)["metrics"]["label_agreement"]["value"])
        case["annotation"]["transcript_version"] = values[1][case["id"]][
            "transcript_version"
        ]
        case["annotation"]["reviewed_at"] = "2027-01-01"
        self.assertIsNone(evaluate(values)["metrics"]["label_agreement"]["value"])

    def test_changed_report_content_requires_fresh_human_review(self):
        for mutation in (
            "summary",
            "claim-kind",
            "topic",
            "category",
            "citation-order",
        ):
            values = fixture("held-out")
            case = values[0]["cases"][20]
            report = values[1][case["id"]]
            passages = conversation_passages([values[2]["conversations"][0]])
            claim = report["summary"]["claims"][0]
            if mutation == "citation-order":
                claim["citations"].append(deepcopy(passages[-1]["citation"]))
            freeze(values[0], values[1])
            for entry in values[0]["cases"][20:]:
                review(entry, values[1][entry["id"]])
            self.assertEqual(
                evaluate(values, partition="held-out")["release"]["status"], "ready"
            )
            if mutation == "summary":
                citation = deepcopy(passages[-1]["citation"])
                claim.update(text=citation["quote"], citations=[citation])
            elif mutation == "claim-kind":
                claim["kind"] = "agent-promise"
            elif mutation == "topic":
                report["topic"].update(
                    labels=["refund"], citations=[deepcopy(passages[1]["citation"])]
                )
            elif mutation == "category":
                report["categories"][0]["result"]["explanation"] = "Revised assessment."
            else:
                claim["citations"].reverse()
            with self.subTest(mutation=mutation):
                result = evaluate(values, partition="held-out")
                self.assertEqual(result["counts"]["invalid_reports"], 0)
                self.assertEqual(result["counts"]["unreviewed_cases"], 1)
                self.assertEqual(result["release"]["status"], "pending")
                self.assertEqual(
                    result["metrics"]["summary_faithfulness"]["denominator"], 18
                )
                review(case, report)
                self.assertEqual(
                    evaluate(values, partition="held-out")["release"]["status"],
                    "ready",
                )

    def test_review_fingerprint_is_stable_and_runtime_metrics_do_not_invalidate_it(
        self,
    ):
        values = fixture("held-out")
        freeze(values[0], values[1])
        for case in values[0]["cases"][20:]:
            review(case, values[1][case["id"]])
        report = next(iter(values[1].values()))
        before = deepcopy(report)
        version = report_content_version(report)
        self.assertEqual(report, before)
        self.assertEqual(
            report_content_version(dict(reversed(list(report.items())))), version
        )
        report["metrics"]["elapsed_ms"] = 6.0
        self.assertEqual(report_content_version(report), version)
        self.assertEqual(
            evaluate(values, partition="held-out")["release"]["status"], "ready"
        )
        for missing in (None, "stale"):
            values[0]["cases"][20]["annotation"]["report_version"] = missing
            with self.subTest(report_version=missing):
                result = evaluate(values, partition="held-out")
                self.assertEqual(result["counts"]["unreviewed_cases"], 1)
                self.assertEqual(result["release"]["status"], "pending")

    def test_oversized_numeric_metrics_are_isolated_as_invalid_reports(self):
        for field in ("elapsed_ms", "model_call_cost_usd"):
            for value in (10**400, -(10**400), float("inf"), float("nan")):
                values = fixture()
                report = next(iter(values[1].values()))
                report["metrics"][field] = (
                    json.loads(json.dumps(value)) if isinstance(value, int) else value
                )
                with self.subTest(field=field, value=value):
                    result = evaluate(values)
                    self.assertEqual(result["counts"]["invalid_reports"], 1)
                    self.assertEqual(result["counts"]["processing_errors"], 1)
                    self.assertEqual(result["counts"]["completed_categories"], 76)
                    self.assertEqual(result["execution"]["measured_reports"], 19)
                    self.assertEqual(result["release"]["status"], "blocked")
                    json.dumps(result, allow_nan=False)

    def test_timing_total_overflow_rejects_only_unrepresentable_reports(self):
        for value in (1e308, 10**308):
            values = fixture()
            reports = list(values[1].values())
            reports[0]["metrics"]["elapsed_ms"] = value
            reports[1]["metrics"]["elapsed_ms"] = value
            with self.subTest(value=value):
                result = evaluate(values)
                self.assertEqual(result["counts"]["invalid_reports"], 1)
                self.assertEqual(result["counts"]["completed_categories"], 76)
                self.assertEqual(result["execution"]["measured_reports"], 19)
                self.assertEqual(result["execution"]["elapsed_ms_total"], float(value))
                self.assertEqual(result["release"]["status"], "blocked")
                json.dumps(result, allow_nan=False)

    def test_non_json_review_content_is_a_controlled_report_error(self):
        for value in (float("nan"), object()):
            values = fixture()
            report = next(iter(values[1].values()))
            report["categories"][0]["result"]["details"]["invalid"] = value
            with self.subTest(value=value):
                result = evaluate(values)
                self.assertEqual(result["counts"]["invalid_reports"], 1)
                self.assertEqual(result["execution"]["measured_reports"], 19)
                self.assertEqual(result["release"]["status"], "blocked")

    def test_partial_missing_and_unbound_failures_are_processing_errors(self):
        values = fixture()
        case = values[0]["cases"][0]
        report = values[1][case["id"]]
        report["processing_status"] = "partial"
        report["categories"][0].update(status="failed", result=None, error="deadline")
        report["errors"] = [
            {"code": "deadline", "category": "procedure", "message": "Time expired."}
        ]
        review(case, report)
        result = evaluate(values)
        self.assertEqual(result["counts"]["processing_errors"], 1)
        self.assertEqual(result["counts"]["failed_categories"], 1)
        self.assertEqual(result["metrics"]["label_agreement"]["denominator"], 3)
        report.update(
            processing_status="failed",
            conversation_id=None,
            transcript_version=None,
            source=None,
            masking_version=None,
            licence=None,
            as_of=None,
            scope=None,
        )
        report["versions"]["references"] = report["versions"]["rubric"] = []
        report["categories"] = [
            {"category": name, "status": "not-run", "result": None, "error": None}
            for name in CATEGORIES
        ]
        report["summary"]["claims"] = []
        result = evaluate(values)
        self.assertEqual(result["counts"]["invalid_reports"], 0)
        self.assertEqual(result["counts"]["processing_errors"], 1)
        values[1].pop(case["id"])
        self.assertEqual(evaluate(values)["counts"]["failed_categories"], 4)

    def test_fabricated_quotes_or_summary_claims_and_wrong_roles_block_release(self):
        for mutation in (
            "citation",
            "category-citation",
            "null-citation",
            "report-type",
            "claim",
            "role",
            "tokens",
            "version",
        ):
            values = fixture()
            report = next(iter(values[1].values()))
            if mutation == "citation":
                report["summary"]["claims"][0]["citations"][0] = {
                    **report["summary"]["claims"][0]["citations"][0],
                    "quote": "Fabricated text.",
                }
            elif mutation == "category-citation":
                report["categories"][0]["result"]["details"]["checks"][0]["citations"][
                    0
                ] = {
                    **report["categories"][0]["result"]["details"]["checks"][0][
                        "citations"
                    ][0],
                    "quote": "Fabricated text.",
                }
            elif mutation == "null-citation":
                report["summary"]["claims"][0]["citations"].append(None)
            elif mutation == "report-type":
                values[1][next(iter(values[1]))] = []
            elif mutation == "claim":
                report["summary"]["claims"][0]["text"] = "The refund succeeded."
            elif mutation == "role":
                report["summary"]["claims"][0]["kind"] = "recorded-action"
            elif mutation == "tokens":
                report["metrics"]["token_usage"] = 100
            else:
                report["transcript_version"] = "stale"
            with self.subTest(mutation=mutation):
                result = evaluate(values)
                self.assertEqual(result["release"]["status"], "blocked")
                self.assertGreater(result["counts"]["invalid_reports"], 0)
                self.assertEqual(result["counts"]["processing_errors"], 1)
                if "citation" in mutation:
                    self.assertGreater(result["counts"]["invalid_citations"], 0)

    def test_evidence_and_reports_cannot_cross_partitions_or_source_positions(self):
        values = fixture()
        values[1]["200001"] = deepcopy(next(iter(values[1].values())))
        with self.assertRaises(ValueError):
            evaluate(values)
        values = fixture()
        values[0]["cases"][0]["source_pointer"] = "/train/9999"
        with self.assertRaises(ValueError):
            evaluate(values)

    def test_human_confirmed_unsupported_findings_block_even_with_exact_citations(self):
        values = fixture()
        case = values[0]["cases"][0]
        report, conversation = values[1][case["id"]], values[2]["conversations"][0]
        cite = conversation_passages([conversation])[0]["citation"]
        check = {
            "rule_id": "constructed-refusal",
            "result": "needs-review",
            "explanation": "Constructed fault for semantic review.",
            "advice": "Review source.",
            "citations": [cite],
        }
        report["categories"][2]["result"] = category_result(
            conversation, "completeness", [check]
        )
        review(case, report)
        case["annotation"]["unsupported_findings"] = 1
        result = evaluate(values)
        self.assertEqual(result["counts"]["unsupported_findings"], 1)
        self.assertEqual(result["metrics"]["unsupported_fault_rate"]["value"], 1)
        self.assertEqual(result["release"]["status"], "blocked")

    def test_heldout_is_locked_until_versions_and_checks_are_frozen(self):
        values = fixture("held-out")
        with self.assertRaises(ValueError):
            evaluate(values, partition="held-out")
        freeze(values[0], values[1])
        result = evaluate(values, partition="held-out")
        self.assertEqual(result["release"]["status"], "pending")
        for case in values[0]["cases"][20:]:
            review(case, values[1][case["id"]])
        self.assertEqual(
            evaluate(values, partition="held-out")["release"]["status"], "ready"
        )
        next(iter(values[1].values()))["versions"]["rules"] = {"changed": "2"}
        self.assertEqual(
            evaluate(values, partition="held-out")["release"]["status"], "blocked"
        )

    def test_changed_execution_limits_cannot_reuse_a_heldout_freeze(self):
        for name in (
            "max_events",
            "max_input_bytes",
            "max_output_bytes",
            "timeout_seconds",
        ):
            values = fixture("held-out")
            freeze(values[0], values[1])
            for case in values[0]["cases"][20:]:
                review(case, values[1][case["id"]])
            case = values[0]["cases"][20]
            report = values[1][case["id"]]
            report["versions"]["limits"][name] *= 2
            review(case, report)
            with self.subTest(limit=name):
                result = evaluate(values, partition="held-out")
                self.assertEqual(result["counts"]["invalid_reports"], 1)
                self.assertEqual(result["release"]["status"], "blocked")

    def test_missing_or_invalid_execution_limits_cannot_unlock_heldout(self):
        defaults = next(iter(fixture()[1].values()))["versions"]["limits"]
        for limits in (
            None,
            {},
            {**defaults, "unknown": 1},
            {**defaults, "max_events": True},
            {**defaults, "max_input_bytes": 0},
            {**defaults, "max_output_bytes": 1000},
            {**defaults, "timeout_seconds": float("nan")},
            {**defaults, "timeout_seconds": 10**400},
        ):
            with self.subTest(limits=limits):
                values = fixture("held-out")
                freeze(values[0], values[1])
                if limits is None:
                    values[0]["freeze"]["versions"].pop("limits")
                else:
                    values[0]["freeze"]["versions"]["limits"] = limits
                with self.assertRaises(ValueError):
                    evaluate(values, partition="held-out")
                values = fixture()
                report = next(iter(values[1].values()))
                if limits is None:
                    report["versions"].pop("limits")
                else:
                    report["versions"]["limits"] = limits
                self.assertEqual(evaluate(values)["counts"]["invalid_reports"], 1)

    def test_metadata_only_and_incomplete_or_disputed_reviews_cannot_release(self):
        for missing in (
            "expected_results",
            "reasons",
            "evidence_gaps",
            "citation_support",
            "summary_faithfulness",
            "topic_faithfulness",
            "second_review_agreement",
            "disagreement",
        ):
            values = fixture("held-out")
            freeze(values[0], values[1])
            for case in values[0]["cases"][20:]:
                review(case, values[1][case["id"]])
            annotation = values[0]["cases"][21]["annotation"]
            if missing == "disagreement":
                annotation["second_review_agreement"] = False
                annotation["disagreements"] = [
                    {"note": "Unresolved interpretation.", "resolved": False}
                ]
            else:
                annotation[missing] = None
            with self.subTest(missing=missing):
                self.assertEqual(
                    evaluate(values, partition="held-out")["release"]["status"],
                    "pending",
                )
        values = fixture("held-out")
        freeze(values[0], values[1])
        for case in values[0]["cases"][20:]:
            annotation = case["annotation"]
            annotation.update(
                transcript_version=values[1][case["id"]]["transcript_version"],
                versions=deepcopy(values[1][case["id"]]["versions"]),
                reviewed_by="Test reviewer",
                reviewed_at=AS_OF,
            )
        self.assertEqual(
            evaluate(values, partition="held-out")["release"]["status"], "pending"
        )

    def test_historical_reports_use_their_assessment_date_not_review_cutoff(self):
        values = fixture()
        reference = eligible_references(
            values[3], as_of=AS_OF, scope="refund-initiation"
        )[0]
        from ml.references import reference_passages

        citation = reference_passages([reference])[0]["citation"]
        report = next(iter(values[1].values()))
        report["categories"][0]["result"]["details"]["checks"][0]["citations"].append(
            citation
        )
        result = evaluate_reports(
            values[0],
            values[1],
            evidence=values[2],
            references=values[3],
            rubric=values[4],
            as_of="2027-10-29",
        )
        self.assertEqual(result["counts"]["invalid_reports"], 0)
        self.assertEqual(result["counts"]["invalid_citations"], 0)
        report["as_of"] = "2028-01-01"
        self.assertEqual(evaluate(values)["counts"]["invalid_reports"], 1)

    def test_invalid_or_future_review_provenance_cannot_unlock_holdout(self):
        for record in ("freeze", "release_checks"):
            for day in (None, "yesterday", "2027-01-01", "20261030"):
                values = fixture("held-out")
                freeze(values[0], values[1])
                values[0][record]["reviewed_at"] = day
                with (
                    self.subTest(record=record, day=day),
                    self.assertRaises(ValueError),
                ):
                    evaluate(values, partition="held-out")

    def test_reviewed_topic_error_blocks_the_approved_quality_threshold(self):
        values = fixture("held-out")
        freeze(values[0], values[1])
        for case in values[0]["cases"][20:]:
            review(case, values[1][case["id"]])
        values[0]["cases"][20]["annotation"]["topic_faithfulness"] = False
        result = evaluate(values, partition="held-out")
        self.assertEqual(result["metrics"]["topic_faithfulness"]["numerator"], 18)
        self.assertEqual(result["metrics"]["topic_faithfulness"]["denominator"], 19)
        self.assertEqual(result["release"]["status"], "blocked")


class RetrievalTests(unittest.TestCase):
    def test_retrieval_has_separate_unset_human_judgements_and_eligible_sources(self):
        references = catalog()
        cases = [
            {
                "query": "username email order ID validate purchase",
                "expected_ids": None,
                "reviewed_by": None,
                "reviewed_at": None,
            }
        ]
        before = deepcopy(references)
        result = evaluate_retrieval(
            cases, references, as_of=AS_OF, scope="refund-initiation"
        )
        self.assertIsNone(result["relevant_top_three"]["value"])
        cases[0].update(
            expected_ids=["abcd-refund-initiate-purchase-validation"],
            reviewed_by="Test reviewer",
            reviewed_at=AS_OF,
            reference_versions=[
                {"id": ref["id"], "version": ref["version"]}
                for ref in eligible_references(
                    references, as_of=AS_OF, scope="refund-initiation"
                )
            ],
        )
        self.assertEqual(
            evaluate_retrieval(
                cases, references, as_of=AS_OF, scope="refund-initiation"
            )["relevant_top_three"]["value"],
            1,
        )
        expired = evaluate_retrieval(
            cases, references, as_of="2027-10-29", scope="refund-initiation"
        )
        self.assertEqual(expired["results"][0]["ids"], [])
        self.assertIsNone(expired["relevant_top_three"]["value"])
        self.assertEqual(references, before)


if __name__ == "__main__":
    unittest.main()
