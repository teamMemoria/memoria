"""Business policy checks using only in-memory ports and authored values."""

from dataclasses import replace
from types import SimpleNamespace

import pytest

from backend.entities.assessments import AnalysisRequest, ParsedReport
from backend.entities.errors import ConflictError
from backend.entities.knowledge import (
    DraftDecisionState,
    KnowledgeDecisionRejected,
    KnowledgeInput,
    validate_decision,
)
from backend.entities.reviews import ReviewInput
from backend.use_cases.assessments import AssessmentInteractor
from backend.use_cases.knowledge import KnowledgeInteractor
from backend.use_cases.reviews import ReviewInteractor


class Reviews:
    def __init__(self, existing=None):
        self.value = existing
        self.saved = 0

    async def existing(self):
        return self.value

    async def result(self):
        return self.value

    async def save(self, decision):
        self.saved += 1
        self.value = decision
        return decision, True


async def test_review_is_idempotent_and_conflicts_do_not_write():
    value = ReviewInput("confirmed", None, "Source checked", "Keep it up")
    repository = Reviews()
    interactor = ReviewInteractor()
    assert await interactor.execute(value, repository) == (value, True)
    assert await interactor.execute(value, repository) == (value, False)
    with pytest.raises(ConflictError):
        await interactor.execute(replace(value, reason="Different"), repository)
    assert repository.saved == 1


@pytest.mark.parametrize(
    "change,decision_change,message",
    [
        ({"pending": False}, {}, "already decided"),
        ({}, {"version": "old"}, "Draft changed"),
        ({"reference": None}, {}, "authoritative reference"),
        ({"reference": {"url": "file:///private"}}, {}, "authoritative reference"),
        ({"has_conflict": True}, {}, "conflict"),
        ({"duplicate": True}, {}, "duplicate"),
        (
            {},
            {"verified_reference_url": "https://example.test/wrong"},
            "authoritative reference",
        ),
        ({}, {"outcome": "rejected", "reason": "   "}, "reason"),
        ({}, {"outcome": "unknown"}, "Unknown decision"),
    ],
)
def test_knowledge_gate_without_database(change, decision_change, message):
    state = DraftDecisionState(
        True, "v1", {"url": "https://example.test/reference"}, False, False
    )
    decision = KnowledgeInput("approved", "v1", "https://example.test/reference", None)
    with pytest.raises(KnowledgeDecisionRejected, match=message):
        validate_decision(
            replace(state, **change), replace(decision, **decision_change)
        )


async def test_knowledge_rejection_does_not_require_reference_but_checks_version():
    state = DraftDecisionState(True, "v1", None, True, False)

    class Store:
        def __init__(self):
            self.saved = []

        async def state(self):
            return state

        async def save(self, decision):
            self.saved.append(decision)
            return decision

    repository = Store()
    decision = KnowledgeInput("rejected", "v1", None, "Missing reference")
    assert await KnowledgeInteractor().execute(decision, repository) == decision
    assert repository.saved == [decision]


async def test_assessment_validation_is_required_before_returning():
    calls = []
    request = AnalysisRequest({}, [], [], 1, "2026-11-15", "test")
    parsed = ParsedReport({}, None, None, {"authored": True})

    async def generate(value):
        calls.append(("generate", value))
        return {"candidate": True}

    def parse(value, report):
        calls.append(("parse", report))
        return parsed

    def validate(value, report):
        calls.append(("validate", report))
        raise ValueError("unsupported evidence")

    with pytest.raises(ValueError, match="unsupported evidence"):
        await AssessmentInteractor(generate, parse, validate).execute(request)
    assert [name for name, _ in calls] == ["generate", "parse", "validate"]


async def test_application_settings_own_separate_resources():
    from backend.core.config import Settings
    from backend.main import create_app

    a = create_app(
        settings=Settings(database_url="postgresql+psycopg://test@localhost/first")
    )
    b = create_app(
        settings=Settings(database_url="postgresql+psycopg://test@localhost/second")
    )
    assert a.state.database.engine is not b.state.database.engine
    assert a.state.database.engine.url.database == "first"
    assert b.state.database.engine.url.database == "second"
    assert a.state.analysis.sessions is a.state.database.sessions
    assert b.state.knowledge_import.sessions is b.state.database.sessions
    await a.state.database.close()
    await b.state.database.close()


async def test_http_dependency_uses_request_app_not_legacy_global(monkeypatch):
    from unittest.mock import AsyncMock

    from backend.db import session as legacy

    session = AsyncMock()
    context = AsyncMock()
    context.__aenter__.return_value = session
    monkeypatch.setattr(
        legacy,
        "async_session_factory",
        lambda: (_ for _ in ()).throw(AssertionError("global session used")),
    )
    request = SimpleNamespace(
        app=SimpleNamespace(
            state=SimpleNamespace(database=SimpleNamespace(sessions=lambda: context))
        )
    )
    generator = legacy.get_db_session(request)
    assert await anext(generator) is session
    await generator.aclose()
    context.__aexit__.assert_awaited_once()
