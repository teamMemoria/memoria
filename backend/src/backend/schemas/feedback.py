from typing import Annotated

from pydantic import StringConstraints

from backend.schemas.base import ApiModel

# Surrounding whitespace is dropped; an empty or whitespace-only value is a 422.
ContextText = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=4000)
]
Reason = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=2000)
]


class SaveContextInput(ApiModel):
    text: ContextText


class RequestReviewInput(ApiModel):
    finding_id: Annotated[str, StringConstraints(min_length=1, max_length=40)]
    reason: Reason
