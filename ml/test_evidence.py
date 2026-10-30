"""Synthetic safety cases and optional comparisons with locally held pinned data."""

import gzip
import json
import unittest
from copy import deepcopy
from hashlib import sha256
from pathlib import Path

from ml.abcd import (
    ABCD_COMMIT,
    ABCD_SHA256,
    MIT_NOTICE,
    conversation_passages,
    mask_texts,
    prepare_conversation,
    prepare_dataset,
    validate_evidence,
)
from ml.citations import validate_citations
from ml.references import (
    eligible_references,
    reference_issues,
    reference_passages,
    reference_version,
    search_passages,
)

ML_ROOT = Path(__file__).resolve().parent
ASSESSMENT = {"as_of": "2026-10-25", "scope": "refund-initiation"}
SOURCE = {
    "dataset": "ABCD",
    "commit": ABCD_COMMIT,
    "path": "data/abcd_v1.1.json",
    "sha256": ABCD_SHA256,
}
HUMAN_REVIEW = {
    "reviewed_by": "Nicolas",
    "reviewed_at": "2026-10-28",
    "review_basis": "Human acceptance of AI-assisted relevance review",
}
HUMAN_SEARCH_CASES = tuple(
    {**case, **HUMAN_REVIEW}
    for case in (
        {
            "query": "username email order ID validate purchase",
            "target": "references",
            "expected_ids": ["abcd-refund-initiate-purchase-validation"],
            "forbidden_ids": [
                "abcd-refund-initiate-account-lookup",
                "abcd-refund-initiate-refund-details",
            ],
        },
        {
            "query": "gift card paper check full address",
            "target": "references",
            "expected_ids": [
                "abcd-refund-initiate-refund-details",
                "abcd-refund-initiate-refund-method",
            ],
            "forbidden_ids": ["abcd-refund-initiate-account-lookup"],
        },
        {
            "query": "existing refund add another item",
            "target": "references",
            "expected_ids": [],
            "forbidden_ids": [
                "abcd-refund-initiate-refund-method",
                "abcd-refund-initiate-purchase-validation",
                "abcd-refund-initiate-refund-amount",
            ],
        },
        {
            "query": "orbital telescope calibration",
            "target": "references",
            "expected_ids": [],
            "forbidden_ids": [],
        },
    )
)


def source_record(identifier=7921):
    original = [
        ["agent", "Hello Taylor. Please give your username and order ID."],
        ["customer", "Taylor Parker, tparker321, tparker321@example.test, ORD1234567."],
        ["action", "Account has been pulled up for Taylor Parker."],
        ["customer", "Please use account AC98765432 for my $79 refund."],
        ["action", "Purchase validation in progress ..."],
        ["agent", "Thanks Taylor, your refund is in progress."],
    ]
    return {
        "convo_id": identifier,
        "scenario": {
            "personal": {
                "customer_name": "taylor parker",
                "username": "tparker321",
                "email": "tparker321@example.test",
                "account_id": "AC98765432",
                "phone": "(555) 123-4567",
                "pin_number": "2468",
            },
            "order": {
                "order_id": "ORD1234567",
                "full_address": "12 Test St  Ottawa, ON A1A1A1",
                "street_address": "12 Test St",
                "city": "Ottawa",
                "state": "ON",
                "zip_code": "A1A1A1",
                "purchase_date": "2020-01-28",
            },
            "flow": "FLOW_LABEL_CANARY",
            "subflow": "SUBFLOW_LABEL_CANARY",
        },
        "original": original,
        "delexed": [
            {
                "speaker": speaker,
                "text": text.lower(),
                "turn_count": turn,
                "targets": ["TARGET_LABEL_CANARY"],
                "candidates": ["CANDIDATE_LABEL_CANARY"],
            }
            for turn, (speaker, text) in enumerate(original, 1)
        ],
        "actions_taken": ["DERIVED_ACTION_CANARY"],
    }


def prepared():
    return prepare_dataset(
        {"train": [source_record()], "dev": [], "test": []}, SOURCE, ("7921",)
    )


def catalog():
    return json.loads((ML_ROOT / "references.json").read_text(encoding="utf-8"))[
        "references"
    ]


