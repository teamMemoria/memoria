import json
from copy import deepcopy

import pytest

from backend.data.conversation_corpus import (
    build_profile,
    format_issue,
    main,
    serialize_profile,
    validate_corpus,
)


def hvb_record() -> dict[str, object]:
    return {
        "id": "HVB-0001",
        "source": {"dataset": "HarperValleyBank", "original_id": "hvb-1"},
        "modifications": [],
        "channel": "voice",
        "agent_id": "agent-7",
        "turns": [
            {"n": 1, "speaker": "agent", "text": "Hello"},
            {"n": 3, "speaker": "customer", "text": "Replace my card"},
        ],
        "source_fields": {"task_assigned": ["replace card"]},
    }


def abcd_record() -> dict[str, object]:
    return {
        "id": "ABCD-0001",
        "source": {"dataset": "ABCD", "original_id": "abcd-1"},
        "modifications": [],
        "channel": "chat",
        "turns": [
            {"n": 1, "speaker": "agent", "text": "Hello"},
            {"n": 2, "speaker": "system_action", "text": "Account opened"},
            {"n": 4, "speaker": "customer", "text": "Reset my login"},
        ],
        "source_fields": {"flow": "account_access", "subflow": "reset_2fa"},
    }


def write_json(directory, name: str, record: object):
    path = directory / name
    path.write_text(json.dumps(record), encoding="utf-8")
    return path


def test_profiles_valid_records_without_merging_dataset_topics(tmp_path):
    write_json(tmp_path, "HVB-0001.json", hvb_record())
    write_json(tmp_path, "ABCD-0001.json", abcd_record())

    result = validate_corpus(tmp_path)
    profile = build_profile(result.records)

    assert result.issues == ()
    assert profile == {
        "files": 2,
        "distributions": {
            "datasets": {"ABCD": 1, "HarperValleyBank": 1},
            "channels": {
                "ABCD": {"chat": 1},
                "HarperValleyBank": {"voice": 1},
            },
            "topics": {
                "ABCD": {"account_access/reset_2fa": 1},
                "HarperValleyBank": {"replace card": 1},
            },
            "agents": {
                "ABCD": {"unavailable": 1},
                "HarperValleyBank": {"agent-7": 1},
            },
            "speakers": {
                "ABCD": {"agent": 1, "customer": 1, "system_action": 1},
                "HarperValleyBank": {"agent": 1, "customer": 1},
            },
            "turn_counts": {
                "ABCD": {"3": 1},
                "HarperValleyBank": {"2": 1},
            },
        },
    }


def test_profile_serialization_is_deterministic():
    records = [hvb_record(), abcd_record()]

    forward = serialize_profile(build_profile(records))
    reverse = serialize_profile(build_profile(list(reversed(records))))

    assert forward == reverse
    assert forward.endswith("\n") and not forward.endswith("\n\n")


@pytest.mark.parametrize(
    "required_key",
    ["id", "source", "modifications", "channel", "turns", "source_fields"],
)
def test_reports_each_missing_required_top_level_key(tmp_path, required_key):
    record = hvb_record()
    del record[required_key]
    path = write_json(tmp_path, "bad.json", record)

    result = validate_corpus(tmp_path)

    assert any(
        issue.file == path and issue.field == required_key for issue in result.issues
    )


def test_rejects_an_unsupported_dataset(tmp_path):
    record = hvb_record()
    record["source"]["dataset"] = "OtherCorp"
    write_json(tmp_path, "bad.json", record)

    result = validate_corpus(tmp_path)

    assert any(issue.field == "source.dataset" for issue in result.issues)


@pytest.mark.parametrize("speaker", ["bot", "assistant", None])
def test_rejects_unsupported_speakers(tmp_path, speaker):
    record = abcd_record()
    record["turns"][0]["speaker"] = speaker
    write_json(tmp_path, "bad.json", record)

    result = validate_corpus(tmp_path)

    assert any(issue.field == "turns[0].speaker" for issue in result.issues)


@pytest.mark.parametrize("turn_numbers", [[1, 1, 4], [2, 1, 4]])
def test_rejects_turn_numbers_that_are_not_strictly_increasing(tmp_path, turn_numbers):
    record = abcd_record()
    for turn, number in zip(record["turns"], turn_numbers, strict=True):
        turn["n"] = number
    write_json(tmp_path, "bad.json", record)

    result = validate_corpus(tmp_path)

    assert any(issue.field == "turns[1].n" for issue in result.issues)


def test_rejects_a_non_integer_turn_number(tmp_path):
    record = hvb_record()
    record["turns"][0]["n"] = "1"
    write_json(tmp_path, "bad.json", record)

    result = validate_corpus(tmp_path)

    assert any(issue.field == "turns[0].n" for issue in result.issues)


@pytest.mark.parametrize("value", [None, "replace card", ["replace card", 4]])
def test_rejects_invalid_hvb_topic_fields(tmp_path, value):
    record = hvb_record()
    record["source_fields"]["task_assigned"] = value
    write_json(tmp_path, "bad.json", record)

    result = validate_corpus(tmp_path)

    assert any(issue.field == "source_fields.task_assigned" for issue in result.issues)


@pytest.mark.parametrize("field", ["flow", "subflow"])
def test_rejects_invalid_abcd_topic_fields(tmp_path, field):
    record = abcd_record()
    record["source_fields"][field] = None
    write_json(tmp_path, "bad.json", record)

    result = validate_corpus(tmp_path)

    assert any(issue.field == f"source_fields.{field}" for issue in result.issues)


