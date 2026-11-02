"""Pure evaluation of a fixed pilot; human judgements are never inferred."""

import json
import re
from copy import deepcopy
from hashlib import sha256
from math import isfinite

from .abcd import MASKING_VERSION, _validate_source, validate_evidence
from .audit import (
    CATEGORIES,
    RESULTS,
    _result_citations,
    eligible_criteria,
    validate_report_limits,
    validate_results,
)
from .citations import validate_citations
from .references import (
    _day,
    _has_text_fields,
    _text_list,
    eligible_references,
    reference_passages,
    search_passages,
)

SELECTION_VERSION = "memoria-evaluation-v1"
PARTITIONS = {"development": ("train", 20), "held-out": ("test", 19)}
CASE_FIELDS = ("id", "split", "source_pointer", "partition")
KNOWN_IDS = ("7921", "8570")
HUMAN_FIELDS = (
    "transcript_version",
    "versions",
    "report_version",
    "expected_results",
    "unsupported_findings",
    "citation_support",
    "summary_faithfulness",
    "topic_faithfulness",
    "reviewed_by",
    "reviewed_at",
    "second_reviewed_by",
    "second_reviewed_at",
    "reasons",
    "evidence_gaps",
    "disagreements",
    "second_review_agreement",
)
QUALITY_METRICS = (
    "label_agreement",
    "citation_support",
    "summary_faithfulness",
    "topic_faithfulness",
)


def report_content_version(report):
    """Identify reviewed content, preserving order and excluding runtime metrics."""
    if not isinstance(report, dict):
        raise TypeError("Report records must be objects.")
    content = {key: value for key, value in report.items() if key != "metrics"}
    encoded = json.dumps(
        content, sort_keys=True, ensure_ascii=False, allow_nan=False
    ).encode()
    return "sha256:" + sha256(encoded).hexdigest()


def _cohort_version(manifest):
    identity = {
        "source": manifest["source"],
        "masking_version": manifest["masking_version"],
        "selection_version": manifest["selection_version"],
        "cases": [
            {key: case[key] for key in CASE_FIELDS} for case in manifest["cases"]
        ],
    }
    encoded = json.dumps(identity, sort_keys=True, allow_nan=False).encode()
    return "sha256:" + sha256(encoded).hexdigest()


def _eligible_sources(references, rubric, as_of):
    sources = eligible_references(
        references, as_of=as_of, scope="refund-initiation"
    ) + eligible_criteria(rubric["references"], as_of=as_of, scope="refund-initiation")
    if len({ref["id"] for ref in sources}) != len(sources):
        raise ValueError("Eligible guideline and rubric IDs must be unique.")
    return sources


def _processing_error(counters, errors, identifier, code):
    counters["processing_errors"] += 1
    counters["failed_categories"] += 4
    counters["unreviewed_cases"] += 1
    counters["invalid_reports"] += code == "invalid-report"
    errors.append({"conversation_id": identifier, "code": code})


