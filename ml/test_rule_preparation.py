"""Opt-in financial masking retains legacy evidence and canonical positions."""

import json
import unittest
from copy import deepcopy
from pathlib import Path
from unittest.mock import patch

from ml.abcd import (
    ABCD_COMMIT,
    ABCD_SHA256,
    MASKING_VERSION,
    MIT_NOTICE,
    UNMASKED_DEMO_VERSION,
    mask_texts,
    prepare_conversation,
    transcript_version,
    validate_evidence,
)
from ml.rule_batch import prepare_cohort, restore_demo_text, run_cohort
from ml.scoring import content_version


def record():
    return {
        "convo_id": 701,
        "original": [
            ["customer", "Please refund to 4242 1234 5678 9012."],
            ["agent", "I recorded 4242-1234-5678-9012."],
            ["action", "Details of 4242123456789012 have been entered."],
        ],
    }


def envelope(conversation, version):
    return {
        "schema_version": 1,
        "source": {
            "dataset": "ABCD",
            "commit": ABCD_COMMIT,
            "path": "data/abcd_v1.1.json",
            "sha256": ABCD_SHA256,
        },
        "masking_version": version,
        "conversations": [conversation],
        "licence": {"name": "MIT", "notice": MIT_NOTICE},
    }


class RulePreparationTests(unittest.TestCase):
    def test_restoration_preserves_scores_and_revalidates_original_citations(self):
        from ml.rule_assessment import assess_conversation
        from ml.scoring import eligible_sources, validate_scored_report
        from ml.test_rule_scoring import AS_OF, decision_tables

        source = {
            "convo_id": 701,
            "original": [
                ["customer", "Where is my shipment? My email is rene@example.test."],
                ["agent", "Thanks for waiting."],
                ["agent", "Shipping takes 3 business days after dispatch."],
                ["agent", "You are an idiot."],
            ],
            "targets": ["HIDDEN_LABEL"],
        }
        evidence = envelope(prepare_conversation(source, split="train", index=3), "4")
        tables = decision_tables()
        rubric = {"references": []}
        report = assess_conversation(evidence, [], rubric, tables, as_of=AS_OF)
        before = deepcopy(report)
        restored = restore_demo_text(report, evidence, source)
        refs = eligible_sources(
            [], rubric, tables, as_of=AS_OF, workflows=report["workflows"]
        )
        validate_scored_report(
            restored["report"], restored["evidence"], refs, tables, as_of=AS_OF
        )
        self.assertEqual(report, before)
        self.assertEqual(restored["report"]["overall"], before["overall"])
        for old, new in zip(before["categories"], restored["report"]["categories"]):
            self.assertEqual(old["scoring"]["score"], new["scoring"]["score"])
            self.assertEqual(old["scoring"]["coverage"], new["scoring"]["coverage"])
        self.assertNotIn("HIDDEN_LABEL", json.dumps(restored))
        self.assertIn("rene@example.test", json.dumps(restored))
        self.assertTrue(
            any(row["result"]["findings"] for row in restored["report"]["categories"])
        )
        # Names/contact values must come from the original, never a guessed token replacement.
        wrong = deepcopy(source)
        wrong["original"][0][1] = "Cancel my shipment instead."
        with self.assertRaises(ValueError):
            restore_demo_text(report, evidence, wrong)
        bad = deepcopy(report)
        citation = next(
            c
            for row in bad["categories"]
            for check in row["scoring"]["checks"]
            for c in check["citations"]
            if c["kind"] == "conversation"
        )
        citation["quote"] = "Invented quotation"
        with self.assertRaises(ValueError):
            restore_demo_text(bad, evidence, source)
        # Even a valid substring must not be expanded or remapped by guessing.
        citation["quote"] = "Thanks"
        citation["turn_id"] = 2
        with self.assertRaises(ValueError):
            restore_demo_text(bad, evidence, source)

    def test_unmasked_demo_retains_exact_original_text_and_source_positions(self):
        source = record()
        source["original"][0][1] = "I'm René. Email René@example.test; refund $45.99."
        source["targets"] = ["HIDDEN_LABEL"]
        original = deepcopy(source)
        prepared = prepare_conversation(
            source, split="train", index=3, masking_version=UNMASKED_DEMO_VERSION
        )
        self.assertEqual(
            [event["text"] for event in prepared["events"]],
            [event[1] for event in source["original"]],
        )
        self.assertEqual(
            [event["source_pointer"] for event in prepared["events"]],
            [f"/train/3/original/{i}" for i in range(3)],
        )
        self.assertNotIn("HIDDEN_LABEL", json.dumps(prepared))
        self.assertEqual(source, original)
        validate_evidence(envelope(prepared, UNMASKED_DEMO_VERSION))
        with self.assertRaises(ValueError):
            validate_evidence(envelope(prepared, "5"))
        changed = deepcopy(prepared)
        changed["events"][0]["text"] += " Changed."
        with self.assertRaises(ValueError):
            validate_evidence(envelope(changed, UNMASKED_DEMO_VERSION))

    def test_unmasked_demo_rejects_held_out_splits(self):
        for split in ("dev", "test"):
            with self.assertRaises(ValueError):
                prepare_conversation(
                    record(),
                    split=split,
                    index=3,
                    masking_version=UNMASKED_DEMO_VERSION,
                )
            prepared = prepare_conversation(record(), split=split, index=3)
            prepared["transcript_version"] = transcript_version(
                prepared, masking_version=UNMASKED_DEMO_VERSION
            )
            with self.assertRaises(ValueError):
                validate_evidence(envelope(prepared, UNMASKED_DEMO_VERSION))

    def test_default_v4_evidence_is_byte_compatible(self):
        legacy = prepare_conversation(record(), split="train", index=3)
        self.assertEqual(MASKING_VERSION, "4")
        self.assertEqual(
            legacy,
            prepare_conversation(record(), split="train", index=3, masking_version="4"),
        )
        self.assertEqual(
            legacy["transcript_version"],
            "sha256:0a2d6066cad332bdea4942ab950f0d2da6ce0b145862fe3dae53dc3bfabbadd4",
        )
        validate_evidence(envelope(legacy, "4"))

    def test_v5_masks_equivalent_formats_consistently_in_every_role(self):
        prepared = prepare_conversation(
            record(), split="train", index=3, masking_version="5"
        )
        self.assertEqual(
            [event["text"] for event in prepared["events"]],
            [
                "Please refund to [FINANCIAL_ID_1].",
                "I recorded [FINANCIAL_ID_1].",
                "Details of [FINANCIAL_ID_1] have been entered.",
            ],
        )
        self.assertEqual([event["turn_id"] for event in prepared["events"]], [1, 2, 3])
        self.assertEqual(
            [event["source_pointer"] for event in prepared["events"]],
            [f"/train/3/original/{index}" for index in range(3)],
        )
        validate_evidence(envelope(prepared, "5"))
        self.assertEqual(
            prepared["transcript_version"],
            transcript_version(prepared, masking_version="5"),
        )
        self.assertNotEqual(
            prepared["transcript_version"], transcript_version(prepared)
        )

    def test_version_is_explicit_and_cannot_be_relabelled(self):
        for version in ("4", "5"):
            prepared = prepare_conversation(
                record(), split="train", index=3, masking_version=version
            )
            wrong = "5" if version == "4" else "4"
            with self.assertRaises(ValueError):
                validate_evidence(envelope(prepared, wrong))
        for unsupported in ("6", None, True):
            with self.assertRaises(ValueError):
                prepare_conversation(
                    record(), split="train", index=3, masking_version=unsupported
                )

    def test_length_boundaries_grouping_and_currency(self):
        for digits in ("1234567890123", "1234567890123456789"):
            forms = [digits, "-".join(digits), "  ".join(digits), "\u00a0".join(digits)]
            self.assertEqual(
                mask_texts(forms, {}, masking_version="5"), ["[FINANCIAL_ID_1]"] * 4
            )
        for text in (
            "Refund $1234567890123.",
            "Fee €1234567890123",
            "Please refund $45.99",
        ):
            self.assertEqual(mask_texts([text], {}, masking_version="5"), [text])
        values = ["4242 1234 5678 9012", "1234 5678 9012 3456", "4242123456789012"]
        self.assertEqual(
            mask_texts(values, {}, masking_version="5"),
            ["[FINANCIAL_ID_1]", "[FINANCIAL_ID_2]", "[FINANCIAL_ID_1]"],
        )

    def test_gold_annotations_stay_out_and_input_is_unchanged(self):
        source = record()
        source.update(flow="GOLD_FLOW", subflow="GOLD_SUBFLOW", targets=["GOLD_TARGET"])
        source["scenario"] = {"intent": "GOLD_INTENT", "customer": "GOLD_CUSTOMER"}
        before = deepcopy(source)
        prepared = prepare_conversation(
            source, split="train", index=3, masking_version="5"
        )
        self.assertNotIn("GOLD_", json.dumps(prepared))
        self.assertEqual(source, before)
        self.assertEqual(prepared["coverage"]["actions"]["status"], "complete")
        self.assertEqual(prepared["coverage"]["transcript"]["status"], "complete")