def approved_reference(reference=None):
    if reference is None:
        reference = next(ref for ref in catalog() if not ref["safety_flags"])
    reference = deepcopy(reference)
    reference.update(
        status="approved",
        approved_by="Test reviewer",
        approved_version=reference["version"],
        approved_at="2026-10-01",
        verified_at="2026-10-01",
        review_due="2026-11-01",
    )
    return reference


def changed(value, path, replacement):
    result = deepcopy(value)
    target = result
    for key in path[:-1]:
        target = target[key]
    target[path[-1]] = replacement
    return result


class PreparationTests(unittest.TestCase):
    def test_source_preparation_and_coverage(self):
        result = prepare_dataset(
            {"train": [source_record()], "dev": [], "test": [source_record(8570)]},
            SOURCE,
        )
        first, second = result["conversations"]
        self.assertEqual(
            (first["id"], first["split"], second["split"]), ("7921", "train", "test")
        )
        events = first["events"]
        self.assertEqual([e["turn_id"] for e in events], list(range(1, 7)))
        actions = [e for e in events if e["kind"] == "action"]
        self.assertEqual([e["turn_id"] for e in actions], [3, 5])
        self.assertEqual(actions[1]["text"], "Purchase validation in progress ...")
        self.assertEqual(actions[0]["source_pointer"], "/train/0/original/2")
        self.assertEqual(
            [c["status"] for c in first["coverage"].values()], ["complete"] * 2
        )
        self.assertEqual(result["licence"]["notice"], MIT_NOTICE)
        self.assertNotIn("time", events[0])
        validate_evidence(result)

        record = source_record()
        before = deepcopy(record)
        self.assertEqual(first, prepare_conversation(record, split="train", index=0))
        self.assertEqual(record, before)
        record["original"][-1][1] = "Thanks Taylor, please contact support."
        updated = prepare_conversation(record, split="train", index=0)
        self.assertNotEqual(first["transcript_version"], updated["transcript_version"])
        encoded = json.dumps(result)
        for label in (
            "FLOW_LABEL_CANARY",
            "SUBFLOW_LABEL_CANARY",
            "TARGET_LABEL_CANARY",
            "CANDIDATE_LABEL_CANARY",
            "DERIVED_ACTION_CANARY",
        ):
            self.assertNotIn(label, encoded)
        for field in (
            "scenario",
            "personal",
            "order",
            "targets",
            "candidates",
            "flow",
            "subflow",
        ):
            self.assertNotIn(f'"{field}":', encoded)

        partial = prepare_conversation(
            source_record(), split="train", index=4, turn_ids=[2, 5, 6]
        )
        self.assertEqual([e["turn_id"] for e in partial["events"]], [2, 5, 6])
        self.assertEqual(
            [c["status"] for c in partial["coverage"].values()], ["partial"] * 2
        )
        self.assertEqual(partial["events"][1]["source_pointer"], "/train/4/original/4")
        record = source_record()
        record["original"] = [e for e in record["original"] if e[0] != "action"]
        record.pop("delexed")
        coverage = prepare_conversation(record, split="train", index=0)["coverage"][
            "actions"
        ]
        self.assertEqual(coverage["status"], "unknown")
        self.assertIn("absence is not failure", coverage["reason"])

    def test_masking_preserves_non_sensitive_facts(self):
        self.assertEqual(
            [e["text"] for e in prepared()["conversations"][0]["events"]],
            [
                "Hello [PERSON_1]. Please give your username and order ID.",
                "[PERSON_1], [USERNAME_1], [EMAIL_1], [ORDER_ID_1].",
                "Account has been pulled up for [PERSON_1].",
                "Please use account [ACCOUNT_ID_1] for my $79 refund.",
                "Purchase validation in progress ...",
                "Thanks [PERSON_1], your refund is in progress.",
            ],
        )
        cases = (
            (
                [
                    "Taylor Parker: 12 Test St Ottawa, ON A1A1A1; (555) 123-4567; 2020-01-28; PIN is 2468."
                ],
                source_record()["scenario"],
                [
                    "[PERSON_1]: [ADDRESS_1]; [PHONE_1]; [PURCHASE_DATE_1]; PIN is [SECRET_1]."
                ],
            ),
            (
                [
                    "Email new@example.test or phone +1 555-222-3333. Password is s3cret.",
                    'new@example.test, +1 555-222-3333, PIN: "9999", ID ABC98765; refund $79.',
                ],
                {},
                [
                    "Email [EMAIL_1] or phone [PHONE_1]. Password is [SECRET_1]",
                    '[EMAIL_1], [PHONE_1], PIN: "[SECRET_2]", ID [IDENTIFIER_1]; refund $79.',
                ],
            ),
            (
                ["Taylor@new.example.test"],
                {"personal": {"customer_name": "Taylor Parker"}},
                ["[EMAIL_1]"],
            ),
            (
                ["Refund $100000; ID 123456; ID ABC123456."],
                {},
                ["Refund $100000; ID [IDENTIFIER_1]; ID [IDENTIFIER_2]."],
            ),
            (
                ["Account: $100000."],
                {"personal": {"account_id": "100000"}},
                ["Account: $[ACCOUNT_ID_1]."],
            ),
            (["PIN: $123456."], {}, ["PIN: [SECRET_1]"]),
        )
        for texts, scenario, expected in cases:
            with self.subTest(texts=texts):
                self.assertEqual(mask_texts(texts, scenario), expected)
        formats = (
            "(555) 123-4567",
            "(555)123-4567",
            "555-123-4567",
            "555.123.4567",
            "555 123 4567",
            "5551234567",
        )
        for prefix in ("", "+1 "):
            numbers = [prefix + number for number in formats]
            for scenario in ({}, {"personal": {"phone": numbers[0]}}):
                with self.subTest(prefix=prefix, known=bool(scenario)):
                    self.assertEqual(
                        mask_texts(numbers, scenario), ["[PHONE_1]"] * len(numbers)
                    )
        for amount in (
            "$79",
            "$100000",
            "$1000000000",
            "$1,000,000.00",
            "$100000.123456",
            "$100000.1234",
            "$ 100000",
            "$-100000.00",
            "€100000",
            "£100000",
            "¥100000",
        ):
            text = f"The refund amount is {amount}."
            with self.subTest(amount=amount):
                self.assertEqual(mask_texts([text], {}), [text])
        for field, label, value in (
            ("security_answer", "Security answer", "maple primary school"),
            ("password", "Password", "some.pass!word?"),
        ):
            for opening, closing in (
                ("", ""),
                ("'", "'"),
                ('"', '"'),
                ("‘", "’"),
                ("“", "”"),
            ):
                with self.subTest(field=field, opening=opening):
                    texts = [f"{label}: {opening}{value}{closing}.", value]
                    expected = [f"{label}: {opening}[SECRET_1]{closing}.", "[SECRET_1]"]
                    self.assertEqual(
                        mask_texts(texts, {"personal": {field: value}}), expected
                    )

    def test_unknown_labelled_secrets_are_redacted_in_full_across_turns(self):
        for opening, closing in (("'", "'"), ('"', '"'), ("‘", "’"), ("“", "”")):
            for label in ("Password is", "Security answer:", "PIN number ="):
                for value in ("alpha.beta", "blue sky", "some.pass!word?", "a;b,c"):
                    with self.subTest(opening=opening, label=label, value=value):
                        texts = [
                            f"Earlier action recorded {value}.",
                            f"{label} {opening}{value}{closing}.",
                            f"The agent repeated {value}.",
                        ]
                        self.assertEqual(
                            mask_texts(texts, {}),
                            [
                                "Earlier action recorded [SECRET_1].",
                                f"{label} {opening}[SECRET_1]{closing}.",
                                "The agent repeated [SECRET_1].",
                            ],
                        )
        for value in ("hunter", "alpha.beta", "blue sky", "some.pass!word?"):
            with self.subTest(unquoted=value):
                texts = [value, f"Security answer: {value}.", value]
                self.assertEqual(
                    mask_texts(texts, {}),
                    ["[SECRET_1]", "Security answer: [SECRET_1]", "[SECRET_1]"],
                )

    def test_labelled_secret_boundaries_preserve_separate_facts_or_fail_closed(self):
        self.assertEqual(
            mask_texts(
                [
                    'Password is "alpha.beta"; refund $79.',
                    'PIN: "4321", ID ABC98765; refund $100000.',
                    "Action copied alpha.beta and 4321.",
                ],
                {},
            ),
            [
                'Password is "[SECRET_1]"; refund $79.',
                'PIN: "[SECRET_2]", ID [IDENTIFIER_1]; refund $100000.',
                "Action copied [SECRET_1] and [SECRET_2].",
            ],
        )
        for text in (
            'Password is "alpha.beta.',
            "Security answer: ‘blue sky.",
            'Password is "".',
            'Password: "alpha"beta',
            'Password: "alpha"#suffix',
            'Password: "alpha".beta',
            "PIN:",
            "Password is alpha.beta. Please refund $79.",
        ):
            with self.subTest(text=text), self.assertRaises(ValueError) as error:
                mask_texts([text], {})
            self.assertNotIn("alpha", str(error.exception))
            self.assertNotIn("blue", str(error.exception))
        self.assertEqual(
            mask_texts(
                ['Password: "alpha"; password: "alpha.beta".', "alpha.beta"], {}
            ),
            ['Password: "[SECRET_1]"; password: "[SECRET_2]".', "[SECRET_2]"],
        )

    def test_overlapping_recognisers_redact_the_complete_sensitive_span(self):
        for value in (
            "alpha@example.test#suffix",
            "ABC123456#suffix",
            "+1 555-222-3333.ext",
            "$123456.78#suffix",
        ):
            with self.subTest(value=value):
                self.assertEqual(
                    mask_texts([f'Password: "{value}".', value], {}),
                    ['Password: "[SECRET_1]".', "[SECRET_1]"],
                )
        self.assertEqual(
            mask_texts(
                ["alpha@example.test", "Taylor@new.example.test"],
                {"personal": {"password": "alpha", "customer_name": "Taylor Parker"}},
            ),
            ["[EMAIL_1]", "[EMAIL_2]"],
        )
        self.assertEqual(
            mask_texts(
                ["alpha.beta.gamma"],
                {
                    "personal": {
                        "password": "alpha.beta",
                        "security_answer": "beta.gamma",
                    }
                },
            ),
            ["[IDENTIFIER_1]"],
        )

    def test_secret_matching_retains_literal_unicode_and_quoted_whitespace(self):
        for value, folded in (("Straße", "STRASSE"), ("ﬃ", "FFI")):
            with self.subTest(value=value):
                self.assertEqual(
                    mask_texts([f'Password: "{value}"', value, folded], {}),
                    ['Password: "[SECRET_1]"', "[SECRET_1]", "[SECRET_1]"],
                )
                self.assertEqual(
                    mask_texts([value, f"Password: {value}.", folded], {}),
                    ["[SECRET_1]", "Password: [SECRET_1]", "[SECRET_1]"],
                )
        self.assertEqual(
            mask_texts(
                [
                    'Password: "  alpha.beta  ".',
                    "  alpha.beta  ",
                    "Read  alpha.beta  now.",
                ],
                {},
            ),
            ['Password: "[SECRET_1]".', "[SECRET_1]", "Read[SECRET_1]now."],
        )
        self.assertEqual(
            mask_texts(
                ["Straße@new.example.test"], {"personal": {"password": "Straße"}}
            ),
            ["[EMAIL_1]"],
        )

    def test_unquoted_separators_require_an_unambiguous_known_value(self):
        for value in ("alpha,beta", "alpha;beta", "alpha\nbeta"):
            with self.subTest(value=value), self.assertRaises(ValueError) as error:
                mask_texts(["Password: " + value], {})
            self.assertNotIn("alpha", str(error.exception))
            self.assertNotIn("beta", str(error.exception))
            self.assertEqual(
                mask_texts([f'Password: "{value}"; refund $79.', value], {}),
                ['Password: "[SECRET_1]"; refund $79.', "[SECRET_1]"],
            )
            self.assertEqual(
                mask_texts(["Password: " + value], {"personal": {"password": value}}),
                ["Password: [SECRET_1]"],
            )
        for text in (
            "PIN: 9999, ID ABC98765; refund $79.",
            "PIN: 4321, ID ABC98765; refund $100000.",
        ):
            with self.subTest(text=text), self.assertRaises(ValueError):
                mask_texts([text], {})
        with self.assertRaises(ValueError):
            mask_texts(
                ["Password: hunter; refund $79."],
                {"personal": {"password": "hunter"}},
            )

    def test_unquoted_multiple_secret_labels_fail_closed(self):
        for value in (
            "alpha PIN: beta",
            "alpha and security answer: beta",
            "alpha password is beta",
        ):
            with self.subTest(value=value), self.assertRaises(ValueError) as error:
                mask_texts(["Earlier alpha then beta", "Password: " + value], {})
            self.assertNotIn("alpha", str(error.exception))
            self.assertNotIn("beta", str(error.exception))
            self.assertEqual(
                mask_texts(
                    [value, "Password: " + value], {"personal": {"password": value}}
                ),
                ["[SECRET_1]", "Password: [SECRET_1]"],
            )

    def test_discovered_secrets_are_masked_in_preserved_message_and_action_events(self):
        record = source_record()
        record["original"] = [
            ["action", "Copied alpha.beta and blue sky."],
            ["customer", 'Password: "alpha.beta"; security answer: "blue sky".'],
            ["action", "Stored alpha.beta and blue sky."],
        ]
        record.pop("delexed")
        conversation = prepare_conversation(record, split="dev", index=2)
        self.assertEqual(
            [event["text"] for event in conversation["events"]],
            [
                "Copied [SECRET_2] and [SECRET_3].",
                'Password: "[SECRET_2]"; security answer: "[SECRET_3]".',
                "Stored [SECRET_2] and [SECRET_3].",
            ],
        )
        self.assertEqual(
            [event["kind"] for event in conversation["events"]],
            ["action", "message", "action"],
        )
        self.assertEqual(
            [event["source_pointer"] for event in conversation["events"]],
            ["/dev/2/original/0", "/dev/2/original/1", "/dev/2/original/2"],
        )

    def test_invalid_sources_and_prepared_evidence_fail_closed(self):
        bad_changes = [
            (("original", 1), event)
            for event in (
                ["unknown", "PRIVATE"],
                ["agent", ""],
                ["agent", 42],
                ["agent"],
            )
        ] + [
            (("delexed", 1, "turn_count"), 1),
            (("delexed",), source_record()["delexed"][:-1]),
        ]
        for path, value in bad_changes:
            with self.subTest(path=path, value=value):
                with self.assertRaises(ValueError) as error:
                    prepare_conversation(
                        changed(source_record(), path, value), split="train", index=5
                    )
                self.assertIn("/train/5", str(error.exception))
                self.assertNotIn("PRIVATE", str(error.exception))
                self.assertNotIn("Taylor", str(error.exception))
        for dataset in (
            {"train": [], "dev": [], "test": []},
            {"train": [source_record()], "dev": [source_record()], "test": []},
            {"train": [source_record()]},
        ):
            with self.subTest(dataset=dataset.keys()), self.assertRaises(ValueError):
                prepare_dataset(dataset, SOURCE, ("7921",))
        for split in (None, [], {}, True):
            with self.subTest(split=split), self.assertRaises(ValueError):
                prepare_conversation(source_record(), split=split, index=0)
        for version in ("1", "2", "3"):
            with (
                self.subTest(version=version),
                self.assertRaisesRegex(ValueError, "masking version"),
            ):
                validate_evidence(changed(prepared(), ("masking_version",), version))
        conversation = ("conversations", 0)
        event = (*conversation, "events", 0)
        for path, value in (
            (("targets",), ["LEAK"]),
            ((*conversation, "flow"), "LEAK"),
            ((*event, "targets"), ["LEAK"]),
            ((*event, "text"), "Changed"),
            ((*event, "source_pointer"), "/test/0/original/0"),
            ((*conversation, "split"), []),
            (("source", "sha256"), "0" * 64),
            (("licence",), {"name": "MIT"}),
        ):
            with self.subTest(path=path), self.assertRaises(ValueError):
                validate_evidence(changed(prepared(), path, value))


