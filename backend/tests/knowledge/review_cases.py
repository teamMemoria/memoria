from backend.services.knowledge import extract_drafts

from .conftest import COMPANY

SCOPE = {"flow": "product_defect", "subflow": "return_size"}


def chat(cid, answer, question="Can I return this?", record=None, flow=SCOPE):
    out = {
        "id": cid,
        "source": {"dataset": "SYNTHETIC", "original_id": cid},
        "modifications": [],
        "channel": "chat",
        "turns": [
            {"n": 1, "speaker": "customer", "text": question},
            {"n": 2, "speaker": "agent", "text": answer},
        ],
        "source_fields": {**flow, "actions_taken": []},
        "customer_record": record or {},
    }
    return out


def draft(record):
    [d] = extract_drafts(record, COMPANY).drafts
    return d


def entry(version, answer):
    return {
        "entry_id": "E1",
        "company_id": COMPANY,
        "version": version,
        "status": "approved",
        "scope": SCOPE,
        "question": "Can I return this?",
        "answer": answer,
    }


def reference(text, rid="r1", **extra):
    return {
        "reference_id": rid,
        "company_id": COMPANY,
        "kind": "authoritative_reference",
        "scope": SCOPE,
        "version": "1",
        "text": text,
        "approval": {"status": "approved"},
        "eligibility": {"status": "eligible"},
        **extra,
    }
