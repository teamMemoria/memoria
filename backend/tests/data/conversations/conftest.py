from copy import deepcopy
import json

import pytest


@pytest.fixture
def hvb_payload() -> dict[str, object]:
    return {
        "id": "HVB-9001",
        "source": {
            "dataset": "HarperValleyBank",
            "original_id": "synthetic-hvb-9001",
            "licence": "CC BY 4.0",
            "url": "https://example.test/hvb",
            "citation": "Synthetic test fixture",
        },
        "modifications": [],
        "channel": "voice",
        "agent_id": "hvb-speaker-7",
        "customer_id": "hvb-speaker-8",
        "customer_record": {
            "customer_name": "Test Customer",
            "captured_by_agent": {"replacement card type": "debit"},
        },
        "turns": [
            {
                "n": 1,
                "speaker": "agent",
                "text": "How can I help?",
                "asr_text": "How can I help?",
                "start_ms": 100,
                "duration_ms": 400,
                "dialog_acts": ["greeting"],
            },
            {
                "n": 2,
                "speaker": "customer",
                "text": "I need a replacement card.",
                "asr_text": "I need a replacement card.",
                "start_ms": 550,
                "duration_ms": 900,
                "dialog_acts": ["problem_description"],
            },
            {
                "n": 4,
                "speaker": "agent",
                "text": "I can arrange that.",
                "asr_text": "I can arrange that.",
                "start_ms": 1500,
                "duration_ms": 500,
                "dialog_acts": ["response"],
            },
        ],
        "source_fields": {
            "task_assigned": ["replace card"],
            "task_logged_by_agent": ["replace card"],
            "labels": {"agent_mos": 4.0},
            "session": "Synthetic Session",
            "agent_survey_response": {"partner_rating": "10"},
            "customer_survey_response": {"partner_rating": "9"},
        },
    }


@pytest.fixture
def abcd_payload() -> dict[str, object]:
    return {
        "id": "ABCD-9001",
        "source": {
            "dataset": "ABCD",
            "original_id": "synthetic-abcd-9001",
            "licence": "MIT",
            "url": "https://example.test/abcd",
            "citation": "Synthetic test fixture",
        },
        "modifications": [],
        "channel": "chat",
        "customer_id": "synthetic-customer",
        "customer_record": {
            "customer_name": "Test Customer",
            "member_level": "silver",
        },
        "turns": [
            {"n": 1, "speaker": "agent", "text": "How can I help?"},
            {"n": 2, "speaker": "customer", "text": "Reset my login."},
            {
                "n": 3,
                "speaker": "system_action",
                "text": "Account has been pulled up.",
            },
        ],
        "source_fields": {
            "flow": "account_access",
            "subflow": "reset_2fa",
            "actions_taken": ["pull-up-account", "send-link"],
        },
    }


@pytest.fixture
def copied_payload():
    def copy(payload: dict[str, object]) -> dict[str, object]:
        return deepcopy(payload)

    return copy


@pytest.fixture
def write_json(tmp_path):
    def write(name: str, payload: object):
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload), encoding="utf-8")
        return path

    return write
