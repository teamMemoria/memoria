"""Inputs shared by the scoring and evidence-gate tests."""

from backend.core.config import Settings
from backend.entities.assessments import AnalysisRequest
from backend.entities.guidelines import GUIDELINE_URL, GUIDELINES
from backend.frameworks.data_access.scoring_setup import pilot_services


def events(pairs):
    return [
        {
            "turn_id": i,
            "kind": "action" if speaker == "action" else "message",
            "speaker": speaker,
            "text": words,
        }
        for i, (speaker, words) in enumerate(pairs, 1)
    ]


def approved_guideline(key, reference_id="1"):
    policy = GUIDELINES[key]
    return {
        "id": reference_id,
        "section_id": reference_id,
        "version": f"review-{reference_id}",
        "text": policy.answer,
        "status": "approved",
        "draft_source_key": key,
        "draft_conversation_ids": [],
        "verified_reference_url": GUIDELINE_URL,
        "verification": {"url": GUIDELINE_URL, "quote": policy.quote},
    }


def scoring_request(
    conversation, references=None, *, canonical=None, scope="test", as_of="2026-11-22"
):
    if canonical is None:
        canonical = {"conversations": []}
    return AnalysisRequest(
        conversation,
        references or [],
        [],
        1,
        as_of,
        scope,
        canonical_evidence=canonical,
    )


def scoring_service():
    return pilot_services(None, Settings(app_env="test", layer2_template_pilot=True))[0]