class ReferenceTests(unittest.TestCase):
    def assert_ineligible(self, reference):
        self.assertTrue(reference_issues(reference, **ASSESSMENT))
        self.assertEqual(eligible_references([reference], **ASSESSMENT), [])

    def test_reference_approval_version_safety_and_currentness(self):
        references = catalog()
        self.assertEqual(len(references), 7)
        for ref in references:
            with self.subTest(reference=ref["id"]):
                self.assertEqual(ref["version"], reference_version(ref))
                if ref["status"] == "approved":
                    self.assertTrue(ref["approved_by"])
                    self.assertEqual(ref["approved_version"], ref["version"])
                    self.assertTrue(ref["interpretation_limits"])
                    self.assertFalse(ref["safety_flags"])
                else:
                    self.assertEqual(ref["status"], "unapproved")
                    self.assertTrue(ref["safety_flags"])
        self.assertEqual(eligible_references(references, **ASSESSMENT), [])
        valid = approved_reference()
        self.assertEqual(reference_issues(valid, **ASSESSMENT), [])
        self.assertEqual(eligible_references([valid], **ASSESSMENT), [valid])
        self.assertEqual(valid["version"], reference_version(valid))
        self.assertEqual(
            reference_passages([valid])[0]["interpretation_limits"],
            valid["interpretation_limits"],
        )
        for limits in (
            [*valid["interpretation_limits"], "Changed interpretation."],
            "invalid",
        ):
            ref = {**valid, "interpretation_limits": limits}
            self.assertNotEqual(valid["version"], reference_version(ref))
            ref["version"] = reference_version(ref)
            if isinstance(limits, str):
                ref["approved_version"] = ref["version"]
            self.assert_ineligible(ref)
        requirements = (
            ("status", "stale"),
            ("status", "disputed"),
            ("status", "unapproved"),
            ("approved_by", None),
            ("approved_version", None),
            ("approved_version", "outdated-version"),
            ("approved_at", None),
            ("verified_at", None),
            ("verified_at", "2026-10-26"),
            ("review_due", None),
            ("review_due", "2026-10-24"),
        )
        for field, value in requirements:
            with self.subTest(field=field, value=value):
                self.assert_ineligible({**valid, field: value})
        for day, scope, allowed in (
            ("2026-10-25", "refund-status", False),
            ("2026-11-01", "refund-initiation", True),
            ("2026-11-02", "refund-initiation", False),
        ):
            with self.subTest(day=day, scope=scope):
                self.assertEqual(
                    not reference_issues(valid, as_of=day, scope=scope), allowed
                )
        unsafe = [approved_reference(ref) for ref in references if ref["safety_flags"]]
        self.assertEqual(len(unsafe), 2)
        for ref in unsafe:
            self.assert_ineligible(ref)
        self.assertEqual(eligible_references(unsafe, **ASSESSMENT), [])
        for day, allowed in (
            ("2026-10-29", True),
            ("2027-10-28", True),
            ("2027-10-29", False),
        ):
            with self.subTest(deadline=day):
                ref = {**valid, "review_due": "2027-10-28"}
                self.assertEqual(
                    bool(
                        eligible_references([ref], as_of=day, scope="refund-initiation")
                    ),
                    allowed,
                )
        for mode in ("unchanged version", "changed version", "explicitly reapproved"):
            with self.subTest(edit=mode):
                ref = {**valid, "text": valid["text"] + " Changed wording."}
                self.assertNotEqual(valid["version"], reference_version(ref))
                if mode != "unchanged version":
                    ref["version"] = reference_version(ref)
                if mode == "explicitly reapproved":
                    ref["approved_version"] = ref["version"]
                    self.assertEqual(reference_issues(ref, **ASSESSMENT), [])
                else:
                    self.assert_ineligible(ref)
        missing_version = dict(valid)
        missing_version.pop("approved_version")
        for ref in (missing_version, None, [], {}, {"id": "broken"}):
            with self.subTest(malformed=ref):
                self.assert_ineligible(ref)
        for day in (None, "20261025", "2026-02-30", "today"):
            with self.subTest(day=day), self.assertRaises(ValueError):
                eligible_references(references, as_of=day, scope="refund-initiation")
        with self.assertRaises(ValueError):
            eligible_references([valid, valid], **ASSESSMENT)


