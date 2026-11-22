"""Errors raised by the knowledge pipeline.

Every failure is reported as a ``PipelineError`` with a stable ``code``. Callers
never receive an empty "successful" result in place of an error: invalid input,
oversized input, model failures and unexpected internal errors all raise (or, in the batch helpers, are
returned in an ``errors`` list next to an explicit ``status: "error"``).
"""

from __future__ import annotations

import dataclasses
from dataclasses import dataclass
from typing import Any

INVALID_INPUT = "invalid_input"
OVERSIZED_INPUT = "oversized_input"
MODEL_FAILURE = "model_failure"
MODEL_OUTPUT_INVALID = "model_output_invalid"
REFERENCE_INVALID = "reference_invalid"
INTERNAL_ERROR = "internal_error"

ERROR_CODES = frozenset(
    {
        INVALID_INPUT,
        OVERSIZED_INPUT,
        MODEL_FAILURE,
        MODEL_OUTPUT_INVALID,
        REFERENCE_INVALID,
        INTERNAL_ERROR,
    }
)


@dataclass
class PipelineError(Exception):
    code: str
    message: str
    field: str = "$"
    details: dict[str, Any] = dataclasses.field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.code not in ERROR_CODES:
            raise ValueError(f"unknown error code {self.code!r}")
        super().__init__(f"{self.code}: {self.field}: {self.message}")

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            "code": self.code,
            "field": self.field,
            "message": self.message,
        }
        if self.details:
            out["details"] = self.details
        return out


def invalid(field_name: str, message: str, **details: Any) -> PipelineError:
    return PipelineError(INVALID_INPUT, message, field_name, dict(details))


def oversized(field_name: str, message: str, **details: Any) -> PipelineError:
    return PipelineError(OVERSIZED_INPUT, message, field_name, dict(details))
