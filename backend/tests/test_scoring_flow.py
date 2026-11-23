"""Run the pilot through the real HTTP routes, importer and PostgreSQL storage."""

import httpx
import pytest
from ml.abcd import _source_metadata, prepare_dataset

from backend.core.config import Settings
from backend.entities.assessments import ReportRejectedError
from backend.entities.extension import extension_refusal
from backend.entities.policies import _VERIFICATION_SOURCES
from backend.entities.score_policy import overall_for_form, overall_for_profile
from backend.frameworks.data_access.assessment_storage import import_prepared
from backend.frameworks.data_access.scoring_setup import pilot_services
from backend.interface_adapters.controllers.assessments import validate_payload
from backend.main import create_app
from backend.providers.database import create_database_providers
from tests.database_seed import ALEX, MAYA, RILEY, SAM, scoring_data, sessions_for
from tests.scoring_fixtures import events, scoring_request, scoring_service

DRAFTS = "/api/manager/knowledge/drafts"
IMPORT = "/api/manager/knowledge/imports"


def headers(user):
    return {"X-Dev-User": user}


def test_overall_uses_form_weights_and_requires_every_metric():
    weights = {
        "procedure": 0.3,
        "completeness": 0.3,
        "communication-style": 0.2,
        "answer-support": 0.2,
    }
    criteria = [
        {"category": k, "weight": w, "enabled": True} for k, w in weights.items()
    ]
    scores = dict.fromkeys(weights, 100)
    scores["answer-support"] = 50
    coverage = dict.fromkeys(weights, 100)
    coverage["answer-support"] = 0
    result = overall_for_form(criteria, 2, scores, coverage)
    assert (result["score"], result["coverage"]) == (90, 80)
    assert overall_for_form(criteria[:-1], 2, scores, coverage)["score"] is None
    scores["answer-support"] = None
    assert overall_for_form(criteria, 2, scores, coverage)["score"] is None


def test_category_weights_change_only_the_overall():
    service = scoring_service()
    profiles = service.adapter.weight_profiles
    scores = {
        "procedure": 100,
        "completeness": 100,
        "communication-style": 100,
        "answer-support": 90,
    }
    coverage = dict.fromkeys(scores, 100)
    assert (
        overall_for_profile(profiles["subscription"], scores, coverage)["score"] == 97
    )
    assert overall_for_profile(profiles["website"], scores, coverage)["score"] == 98.5
    scores["answer-support"] = None
    assert (
        overall_for_profile(profiles["subscription"], scores, coverage)["score"] is None
    )


@pytest.mark.parametrize(
    "defect",
    [
        "metric",
        "overall",
        "version",
        "weights",
        "profile",
        "weight-version",
        "inventory",
        "approval",
    ],
)
def test_storage_rejects_inconsistent_midpoint_even_after_parsing(defect):
    service = scoring_service()
    replies = [
        ("customer", "How long are standard promo codes valid?"),
        ("agent", "Standard promo codes are valid for 7 days."),
    ]
    request = scoring_request(
        {"id": "test", "transcript_version": "test-v1", "events": events(replies)}
    )
    report = service.adapter.analyse(request)
    parsed = service.report_parser(request, report)
    validate_payload(request, parsed, policy=service.percentage_policy)
    scoring = report["categories"][0]["scoring"]
    if defect == "metric":
        scoring["score"] = 100
    elif defect == "overall":
        report["overall"]["score"] = 50
    elif defect == "version":
        del report["versions"]["scoring"]
    elif defect == "weights":
        report["overall"]["weights"]["procedure"] += 1
        report["overall"]["weights"]["completeness"] -= 1
    elif defect == "profile":
        report["overall"]["profile_id"] = "subscription"
    elif defect == "weight-version":
        del report["versions"]["weight_profile"]
    elif defect == "inventory":
        scoring.update(inventory_complete=False, possible=None, coverage=None)
    else:
        report["approval"] = {"status": "approved"}
    with pytest.raises(ReportRejectedError):
        validate_payload(request, parsed, policy=service.percentage_policy)


