import hashlib
import json
from dataclasses import replace

import pytest
from backend.api import narration
from backend.core.config import Settings
from backend.main import create_app
from backend.providers import create_fixture_providers
from backend.providers.fixture_data import CALLS, NORTHWIND
from backend.schemas import CallReview
from backend.schemas.reviews import FindingReviewDetail
from backend.services.narration import clip_identity, clip_key, read_clip, text_hash
from fastapi.testclient import TestClient

ALEX = "agent-alex-morgan"
MAYA = "manager-maya-chen"


def store(directory, identity, content=b"ID3-test-generated-narration"):
    key = clip_key(identity)
    (directory / f"{key}.mp3").write_bytes(content)
    (directory / f"{key}.json").write_text(
        json.dumps(
            {"identity": identity, "sha256": hashlib.sha256(content).hexdigest()}
        )
    )
    return content


@pytest.fixture
def setup(tmp_path, monkeypatch):
    monkeypatch.setattr(narration, "DEFAULT_CACHE", tmp_path)
    call = CallReview.model_validate(
        next(c for c in CALLS[NORTHWIND] if c["id"] == "C1042")
    )
    turn = next(t for t in call.transcript.turns if t.speaker == "Agent")
    identity = clip_identity(turn.text, turn.speaker, "am_michael")
    content = store(tmp_path, identity)
    providers = create_fixture_providers()

    class Reviews:
        async def get_for_manager(self, org, user, call_id):
            if org == NORTHWIND and user == MAYA and call_id == call.id:
                return FindingReviewDetail(call=call, can_decide=False)
            return None

    providers = replace(providers, reviews=Reviews())
    client = TestClient(
        create_app(providers=providers, settings=Settings(app_env="test"))
    )
    path = f"/conversations/{call.id}/turns/{turn.number}/narration"
    params = {"voice": "am_michael", "text_sha256": text_hash(turn.text)}
    return client, path, params, content, identity, tmp_path


def test_narration_reuses_agent_and_manager_access(setup):
    client, path, params, content, *_ = setup
    for role, user in [("agent", ALEX), ("manager", MAYA)]:
        result = client.get(
            "/api/" + role + path, params=params, headers={"X-Dev-User": user}
        )
        assert result.status_code == 200
        assert result.content == content
        assert result.headers["content-type"] == "audio/mpeg"
        assert result.headers["cache-control"] == "private, no-store"
        assert result.headers["x-narration-type"] == "synthetic"


@pytest.mark.parametrize("user", ["agent-sam-rivera", "agent-riley-chen"])
def test_other_agents_and_organizations_cannot_read_audio(setup, user):
    client, path, params, *_ = setup
    assert (
        client.get(
            "/api/agent" + path, params=params, headers={"X-Dev-User": user}
        ).status_code
        == 404
    )
    assert (
        client.get(
            "/api/manager" + path, params=params, headers={"X-Dev-User": user}
        ).status_code
        == 403
    )


def test_stale_text_wrong_role_missing_and_corrupt_clips_fail_closed(setup):
    client, path, params, _, identity, directory = setup

    def get(p):
        return client.get("/api/agent" + path, params=p, headers={"X-Dev-User": ALEX})

    assert (
        get({**params, "text_sha256": text_hash("different words")}).status_code == 409
    )
    assert get({**params, "voice": "af_heart"}).status_code == 422
    assert get({**params, "voice": "af_bella"}).status_code == 503
    (directory / f"{clip_key(identity)}.mp3").write_bytes(b"wrong audio")
    assert get(params).status_code == 503


def test_unknown_turn_and_no_identity_do_not_expose_audio(setup):
    client, path, params, *_ = setup
    assert client.get("/api/agent" + path, params=params).status_code == 401
    missing = path.split("/turns/")[0] + "/turns/999/narration"
    assert (
        client.get(
            "/api/agent" + missing, params=params, headers={"X-Dev-User": ALEX}
        ).status_code
        == 404
    )


def test_cache_identity_covers_exact_unicode_text_role_voice_and_recipe(tmp_path):
    identity = clip_identity("Thanks, [PERSON_1] — café.", "Agent", "am_michael")
    content = store(tmp_path, identity)
    assert read_clip(tmp_path, identity) == content
    for changed in [
        dict(identity, text="Thanks."),
        dict(identity, voice="af_bella"),
        dict(identity, recipe={}),
    ]:
        assert clip_key(changed) != clip_key(identity)
        assert read_clip(tmp_path, changed) is None
    for role in ["System action", "Unknown"]:
        with pytest.raises(ValueError):
            clip_identity("Some action", role, "am_michael")
