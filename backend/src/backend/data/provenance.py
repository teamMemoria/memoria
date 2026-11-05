from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path


class ValueOrigin(StrEnum):
    ORIGINAL = "original"
    DERIVED = "derived"
    SYNTHETIC = "synthetic"


def _required_string(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} must be a non-empty string")
    return value


@dataclass(frozen=True, order=True)
class SourceConversation:
    dataset: str
    original_id: str

    def __post_init__(self) -> None:
        _required_string(self.dataset, "source.dataset")
        _required_string(self.original_id, "source.original_id")

    def as_dict(self) -> dict[str, str]:
        return {"dataset": self.dataset, "original_id": self.original_id}


@dataclass(frozen=True)
class ArtifactManifest:
    artifact_id: str
    sources: tuple[SourceConversation, ...]
    field_origins: Mapping[str, ValueOrigin]
    transformation_version: str
    generated_at: datetime

    def __post_init__(self) -> None:
        _required_string(self.artifact_id, "artifact_id")
        _required_string(self.transformation_version, "transformation_version")
        if not self.sources:
            raise ValueError("sources must contain at least one source conversation")
        if len(set(self.sources)) != len(self.sources):
            raise ValueError("sources must not contain duplicates")
        if not self.field_origins:
            raise ValueError("field_origins must contain at least one field")
        for field, origin in self.field_origins.items():
            _required_string(field, "field_origins key")
            if not isinstance(origin, ValueOrigin):
                raise TypeError(
                    f"field_origins.{field} must be original, derived, or synthetic"
                )
        if self.generated_at.tzinfo is None:
            raise ValueError("generated_at must include a timezone")

    def as_dict(self) -> dict[str, object]:
        generated_at = self.generated_at.astimezone(UTC)
        return {
            "artifact_id": self.artifact_id,
            "field_origins": {
                field: origin.value
                for field, origin in sorted(self.field_origins.items())
            },
            "generated_at": generated_at.isoformat().replace("+00:00", "Z"),
            "sources": [source.as_dict() for source in sorted(self.sources)],
            "transformation_version": self.transformation_version,
        }


def create_manifest(
    *,
    artifact_id: str,
    sources: Sequence[SourceConversation],
    field_origins: Mapping[str, ValueOrigin],
    transformation_version: str,
    generated_at: datetime | None = None,
) -> ArtifactManifest:
    return ArtifactManifest(
        artifact_id=artifact_id,
        sources=tuple(sorted(sources)),
        field_origins=dict(field_origins),
        transformation_version=transformation_version,
        generated_at=generated_at or datetime.now(UTC),
    )


def parse_manifest(value: object) -> ArtifactManifest:
    if not isinstance(value, Mapping):
        raise TypeError("manifest must be an object")
    known_keys = {
        "artifact_id",
        "field_origins",
        "generated_at",
        "sources",
        "transformation_version",
    }
    unknown_keys = sorted(set(value) - known_keys)
    if unknown_keys:
        raise ValueError(f"unknown manifest keys: {', '.join(unknown_keys)}")

    try:
        raw_sources = value["sources"]
        raw_origins = value["field_origins"]
        raw_generated_at = value["generated_at"]
    except KeyError as exc:
        raise ValueError(f"{exc.args[0]} is required") from None

    if not isinstance(raw_sources, list):
        raise TypeError("sources must be an array")
    sources: list[SourceConversation] = []
    for index, source in enumerate(raw_sources):
        if not isinstance(source, Mapping):
            raise TypeError(f"sources[{index}] must be an object")
        try:
            sources.append(
                SourceConversation(
                    dataset=source["dataset"], original_id=source["original_id"]
                )
            )
        except KeyError as exc:
            raise ValueError(f"sources[{index}].{exc.args[0]} is required") from None

    if not isinstance(raw_origins, Mapping):
        raise TypeError("field_origins must be an object")
    origins: dict[str, ValueOrigin] = {}
    for field, origin in raw_origins.items():
        try:
            origins[field] = ValueOrigin(origin)
        except (TypeError, ValueError):
            raise ValueError(
                f"field_origins.{field} must be original, derived, or synthetic"
            ) from None

    if not isinstance(raw_generated_at, str):
        raise TypeError("generated_at must be an ISO 8601 string")
    try:
        generated_at = datetime.fromisoformat(raw_generated_at)
    except ValueError:
        raise ValueError("generated_at must be an ISO 8601 string") from None

    try:
        artifact_id = value["artifact_id"]
        transformation_version = value["transformation_version"]
    except KeyError as exc:
        raise ValueError(f"{exc.args[0]} is required") from None

    return create_manifest(
        artifact_id=artifact_id,
        sources=sources,
        field_origins=origins,
        transformation_version=transformation_version,
        generated_at=generated_at,
    )


def serialize_manifest(manifest: ArtifactManifest) -> str:
    return (
        json.dumps(manifest.as_dict(), indent=2, sort_keys=True, ensure_ascii=False)
        + "\n"
    )


def write_manifest(artifact_path: str | Path, manifest: ArtifactManifest) -> Path:
    artifact_path = Path(artifact_path)
    manifest_path = artifact_path.with_name(f"{artifact_path.name}.provenance.json")
    manifest_path.write_text(serialize_manifest(manifest), encoding="utf-8")
    return manifest_path
