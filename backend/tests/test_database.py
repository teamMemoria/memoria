import logging
from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.exc import OperationalError
from sqlalchemy.sql.elements import TextClause

from backend.core.config import Settings
from backend.db import session as session_module
from backend.db.session import get_db_session
from backend.main import app


def test_settings_reads_database_url_from_environment(monkeypatch):
    database_url = "postgresql+psycopg://user:password@database:5432/memoria"
    monkeypatch.setenv("DATABASE_URL", database_url)

    assert Settings().database_url == database_url


def test_readiness_executes_select_one():
    session = AsyncMock()

    async def override_db_session():
        yield session

    app.dependency_overrides[get_db_session] = override_db_session
    try:
        response = TestClient(app).get("/ready")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.json() == {"status": "ready"}
    statement = session.execute.await_args.args[0]
    assert isinstance(statement, TextClause)
    assert str(statement) == "SELECT 1"


@pytest.mark.asyncio
async def test_session_dependency_closes_session(monkeypatch):
    session = AsyncMock()
    session_context = AsyncMock()
    session_context.__aenter__.return_value = session

    monkeypatch.setattr(
        session_module,
        "async_session_factory",
        lambda: session_context,
    )

    dependency = get_db_session()
    yielded_session = await anext(dependency)
    await dependency.aclose()

    assert yielded_session is session
    session_context.__aexit__.assert_awaited_once()


@pytest.mark.asyncio
async def test_session_dependency_closes_session_after_error(monkeypatch):
    session_context = AsyncMock()

    monkeypatch.setattr(
        session_module,
        "async_session_factory",
        lambda: session_context,
    )

    dependency = get_db_session()
    await anext(dependency)

    with pytest.raises(RuntimeError, match="request failed"):
        await dependency.athrow(RuntimeError("request failed"))

    session_context.__aexit__.assert_awaited_once()


def test_readiness_returns_503_without_traceback_when_database_is_down(caplog):
    session = AsyncMock()
    session.execute.side_effect = OperationalError(
        "SELECT 1", {}, Exception("connection refused\nsecond line")
    )

    async def override_db_session():
        yield session

    app.dependency_overrides[get_db_session] = override_db_session
    try:
        with caplog.at_level(logging.WARNING, logger="backend.main"):
            response = TestClient(app, raise_server_exceptions=False).get("/ready")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 503
    assert response.json() == {"detail": "database unavailable"}
    records = [r for r in caplog.records if r.name == "backend.main"]
    assert len(records) == 1
    assert records[0].getMessage() == (
        "Readiness check failed: Exception: connection refused"
    )
    assert records[0].exc_info is None
    assert "Traceback" not in caplog.text


def test_app_shutdown_disposes_the_engine(monkeypatch):
    engine = AsyncMock()
    monkeypatch.setattr(session_module, "engine", engine)

    with TestClient(app) as client:
        assert client.get("/health").status_code == 200
        engine.dispose.assert_not_awaited()

    engine.dispose.assert_awaited_once()
