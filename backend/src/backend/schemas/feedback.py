from typing import Annotated

from pydantic import StringConstraints

from backend.schemas.base import ApiModel

# PostgreSQL text cannot hold a NUL character, so it is rejected up front.
NO_NUL = r"^[^\x00]*$"


def text_field(max_length: int):
    """Text a person typed: trimmed, not blank, bounded, no NUL (422 otherwise)."""
    return Annotated[
        str,
        StringConstraints(
            strip_whitespace=True,
            min_length=1,
            max_length=max_length,
            pattern=NO_NUL,
        ),
    ]


ContextText = text_field(4000)
Reason = text_field(2000)


class SaveContextInput(ApiModel):
    text: ContextText


class RequestReviewInput(ApiModel):
    finding_id: Annotated[
        str, StringConstraints(min_length=1, max_length=40, pattern=NO_NUL)
    ]
    reason: Reason
