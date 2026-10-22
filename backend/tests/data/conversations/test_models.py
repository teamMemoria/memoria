import pytest
from pydantic import ValidationError

from backend.data.conversations.models import (
    ABCDConversation,
    HarperValleyBankConversation,
    parse_conversation,
)


def error_locations(exc: ValidationError) -> set[tuple[object, ...]]:
    return {tuple(error["loc"]) for error in exc.errors()}


def test_hvb_preserves_increasing_non_contiguous_turn_numbers(hvb_payload):
    conversation = HarperValleyBankConversation.model_validate(hvb_payload)

    assert [turn.n for turn in conversation.turns] == [1, 2, 4]


@pytest.mark.parametrize(
    "required_key",
    ["id", "source", "modifications", "channel", "turns", "source_fields"],
)
def test_hvb_rejects_a_missing_required_top_level_key(
    hvb_payload, copied_payload, required_key
):
    payload = copied_payload(hvb_payload)
    del payload[required_key]

    with pytest.raises(ValidationError) as captured:
        HarperValleyBankConversation.model_validate(payload)

    assert (required_key,) in error_locations(captured.value)


@pytest.mark.parametrize(
    ("container_path", "field_path"),
    [
        ((), ("unexpected",)),
        (("source",), ("source", "unexpected")),
        (("source_fields",), ("source_fields", "unexpected")),
        (("turns", 0), ("turns", 0, "unexpected")),
    ],
)
def test_hvb_rejects_unknown_fields(
    hvb_payload, copied_payload, container_path, field_path
):
    payload = copied_payload(hvb_payload)
    container = payload
    for part in container_path:
        container = container[part]
    container["unexpected"] = "surprise"

    with pytest.raises(ValidationError) as captured:
        HarperValleyBankConversation.model_validate(payload)

    assert field_path in error_locations(captured.value)


def test_hvb_rejects_an_empty_turn_list(hvb_payload, copied_payload):
    payload = copied_payload(hvb_payload)
    payload["turns"] = []

    with pytest.raises(ValidationError) as captured:
        HarperValleyBankConversation.model_validate(payload)

    assert ("turns",) in error_locations(captured.value)


@pytest.mark.parametrize("turn_numbers", [[0, 2, 4], [-1, 2, 4], [1, 1, 4], [1, 4, 3]])
def test_hvb_rejects_non_positive_duplicate_or_decreasing_turn_numbers(
    hvb_payload, copied_payload, turn_numbers
):
    payload = copied_payload(hvb_payload)
    for turn, number in zip(payload["turns"], turn_numbers, strict=True):
        turn["n"] = number

    with pytest.raises(ValidationError) as captured:
        HarperValleyBankConversation.model_validate(payload)

    assert any(location[0] == "turns" for location in error_locations(captured.value))


@pytest.mark.parametrize("speaker", ["bot", "system_action"])
def test_hvb_rejects_unsupported_speakers(hvb_payload, copied_payload, speaker):
    payload = copied_payload(hvb_payload)
    payload["turns"][0]["speaker"] = speaker

    with pytest.raises(ValidationError) as captured:
        HarperValleyBankConversation.model_validate(payload)

    assert ("turns", 0, "speaker") in error_locations(captured.value)


def test_hvb_allows_absent_survey_fields(hvb_payload, copied_payload):
    payload = copied_payload(hvb_payload)
    del payload["source_fields"]["agent_survey_response"]
    del payload["source_fields"]["customer_survey_response"]

    conversation = HarperValleyBankConversation.model_validate(payload)

    assert "agent_survey_response" not in conversation.source_fields.model_fields_set
    assert "customer_survey_response" not in conversation.source_fields.model_fields_set


def test_hvb_rejects_an_explicitly_null_optional_survey(hvb_payload, copied_payload):
    payload = copied_payload(hvb_payload)
    payload["source_fields"]["agent_survey_response"] = None

    with pytest.raises(ValidationError) as captured:
        HarperValleyBankConversation.model_validate(payload)

    assert ("source_fields", "agent_survey_response") in error_locations(
        captured.value
    )


def test_hvb_rejects_an_empty_assigned_task_list(hvb_payload, copied_payload):
    payload = copied_payload(hvb_payload)
    payload["source_fields"]["task_assigned"] = []

    with pytest.raises(ValidationError) as captured:
        HarperValleyBankConversation.model_validate(payload)

    assert ("source_fields", "task_assigned") in error_locations(captured.value)


def test_abcd_accepts_all_supported_speakers(abcd_payload):
    conversation = ABCDConversation.model_validate(abcd_payload)

    assert [turn.speaker for turn in conversation.turns] == [
        "agent",
        "customer",
        "system_action",
    ]


def test_abcd_binds_the_dataset_to_the_chat_channel(abcd_payload, copied_payload):
    payload = copied_payload(abcd_payload)
    payload["channel"] = "voice"

    with pytest.raises(ValidationError) as captured:
        ABCDConversation.model_validate(payload)

    assert ("channel",) in error_locations(captured.value)


def test_abcd_allows_an_absent_customer_id(abcd_payload, copied_payload):
    payload = copied_payload(abcd_payload)
    del payload["customer_id"]

    conversation = ABCDConversation.model_validate(payload)

    assert "customer_id" not in conversation.model_fields_set


def test_abcd_rejects_an_explicitly_null_customer_id(abcd_payload, copied_payload):
    payload = copied_payload(abcd_payload)
    payload["customer_id"] = None

    with pytest.raises(ValidationError) as captured:
        ABCDConversation.model_validate(payload)

    assert ("customer_id",) in error_locations(captured.value)


@pytest.mark.parametrize(
    ("field", "location"),
    [
        ("agent_id", ("agent_id",)),
        ("asr_text", ("turns", 0, "asr_text")),
        ("start_ms", ("turns", 0, "start_ms")),
    ],
)
def test_abcd_rejects_hvb_only_fields(
    abcd_payload, copied_payload, field, location
):
    payload = copied_payload(abcd_payload)
    if field == "agent_id":
        payload[field] = "hvb-speaker-1"
    else:
        payload["turns"][0][field] = "unexpected"

    with pytest.raises(ValidationError) as captured:
        ABCDConversation.model_validate(payload)

    assert location in error_locations(captured.value)


@pytest.mark.parametrize(
    ("field", "invalid_value"),
    [
        ("flow", ["account_access"]),
        ("subflow", 42),
        ("actions_taken", ["pull-up-account", 42]),
    ],
)
def test_abcd_rejects_invalid_source_field_types(
    abcd_payload, copied_payload, field, invalid_value
):
    payload = copied_payload(abcd_payload)
    payload["source_fields"][field] = invalid_value

    with pytest.raises(ValidationError) as captured:
        ABCDConversation.model_validate(payload)

    assert any(
        location[:2] == ("source_fields", field)
        for location in error_locations(captured.value)
    )


def test_dispatches_each_supported_dataset(hvb_payload, abcd_payload):
    assert isinstance(parse_conversation(hvb_payload), HarperValleyBankConversation)
    assert isinstance(parse_conversation(abcd_payload), ABCDConversation)


def test_dispatch_rejects_an_unknown_dataset_at_the_dataset_field(
    abcd_payload, copied_payload
):
    payload = copied_payload(abcd_payload)
    payload["source"]["dataset"] = "OtherCorp"

    with pytest.raises(ValidationError) as captured:
        parse_conversation(payload)

    assert ("source", "dataset") in error_locations(captured.value)
