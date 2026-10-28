"""Synthetic safety cases and optional comparisons with locally held pinned data."""

import gzip
import json
import tempfile
import unittest
from contextlib import contextmanager, redirect_stderr, redirect_stdout
from copy import deepcopy
from hashlib import sha256
from io import StringIO
from pathlib import Path
from unittest.mock import patch

from ml.abcd import (
    ABCD_COMMIT,
    ABCD_SHA256,
    MIT_NOTICE,
    conversation_passages,
    main,
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
HUMAN_SEARCH_CASES = (
    {
        "query": "username email order ID validate purchase",
        "target": "references",
        "expected_ids": ["abcd-refund-initiate-purchase-validation"],
        "forbidden_ids": [
            "abcd-refund-initiate-account-lookup",
            "abcd-refund-initiate-refund-details",
        ],
        "reviewed_by": "Nicolas",
        "reviewed_at": "2026-10-28",
        "review_basis": "Human acceptance of AI-assisted relevance review",
    },
    {
        "query": "gift card paper check full address",
        "target": "references",
        "expected_ids": [
            "abcd-refund-initiate-refund-details",
            "abcd-refund-initiate-refund-method",
        ],
        "forbidden_ids": ["abcd-refund-initiate-account-lookup"],
        "reviewed_by": "Nicolas",
        "reviewed_at": "2026-10-28",
        "review_basis": "Human acceptance of AI-assisted relevance review",
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
        "reviewed_by": "Nicolas",
        "reviewed_at": "2026-10-28",
        "review_basis": "Human acceptance of AI-assisted relevance review",
    },
    {
        "query": "orbital telescope calibration",
        "target": "references",
        "expected_ids": [],
        "forbidden_ids": [],
        "reviewed_by": "Nicolas",
        "reviewed_at": "2026-10-28",
        "review_basis": "Human acceptance of AI-assisted relevance review",
    },
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


class PreparationTests(unittest.TestCase):
    def test_source_preparation_and_coverage(self):
        with self.subTest(case="source order, splits and licence"):
            result = prepare_dataset(
                {"train": [source_record()], "dev": [], "test": [source_record(8570)]},
                SOURCE,
            )
            first, second = result["conversations"]
            self.assertEqual(
                (first["id"], first["split"], second["split"]),
                ("7921", "train", "test"),
            )
            self.assertEqual(
                [event["turn_id"] for event in first["events"]], list(range(1, 7))
            )
            actions = [event for event in first["events"] if event["kind"] == "action"]
            self.assertEqual([event["turn_id"] for event in actions], [3, 5])
            self.assertEqual(actions[1]["text"], "Purchase validation in progress ...")
            self.assertEqual(actions[0]["source_pointer"], "/train/0/original/2")
            self.assertEqual(first["coverage"]["transcript"]["status"], "complete")
            self.assertEqual(first["coverage"]["actions"]["status"], "complete")
            self.assertEqual(result["licence"]["notice"], MIT_NOTICE)
            self.assertNotIn("time", first["events"][0])
            validate_evidence(result)

        with self.subTest(case="determinism, input immutability and content version"):
            record = source_record()
            before = deepcopy(record)
            first = prepare_conversation(record, split="train", index=0)
            self.assertEqual(
                first, prepare_conversation(record, split="train", index=0)
            )
            self.assertEqual(record, before)
            changed = deepcopy(record)
            changed["original"][-1][1] = "Thanks Taylor, please contact support."
            self.assertNotEqual(
                first["transcript_version"],
                prepare_conversation(changed, split="train", index=0)[
                    "transcript_version"
                ],
            )

        with self.subTest(case="audit allowlist excludes labels and customer records"):
            encoded = json.dumps(prepared())
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

        with self.subTest(case="partial coverage preserves source positions"):
            conversation = prepare_conversation(
                source_record(), split="train", index=4, turn_ids=[2, 5, 6]
            )
            self.assertEqual(
                [event["turn_id"] for event in conversation["events"]], [2, 5, 6]
            )
            self.assertEqual(
                conversation["coverage"]["transcript"]["status"], "partial"
            )
            self.assertEqual(conversation["coverage"]["actions"]["status"], "partial")
            self.assertEqual(
                conversation["events"][1]["source_pointer"], "/train/4/original/4"
            )

        with self.subTest(case="missing actions do not imply failure"):
            record = source_record()
            record["original"] = [
                event for event in record["original"] if event[0] != "action"
            ]
            record.pop("delexed")
            conversation = prepare_conversation(record, split="train", index=0)
            self.assertEqual(conversation["coverage"]["actions"]["status"], "unknown")
            self.assertIn(
                "absence is not failure", conversation["coverage"]["actions"]["reason"]
            )

    def test_masking_preserves_non_sensitive_facts(self):
        with self.subTest(case="names, identifiers and action text"):
            events = prepared()["conversations"][0]["events"]
            self.assertEqual(
                [event["text"] for event in events],
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
                "structured contact, address, date and PIN",
                [
                    (
                        "Taylor Parker: 12 Test St Ottawa, ON A1A1A1; (555) 123-4567; "
                        "2020-01-28; PIN is 2468."
                    )
                ],
                source_record()["scenario"],
                [
                    (
                        "[PERSON_1]: [ADDRESS_1]; [PHONE_1]; [PURCHASE_DATE_1]; "
                        "PIN is [SECRET_1]."
                    )
                ],
            ),
            (
                "consistent fallback tokens",
                [
                    "Email new@example.test or phone +1 555-222-3333. Password is s3cret.",
                    "new@example.test, +1 555-222-3333, PIN: 9999, ID ABC98765; refund $79.",
                ],
                {},
                [
                    "Email [EMAIL_1] or phone [PHONE_1]. Password is [SECRET_1].",
                    "[EMAIL_1], [PHONE_1], PIN: [SECRET_2], ID [IDENTIFIER_1]; refund $79.",
                ],
            ),
            (
                "email containing a known name",
                ["Taylor@new.example.test"],
                {"personal": {"customer_name": "Taylor Parker"}},
                ["[EMAIL_1]"],
            ),
            (
                "currency does not exempt identifiers",
                ["Refund $100000; ID 123456; ID ABC123456."],
                {},
                ["Refund $100000; ID [IDENTIFIER_1]; ID [IDENTIFIER_2]."],
            ),
            (
                "known account preceded by currency",
                ["Account: $100000."],
                {"personal": {"account_id": "100000"}},
                ["Account: $[ACCOUNT_ID_1]."],
            ),
            (
                "labelled secret preceded by currency",
                ["PIN: $123456."],
                {},
                ["PIN: [SECRET_1]."],
            ),
        )
        for name, texts, scenario, expected in cases:
            with self.subTest(case=name):
                self.assertEqual(mask_texts(texts, scenario), expected)

        for prefix in ("", "+1 "):
            numbers = [
                prefix + number
                for number in (
                    "(555) 123-4567",
                    "(555)123-4567",
                    "555-123-4567",
                    "555.123.4567",
                    "555 123 4567",
                    "5551234567",
                )
            ]
            for scenario in ({}, {"personal": {"phone": numbers[0]}}):
                with self.subTest(
                    case="phone formats", prefix=prefix, known=bool(scenario)
                ):
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
            with self.subTest(case="refund amount", amount=amount):
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
                with self.subTest(case="known secret", field=field, opening=opening):
                    self.assertEqual(
                        mask_texts(
                            [f"{label}: {opening}{value}{closing}.", value],
                            {"personal": {field: value}},
                        ),
                        [f"{label}: {opening}[SECRET_1]{closing}.", "[SECRET_1]"],
                    )

    def test_invalid_sources_and_prepared_evidence_fail_closed(self):
        bad_records = []
        for replacement in (
            ["unknown", "PRIVATE"],
            ["agent", ""],
            ["agent", 42],
            ["agent"],
        ):
            record = source_record()
            record["original"][1] = replacement
            bad_records.append(record)
        record = source_record()
        record["delexed"][1]["turn_count"] = 1
        bad_records.append(record)
        record = source_record()
        record["delexed"].pop()
        bad_records.append(record)
        for index, record in enumerate(bad_records):
            with self.subTest(case="invalid record", index=index):
                with self.assertRaises(ValueError) as error:
                    prepare_conversation(record, split="train", index=5)
                self.assertIn("/train/5", str(error.exception))
                self.assertNotIn("PRIVATE", str(error.exception))
                self.assertNotIn("Taylor", str(error.exception))

        for name, dataset in (
            ("missing ID", {"train": [], "dev": [], "test": []}),
            (
                "duplicate ID",
                {"train": [source_record()], "dev": [source_record()], "test": []},
            ),
            ("missing split", {"train": [source_record()]}),
        ):
            with self.subTest(case=name), self.assertRaises(ValueError):
                prepare_dataset(dataset, SOURCE, ("7921",))
        for split in (None, [], {}, True):
            with (
                self.subTest(case="invalid split", split=split),
                self.assertRaises(ValueError),
            ):
                prepare_conversation(source_record(), split=split, index=0)

        for version in ("1", "2"):
            evidence = prepared()
            evidence["masking_version"] = version
            with (
                self.subTest(case="legacy masking version", version=version),
                self.assertRaisesRegex(ValueError, "masking version"),
            ):
                validate_evidence(evidence)

        for name, change in (
            ("top-level labels", lambda data: data.update(targets=["LEAK"])),
            (
                "conversation labels",
                lambda data: data["conversations"][0].update(flow="LEAK"),
            ),
            (
                "event labels",
                lambda data: data["conversations"][0]["events"][0].update(
                    targets=["LEAK"]
                ),
            ),
            (
                "changed text",
                lambda data: data["conversations"][0]["events"][0].update(
                    text="Changed"
                ),
            ),
            (
                "source pointer",
                lambda data: data["conversations"][0]["events"][0].update(
                    source_pointer="/test/0/original/0"
                ),
            ),
            ("invalid split", lambda data: data["conversations"][0].update(split=[])),
            ("source checksum", lambda data: data["source"].update(sha256="0" * 64)),
            ("incomplete licence", lambda data: data.update(licence={"name": "MIT"})),
        ):
            data = prepared()
            change(data)
            with (
                self.subTest(case="tampered evidence", change=name),
                self.assertRaises(ValueError),
            ):
                validate_evidence(data)


class ReferenceTests(unittest.TestCase):
    def assert_ineligible(self, reference):
        self.assertTrue(reference_issues(reference, **ASSESSMENT))
        self.assertEqual(eligible_references([reference], **ASSESSMENT), [])

    def test_reference_approval_version_safety_and_currentness(self):
        references = catalog()
        for reference in references:
            with self.subTest(
                case="catalog approval binding", reference=reference["id"]
            ):
                self.assertEqual(reference["version"], reference_version(reference))
                if reference["status"] == "approved":
                    self.assertTrue(reference["approved_by"])
                    self.assertEqual(
                        reference["approved_version"], reference["version"]
                    )
                    self.assertTrue(reference["interpretation_limits"])
                    self.assertFalse(reference["safety_flags"])
                else:
                    self.assertEqual(reference["status"], "unapproved")
                    self.assertTrue(reference["safety_flags"])
        self.assertEqual(len(references), 7)
        self.assertEqual(eligible_references(references, **ASSESSMENT), [])

        with self.subTest(case="explicit approval"):
            valid = approved_reference()
            self.assertEqual(reference_issues(valid, **ASSESSMENT), [])
            self.assertEqual(eligible_references([valid], **ASSESSMENT), [valid])
            self.assertEqual(valid["version"], reference_version(valid))
            self.assertEqual(
                reference_passages([valid])[0]["interpretation_limits"],
                valid["interpretation_limits"],
            )

        with self.subTest(case="interpretation limits are approval-bound content"):
            reference = approved_reference()
            old_version = reference["version"]
            reference["interpretation_limits"].append("Changed interpretation.")
            self.assertNotEqual(old_version, reference_version(reference))
            reference["version"] = reference_version(reference)
            self.assert_ineligible(reference)

        with self.subTest(case="interpretation limits must be a text list"):
            reference = approved_reference()
            reference["interpretation_limits"] = "invalid"
            reference["version"] = reference_version(reference)
            reference["approved_version"] = reference["version"]
            self.assert_ineligible(reference)

        for field, value in (
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
        ):
            reference = approved_reference()
            reference[field] = value
            with self.subTest(case="approval requirement", field=field, value=value):
                self.assert_ineligible(reference)

        for date, scope, allowed in (
            ("2026-10-25", "refund-status", False),
            ("2026-11-01", "refund-initiation", True),
            ("2026-11-02", "refund-initiation", False),
        ):
            with self.subTest(case="applicability", date=date, scope=scope):
                self.assertEqual(
                    reference_issues(approved_reference(), as_of=date, scope=scope)
                    == [],
                    allowed,
                )

        unsafe = [approved_reference(ref) for ref in references if ref["safety_flags"]]
        self.assertEqual(len(unsafe), 2)
        for reference in unsafe:
            with self.subTest(case="unsafe guidance", reference=reference["id"]):
                self.assert_ineligible(reference)
        self.assertEqual(eligible_references(unsafe, **ASSESSMENT), [])

        for assessment_date, allowed in (
            ("2026-10-29", True),
            ("2027-10-28", True),
            ("2027-10-29", False),
        ):
            with self.subTest(case="extended deadline", date=assessment_date):
                reference = approved_reference()
                reference["review_due"] = "2027-10-28"
                self.assertEqual(
                    bool(
                        eligible_references(
                            [reference],
                            as_of=assessment_date,
                            scope="refund-initiation",
                        )
                    ),
                    allowed,
                )

        for mode in ("unchanged version", "changed version", "explicitly reapproved"):
            with self.subTest(case="content edit", mode=mode):
                reference = approved_reference()
                version = reference["version"]
                reference["text"] += " Changed wording."
                self.assertNotEqual(version, reference_version(reference))
                if mode != "unchanged version":
                    reference["version"] = reference_version(reference)
                if mode == "explicitly reapproved":
                    reference["approved_version"] = reference["version"]
                    self.assertEqual(reference_issues(reference, **ASSESSMENT), [])
                else:
                    self.assert_ineligible(reference)

        with self.subTest(case="missing approved version"):
            reference = approved_reference()
            reference.pop("approved_version")
            self.assert_ineligible(reference)
        for value in (None, [], {}, {"id": "broken"}):
            with self.subTest(case="malformed reference", value=value):
                self.assert_ineligible(value)
        for date in (None, "20261025", "2026-02-30", "today"):
            with (
                self.subTest(case="invalid date", date=date),
                self.assertRaises(ValueError),
            ):
                eligible_references(references, as_of=date, scope="refund-initiation")
        with self.subTest(case="duplicate reference ID"), self.assertRaises(ValueError):
            reference = approved_reference()
            eligible_references([reference, reference], **ASSESSMENT)


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
        for name, citation in (
            ("message", event),
            ("action", action),
            ("exact substring", {**event, "quote": "[PERSON_1]"}),
            ("reference", reference),
        ):
            with self.subTest(case="valid citation", kind=name):
                self.assertEqual(
                    validate_citations([citation], conversations, references), []
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
    @classmethod
    def setUpClass(cls):
        path = ML_ROOT / "raw" / "abcd_v1.1.json.gz"
        guidelines = ML_ROOT / "raw" / "guidelines.json"
        if not path.exists() or not guidelines.exists():
            raise unittest.SkipTest(
                "Download the pinned ABCD files locally for source comparisons."
            )
        raw = gzip.decompress(path.read_bytes())
        if sha256(raw).hexdigest() != ABCD_SHA256:
            raise ValueError("Local dataset is not the pinned source.")
        dataset = json.loads(raw)
        cls.evidence = prepare_dataset(dataset, SOURCE)
        cls.originals = {
            str(record["convo_id"]): (split, index, record)
            for split, records in dataset.items()
            for index, record in enumerate(records)
            if str(record["convo_id"]) in {"7921", "8570"}
        }
        cls.guideline_bytes = guidelines.read_bytes()
        cls.guidelines = json.loads(cls.guideline_bytes)

    def test_pinned_conversations_and_reference_snapshots(self):
        for conversation in self.evidence["conversations"]:
            with self.subTest(case="conversation", source_id=conversation["id"]):
                split, index, original = self.originals[conversation["id"]]
                self.assertEqual(conversation["split"], split)
                self.assertEqual(split, "train")
                self.assertEqual(conversation["source_pointer"], f"/{split}/{index}")
                self.assertEqual(len(conversation["events"]), len(original["original"]))
                expected_texts = mask_texts(
                    [event[1] for event in original["original"]], original["scenario"]
                )
                for event, source_event, annotated, expected in zip(
                    conversation["events"],
                    original["original"],
                    original["delexed"],
                    expected_texts,
                ):
                    self.assertEqual(event["turn_id"], annotated["turn_count"])
                    self.assertEqual(event["speaker"], source_event[0])
                    self.assertEqual(event["text"], expected)
                    self.assertEqual(
                        event["kind"],
                        "action" if source_event[0] == "action" else "message",
                    )
                encoded = json.dumps(conversation["events"]).casefold()
                for field, value in original["scenario"]["personal"].items():
                    if field != "member_level" and isinstance(value, str):
                        self.assertNotIn(value.casefold(), encoded)
                for part in original["scenario"]["personal"]["customer_name"].split():
                    self.assertNotRegex(encoded, r"\b" + part.casefold() + r"\b")
        validate_evidence(self.evidence)

        for reference in catalog():
            with self.subTest(case="reference", source_id=reference["id"]):
                self.assertEqual(
                    reference["source"]["sha256"],
                    sha256(self.guideline_bytes).hexdigest(),
                )
                section = self.guidelines
                for segment in reference["source"]["pointer"].split("/")[1:]:
                    segment = segment.replace("~1", "/").replace("~0", "~")
                    section = (
                        section[int(segment)]
                        if isinstance(section, list)
                        else section[segment]
                    )
                expected = (
                    "\n".join([section["text"], *section["subtext"]])
                    if isinstance(section, dict)
                    else section
                )
                self.assertEqual(reference["text"], expected)
                self.assertEqual(
                    reference["conditions"],
                    section["subtext"] if isinstance(section, dict) else [],
                )


class CliTests(unittest.TestCase):
    def test_cli_review_respects_requested_scope(self):
        with self.workspace():
            destination = self.root / "scoped-review.json"
            code, _, errors = self.run_review(
                "search",
                destination,
                "--query",
                "refund",
                "--review-only",
                "--scope",
                "refund-update",
            )
            self.assertEqual((code, errors), (0, ""))
            result = json.loads(destination.read_text())
            self.assertEqual(result["scope"], "refund-update")
            self.assertEqual(result["reference_matches"], [])
            self.assertNotIn("audit_input", result)

    @contextmanager
    def workspace(self):
        output_root = ML_ROOT / "output"
        output_root.mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(dir=output_root) as directory:
            self.root = Path(directory)
            self.input = self.write_json("prepared.json", prepared())
            yield

    def write_json(self, filename, data):
        path = self.root / filename
        path.write_text(json.dumps(data), encoding="utf-8")
        return path

    def run_cli(self, *arguments):
        output, errors = StringIO(), StringIO()
        with redirect_stdout(output), redirect_stderr(errors):
            code = main(list(arguments))
        return code, output.getvalue(), errors.getvalue()

    def run_review(self, command, destination, *arguments):
        return self.run_cli(
            command,
            "--evidence",
            str(self.input),
            "--as-of",
            ASSESSMENT["as_of"],
            "--output",
            str(destination),
            *arguments,
        )

    def test_cli_search_review_and_citation_validation(self):
        for review_only in (False, True):
            with self.subTest(case="search", review_only=review_only), self.workspace():
                destination = self.root / "search.json"
                arguments = ["--query", "username order ID"]
                if review_only:
                    arguments.append("--review-only")
                with patch(
                    "socket.socket", side_effect=AssertionError("Network forbidden")
                ):
                    code, _, errors = self.run_review("search", destination, *arguments)
                self.assertEqual((code, errors), (0, ""))
                result = json.loads(destination.read_text())
                if review_only:
                    self.assertEqual(result["purpose"], "reference-review")
                    self.assertNotIn("audit_input", result)
                    self.assertTrue(result["reference_matches"])
                    self.assertEqual(
                        {ref["id"]: ref["status"] for ref in result["review_states"]},
                        {ref["id"]: ref["status"] for ref in catalog()},
                    )
                else:
                    self.assertEqual(result["purpose"], "audit-input")
                    self.assertEqual(result["reference_matches"], [])
                    self.assertEqual(result["audit_input"]["references"], [])
                    self.assertTrue(result["reference_exclusions"])
                    self.assertTrue(result["conversation_matches"])

        for kind in ("conversation", "unapproved reference"):
            with self.subTest(case="validate", kind=kind), self.workspace():
                citation = (
                    conversation_passages(prepared()["conversations"])[0]["citation"]
                    if kind == "conversation"
                    else reference_passages(catalog())[0]["citation"]
                )
                citations = self.write_json("citations.json", [citation])
                destination = self.root / "validation.json"
                code, _, _ = self.run_review(
                    "validate", destination, "--citations", str(citations)
                )
                result = json.loads(destination.read_text())
                if kind == "conversation":
                    self.assertEqual(code, 0)
                    self.assertEqual(result, {"valid": True, "errors": []})
                else:
                    self.assertEqual(code, 1)
                    self.assertFalse(result["valid"])

    def test_cli_invalid_inputs_and_output_safeguards(self):
        missing_status = catalog()[0]
        missing_status.pop("status")
        for name, records, review_only in (
            ("malformed records", [None, 12, {}], False),
            ("missing review state", [missing_status], True),
        ):
            with self.subTest(case=name), self.workspace():
                references = self.write_json(
                    "references.json", {"schema_version": 1, "references": records}
                )
                destination = self.root / "search.json"
                arguments = ["--references", str(references), "--query", "refund"]
                if review_only:
                    arguments.append("--review-only")
                code, _, errors = self.run_review("search", destination, *arguments)
                self.assertEqual(code, 1)
                self.assertIn("invalid record", errors)
                self.assertFalse(destination.exists())

        for name, content in (
            ("corrupt.gz", bytes.fromhex("1f8b0800000000000000ff")),
            ("missing.json", None),
            ("invalid.json", b"{not JSON with PRIVATE_VALUE"),
            ("checksum.json", b"{}"),
        ):
            with self.subTest(case=name), self.workspace():
                source = self.root / name
                if content is not None:
                    source.write_bytes(content)
                destination = self.root / "output.json"
                code, _, errors = self.run_cli(
                    "prepare", "--source", str(source), "--output", str(destination)
                )
                self.assertEqual(code, 1)
                self.assertIn("error", json.loads(errors))
                self.assertNotIn("PRIVATE_VALUE", errors)
                self.assertNotIn("Traceback", errors)
                self.assertFalse(destination.exists())

        with self.subTest(case="output cannot replace input"), self.workspace():
            before = self.input.read_bytes()
            code, _, errors = self.run_review("search", self.input, "--query", "refund")
            self.assertEqual(code, 1)
            self.assertIn("overwrite", errors)
            self.assertEqual(before, self.input.read_bytes())

        with self.subTest(case="outputs must remain local"), self.workspace():
            code, _, errors = self.run_cli(
                "prepare",
                "--source",
                str(self.input),
                "--output",
                "/tmp/not-ignored-evidence.json",
            )
            self.assertEqual(code, 1)
            self.assertIn("ml/output", errors)


if __name__ == "__main__":
    unittest.main()
