"""Check that recurring replies are reviewable evidence only."""

from backend.entities.inferred_knowledge import Settings as KnowledgeSettings
from backend.interface_adapters.drafts import draft_candidates


def test_recurring_questions_preserve_each_variant_and_require_exact_evidence():
    conversations = [
        {
            "id": str(i),
            "transcript_version": f"version-{i}",
            "events": [
                {
                    "turn_id": 1,
                    "speaker": "customer",
                    "text": "What is the return period?",
                },
                {"turn_id": 2, "speaker": "agent", "text": answer},
            ],
        }
        for i, answer in [(1, "Thirty days."), (2, "Sixty days.")]
    ]
    candidate = {
        "category": "return",
        "question": "What is the return period?",
        "occurrences": [
            {
                "abcd_id": c["id"],
                "source_version": c["transcript_version"],
                "observations": [
                    [e["turn_id"], e["speaker"], e["text"]] for e in c["events"]
                ],
            }
            for c in conversations
        ],
    }
    results = draft_candidates(
        "org", conversations, KnowledgeSettings(min_calls=2), [candidate]
    )
    (draft,) = results["drafts"]
    assert (
        draft["status"] == "draft"
        and not draft["audit_eligible"]
        and not draft["trusted"]
    )
    assert {p["quote"] for p in draft["answer_passages"]} == {
        "Thirty days.",
        "Sixty days.",
    }
    candidate["occurrences"][0]["observations"][1][2] = "An invented quote"
    assert not draft_candidates(
        "org", conversations, KnowledgeSettings(min_calls=2), [candidate]
    )["drafts"]
