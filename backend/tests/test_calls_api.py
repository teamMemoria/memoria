from dataclasses import replace

import pytest
from fastapi.testclient import TestClient

from backend.core.config import Settings
from backend.main import create_app
from backend.providers import ProviderUnavailableError, create_fixture_providers
from backend.providers.fixture_data import CALLS, NORTHWIND
from backend.schemas import CallReview

ALEX = "agent-alex-morgan"
SAM = "agent-sam-rivera"
RILEY = "agent-riley-chen"


def make_client(calls=None):
    providers = create_fixture_providers()
    if calls is not None:
        providers = replace(providers, calls=calls)
    return TestClient(
        create_app(providers=providers, settings=Settings(app_env="test"))
    )


def get(conversation_id, user_id=ALEX, client=None):
    return (client or make_client()).get(
        f"/api/agent/conversations/{conversation_id}", headers={"X-Dev-User": user_id}
    )


def raw_call(conversation_id):
    return next(call for call in CALLS[NORTHWIND] if call["id"] == conversation_id)


# --- ready call -----------------------------------------------------------------


def test_ready_call_matches_frontend_shape():
    response = get("C1042")
    assert response.status_code == 200
    assert response.json() == raw_call("C1042")


def test_ready_call_has_four_categories_findings_transcript_and_references():
    call = get("C1042").json()
    assert [c["id"] for c in call["criteria"]] == [
        "procedure",
        "answer-support",
        "completeness",
        "communication-style",
    ]
    assert (
        call["findings"][0]["suggestion"]
        == "Verify the purchase before offering a refund."
    )
    assert len(call["transcript"]["turns"]) == 16
    assert [r["id"] for r in call["references"]] == ["RP-01"]


@pytest.mark.parametrize("conversation_id", ["C1042", "C1043", "C1047"])
def test_evidence_points_to_turns_in_the_selected_conversation(conversation_id):
    call = get(conversation_id).json()
    turns = {turn["number"] for turn in call["transcript"]["turns"]}
    cited = [n for c in call["criteria"] for n in c["evidenceTurnNumbers"]]
    cited += [n for f in call["findings"] for n in f["evidenceTurnNumbers"]]
    cited += [
        n
        for f in call["findings"]
        for s in f["procedureSteps"]
        for n in s["turnNumbers"]
    ]
    assert cited and set(cited) <= turns


def test_evidence_turn_is_the_right_text():
    call = get("C1042").json()
    turns = {turn["number"]: turn["text"] for turn in call["transcript"]["turns"]}
    procedure = call["criteria"][0]
    assert procedure["evidenceTurnNumbers"] == [8, 13]
    assert turns[8] == "I can offer you a refund."


def test_original_turn_numbers_are_kept():
    call = get("C1043").json()
    assert [turn["number"] for turn in call["transcript"]["turns"]] == [
        1,
        2,
        5,
        6,
        9,
        10,
        11,
    ]
    assert call["criteria"][0]["evidenceTurnNumbers"] == [5, 9]


def test_manager_decision_is_separate_from_the_automated_assessment():
    call = get("C1043").json()
    assert call["decision"]["outcome"] == "confirmed"
    assert call["decision"]["managerName"] == "Maya Chen"
    assert {c["result"] for c in call["criteria"]} == {"meets-criteria"}
    assert all("decision" not in c for c in call["criteria"])
    assert get("C1042").json()["decision"] is None


# --- missing evidence and processing ----------------------------------------------


def test_missing_transcript_is_cannot_assess_not_a_failure():
    call = get("C1044").json()
    assert call["transcript"] is None
    assert {c["result"] for c in call["criteria"]} == {"cannot-assess"}
    assert all(c["evidenceTurnNumbers"] == [] for c in call["criteria"])
    assert call["findings"] == []


def test_partial_transcript_says_why():
    call = get("C1047").json()
    assert call["transcript"]["complete"] is False
    assert (
        call["transcript"]["unavailableReason"]
        == "The recording ended before the call finished."
    )
    completeness = next(c for c in call["criteria"] if c["id"] == "completeness")
    assert completeness["result"] == "cannot-assess"


def test_processing_call_is_explicit():
    call = get("C1045").json()
    assert call["status"] == "processing"
    assert (
        call["criteria"] == [] and call["findings"] == [] and call["decision"] is None
    )


# --- references -------------------------------------------------------------------


def test_reference_keeps_the_version_the_call_was_assessed_against():
    call = get("C1047").json()
    [reference] = call["references"]
    assert (reference["id"], reference["version"], reference["status"]) == (
        "RP-01",
        "v0",
        "stale",
    )
    assert call["criteria"][0]["referenceId"] == "RP-01"


def test_call_with_no_applicable_reference_has_none():
    call = get("C1044").json()
    assert call["references"] == []
    assert all(c["referenceId"] is None for c in call["criteria"])


# --- access ----------------------------------------------------------------------


@pytest.mark.parametrize(
    ("conversation_id", "user_id"),
    [
        ("C9999", ALEX),  # unknown conversation
        ("C1046", ALEX),  # listed, but its call record is unavailable
        ("C2001", ALEX),  # another agent in the same organization
        ("C1042", SAM),  # another agent asking for Alex's call
        ("C1042", RILEY),  # another organization
    ],
)
def test_unavailable_or_unauthorized_calls_get_the_same_404(conversation_id, user_id):
    response = get(conversation_id, user_id)
    assert response.status_code == 404
    assert response.json() == {"detail": "Conversation not found"}


@pytest.mark.parametrize("user_id", ["manager-maya-chen", "approver-devon-park"])
def test_users_without_agent_permission_are_forbidden(user_id):
    assert get("C1042", user_id).status_code == 403


def test_missing_identity_is_rejected():
    assert make_client().get("/api/agent/conversations/C1042").status_code == 401


class _Broken:
    async def get_for_agent(self, organization_id, agent_id, conversation_id):
        raise ProviderUnavailableError


class _Leaky:
    """A buggy provider that ignores the agent and returns Sam's call."""

    async def get_for_agent(self, organization_id, agent_id, conversation_id):
        return CallReview.model_validate(raw_call("C2001"))


def test_provider_failure_is_503():
    response = get("C1042", client=make_client(_Broken()))
    assert response.status_code == 503


def test_another_agents_call_is_never_returned_even_if_the_provider_leaks_it():
    assert get("C2001", ALEX, make_client(_Leaky())).status_code == 404
