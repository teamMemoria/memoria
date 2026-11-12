import copy

import pytest
from pydantic import ValidationError

from backend.providers.fixture_data import CALLS, CONVERSATIONS, NORTHWIND
from backend.schemas import CallReview, Conversation, KnowledgeEntry


def c1042():
    return copy.deepcopy(
        next(call for call in CALLS[NORTHWIND] if call["id"] == "C1042")
    )


def test_serializes_with_frontend_field_names():
    call = CallReview.model_validate(c1042())
    data = call.model_dump()

    assert {
        "agentId",
        "agentName",
        "criteria",
        "findings",
        "transcript",
        "decision",
    } <= data.keys()
    assert data["criteria"][0]["evidenceTurnNumbers"] == [8, 13]
    assert data["transcript"]["unavailableReason"] is None
    assert data["references"][0]["availableToAgentIds"]


def test_round_trips_without_losing_fields():
    raw = c1042()
    assert CallReview.model_validate(raw).model_dump(exclude_unset=True) == raw


@pytest.mark.parametrize("result", ["meets-criteria", "needs-review", "cannot-assess"])
def test_accepts_existing_audit_results(result):
    raw = c1042()
    raw["criteria"][1]["result"] = result
    CallReview.model_validate(raw)


@pytest.mark.parametrize("result", ["pass", "fail", "Meets criteria", "processing"])
def test_rejects_unknown_audit_results(result):
    raw = c1042()
    raw["criteria"][0]["result"] = result
    with pytest.raises(ValidationError):
        CallReview.model_validate(raw)


def test_rejects_unknown_fields():
    raw = c1042()
    raw["score"] = 87
    with pytest.raises(ValidationError, match="score"):
        CallReview.model_validate(raw)


def test_rejects_criterion_evidence_outside_transcript():
    raw = c1042()
    raw["criteria"][0]["evidenceTurnNumbers"] = [8, 99]
    with pytest.raises(ValidationError, match=r"cites turns \[99\]"):
        CallReview.model_validate(raw)


def test_rejects_finding_evidence_outside_transcript():
    raw = c1042()
    raw["findings"][0]["evidenceTurnNumbers"].append(40)
    with pytest.raises(ValidationError, match=r"cites turns \[40\]"):
        CallReview.model_validate(raw)


def test_rejects_procedure_step_evidence_outside_transcript():
    raw = c1042()
    raw["findings"][0]["procedureSteps"][0]["turnNumbers"] = [17]
    with pytest.raises(ValidationError, match="Identify customer"):
        CallReview.model_validate(raw)


def test_rejects_evidence_when_transcript_is_missing():
    raw = c1042()
    raw["transcript"] = None
    with pytest.raises(ValidationError, match="not in the transcript"):
        CallReview.model_validate(raw)


def test_rejects_unknown_finding_reference():
    raw = c1042()
    raw["criteria"][0]["findingId"] = "no-such-finding"
    with pytest.raises(ValidationError, match="unknown finding"):
        CallReview.model_validate(raw)


def test_rejects_reference_that_is_not_included():
    raw = c1042()
    raw["references"] = []
    with pytest.raises(ValidationError, match="RP-01"):
        CallReview.model_validate(raw)


def test_rejects_needs_review_without_evidence():
    raw = c1042()
    raw["criteria"][0]["evidenceTurnNumbers"] = []
    with pytest.raises(ValidationError, match="cites no evidence"):
        CallReview.model_validate(raw)


def test_rejects_missing_or_duplicate_criteria():
    raw = c1042()
    raw["criteria"] = raw["criteria"][:3]
    with pytest.raises(ValidationError, match="exactly one result per criterion"):
        CallReview.model_validate(raw)

    raw = c1042()
    raw["criteria"][3] = copy.deepcopy(raw["criteria"][2])
    with pytest.raises(ValidationError, match="exactly one result per criterion"):
        CallReview.model_validate(raw)


def test_keeps_non_contiguous_turn_numbers():
    raw = c1042()
    raw["transcript"]["turns"] = [
        turn for turn in raw["transcript"]["turns"] if turn["number"] != 12
    ]
    call = CallReview.model_validate(raw)
    numbers = [turn.number for turn in call.transcript.turns]
    assert 12 not in numbers and numbers[-1] == 16


def test_rejects_duplicate_or_unordered_turns():
    raw = c1042()
    raw["transcript"]["turns"][1]["number"] = 1
    with pytest.raises(ValidationError, match="unique and ascending"):
        CallReview.model_validate(raw)


def test_processing_call_has_no_assessment():
    raw = c1042()
    raw["status"] = "processing"
    with pytest.raises(ValidationError, match="processing call"):
        CallReview.model_validate(raw)


def test_processing_conversation_has_no_review_status():
    raw = copy.deepcopy(CONVERSATIONS[NORTHWIND][0])
    raw["automatedResult"] = "processing"
    with pytest.raises(ValidationError, match="processing conversation"):
        Conversation.model_validate(raw)


def test_unknown_knowledge_dates_stay_none():
    entry = KnowledgeEntry.model_validate(
        {
            "id": "KB-X",
            "title": "t",
            "topic": "t",
            "kind": "knowledge",
            "status": "approved",
            "availableToAgentIds": [],
            "version": "v1",
            "approvedAt": None,
            "approvedBy": None,
            "effectiveAt": None,
            "lastConfirmedAt": None,
            "owner": None,
            "source": None,
            "paragraphs": [],
            "steps": [],
        }
    )
    assert entry.model_dump()["approvedAt"] is None
