"""Legacy database imports, resolved lazily."""

from backend.db.session import get_db_session

__all__ = ["async_session_factory", "engine", "get_db_session"]


def __getattr__(name):
    from backend.db import session

    return getattr(session, name)