def build_cohort(dataset, source):
    """Select metadata only, after the caller verifies the pinned raw bytes."""
    _validate_source(source)
    if not isinstance(dataset, dict) or set(dataset) != {"train", "dev", "test"}:
        raise ValueError("Preserve the official ABCD splits.")
    candidates, seen = {split: [] for split in dataset}, set()
    for split, records in dataset.items():
        if not isinstance(records, list):
            raise TypeError("Source splits must contain record lists.")
        for index, record in enumerate(records):
            identifier = str(record.get("convo_id")) if isinstance(record, dict) else ""
            if not re.fullmatch(r"[0-9]+", identifier) or identifier in seen:
                raise ValueError("Source IDs must be numeric and globally unique.")
            seen.add(identifier)
            scenario = record.get("scenario", {})
            if not isinstance(scenario, dict):
                raise TypeError("Source selection metadata must be an object.")
            if scenario.get("subflow") == "refund_initiate":
                candidates[split].append(
                    {
                        "id": identifier,
                        "split": split,
                        "source_pointer": f"/{split}/{index}",
                    }
                )
    training = {case["id"]: case for case in candidates["train"]}
    if (
        not set(KNOWN_IDS) <= training.keys()
        or len(training) < 20
        or len(candidates["test"]) != 19
    ):
        raise ValueError("The pinned refund-initiation cohort is unavailable.")
    known = [training.pop(identifier) for identifier in KNOWN_IDS]
    remaining = sorted(
        training.values(),
        key=lambda case: sha256(
            (SELECTION_VERSION + ":" + case["id"]).encode()
        ).hexdigest(),
    )
    cases = []
    for partition, selected in (
        ("development", known + remaining[:18]),
        ("held-out", sorted(candidates["test"], key=lambda case: int(case["id"]))),
    ):
        cases.extend(
            {**case, "partition": partition, "annotation": dict.fromkeys(HUMAN_FIELDS)}
            for case in selected
        )
    manifest = {
        "schema_version": 1,
        "selection_version": SELECTION_VERSION,
        "source": deepcopy(source),
        "masking_version": MASKING_VERSION,
        "cases": cases,
        "freeze": None,
        "release_checks": None,
        "pilot_note": "39 cases: 20 development and 19 held out; the official test split has only 19 refund-initiation cases.",
    }
    manifest["version"] = _cohort_version(manifest)
    return manifest


def validate_cohort(manifest):
    if (
        not isinstance(manifest, dict)
        or manifest.get("schema_version") != 1
        or manifest.get("selection_version") != SELECTION_VERSION
    ):
        raise ValueError("Unsupported cohort manifest.")
    _validate_source(manifest.get("source"))
    if manifest.get("masking_version") != MASKING_VERSION or not isinstance(
        manifest.get("cases"), list
    ):
        raise ValueError("Cohort masking version or cases are invalid.")
    seen, counts = set(), dict.fromkeys(PARTITIONS, 0)
    for case in manifest["cases"]:
        if not isinstance(case, dict) or set(case) != {*CASE_FIELDS, "annotation"}:
            raise ValueError("Cohort case fields are invalid.")
        identifier, partition = case["id"], case["partition"]
        if (
            not isinstance(identifier, str)
            or not re.fullmatch(r"[0-9]+", identifier)
            or identifier in seen
            or partition not in PARTITIONS
        ):
            raise ValueError("Cohort IDs overlap or are invalid.")
        split = PARTITIONS[partition][0]
        if case["split"] != split or not re.fullmatch(
            r"/" + split + r"/[0-9]+", case["source_pointer"]
        ):
            raise ValueError(
                "Official splits and source positions must remain unchanged."
            )
        if not isinstance(case["annotation"], dict) or set(case["annotation"]) != set(
            HUMAN_FIELDS
        ):
            raise ValueError("Every case needs an explicit annotation record.")
        seen.add(identifier)
        counts[partition] += 1
    if counts != {key: value[1] for key, value in PARTITIONS.items()} or not set(
        KNOWN_IDS
    ) <= {c["id"] for c in manifest["cases"] if c["partition"] == "development"}:
        raise ValueError("The pilot requires 20 development and 19 held-out cases.")
    if manifest.get("version") != _cohort_version(manifest):
        raise ValueError("The cohort version does not match its source identities.")


def _has_text(value):
    return isinstance(value, str) and bool(value.strip())


def _reviewed(record, as_of, *, prefix=""):
    return (
        isinstance(record, dict)
        and _has_text(record.get(prefix + "reviewed_by"))
        and (reviewed := _day(record.get(prefix + "reviewed_at"))) is not None
        and (assessment := _day(as_of)) is not None
        and reviewed <= assessment
    )


def _heldout_ready(manifest, as_of):
    freeze, checks = manifest.get("freeze"), manifest.get("release_checks")
    try:
        validate_report_limits(freeze["versions"]["limits"])
    except (KeyError, TypeError, ValueError):
        return False
    return (
        _reviewed(freeze, as_of)
        and freeze.get("cohort_version") == manifest["version"]
        and isinstance(freeze.get("versions"), dict)
        and _reviewed(checks, as_of)
        and isinstance(checks.get("thresholds"), dict)
        and all(
            type(checks["thresholds"].get(name)) in (int, float)
            and 0 <= checks["thresholds"][name] <= 1
            for name in QUALITY_METRICS
        )
    )


