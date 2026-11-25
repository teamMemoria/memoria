"""Stable versions for structured evidence and catalogue inputs."""

import json
from hashlib import sha256


def digest(value):
    return (
        "sha256:"
        + sha256(
            json.dumps(
                value,
                sort_keys=True,
                ensure_ascii=False,
                allow_nan=False,
                separators=(",", ":"),
            ).encode()
        ).hexdigest()
    )