class SearchTests(unittest.TestCase):
    def test_partial_word_overlap_is_not_enough_for_retrieval(self):
        passages = [
            {"id": "weak", "text": "receipt address"},
            {"id": "half", "text": "receipt address packaging"},
            {"id": "specific", "text": "receipt address packaging return"},
        ]
        self.assertEqual(
            [
                match["id"]
                for match in search_passages(
                    "receipt packaging return eligibility", passages
                )
            ],
            ["specific"],
        )
        self.assertEqual(search_passages("receipt unrelated", passages), [])
        self.assertEqual(len(search_passages("receipt", passages)), 3)

    def test_reference_scope_is_filtered_even_for_review_only_candidates(self):
        references = catalog()
        self.assertEqual(reference_passages(references, scope="refund-update"), [])
        passages = reference_passages(references, scope="refund-initiation")
        self.assertEqual(len(passages), len(references))
        self.assertIn("abcd-refund-initiate-refund-method", [p["id"] for p in passages])
        self.assertTrue(
            validate_citations(
                [
                    p["citation"]
                    for p in passages
                    if p["id"] == "abcd-refund-initiate-refund-method"
                ],
                [],
                eligible_references(
                    references, as_of="2026-10-28", scope="refund-initiation"
                ),
            )
        )
        excluded = approved_reference()
        excluded["exclusions"].append("refund-initiation")
        excluded["version"] = reference_version(excluded)
        self.assertEqual(reference_passages([excluded], scope="refund-initiation"), [])
        for scope in ("", " refund-initiation ", [], 1):
            with self.subTest(scope=scope), self.assertRaises(ValueError):
                reference_passages(references, scope=scope)

    def test_search_ranking_eligibility_and_citation_links(self):
        with self.subTest(case="deterministic top three and no match"):
            passages = [
                {"id": value, "text": "refund purchase", "citation": {}}
                for value in ("d", "c", "b", "a")
            ]
            results = search_passages("REFUND purchase", passages)
            self.assertEqual([result["id"] for result in results], ["a", "b", "c"])
            self.assertEqual(
                search_passages("refund", list(reversed(passages))), results
            )
            for query in ("orbital telescope", "the and", ""):
                with self.subTest(query=query):
                    self.assertEqual(search_passages(query, passages), [])

        with self.subTest(case="out-of-scope guidance excluded before ranking"):
            suitable = approved_reference()
            unsuitable = deepcopy(suitable)
            unsuitable.update(
                id="unrelated-guidance",
                scope=["refund-status"],
                text="refund refund purchase username email order",
            )
            unsuitable["version"] = reference_version(unsuitable)
            unsuitable["approved_version"] = unsuitable["version"]
            eligible = eligible_references([suitable, unsuitable], **ASSESSMENT)
            self.assertEqual([ref["id"] for ref in eligible], [suitable["id"]])
            matches = search_passages("refund purchase", reference_passages(eligible))
            self.assertNotIn(unsuitable["id"], [match["id"] for match in matches])

        with self.subTest(case="search cannot approve or reverify guidance"):
            references = catalog()
            before = deepcopy(references)
            self.assertTrue(
                search_passages("username email order", reference_passages(references))
            )
            self.assertEqual(references, before)
            self.assertEqual(eligible_references(references, **ASSESSMENT), [])

        with self.subTest(case="matches cite real passages without invented scores"):
            conversations = prepared()["conversations"]
            matches = search_passages(
                "purchase validation", conversation_passages(conversations)
            )
            self.assertTrue(matches)
            self.assertEqual(
                validate_citations(
                    [match["citation"] for match in matches], conversations, []
                ),
                [],
            )
            self.assertNotIn("score", matches[0])
            self.assertNotIn("confidence", matches[0])

    def test_human_relevance_top_three(self):
        if any(
            case["expected_ids"] is None
            or case["forbidden_ids"] is None
            or not case["reviewed_by"]
            or not case["reviewed_at"]
            for case in HUMAN_SEARCH_CASES
        ):
            self.skipTest(
                "Four relevance cases await human labels, reviewer and review date."
            )
        for case in HUMAN_SEARCH_CASES:
            with self.subTest(query=case["query"]):
                results = search_passages(case["query"], reference_passages(catalog()))
                ids = [result["id"] for result in results]
                self.assertTrue(set(case["expected_ids"]) <= set(ids))
                self.assertTrue(set(case["forbidden_ids"]).isdisjoint(ids))
                if not case["expected_ids"]:
                    self.assertEqual(ids, [])