def _rate(numerator, denominator):
    return {
        "value": numerator / denominator if denominator else None,
        "numerator": numerator,
        "denominator": denominator,
    }


def _check_report(report, conversation, evidence, sources, references, rubric):
    """The caller has checked report type, dates and citation collection shapes."""
    status = report.get("processing_status")
    if report.get("schema_version") != 1 or status not in {
        "complete",
        "partial",
        "failed",
    }:
        raise ValueError("Report processing status is invalid.")
    unbound = status == "failed" and all(
        report.get(name) is None for name in ("conversation_id", "transcript_version")
    )
    if not unbound:
        expected = {
            "conversation_id": conversation["id"],
            "transcript_version": conversation["transcript_version"],
            "source": evidence["source"],
            "masking_version": evidence["masking_version"],
            "licence": evidence["licence"],
            "scope": "refund-initiation",
        }
        if any(report.get(key) != value for key, value in expected.items()):
            raise ValueError("Report identity, source or context does not match.")
        if not report.get("as_of"):
            raise ValueError("Report assessment date is invalid or after evaluation.")
    versions = report.get("versions")
    if (
        not isinstance(versions, dict)
        or versions.get("report") != "local-feedback-v1"
        or not isinstance(versions.get("rules"), dict)
        or not versions["rules"]
        or not _text_list(list(versions["rules"].values()))
    ):
        raise ValueError("Report implementation versions are missing.")
    validate_report_limits(versions.get("limits"))
    if not unbound:
        for key, records in (
            ("references", references),
            ("rubric", rubric["references"]),
        ):
            expected = [{"id": ref["id"], "version": ref["version"]} for ref in records]
            if versions.get(key) != expected:
                raise ValueError("Report reference/rubric versions do not match.")
    categories, errors = report.get("categories"), report.get("errors")
    if not isinstance(categories, list) or len(categories) != len(CATEGORIES):
        raise ValueError("Reports require the four processing records.")
    if {entry["category"] for entry in categories} != set(CATEGORIES):
        raise ValueError("Reports require the four processing records.")
    if not isinstance(errors, list) or any(
        not _has_text_fields(error, ("code", "message")) for error in errors
    ):
        raise ValueError("Processing errors require explicit codes and explanations.")
    completed = []
    for entry in categories:
        result, error = entry.get("result"), entry.get("error")
        if entry.get("status") == "completed":
            if error is not None or result["category"] != entry["category"]:
                raise ValueError("Completed category state is inconsistent.")
            completed.append(result)
        else:
            valid_error = _has_text(error) or unbound and error is None
            if (
                entry.get("status") not in {"failed", "not-run"}
                or result is not None
                or not valid_error
            ):
                raise ValueError("Technical failure must not become an audit result.")
    if status == "complete":
        valid_status = len(completed) == len(CATEGORIES) and not errors
    else:
        valid_status = bool(errors) and (status != "failed" or not completed)
    if not valid_status:
        raise ValueError("Processing status disagrees with category results/errors.")
    if completed:
        validate_results(
            conversation,
            completed,
            sources,
            as_of=report["as_of"],
            scope="refund-initiation",
            require_all=False,
        )
    metrics = report.get("metrics")
    if not isinstance(metrics, dict):
        raise TypeError("Execution measurements are missing.")
    for name in ("elapsed_ms", "model_call_cost_usd"):
        value = metrics.get(name)
        if type(value) not in (int, float) or not isfinite(value) or value < 0:
            raise ValueError("Execution measurements must be finite and nonnegative.")
    if (
        metrics.get("engine") != "local-rules"
        or metrics["model_call_cost_usd"] != 0
        or any(
            metrics.get(name) is not None for name in ("model", "prompt", "token_usage")
        )
    ):
        raise ValueError("Local-rule reports cannot invent model usage.")
    topic, summary = report.get("topic"), report.get("summary")
    if not isinstance(topic, dict) or not isinstance(summary, dict):
        raise TypeError("Topic and summary records are required.")
    labels, citations = topic.get("labels"), topic.get("citations")
    if (
        not isinstance(labels, list)
        or set(labels) - {"refund", "return", "method", "next-step"}
        or not isinstance(citations, list)
        or labels
        and not citations
    ):
        raise ValueError("Recognised topics require source citations.")
    if any(not _text_list(value.get("limitations")) for value in (topic, summary)):
        raise ValueError("Narrative limitations must be explicit text.")
    claims = summary.get("claims")
    if not isinstance(claims, list):
        raise TypeError("Summary claims must be a list.")
    roles = {
        "request": "customer",
        "request-change": "customer",
        "agent-promise": "agent",
        "agent-claim": "agent",
        "recorded-action": "action",
    }
    events = {event["turn_id"]: event for event in conversation["events"]}
    for claim in claims:
        if not _has_text_fields(claim, ("text",)) or claim.get("kind") not in roles:
            raise ValueError("Every summary claim needs a known kind and evidence.")
        citations = claim.get("citations")
        if not citations:
            raise ValueError("Every summary claim needs a known kind and evidence.")
        quoted = any(
            isinstance(cite, dict) and claim["text"] == cite.get("quote")
            for cite in citations
        )
        correct_role = all(
            isinstance(cite, dict)
            and cite.get("kind") == "conversation"
            and events.get(cite.get("turn_id"), {}).get("speaker")
            == roles[claim["kind"]]
            for cite in citations
        )
        if not quoted or not correct_role:
            raise ValueError(
                "Summary text and role must match cited conversation evidence."
            )
    if unbound and (labels or topic["citations"] or claims):
        raise ValueError("Unbound processing failures cannot claim evidence.")
    return completed


