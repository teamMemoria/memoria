from backend.data.conversations.validation import format_issue, validate_corpus


def test_validation_discovers_only_top_level_json_in_filename_order(
    tmp_path, hvb_payload, abcd_payload, copied_payload, write_json
):
    later = copied_payload(abcd_payload)
    later["id"] = "ABCD-9002"
    write_json("z-later.json", later)
    write_json("a-first.json", hvb_payload)
    write_json("nested/ignored.json", abcd_payload)
    (tmp_path / "ignored.txt").write_text("not json", encoding="utf-8")

    result = validate_corpus(tmp_path)

    assert result.issues == ()
    assert [conversation.id for conversation in result.conversations] == [
        "HVB-9001",
        "ABCD-9002",
    ]


def test_validation_rejects_a_missing_directory(tmp_path):
    missing = tmp_path / "missing"

    result = validate_corpus(missing)

    assert result.conversations == ()
    assert len(result.issues) == 1
    assert result.issues[0].file == missing
    assert result.issues[0].field == "$"
    assert "directory" in result.issues[0].message


def test_validation_rejects_a_regular_file_path(tmp_path):
    regular_file = tmp_path / "record.json"
    regular_file.write_text("{}", encoding="utf-8")

    result = validate_corpus(regular_file)

    assert result.conversations == ()
    assert len(result.issues) == 1
    assert result.issues[0].file == regular_file
    assert result.issues[0].field == "$"
    assert "directory" in result.issues[0].message


def test_validation_rejects_an_empty_directory(tmp_path):
    result = validate_corpus(tmp_path)

    assert result.conversations == ()
    assert len(result.issues) == 1
    assert result.issues[0].file == tmp_path
    assert result.issues[0].field == "$"
    assert "no JSON files" in result.issues[0].message


def test_validation_reports_malformed_json_against_the_file(tmp_path):
    path = tmp_path / "broken.json"
    path.write_text('{"id":', encoding="utf-8")

    result = validate_corpus(tmp_path)

    assert result.conversations == ()
    assert len(result.issues) == 1
    assert result.issues[0].file == path
    assert result.issues[0].field == "$"
    assert "invalid JSON" in result.issues[0].message


def test_validation_reports_a_non_object_json_value_at_the_root(write_json, tmp_path):
    path = write_json("array.json", ["not", "an", "object"])

    result = validate_corpus(tmp_path)

    assert result.conversations == ()
    assert len(result.issues) == 1
    assert result.issues[0].file == path
    assert result.issues[0].field == "$"
    assert "object" in result.issues[0].message


def test_validation_formats_nested_model_error_locations(
    tmp_path, abcd_payload, copied_payload, write_json
):
    payload = copied_payload(abcd_payload)
    payload["turns"][1]["speaker"] = "bot"
    path = write_json("bad-speaker.json", payload)

    result = validate_corpus(tmp_path)

    assert result.conversations == ()
    assert any(
        issue.file == path and issue.field == "turns[1].speaker"
        for issue in result.issues
    )


def test_validation_aggregates_errors_in_filename_then_field_order(
    tmp_path, hvb_payload, abcd_payload, copied_payload, write_json
):
    later = copied_payload(hvb_payload)
    del later["channel"]
    write_json("z-later.json", later)

    earlier = copied_payload(abcd_payload)
    del earlier["id"]
    earlier["turns"][0]["speaker"] = "bot"
    write_json("a-earlier.json", earlier)

    result = validate_corpus(tmp_path)

    assert result.conversations == ()
    assert [(issue.file.name, issue.field) for issue in result.issues] == [
        ("a-earlier.json", "id"),
        ("a-earlier.json", "turns[0].speaker"),
        ("z-later.json", "channel"),
    ]
    assert format_issue(result.issues[0]).startswith("a-earlier.json: id: ")


def test_validation_rejects_a_duplicate_id_on_the_later_file(
    tmp_path, hvb_payload, copied_payload, write_json
):
    first = write_json("a-first.json", hvb_payload)
    duplicate = copied_payload(hvb_payload)
    duplicate["source"]["original_id"] = "another-source-record"
    later = write_json("z-duplicate.json", duplicate)

    result = validate_corpus(tmp_path)

    assert result.conversations == ()
    assert len(result.issues) == 1
    assert result.issues[0].file == later
    assert result.issues[0].field == "id"
    assert first.name in result.issues[0].message
