import io
import json

import pytest

from backend.services.knowledge import (
    OpenAICompatibleClient,
    check_draft_citations,
    extract_drafts,
    read_conversation,
)
from backend.services.knowledge.privacy import Redactor

from .conftest import COMPANY
from .review_cases import chat
from .review_cases import draft as prepare_draft

ANSWER = "Items can be returned after purchase."


@pytest.mark.parametrize("account_id", ["orchardkey", "customer-reference", "abcd"])
def test_account_ids_are_masked_and_independently_detected(account_id):
    record = chat(
        "C1",
        f"The account reference {account_id} is used for returns.",
        record={"account_id": account_id},
    )
    redactor = Redactor(record["customer_record"])
    assert account_id not in redactor.redact(record["turns"][1]["text"]).text
    assert redactor.leaks(account_id) == ["ACCOUNT_DETAIL"]
    result = extract_drafts(record, COMPANY)
    assert result.status == "ok"
    assert account_id not in json.dumps(result.to_dict())


@pytest.mark.parametrize(
    "field,value", [("speaker", []), ("speaker", {}), ("dataset", [])]
)
def test_invalid_enum_values_do_not_abort_valid_conversations(field, value):
    bad = chat("BAD", ANSWER)
    (bad["source"] if field == "dataset" else bad["turns"][0])[field] = value
    result = extract_drafts(bad, COMPANY)
    assert result.status == "error"
    assert result.errors[0]["code"] == "invalid_input"
    assert extract_drafts(chat("GOOD", ANSWER), COMPANY).status == "ok"


@pytest.mark.parametrize("version", [None, "invented-version"])
@pytest.mark.parametrize("location", ["source", "passage"])
def test_citations_bind_to_the_canonical_source_version(version, location):
    record = chat("C1", ANSWER)
    draft = prepare_draft(record)
    if location == "source":
        draft["source"]["version"] = version
    else:
        draft["answer_passages"][0]["source_version"] = version
    assert check_draft_citations(draft, read_conversation(record, COMPANY))


@pytest.mark.parametrize("finish", ["length", "content_filter", None, "stop"])
def test_model_completion_reason_is_required(monkeypatch, finish):
    from backend.services.knowledge.errors import PipelineError

    response = {"choices": [{"finish_reason": finish, "message": {"content": "{}"}}]}
    monkeypatch.setattr(
        "urllib.request.urlopen",
        lambda *a, **k: io.BytesIO(json.dumps(response).encode()),
    )
    client = OpenAICompatibleClient("http://example.invalid", "fake")
    if finish == "stop":
        assert (
            client.complete_json(system="test", prompt="test", max_output_tokens=1)
            == {}
        )
    else:
        with pytest.raises(PipelineError, match="did not finish normally"):
            client.complete_json(system="test", prompt="test", max_output_tokens=1)
