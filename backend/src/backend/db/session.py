"""Legacy session API. HTTP requests always use their own application's resources."""

from collections.abc import AsyncIterator

from fastapi import Request
from sqlalchemy.ext.asyncio import AsyncSession

from backend.frameworks.database.session import create_database

_legacy_database = None


def __getattr__(name):
    # Older CLI callers may still import these names. No resource is constructed
    # until that compatibility API is actually requested.
    global _legacy_database
    if name not in {"engine", "async_session_factory"}:
        raise AttributeError(name)
    if _legacy_database is None:
        from backend.core.config import get_settings

        _legacy_database = create_database(get_settings().database_url)
    return _legacy_database.engine if name == "engine" else _legacy_database.sessions


async def get_db_session(request: Request = None) -> AsyncIterator[AsyncSession]:
    if request is not None:
        sessions = request.app.state.database.sessions
    else:
        # Retain direct generator callers and dependency overrides.
        sessions = globals().get("async_session_factory") or __getattr__(
            "async_session_factory"
        )
    async with sessions() as session:
        yield session
