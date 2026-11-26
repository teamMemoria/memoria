import json
from datetime import UTC, datetime

import pytest

from backend.data.provenance import (
    SourceConversation,
    ValueOrigin,
    create_manifest,
    parse_manifest,
    serialize_manifest,
    write_manifest,
)

GENERATED_AT = datetime(2026, 11, 2, 15, 30, tzinfo=UTC)


def manifest(**overrides):
    values = {
        "artifact_id": "evaluation-split-v1",
        "sources": [
            SourceConversation("HarperValleyBank", "hvb-42"),
            SourceConversation("ABCD", "123"),
        ],
        "field_origins": {
            "transcript": ValueOrigin.ORIGINAL,
            "score": ValueOrigin.DERIVED,
            "conversation_date": ValueOrigin.SYNTHETIC,
        },
        "transformation_version": "split-v1",
        "generated_at": GENERATED_AT,
    }
    values.update(overrides)
    return create_manifest(**values)


def test_manifest_traces_artifact_and_each_value_origin():
    value = manifest().as_dict()

    assert value["sources"] == [
        {"dataset": "ABCD", "original_id": "123"},
        {"dataset": "HarperValleyBank", "original_id": "hvb-42"},
    ]
    assert value["field_origins"] == {
        "conversation_date": "synthetic",
        "score": "derived",
        "transcript": "original",
    }
    assert value["transformation_version"] == "split-v1"
    assert value["generated_at"] == "2026-11-02T15:30:00Z"


def test_serialization_is_deterministic_for_equivalent_inputs():
    forward = manifest()
    reverse = manifest(
        sources=list(reversed(forward.sources)),
        field_origins=dict(reversed(list(forward.field_origins.items()))),
    )

    assert serialize_manifest(forward) == serialize_manifest(reverse)
    assert serialize_manifest(forward).endswith("\n")


def test_manifest_round_trips_through_json():
    original = manifest()

    parsed = parse_manifest(json.loads(serialize_manifest(original)))

    assert parsed == original


@pytest.mark.parametrize(
    ("source", "message"),
    [
        ({"original_id": "123"}, "sources[0].dataset is required"),
        ({"dataset": "ABCD"}, "sources[0].original_id is required"),
        ({"dataset": "", "original_id": "123"}, "source.dataset"),
        ({"dataset": "ABCD", "original_id": ""}, "source.original_id"),
    ],
)
def test_rejects_missing_or_empty_source_information(source, message):
    value = manifest().as_dict()
    value["sources"] = [source]

    with pytest.raises(ValueError, match=message.replace("[", r"\[")):
        parse_manifest(value)


def test_rejects_a_manifest_without_sources():
    value = manifest().as_dict()
    value["sources"] = []

    with pytest.raises(ValueError, match="at least one source conversation"):
        parse_manifest(value)


@pytest.mark.parametrize("origin", ["generated", "", None])
def test_rejects_unknown_value_origins(origin):
    value = manifest().as_dict()
    value["field_origins"] = {"score": origin}

    with pytest.raises(ValueError, match="original, derived, or synthetic"):
        parse_manifest(value)


def test_rejects_a_generation_time_without_timezone():
    value = manifest().as_dict()
    value["generated_at"] = "2026-11-02T15:30:00"

    with pytest.raises(ValueError, match="must include a timezone"):
        parse_manifest(value)


def test_rejects_a_non_object_manifest_with_a_clear_error():
    with pytest.raises(TypeError, match="^manifest must be an object$"):
        parse_manifest([])


def test_rejects_unknown_manifest_keys():
    value = manifest().as_dict()
    value["extra"] = True

    with pytest.raises(ValueError, match="^unknown manifest keys: extra$"):
        parse_manifest(value)


def test_writes_a_provenance_sidecar_next_to_the_artifact(tmp_path):
    artifact_path = tmp_path / "evaluation.csv"

    sidecar_path = write_manifest(artifact_path, manifest())

    assert sidecar_path == tmp_path / "evaluation.csv.provenance.json"
    assert sidecar_path.read_text(encoding="utf-8") == serialize_manifest(manifest())