def _review_notes_complete(annotation):
    reasons = annotation["reasons"]
    disagreements = annotation["disagreements"]
    agreement = annotation["second_review_agreement"]
    return (
        isinstance(reasons, dict)
        and set(reasons) == set(CATEGORIES)
        and _text_list(list(reasons.values()))
        and _text_list(annotation["evidence_gaps"])
        and isinstance(disagreements, list)
        and type(agreement) is bool
        and (agreement or bool(disagreements))
        and all(
            isinstance(item, dict)
            and _has_text(item.get("note"))
            and item.get("resolved") is True
            for item in disagreements
        )
    )


def _score_review(
    annotation, report, completed, citations, scores, counters, as_of, report_version
):
    reviewed = (
        _reviewed(annotation, as_of)
        and annotation["transcript_version"] == report["transcript_version"]
        and annotation["versions"] == report["versions"]
        and annotation["report_version"] == report_version
    )
    if not reviewed:
        return False
    if (
        not _reviewed(annotation, as_of, prefix="second_")
        or annotation["second_reviewed_by"] == annotation["reviewed_by"]
    ):
        counters["blind_review_missing"] += 1
    expected = annotation["expected_results"]
    if expected is not None and (
        not isinstance(expected, dict)
        or set(expected) != set(CATEGORIES)
        or any(value not in (*RESULTS, None) for value in expected.values())
    ):
        raise ValueError(
            "Human labels must name each category and preserve uncertainty."
        )
    complete = expected is not None and None not in expected.values()
    for result in completed:
        label = expected[result["category"]] if expected else None
        if label is not None:
            scores["label_agreement"][0] += label == result["result"]
            scores["label_agreement"][1] += 1
            if result["result"] == "cannot-assess":
                scores["appropriate_cannot_assess"][0] += label == "cannot-assess"
                scores["appropriate_cannot_assess"][1] += 1
    findings = sum(len(result["findings"]) for result in completed)
    unsupported = annotation["unsupported_findings"]
    complete = complete and unsupported is not None
    if unsupported is not None:
        if type(unsupported) is not int or not 0 <= unsupported <= findings:
            raise ValueError("Reviewed unsupported-finding count is invalid.")
        counters["unsupported_findings"] += unsupported
        scores["unsupported_fault_rate"][0] += unsupported
        scores["unsupported_fault_rate"][1] += findings
    for name, size in (
        ("citation_support", len(citations)),
        ("summary_faithfulness", len(report["summary"]["claims"])),
    ):
        values = annotation[name]
        if values is not None:
            if (
                not isinstance(values, list)
                or len(values) != size
                or any(
                    value is not None and type(value) is not bool for value in values
                )
            ):
                raise ValueError(
                    "Human semantic judgements must align with the cited items."
                )
            scores[name][0] += sum(value is True for value in values)
            scores[name][1] += sum(value is not None for value in values)
        complete = complete and values is not None and None not in values
    topic_judgement = annotation["topic_faithfulness"]
    if topic_judgement is not None:
        if type(topic_judgement) is not bool:
            raise ValueError("Topic faithfulness must be a human judgement or unset.")
        scores["topic_faithfulness"][0] += topic_judgement
        scores["topic_faithfulness"][1] += 1
    complete = complete and topic_judgement is not None
    return complete and _review_notes_complete(annotation)


