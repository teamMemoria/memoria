"""Generate review-only candidates from canonical, explicitly linked Q&A.

A quoted agent answer is a proposed source, never an authoritative guideline.
Only general information slots qualify; account details, outcomes, promises,
withdrawn/changed requests and unlinked text cannot become reusable answers.
"""

import re

from .abcd import conversation_passages, validate_evidence
from .citations import validate_citations
from .rule_links import VERSION as LINK_VERSION
from .rule_links import request_links
from .scoring import content_version

VERSION = "linked-knowledge-candidates-v1"
GENERAL_SLOTS = {
    "cost",
    "duration",
    "property",
    "material",
    "color",
    "warranty",
    "care",
    "policy",
}


def generate_candidates(organization_id, evidence_records):
    """Pure composition; isolate invalid records and preserve exact full passages."""
    if not isinstance(organization_id, str) or not organization_id.strip():
        raise ValueError("An organization is required")
    drafts, records, seen = [], [], set()
    for evidence in evidence_records:
        identifier = None
        try:
            validate_evidence(evidence)
            if len(evidence["conversations"]) != 1:
                raise ValueError("Supply one canonical conversation per record")
            conversation = evidence["conversations"][0]
            identifier = conversation["id"]
            if conversation["split"] != "train":
                raise ValueError("Only training conversations are in this pilot")
            if identifier in seen:
                raise ValueError("Duplicate conversation")
            seen.add(identifier)
            passages = {
                row["citation"]["turn_id"]: row["citation"]
                for row in conversation_passages([conversation])
            }
            links, _ = request_links(conversation)
            proposed = []
            for link in links:
                question = link.get("question")
                if (
                    not question
                    or question["kind"] not in GENERAL_SLOTS
                    or link["state"] != "answered"
                ):
                    continue
                if re.search(
                    r"\bmy\b",
                    passages[link["turn_id"]]["quote"],
                    re.IGNORECASE,
                ):
                    continue
                question_turns = [*link.get("context_turn_ids", []), link["turn_id"]]
                answer_turns = link["history"][-1]["turn_ids"]
                citations = [
                    passages[t] for t in dict.fromkeys(question_turns + answer_turns)
                ]
                if validate_citations(citations, [conversation], []):
                    raise ValueError("Candidate citations failed validation")
                # Canonical masking remains unchanged. Do not make individual facts reusable,
                # even if the identifier has already been replaced by a placeholder.
                if any(
                    re.search(r"\[[A-Z_]+_\d+\]", row["quote"]) for row in citations
                ):
                    continue

                proposed.append(
                    {
                        "draft_id": "linked-"
                        + content_version(
                            [
                                organization_id,
                                identifier,
                                conversation["transcript_version"],
                                link["id"],
                                VERSION,
                                LINK_VERSION,
                            ]
                        )[7:47],
                        "kind": "knowledge_draft",
                        "status": "draft",
                        "trusted": False,
                        "audit_eligible": False,
                        "company_id": organization_id,
                        "topic": question["subject"],
                        "question": passages[link["turn_id"]]["quote"],
                        "answer": "\n\n".join(
                            passages[t]["quote"] for t in answer_turns
                        ),
                        "question_passages": [
                            _passage(conversation, passages[t])
                            for t in dict.fromkeys(question_turns)
                        ],
                        "answer_passages": [
                            _passage(conversation, passages[t]) for t in answer_turns
                        ],
                        "conditions": [],
                    }
                )
            drafts.extend(proposed)
            records.append(
                {
                    "conversation_id": identifier,
                    "status": "completed",
                    "drafts": len(proposed),
                    "reason": None
                    if proposed
                    else "No supported reusable question/answer link.",
                }
            )
        except (ValueError, TypeError, KeyError) as error:
            records.append(
                {
                    "conversation_id": identifier,
                    "status": "failed",
                    "drafts": 0,
                    "reason": f"{type(error).__name__}: invalid canonical evidence or citation",
                }
            )
    return {
        "schema": "knowledge-pipeline/1",
        "company_id": organization_id,
        "status": "completed_with_failures"
        if any(r["status"] == "failed" for r in records)
        else "ok",
        "versions": {"generator": VERSION, "links": LINK_VERSION},
        "drafts": drafts,
        "groups": [],
        "conflicts": [],
        "verification": {
            "results": [
                {"draft_id": d["draft_id"], "verification_status": "unverifiable"}
                for d in drafts
            ]
        },
        "release_checks": {
            "release_allowed": True,
            "scope": "exact cited pending candidates only; not semantic verification or approval",
        },
        "records": records,
        "limitations": [
            "Agent statements are not proof of policy correctness.",
            "Full answer passages retain qualifications; no inferred conditions are added.",
            "Automatic grouping, conflict detection and authoritative verification are not performed.",
        ],
    }


def _passage(conversation, citation):
    turn = citation["turn_id"]
    event = next(e for e in conversation["events"] if e["turn_id"] == turn)
    identifier = conversation["id"]
    return {
        "source_key": "ABCD:" + identifier,
        "source_version": conversation["transcript_version"],
        "conversation_id": identifier,
        "turn_id": f"{identifier}#t{turn}",
        "speaker": event["speaker"],
        "quote": citation["quote"],
        "span": [0, len(citation["quote"])],
    }