class CitationTests(unittest.TestCase):
    def test_citation_fidelity_and_ambiguous_sources(self):
        conversations = prepared()["conversations"]
        references = [approved_reference()]
        event = conversation_passages(conversations)[0]["citation"]
        action = conversation_passages(conversations)[2]["citation"]
        reference = reference_passages(references)[0]["citation"]
        with self.subTest(case="mixed valid citation batch"):
            self.assertEqual(
                validate_citations(
                    [event, action, {**event, "quote": "[PERSON_1]"}, reference],
                    conversations,
                    references,
                ),
                [],
            )
        for citation, field, value in (
            (event, "conversation_id", "999"),
            (event, "transcript_version", "changed"),
            (event, "turn_id", 999),
            (event, "turn_id", True),
            (event, "event_kind", "action"),
            (event, "quote", "Taylor Parker"),
            (event, "quote", " "),
            (reference, "reference_id", "missing"),
            (reference, "reference_version", "changed"),
            (reference, "section_id", "missing"),
            (reference, "quote", "Unsupported policy."),
        ):
            with self.subTest(case="invalid citation", field=field, value=value):
                errors = validate_citations(
                    [{**citation, field: value}], conversations, references
                )
                self.assertTrue(errors)
                self.assertNotIn("Taylor", json.dumps(errors))

        duplicate_turn = deepcopy(conversations[0])
        duplicate_turn["events"].append(duplicate_turn["events"][0])
        for name, citations, sources, guidance in (
            ("duplicate conversation", [event], conversations * 2, []),
            ("duplicate reference", [reference], [], references * 2),
            ("duplicate turn", [event], [duplicate_turn], []),
            ("extra fields", [{**event, "targets": []}], conversations, []),
            ("missing reference", [reference], conversations, []),
            ("invalid citation collection", None, [], []),
            ("invalid citation records", [None, {}, []], [], []),
        ):
            with self.subTest(case=name):
                self.assertTrue(validate_citations(citations, sources, guidance))


