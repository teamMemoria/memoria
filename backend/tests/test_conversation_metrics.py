import pytest

from backend.data.conversation_metrics import compute_conversation_metrics


def test_hvb_computes_shared_voice_timing_and_asr_metrics():
    record = {
        "source": {"dataset": "HarperValleyBank"},
        "channel": "voice",
        "turns": [
            {
                "speaker": "agent",
                "text": "How can I help?",
                "start_ms": 0,
                "duration_ms": 1_000,
            },
            {
                "speaker": "customer",
                "text": "I need a debit card",
                "asr_text": "I need debit cart",
                "start_ms": 1_500,
                "duration_ms": 2_500,
            },
        ],
        "source_fields": {},
    }

    metrics = compute_conversation_metrics(record)

    assert metrics.turn_count == 2
    assert metrics.agent_word_count == 4
    assert metrics.customer_word_count == 5
    assert metrics.agent_text_share == pytest.approx(4 / 9)
    assert metrics.customer_text_share == pytest.approx(5 / 9)
    assert metrics.call_elapsed_ms == 4_000
    assert metrics.agent_speaking_ms == 1_000
    assert metrics.customer_speaking_ms == 2_500
    assert metrics.average_turn_duration_ms == 1_750
    assert metrics.asr_word_error_rate == pytest.approx(2 / 5)
    assert metrics.asr_compared_turn_count == 1
    assert metrics.system_action_count is None
    assert metrics.documented_action_count is None


def test_abcd_computes_action_counts_without_voice_metrics():
    record = {
        "source": {"dataset": "ABCD"},
        "channel": "chat",
        "turns": [
            {"speaker": "agent", "text": "I can help with that"},
            {"speaker": "system_action", "text": "Account opened"},
            {"speaker": "customer", "text": "Thank you"},
            {"speaker": "system_action", "text": "Reset link sent"},
        ],
        "source_fields": {"actions_taken": ["pull-up-account", "send-link"]},
    }

    metrics = compute_conversation_metrics(record)

    assert metrics.turn_count == 4
    assert metrics.agent_word_count == 5
    assert metrics.customer_word_count == 2
    assert metrics.system_action_count == 2
    assert metrics.documented_action_count == 2
    assert metrics.call_elapsed_ms is None
    assert metrics.agent_speaking_ms is None
    assert metrics.customer_speaking_ms is None
    assert metrics.average_turn_duration_ms is None
    assert metrics.asr_word_error_rate is None
    assert metrics.asr_compared_turn_count is None


def test_missing_optional_hvb_fields_are_unavailable_instead_of_zero():
    record = {
        "source": {"dataset": "HarperValleyBank"},
        "channel": "voice",
        "turns": [
            {"speaker": "agent", "text": "Hello"},
            {"speaker": "customer", "text": "Hi"},
        ],
        "source_fields": {},
    }

    metrics = compute_conversation_metrics(record)

    assert metrics.call_elapsed_ms is None
    assert metrics.agent_speaking_ms is None
    assert metrics.customer_speaking_ms is None
    assert metrics.average_turn_duration_ms is None
    assert metrics.asr_word_error_rate is None
    assert metrics.asr_compared_turn_count == 0


def test_empty_participant_text_makes_text_shares_unavailable():
    record = {
        "source": {"dataset": "ABCD"},
        "channel": "chat",
        "turns": [
            {"speaker": "agent", "text": ""},
            {"speaker": "customer", "text": ""},
            {"speaker": "system_action", "text": "Account opened"},
        ],
        "source_fields": {},
    }

    metrics = compute_conversation_metrics(record)

    assert metrics.agent_word_count == 0
    assert metrics.customer_word_count == 0
    assert metrics.agent_text_share is None
    assert metrics.customer_text_share is None
    assert metrics.system_action_count == 1
    assert metrics.documented_action_count is None


def test_dataset_metrics_require_the_supported_channel():
    record = {
        "source": {"dataset": "HarperValleyBank"},
        "channel": "chat",
        "turns": [{"speaker": "agent", "text": "Hello"}],
        "source_fields": {},
    }

    metrics = compute_conversation_metrics(record)

    assert metrics.call_elapsed_ms is None
    assert metrics.asr_word_error_rate is None
    assert metrics.asr_compared_turn_count is None
    assert metrics.system_action_count is None