def cohort_manifest(rows):
    value = {"source": envelope(None, "5")["source"], "conversations": rows}
    value["version"] = content_version(value)
    return value


class CohortPreparationTests(unittest.TestCase):
    def test_allowlist_precedes_preparation_and_aliases_are_not_inputs(self):
        source = record()
        source.update(flow="GOLD_FLOW", target="GOLD_TARGET")
        source["scenario"] = {
            "intent": "GOLD_INTENT",
            "personal": {"intent": "GOLD_NESTED"},
        }
        source["delexed"] = [
            {"speaker": event[0], "turn_count": index + 1, "target": "GOLD_ACTION"}
            for index, event in enumerate(source["original"])
        ]
        training = [source]
        manifest = cohort_manifest(
            [{"id": "701", "split": "train", "source_index": 0, "alias": "DEMO_ALIAS"}]
        )
        before = deepcopy(training)
        with patch(
            "ml.rule_batch.prepare_conversation", wraps=prepare_conversation
        ) as prepare:
            result = prepare_cohort(training, manifest["source"], manifest)
        self.assertNotIn("GOLD_", json.dumps(prepare.call_args.args))
        self.assertNotIn("DEMO_ALIAS", json.dumps(prepare.call_args.args))
        self.assertEqual(result["errors"], {})
        self.assertEqual(result["warnings"], {})
        self.assertEqual(training, before)
        validate_evidence(result["evidence"])
        self.assertEqual(result["evidence"]["masking_version"], "5")

    def test_annotation_warning_does_not_discard_valid_original_evidence(self):
        source = record()
        source["delexed"] = [
            {"speaker": "customer", "turn_count": 999, "target": "GOLD"}
        ]
        manifest = cohort_manifest([{"id": "701", "split": "train", "source_index": 0}])
        result = prepare_cohort([source], manifest["source"], manifest)
        self.assertEqual(result["errors"], {})
        self.assertIn("/delexed", result["warnings"]["701"])
        expected = prepare_conversation(
            record(), split="train", index=0, masking_version="5"
        )
        self.assertEqual(result["evidence"]["conversations"], [expected])

    def test_bad_or_missing_records_are_isolated_without_replacement(self):
        manifest = cohort_manifest(
            [
                {"id": "701", "split": "train", "source_index": 0},
                {"id": "702", "split": "train", "source_index": 1},
                {"id": "703", "split": "train", "source_index": 2},
                {"id": "704", "split": "train", "source_index": 3},
            ]
        )
        training = [
            record(),
            {"convo_id": 999, "original": record()["original"]},
            {"convo_id": 703, "original": []},
        ]
        result = prepare_cohort(training, manifest["source"], manifest)
        self.assertEqual(set(result["errors"]), {"702", "703", "704"})
        self.assertEqual(
            [c["id"] for c in result["evidence"]["conversations"]], ["701"]
        )
        validate_evidence(result["evidence"])
        self.assertIn("not replaced", result["errors"]["704"])

    def test_preparation_failure_does_not_block_other_assessments(self):
        manifest = cohort_manifest(
            [
                {"id": "701", "split": "train", "source_index": 0},
                {"id": "702", "split": "train", "source_index": 1},
            ]
        )
        manifest.update(development_ids=["701"], human_spotcheck={"reviewer": None})
        manifest["version"] = content_version(
            {key: value for key, value in manifest.items() if key != "version"}
        )
        preparation = prepare_cohort(
            [record(), {"convo_id": 702, "original": []}], manifest["source"], manifest
        )
        tables = json.loads(Path(__file__).with_name("rule_tables.json").read_text())
        result = run_cohort(
            preparation["evidence"],
            manifest,
            [],
            {"references": []},
            tables,
            as_of="2026-11-09",
            preparation_errors=preparation["errors"],
        )
        self.assertEqual(
            result["records"]["701"]["report"]["processing_status"], "completed"
        )
        self.assertIsNone(result["records"]["701"]["error"])
        self.assertIsNone(result["records"]["702"]["report"])
        self.assertIn("nonempty event list", result["records"]["702"]["error"])

    def test_source_manifest_and_training_boundaries_fail_closed(self):
        row = {"id": "701", "split": "train", "source_index": 0}
        manifest = cohort_manifest([row])
        with self.assertRaises(ValueError):
            prepare_cohort(
                [record()], {**manifest["source"], "commit": "changed"}, manifest
            )
        with self.assertRaises(ValueError):
            prepare_cohort(
                [record()], manifest["source"], {**manifest, "version": "changed"}
            )
        for rows in (
            [row, row],
            [{**row, "split": "test"}],
            [{**row, "source_index": -1}],
        ):
            invalid = cohort_manifest(rows)
            with self.assertRaises(ValueError):
                prepare_cohort([record()], invalid["source"], invalid)
        with self.assertRaises(TypeError):
            prepare_cohort(
                {"train": [record()], "test": []}, manifest["source"], manifest
            )


if __name__ == "__main__":
    unittest.main()
