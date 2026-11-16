from dataclasses import replace
from types import SimpleNamespace

import pytest

from backend.entities.errors import ConflictError
from backend.entities.reviews import ReviewInput
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
