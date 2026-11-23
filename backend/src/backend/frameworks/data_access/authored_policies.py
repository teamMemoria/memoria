"""Read the versioned first-party policy catalogue used for Manager publication."""

import json
from hashlib import sha256
from pathlib import Path

AUTHORED_POLICY_PREFIX = "layer1-memoria-"
CATALOGUE_PATH = Path(__file__).resolve().parents[5] / "ml/layer1/policies.json"


def load_authored_catalogue() -> dict | None:
    catalogue = json.loads(CATALOGUE_PATH.read_text(encoding="utf-8"))
    if (
        catalogue["origin"] != "Memoria-authored"
        or catalogue["historical_abcd_scoring"] is not False
    ):
        return None
    return catalogue


def authored_answer(policy: dict) -> str:
    return f"Memoria-authored policy proposal for future calls. {policy['answer']}"


def authored_policy_version(draft) -> str | None:
    key = draft.source_key or ""
    if not key.startswith(AUTHORED_POLICY_PREFIX):
        return None
    catalogue = load_authored_catalogue()
    if catalogue is None:
        return None
    for policy in catalogue["policies"]:
        if (
            policy["id"] == key
            and policy["question"] == draft.question
            and draft.answer_text == authored_answer(policy)
        ):
            source = [catalogue["version"], catalogue["applies_to"], policy]
            digest = sha256(json.dumps(source, sort_keys=True).encode()).hexdigest()
            return f"sha256:{digest}"
    return None
