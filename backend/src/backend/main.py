import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Annotated

from fastapi import Depends, FastAPI, HTTPException, status
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from backend.db import session as db_session
from backend.db.session import get_db_session

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    yield
    # Close pooled connections so reloads and test runs don't leak them.
    await db_session.engine.dispose()


app = FastAPI(title="Call Assist", lifespan=lifespan)


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/ready")
async def readiness(
    session: Annotated[AsyncSession, Depends(get_db_session)],
):
    try:
        await session.execute(text("SELECT 1"))
    except SQLAlchemyError as exc:
        # Probes call this often while the database is down; one line is
        # enough, a full traceback on every probe just floods the logs.
        logger.warning("Readiness check failed: %s", _first_line(exc))
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="database unavailable",
        ) from None
    return {"status": "ready"}


def _first_line(exc: SQLAlchemyError) -> str:
    cause = getattr(exc, "orig", None) or exc
    lines = str(cause).strip().splitlines()
    return f"{type(cause).__name__}: {lines[0] if lines else ''}"
