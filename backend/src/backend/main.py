from typing import Annotated

from fastapi import Depends, FastAPI
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from backend.db.session import get_db_session

app = FastAPI(title="Call Assist")


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/ready")
async def readiness(
    session: Annotated[AsyncSession, Depends(get_db_session)],
):
    await session.execute(text("SELECT 1"))
    return {"status": "ready"}