def test_reports_malformed_json_with_filename_and_root_field(tmp_path):
    path = tmp_path / "broken.json"
    path.write_text('{"id":', encoding="utf-8")

    result = validate_corpus(tmp_path)

    assert result.records == ()
    assert result.issues[0].file == path
    assert result.issues[0].field == "$"
    assert format_issue(result.issues[0]).startswith("broken.json: $: ")


@pytest.mark.parametrize("kind", ["missing", "empty"])
def test_rejects_missing_or_empty_directories(tmp_path, kind):
    directory = tmp_path / "conversations"
    if kind == "empty":
        directory.mkdir()

    result = validate_corpus(directory)

    assert result.records == ()
    assert len(result.issues) == 1


def test_cli_prints_the_profile_for_a_valid_directory(tmp_path, capsys):
    write_json(tmp_path, "valid.json", hvb_record())

    exit_code = main([str(tmp_path)])
    output = capsys.readouterr()

    assert exit_code == 0
    assert json.loads(output.out)["files"] == 1
    assert output.err == ""


def test_cli_prints_errors_without_a_partial_profile(tmp_path, capsys):
    valid = hvb_record()
    invalid = deepcopy(abcd_record())
    invalid["turns"][0]["speaker"] = "bot"
    write_json(tmp_path, "valid.json", valid)
    write_json(tmp_path, "invalid.json", invalid)

    exit_code = main([str(tmp_path)])
    output = capsys.readouterr()

    assert exit_code == 1
    assert output.out == ""
    assert "invalid.json: turns[0].speaker:" in output.err


@pytest.mark.parametrize("change", ["missing", None, 7])
def test_rejects_turns_without_string_text(tmp_path, change):
    record = hvb_record()
    if change == "missing":
        del record["turns"][1]["text"]
    else:
        record["turns"][1]["text"] = change
    write_json(tmp_path, "bad.json", record)

    result = validate_corpus(tmp_path)

    assert any(issue.field == "turns[1].text" for issue in result.issues)


def test_accepts_empty_string_turn_text(tmp_path):
    # Transcripts can contain empty utterances; only a missing or non-string
    # text breaks the import.
    record = hvb_record()
    record["turns"][1]["text"] = ""
    write_json(tmp_path, "ok.json", record)

    assert validate_corpus(tmp_path).issues == ()


@pytest.mark.parametrize("change", ["missing", None, "", "  ", 123])
def test_rejects_missing_or_invalid_original_id(tmp_path, change):
    record = abcd_record()
    if change == "missing":
        del record["source"]["original_id"]
    else:
        record["source"]["original_id"] = change
    write_json(tmp_path, "bad.json", record)

    result = validate_corpus(tmp_path)

    assert any(issue.field == "source.original_id" for issue in result.issues)


@pytest.mark.parametrize("value", [None, "", 42])
def test_rejects_invalid_curated_id(tmp_path, value):
    record = hvb_record()
    record["id"] = value
    write_json(tmp_path, "bad.json", record)

    result = validate_corpus(tmp_path)

    assert any(issue.field == "id" for issue in result.issues)


def test_rejects_an_empty_turns_list(tmp_path):
    record = hvb_record()
    record["turns"] = []
    write_json(tmp_path, "bad.json", record)

    result = validate_corpus(tmp_path)

    assert any(
        issue.field == "turns" and "at least one" in issue.message
        for issue in result.issues
    )


def test_rejects_duplicate_curated_ids_naming_the_first_file(tmp_path):
    first = hvb_record()
    second = hvb_record()
    second["source"]["original_id"] = "hvb-2"
    write_json(tmp_path, "a.json", first)
    write_json(tmp_path, "b.json", second)

    result = validate_corpus(tmp_path)

    assert result.records == ()
    assert [format_issue(issue) for issue in result.issues] == [
        "b.json: id: duplicates the id in a.json"
    ]


def test_rejects_duplicate_source_records_naming_the_first_file(tmp_path):
    first = abcd_record()
    second = abcd_record()
    second["id"] = "ABCD-0002"
    write_json(tmp_path, "a.json", first)
    write_json(tmp_path, "b.json", second)

    result = validate_corpus(tmp_path)

    assert [format_issue(issue) for issue in result.issues] == [
        "b.json: source.original_id: duplicates the source record in a.json"
    ]


def test_same_original_id_in_different_datasets_is_allowed(tmp_path):
    hvb = hvb_record()
    abcd = abcd_record()
    abcd["source"]["original_id"] = hvb["source"]["original_id"]
    write_json(tmp_path, "HVB-0001.json", hvb)
    write_json(tmp_path, "ABCD-0001.json", abcd)

    assert validate_corpus(tmp_path).issues == ()


def test_turn_counts_are_ordered_numerically_in_output():
    records = []
    for index, turn_total in enumerate([10, 8, 2, 9]):
        record = hvb_record()
        record["id"] = f"HVB-{index}"
        record["turns"] = [
            {"n": n, "speaker": "agent", "text": "x"} for n in range(1, turn_total + 1)
        ]
        records.append(record)

    output = json.loads(serialize_profile(build_profile(records)))

    assert list(output["distributions"]["turn_counts"]["HarperValleyBank"]) == [
        "2",
        "8",
        "9",
        "10",
    ]
