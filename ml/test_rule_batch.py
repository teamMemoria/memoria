"""Synthetic cohort tests: no held-out records or model calls."""

import json
import unittest
from copy import deepcopy
from pathlib import Path
from unittest.mock import patch

from ml.abcd import prepare_dataset
from ml.rule_assessment import RULE_VERSION, assess_conversation
from ml.rule_batch import cohort_summary, run_cohort
from ml.scoring import content_version
from ml.test_evidence import SOURCE, source_record

ROOT = Path(__file__).resolve().parent
DATE = "2026-11-09"


def freeze(manifest):
    manifest["version"] = content_version(
        {key: value for key, value in manifest.items() if key != "version"}
    )
    return manifest


class RuleBatchTests(unittest.TestCase):
    def setUp(self):
        self.evidence = prepare_dataset(
            {"train": [source_record(300), source_record(301)], "dev": [], "test": []},
            SOURCE,
            ("300", "301"),
        )
        self.manifest = freeze(
            {
                "source": SOURCE,
                "development_ids": ["300"],
                "conversations": [
                    {
                        "id": str(identifier),
                        "split": "train",
                        "source_index": index,
                        "alias": alias,
                    }
                    for index, (identifier, alias) in enumerate(
                        ((300, "Avery"), (301, "Jordan"))
                    )
                ],
                "human_spotcheck": {
                    "conversation_ids": ["300"],
                    "reviewer": None,
                    "reviewed_at": None,
                    "judgements": None,
                },
            }
        )
        self.references = json.loads((ROOT / "references.json").read_text())[
            "references"
        ]
        self.rubric = json.loads((ROOT / "rubric.json").read_text())
        self.tables = json.loads((ROOT / "rule_tables.json").read_text())

    def run_batch(self, **kwargs):
        return run_cohort(
            self.evidence,
            self.manifest,
            self.references,
            self.rubric,
            self.tables,
            as_of=kwargs.pop("as_of", DATE),
            **kwargs,
        )

    def test_complete_cohort_is_repeatable_without_manufacturing_scores(self):
        before = deepcopy(
            (self.evidence, self.manifest, self.references, self.rubric, self.tables)
        )
        first, second = self.run_batch(), self.run_batch()
        self.assertEqual(set(first["records"]), {"300", "301"})
        for identifier, attempt in first["records"].items():
            self.assertEqual(attempt["report"], second["records"][identifier]["report"])
            self.assertIsNone(attempt["error"])
            self.assertGreaterEqual(attempt["elapsed_ms"], 0)
            self.assertIsNone(attempt["report"]["overall"]["score"])
        self.assertEqual(
            before,
            (self.evidence, self.manifest, self.references, self.rubric, self.tables),
        )

    def test_development_then_resume_all_keeps_same_frozen_ids(self):
        development = self.run_batch(development=True)
        self.assertEqual(set(development["records"]), {"300"})
        with patch(
            "ml.rule_batch.assess_conversation", wraps=assess_conversation
        ) as evaluate:
            completed = self.run_batch(checkpoint=development)
        self.assertEqual(evaluate.call_count, 1)
        self.assertTrue(completed["records"]["300"]["cached"])
        self.assertFalse(completed["records"]["301"]["cached"])
        with patch(
            "ml.rule_batch.assess_conversation",
            side_effect=AssertionError("Unexpected rerun"),
        ):
            cached = self.run_batch(checkpoint=completed)
        self.assertTrue(all(row["cached"] for row in cached["records"].values()))

    def test_manifest_version_source_and_membership_are_enforced(self):
        mutations = [
            lambda: self.manifest.update(version="changed"),
            lambda: self.evidence["source"].update(commit="wrong"),
            lambda: self.evidence["conversations"].pop(),
            lambda: self.evidence["conversations"].append(
                deepcopy(self.evidence["conversations"][0])
            ),
        ]
        for mutate in mutations:
            with self.subTest(mutate=mutate):
                self.setUp()
                mutate()
                with self.assertRaises(ValueError):
                    self.run_batch()

    def test_nontraining_or_duplicate_manifest_records_are_rejected(self):
        for mutation in ("split", "duplicate", "development"):
            with self.subTest(mutation=mutation):
                self.setUp()
                if mutation == "split":
                    self.manifest["conversations"][0]["split"] = "test"
                elif mutation == "duplicate":
                    self.manifest["conversations"][1]["id"] = "300"
                else:
                    self.manifest["development_ids"] = ["999"]
                freeze(self.manifest)
                with self.assertRaises(ValueError):
                    self.run_batch(development=mutation == "development")

    def test_wrong_original_position_is_isolated_without_replacement(self):
        self.manifest["conversations"][0]["source_index"] = 99
        freeze(self.manifest)
        result = self.run_batch()
        self.assertIsNone(result["records"]["300"]["report"])
        self.assertIn("position", result["records"]["300"]["error"])
        self.assertEqual(
            result["records"]["301"]["report"]["processing_status"], "completed"
        )
        self.assertEqual(set(result["records"]), {"300", "301"})

    def test_invalid_record_does_not_stop_its_valid_neighbor(self):
        self.evidence["conversations"][0]["events"][0]["text"] = (
            "changed without a source version"
        )
        result = self.run_batch()
        self.assertIsNotNone(result["records"]["300"]["error"])
        self.assertIsNone(result["records"]["301"]["error"])
        self.assertEqual(cohort_summary(result)["counts"]["failed"], 1)

    def test_inputs_that_change_authority_or_time_invalidate_checkpoints(self):
        for field in ("references", "rubric", "tables", "date", "rules"):
            with self.subTest(field=field):
                self.setUp()
                previous = self.run_batch()
                kwargs = {}
                if field == "references":
                    self.references[0]["status"] = "unapproved"
                elif field == "rubric":
                    self.rubric["references"][0]["verified_at"] = "2026-11-08"
                elif field == "tables":
                    self.tables["review_package"]["verified_at"] = "2026-11-08"
                elif field == "date":
                    kwargs["as_of"] = "2026-11-10"
                with (
                    patch(
                        "ml.rule_batch.RULE_VERSION",
                        "changed" if field == "rules" else RULE_VERSION,
                    ),
                    patch(
                        "ml.rule_batch.assess_conversation", wraps=assess_conversation
                    ) as evaluate,
                ):
                    current = self.run_batch(checkpoint=previous, **kwargs)
                self.assertEqual(evaluate.call_count, 2)
                self.assertEqual(len(current["history"]), 2)
                self.assertEqual(
                    current["history"][0]["attempt"], previous["records"]["300"]
                )
                self.assertNotEqual(current["run_version"], previous["run_version"])

    def test_changed_alias_metadata_cannot_change_category_scores(self):
        original = self.run_batch()
        self.manifest["conversations"][0]["alias"] = "Different demo alias"
        freeze(self.manifest)
        renamed = self.run_batch()
        self.assertEqual(
            original["records"]["300"]["report"], renamed["records"]["300"]["report"]
        )

    def test_corrupt_checkpoint_is_archived_and_recomputed(self):
        for corrupt in ("not a report", {}, {"processing_status": "completed"}):
            with self.subTest(corrupt=corrupt):
                checkpoint = self.run_batch()
                checkpoint["records"]["300"]["report"] = corrupt
                with patch(
                    "ml.rule_batch.assess_conversation", wraps=assess_conversation
                ) as evaluate:
                    restored = self.run_batch(checkpoint=checkpoint)
                self.assertEqual(evaluate.call_count, 1)
                self.assertEqual(restored["history"][0]["attempt"]["report"], corrupt)
                self.assertIsNone(restored["records"]["300"]["error"])

    def test_changed_canonical_evidence_invalidates_only_that_record(self):
        checkpoint = self.run_batch()
        changed = source_record(300)
        changed["original"][0][1] = "Hello. Please provide your username and order ID."
        self.evidence = prepare_dataset(
            {"train": [changed, source_record(301)], "dev": [], "test": []},
            SOURCE,
            ("300", "301"),
        )
        with patch(
            "ml.rule_batch.assess_conversation", wraps=assess_conversation
        ) as evaluate:
            resumed = self.run_batch(checkpoint=checkpoint)
        self.assertEqual(evaluate.call_count, 1)
        self.assertFalse(resumed["records"]["300"]["cached"])
        self.assertTrue(resumed["records"]["301"]["cached"])
        self.assertNotEqual(
            resumed["records"]["300"]["key"], checkpoint["records"]["300"]["key"]
        )
        self.assertEqual(len(resumed["history"]), 1)

    def test_tampered_cached_percentage_is_not_trusted(self):
        checkpoint = self.run_batch()
        checkpoint["records"]["300"]["report"]["categories"][0]["scoring"]["score"] = (
            100
        )
        resumed = self.run_batch(checkpoint=checkpoint)
        self.assertFalse(resumed["records"]["300"]["cached"])
        self.assertEqual(
            resumed["history"][0]["attempt"]["report"]["categories"][0]["scoring"][
                "score"
            ],
            100,
        )
        self.assertIsNone(
            resumed["records"]["300"]["report"]["categories"][0]["scoring"]["score"]
        )

    def test_partial_categories_are_preserved_then_retried_without_erasing_failure(
        self,
    ):
        with patch(
            "ml.rule_assessment._style", side_effect=ValueError("Simulated failure")
        ):
            failed = self.run_batch()
        self.assertEqual(cohort_summary(failed)["counts"]["partial"], 2)
        for attempt in failed["records"].values():
            self.assertEqual(
                sum(
                    row["status"] == "completed"
                    for row in attempt["report"]["categories"]
                ),
                3,
            )
        resumed = self.run_batch(checkpoint=failed)
        self.assertEqual(cohort_summary(resumed)["counts"]["completed"], 2)
        self.assertEqual(len(resumed["history"]), 2)
        self.assertEqual(resumed["history"][0]["attempt"], failed["records"]["300"])

    def test_foreign_checkpoint_record_never_joins_the_frozen_cohort(self):
        checkpoint = self.run_batch()
        checkpoint["records"]["999"] = deepcopy(checkpoint["records"]["300"])
        try:
            resumed = self.run_batch(checkpoint=checkpoint)
        except ValueError:
            return
        self.assertEqual(set(resumed["records"]), {"300", "301"})
        self.assertTrue(
            any(item["conversation_id"] == "999" for item in resumed["history"])
        )

    def test_changed_version_development_run_cannot_mix_old_full_results(self):
        checkpoint = self.run_batch()
        resumed = self.run_batch(
            checkpoint=checkpoint, development=True, as_of="2026-11-10"
        )
        for attempt in resumed["records"].values():
            self.assertEqual(attempt["report"]["as_of"], "2026-11-10")
        self.assertTrue(
            any(item["conversation_id"] == "301" for item in resumed["history"])
        )

    def test_summary_reports_coverage_without_claiming_accuracy_or_approval(self):
        summary = cohort_summary(self.run_batch())
        self.assertEqual(
            summary["counts"], {"completed": 2, "partial": 0, "failed": 0, "cached": 0}
        )
        self.assertEqual(summary["semantic_accuracy"], "not evaluated")
        self.assertIsNone(summary["human_review"]["reviewer"])
        self.assertIsNone(summary["human_review"]["judgements"])
        for group in summary["candidate_workflow_metrics"].values():
            self.assertEqual(group["scored"], 0)
            self.assertIsNone(group["semantic_errors"])


if __name__ == "__main__":
    unittest.main()