def test_extension_refusal_requires_ordered_actions_and_a_linked_followup():
    dialogue = [
        ("customer", "Could I have an extension for my subscription?"),
        ("action", "Account has been pulled up for [ACCOUNT_ID_1]."),
        ("action", "Identity verification in progress ..."),
        ("action", "Membership level of Guest has been noted."),
        (
            "agent",
            "I'm sorry Dr. [PERSON_2], but your account does not qualify for an extension.",
        ),
        ("customer", "Why is that?"),
        ("agent", "Your membership level does not qualify."),
        ("agent", "Is there anything else I can help you with?"),
        ("customer", "No, thank you."),
    ]
    events = [
        {"speaker": speaker, "text": text, "turn_id": n}
        for n, (speaker, text) in enumerate(dialogue, 1)
    ]
    result = extension_refusal(events)
    assert result is not None
    assert result["verification"] == events[2]
    assert result["reason"] == events[6]
    quoted_action = {**events[3], "speaker": "agent"}
    assert extension_refusal([*events[:3], quoted_action, *events[4:]]) is None
    open_promise = {
        "speaker": "agent",
        "text": "I will call you tomorrow.",
        "turn_id": 10,
    }
    assert extension_refusal([*events, open_promise]) is None


async def add_call(session, data, number, days):
    original = [
        ["customer", "How long are standard promo codes valid?"],
        ["agent", f"Standard promo codes are valid for {days} days."],
    ]
    record = {
        "convo_id": number,
        "original": original,
        "delexed": [
            {"speaker": speaker, "turn_count": i, "text": text}
            for i, (speaker, text) in enumerate(original, 1)
        ],
        "scenario": {},
    }
    evidence = prepare_dataset(
        {"train": [record], "dev": [], "test": []}, _source_metadata(), (str(number),)
    )
    call = await import_prepared(
        session, data.northwind.id, data.alex_agent.id, evidence
    )
    return str(call.id)


def answer_support(call):
    return next(c["scoring"] for c in call["criteria"] if c["id"] == "answer-support")


async def analyse(client, call_id):
    path = f"/api/manager/conversations/{call_id}/analysis"
    response = await client.post(path, headers=headers(MAYA))
    assert response.status_code == 202, response.text
    result = (await client.get(path, headers=headers(MAYA))).json()
    assert result["status"] == "succeeded", result
    return (
        await client.get(path.removesuffix("/analysis"), headers=headers(MAYA))
    ).json()["call"]


