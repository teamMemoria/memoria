import pytest

from backend.services.knowledge import (
    FakeModelClient,
    ModelExtractor,
    release_checks,
    run_pipeline,
)
from backend.services.knowledge.pipeline import repeat_processing_check

from .conftest import COMPANY
from .review_cases import chat, reference

ANSWER = "Items can be returned after purchase."


def model_report(answer=ANSWER, proposed=None):
    record = chat("C1", answer)
    reply = {
        "drafts": [
            {
                "question": record["turns"][0]["text"],
                "question_turn_ids": ["C1#t1"],
                "answer": proposed or answer,
                "answer_turn_ids": ["C1#t2"],
                "conditions": [],
            }
        ]
    }
    extractor = ModelExtractor(FakeModelClient(responder=lambda *_: reply))
    payload = {
        "company_id": COMPANY,
        "conversations": [record],
        "references": [reference(answer)],
    }
    return run_pipeline(payload, extractor=extractor), payload, extractor


@pytest.mark.parametrize("model", [False, True])
@pytest.mark.parametrize(
    "tamper",
    [
        lambda o: o.clear(),
        lambda o: o["verification"]["results"][0]["claims"].clear(),
        lambda o: o["verification"]["results"].clear(),
        lambda o: o["drafts"].clear(),
        lambda o: o["extraction"].clear(),
        lambda o: o.update(schema="unknown"),
        lambda o: o["drafts"][0].update(wording="unknown"),
        lambda o: o.update(counts=None),
        lambda o: o["counts"].update(verification={"supported": 999}),
        lambda o: o["counts"].update(verification=None),
        lambda o: o["counts"].update(drafts=True),
        lambda o: o["counts"].update(conversations=1.0),
        lambda o: o["drafts"][0].update(draft_id=[]),
        lambda o: o["drafts"][0].update(draft_id={}),
    ],
)
def test_invalid_reports_fail_closed(model, tamper):
    output, payload, extractor = model_report()
    client = extractor.client
    if not model:
        output, extractor = run_pipeline(payload), None
    assert output["release_checks"]["release_allowed"]
    calls = client.usage.calls
    tamper(output)
    assert not release_checks(output, payload, extractor)["release_allowed"]
    assert client.usage.calls == calls


@pytest.mark.parametrize(
    "field,value", [("speaker", []), ("speaker", {}), ("dataset", [])]
)
def test_invalid_enum_values_do_not_abort_valid_conversations(field, value):
    bad = chat("BAD", ANSWER)
    (bad["source"] if field == "dataset" else bad["turns"][0])[field] = value
    result = run_pipeline(
        {"company_id": COMPANY, "conversations": [bad, chat("GOOD", ANSWER)]}
    )
    assert result["status"] == "completed_with_failures"
    assert result["technical_failures"][0]["errors"][0]["code"] == "invalid_input"
    assert result["drafts"][0]["source"]["conversation_id"] == "GOOD"


def test_repeat_processing_compares_results_without_cumulative_usage():
    _, payload, extractor = model_report()
    assert repeat_processing_check(payload, extractor)["passed"]
