from typing import Annotated

from fastapi import Depends, FastAPI
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from backend.db.session import get_db_session
from backend.providers import Providers, create_fixture_providers


def create_app(providers: Providers | None = None) -> FastAPI:
    app = FastAPI(title="Call Assist")
    # Fixture providers until the database providers (#75) are ready.
    app.state.providers = providers or create_fixture_providers()

    @app.get("/health")
    def health():
        return {"status": "ok"}

    @app.get("/ready")
    async def readiness(
        session: Annotated[AsyncSession, Depends(get_db_session)],
    ):
        await session.execute(text("SELECT 1"))
        return {"status": "ready"}

    return app


app = create_app()