class LocalSourceTests(unittest.TestCase):
    def test_pinned_conversations_and_reference_snapshots(self):
        path = ML_ROOT / "raw" / "abcd_v1.1.json.gz"
        guidelines = ML_ROOT / "raw" / "guidelines.json"
        if not path.exists() or not guidelines.exists():
            self.skipTest(
                "Download the pinned ABCD files locally for source comparisons."
            )
        raw = gzip.decompress(path.read_bytes())
        self.assertEqual(sha256(raw).hexdigest(), ABCD_SHA256)
        dataset = json.loads(raw)
        evidence = prepare_dataset(dataset, SOURCE)
        originals = {str(record["convo_id"]): record for record in dataset["train"]}
        expected_versions = {
            "7921": "sha256:b95be525b02a5c125054beb7265129e71b0b7b11bb56118256c87d12cb7d6511",
            "8570": "sha256:fcb8c29bf6cc477285c4dcedfd3e45a53e36e6fd7bebc435f3e15f4e4b974585",
        }
        for conversation in evidence["conversations"]:
            with self.subTest(conversation=conversation["id"]):
                self.assertEqual(
                    conversation["transcript_version"],
                    expected_versions[conversation["id"]],
                )
                original = originals[conversation["id"]]
                self.assertEqual(len(conversation["events"]), len(original["original"]))
                encoded = json.dumps(conversation["events"]).casefold()
                for field, value in original["scenario"]["personal"].items():
                    if field != "member_level" and isinstance(value, str):
                        self.assertNotIn(value.casefold(), encoded)
                for part in original["scenario"]["personal"]["customer_name"].split():
                    self.assertNotRegex(encoded, r"\b" + part.casefold() + r"\b")
        validate_evidence(evidence)

        guideline_bytes = guidelines.read_bytes()
        guideline_data = json.loads(guideline_bytes)
        for reference in catalog():
            with self.subTest(reference=reference["id"]):
                self.assertEqual(
                    reference["source"]["sha256"], sha256(guideline_bytes).hexdigest()
                )
                section = guideline_data
                for segment in reference["source"]["pointer"].split("/")[1:]:
                    segment = segment.replace("~1", "/").replace("~0", "~")
                    section = (
                        section[int(segment)]
                        if isinstance(section, list)
                        else section[segment]
                    )
                if isinstance(section, dict):
                    expected = "\n".join([section["text"], *section["subtext"]])
                    conditions = section["subtext"]
                else:
                    expected, conditions = section, []
                self.assertEqual(reference["text"], expected)
                self.assertEqual(reference["conditions"], conditions)


if __name__ == "__main__":
    unittest.main()