def _release(manifest, partition, counters, metrics, as_of):
    status = "pending"
    reason = "Frozen held-out execution, complete human judgements, thresholds and blind review are required."
    if (
        counters["invalid_reports"]
        or counters["invalid_citations"]
        or counters["unsupported_findings"]
    ):
        status, reason = (
            "blocked",
            "Invalid evidence links, invalid reports or reviewed unsupported findings block release.",
        )
    elif (
        partition == "held-out"
        and _heldout_ready(manifest, as_of)
        and not any(
            counters[key]
            for key in ("processing_errors", "unreviewed_cases", "blind_review_missing")
        )
    ):
        thresholds = manifest["release_checks"]["thresholds"]
        if any(metrics[name]["value"] is None for name in QUALITY_METRICS):
            reason = "Required semantic metrics have no reviewed denominator."
        elif any(metrics[name]["value"] < thresholds[name] for name in QUALITY_METRICS):
            status, reason = (
                "blocked",
                "A human-approved release threshold was not met.",
            )
        else:
            status, reason = (
                "ready",
                "The reviewed pilot met its recorded checks; this is not production-safety evidence.",
            )
    return {"status": status, "reason": reason}


def evaluate_reports(
    manifest, reports, *, evidence, references, rubric, as_of, partition="development"
):
    """Score parsed reports without executing a pipeline or reading held-out text."""
    validate_cohort(manifest)
    if (
        partition not in PARTITIONS
        or partition == "held-out"
        and not _heldout_ready(manifest, as_of)
    ):
        raise ValueError(
            "Held-out evaluation requires a frozen cohort/configuration and agreed release checks."
        )
    validate_evidence(evidence)
    cases = {
        case["id"]: case for case in manifest["cases"] if case["partition"] == partition
    }
    conversations = {c["id"]: c for c in evidence["conversations"]}
    if (
        not isinstance(reports, dict)
        or set(reports) - cases.keys()
        or set(conversations) - cases.keys()
    ):
        raise ValueError("Reports/evidence must not leak across evaluation partitions.")
    if (
        evidence["source"] != manifest["source"]
        or evidence["masking_version"] != manifest["masking_version"]
    ):
        raise ValueError("Evidence does not match the cohort source pin.")
    _eligible_sources(references, rubric, as_of)
    counters = dict.fromkeys(
        (
            "processing_errors",
            "invalid_reports",
            "invalid_citations",
            "completed_categories",
            "failed_categories",
            "unreviewed_cases",
            "blind_review_missing",
            "unsupported_findings",
        ),
        0,
    )
    scores = {
        name: [0, 0]
        for name in (
            "label_agreement",
            "appropriate_cannot_assess",
            "citation_validity",
            "unsupported_fault_rate",
            "citation_support",
            "summary_faithfulness",
            "topic_faithfulness",
        )
    }
    timings, costs, errors = [], [], []
    elapsed_total = 0
    for identifier, case in cases.items():
        report, conversation = reports.get(identifier), conversations.get(identifier)
        if report is None or conversation is None:
            _processing_error(
                counters, errors, identifier, "missing-report-or-evidence"
            )
            continue
        if (
            conversation["split"] != case["split"]
            or conversation["source_pointer"] != case["source_pointer"]
        ):
            raise ValueError(
                "Canonical evidence moved from its original source location."
            )
        try:
            if not isinstance(report, dict):
                raise TypeError("Report records must be objects.")
            assessment_day = report.get("as_of") or as_of
            if _day(assessment_day) is None or _day(assessment_day) > _day(as_of):
                raise ValueError("Report date exceeds the review cutoff.")
            sources = _eligible_sources(references, rubric, assessment_day)
            citations = list(
                _result_citations(
                    [report["categories"], report["topic"], report["summary"]]
                )
            )
            citation_errors = validate_citations(citations, [conversation], sources)
            counters["invalid_citations"] += len(citation_errors)
            scores["citation_validity"][0] += len(citations) - len(citation_errors)
            scores["citation_validity"][1] += len(citations)
            completed = _check_report(
                report, conversation, evidence, sources, references, rubric
            )
            if (
                partition == "held-out"
                and report["versions"] != manifest["freeze"]["versions"]
            ):
                raise ValueError(
                    "The held-out report configuration changed after freezing."
                )
            report_version = report_content_version(report)
            next_elapsed_total = sum(timings + [report["metrics"]["elapsed_ms"]])
            if not isfinite(next_elapsed_total):
                raise ValueError("Total elapsed time cannot be represented.")
        except (KeyError, TypeError, ValueError, OverflowError):
            _processing_error(counters, errors, identifier, "invalid-report")
            continue
        counters["completed_categories"] += len(completed)
        counters["failed_categories"] += 4 - len(completed)
        counters["processing_errors"] += report["processing_status"] != "complete"
        elapsed_total = next_elapsed_total
        timings.append(report["metrics"]["elapsed_ms"])
        costs.append(report["metrics"]["model_call_cost_usd"])
        if not _score_review(
            case["annotation"],
            report,
            completed,
            citations,
            scores,
            counters,
            as_of,
            report_version,
        ):
            counters["unreviewed_cases"] += 1
    metrics = {name: _rate(*values) for name, values in scores.items()}
    return {
        "schema_version": 1,
        "cohort_version": manifest["version"],
        "partition": partition,
        "case_count": len(cases),
        "report_count": len(reports),
        "counts": counters,
        "metrics": metrics,
        "execution": {
            "measured_reports": len(timings),
            "elapsed_ms_total": elapsed_total,
            "elapsed_ms_mean": elapsed_total / len(timings) if timings else None,
            "model_call_cost_usd": sum(costs) if costs else None,
        },
        "errors": errors,
        "release": _release(manifest, partition, counters, metrics, as_of),
    }


def evaluate_retrieval(cases, references, *, as_of, scope):
    """Separate top-three relevance cases; retrieval never approves a reference."""
    sources = eligible_references(references, as_of=as_of, scope=scope)
    passages = reference_passages(sources, scope=scope)
    results, correct, reviewed = [], 0, 0
    for case in cases:
        matches = search_passages(case["query"], passages)
        citations = [match["citation"] for match in matches]
        if validate_citations(citations, [], sources):
            raise ValueError("Retrieval produced invalid citations.")
        ids = [match["id"] for match in matches]
        expected = case.get("expected_ids")
        if (
            expected is not None
            and _reviewed(case, as_of)
            and case.get("reference_versions")
            == [{"id": ref["id"], "version": ref["version"]} for ref in sources]
        ):
            if not _text_list(expected):
                raise ValueError("Human retrieval targets must be IDs or unset.")
            reviewed += 1
            correct += set(expected) <= set(ids) if expected else not ids
        results.append({"ids": ids, "citations": citations})
    return {
        "case_count": len(cases),
        "reviewed_cases": reviewed,
        "relevant_top_three": _rate(correct, reviewed),
        "results": results,
    }
