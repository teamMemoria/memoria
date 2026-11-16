from types import SimpleNamespace


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