async def test_layer2_draft_approval_and_persisted_template_assessment(
    session, monkeypatch
):
    data = await scoring_data(session)
    sources = [await add_call(session, data, i, 7) for i in range(200, 210)]
    sessions = sessions_for(session)
    settings = Settings(app_env="test", layer2_template_pilot=True)
    analysis, knowledge_import = pilot_services(sessions, settings)
    app = create_app(
        create_database_providers(sessions), settings, analysis, knowledge_import
    )
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        assert (await client.post(IMPORT, headers=headers(ALEX))).status_code == 403
        generated = await client.post(IMPORT, headers=headers(MAYA))
        assert generated.status_code == 200, generated.text
        assert generated.json()["created"] == 1, generated.text
        assert (await client.post(IMPORT, headers=headers(MAYA))).json()[
            "unchanged"
        ] == 1
        drafts = (await client.get(DRAFTS, headers=headers(MAYA))).json()
        draft = next(
            d
            for d in drafts
            if d["title"] == "How long are standard promo codes valid?"
        )
        assert draft["status"] == "draft" and draft["verificationReference"] is None
        assert set(draft["sourceConversationIds"]) == set(sources)
        assert len(draft["passages"]) == 20
        base = f"{DRAFTS}/{draft['id']}"
        reference = {
            "title": "Northwind sample promotion policy",
            "url": "https://example.test/promo-policy",
            "quote": "Standard promo codes expire after 7 days.",
            "version": draft["version"],
        }
        decision = {
            "version": draft["version"],
            "verifiedReferenceUrl": reference["url"],
        }

        async def verify(payload, *, user=MAYA):
            return await client.put(
                base + "/verification", headers=headers(user), json=payload
            )

        async def approve():
            return await client.post(
                base + "/approve", headers=headers(MAYA), json=decision
            )

        response = await approve()
        assert response.status_code == 409

        early_call = await add_call(session, data, 211, 7)
        early = await analyse(client, early_call)
        assert answer_support(early)["score"] is None
        assert answer_support(early)["coverage"] == answer_support(early)["earned"] == 0

        assert (await verify(reference, user=ALEX)).status_code == 403
        assert (await verify(reference)).status_code == 409

        # Register an independent source for this fixture only.
        monkeypatch.setitem(
            _VERIFICATION_SOURCES,
            "layer2-promo-days-7",
            (reference["quote"], reference["quote"], reference["url"]),
        )
        for invalid in (
            {**reference, "quote": "Standard promo codes expire after 30 days."},
            {**reference, "url": "https://[broken/policy"},
        ):
            assert (await verify(invalid)).status_code == 409
        attached = await verify(reference)
        assert attached.status_code == 200, attached.text
        assert attached.json()["status"] == "draft"
        assert (await approve()).status_code == 409
        decision["version"] = attached.json()["version"]
        approved = await approve()
        assert approved.status_code == 200, approved.text
        assert approved.json()["status"] == "approved"

        target = await add_call(session, data, 212, 14)
        manager = await analyse(client, target)
        route = f"/api/agent/conversations/{target}"
        owner = await client.get(route, headers=headers(ALEX))
        assert owner.status_code == 200, owner.text
        for stranger in (SAM, RILEY):
            assert (
                await client.get(route, headers=headers(stranger))
            ).status_code == 404
        assert answer_support(owner.json()) == answer_support(manager)
        result = answer_support(manager)
        assert result["score"] == 60
        policy_fact = next(
            check
            for check in result["checks"]
            if check["ruleId"] == "answer-support.facts"
        )
        assert policy_fact["outcome"] == "supported"
        assert policy_fact["requirement"] == (
            "Does approved guidance establish that standard promo codes expire?"
        )
        scored_value = next(
            check
            for check in result["checks"]
            if check["ruleId"] == "answer-support.values"
        )
        assert scored_value["outcome"] == "breach"
        assert {cite["kind"] for cite in scored_value["citations"]} == {
            "conversation",
            "reference",
        }
        policy_citation = next(
            cite for cite in scored_value["citations"] if cite["kind"] == "reference"
        )
        assert policy_citation["quote"] == reference["quote"]
        assert policy_citation["reference_version"].startswith("review-")
        assert any(
            entry["id"] == policy_citation["reference_id"]
            for entry in manager["references"]
        )
        assert (
            manager["assessmentVersion"]["scoringMethod"]
            == "applicable-points-midpoint-v2"
        )
        assert manager["overallScoring"] == owner.json()["overallScoring"]
        overall = manager["overallScoring"]
        assert overall["profileId"] == "pricing"
        assert overall["profileVersion"].startswith("sha256:")
        assert overall["weights"] == {
            "procedure": 10,
            "completeness": 25,
            "communication-style": 20,
            "answer-support": 45,
        }
        assert overall["score"] is None
        assert "four metric scores" in overall["reason"]
        assert (
            answer_support(
                (
                    await client.get(
                        f"/api/agent/conversations/{early_call}", headers=headers(ALEX)
                    )
                ).json()
            )["score"]
            is None
        )
        # Even approved knowledge is not independent of the calls that supplied it.
        source = answer_support(await analyse(client, sources[0]))
        assert source["score"] is None and source["coverage"] == 0

        # A later import can surface contradictory source calls without changing
        # the approved entry or assessments that have already been stored.
        reimported = await client.post(IMPORT, headers=headers(MAYA))
        assert reimported.status_code == 200, reimported.text
        assert reimported.json()["created"] == 1
        later_call = await add_call(session, data, 213, 14)
        conflicted = answer_support(await analyse(client, later_call))
        assert conflicted["score"] is None and conflicted["coverage"] == 0
        persisted = await client.get(route, headers=headers(ALEX))
        assert answer_support(persisted.json()) == result
