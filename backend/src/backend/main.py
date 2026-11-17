import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Annotated

from fastapi import Depends, FastAPI, HTTPException, Request, status
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.config import Settings
from backend.db.session import get_db_session
from backend.frameworks.data_access.analysis import AnalysisRunsAdapter, AnalysisService
from backend.frameworks.data_access.database import create_database_providers
from backend.frameworks.data_access.knowledge_import import KnowledgeImportService
from backend.frameworks.database.session import create_database
from backend.frameworks.http import analysis as analysis_api
from backend.frameworks.http import (
    calls,
    conversations,
    demo,
    knowledge,
    knowledge_review,
    narration,
    reviews,
    viewer,
)
from backend.providers import (
    Providers,
    ProviderUnavailableError,
)
from backend.use_cases.assessment_runs import AssessmentRunsInteractor

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    try:
        yield
    finally:
        await app.state.database.close()


def create_app(
    providers: Providers | None = None,
    settings: Settings | None = None,
    analysis: AnalysisService | None = None,
    knowledge_import: KnowledgeImportService | None = None,
) -> FastAPI:
    app = FastAPI(title="Call Assist", lifespan=lifespan)
    settings = settings or Settings()
    database = create_database(settings.database_url)
    app.state.database = database
    if providers is None:
        providers = create_database_providers(database.sessions)
    app.state.providers = providers
    app.state.settings = settings
    # Analysis always reads and writes PostgreSQL; tests inject their own adapter.
    app.state.analysis = analysis or AnalysisService(database.sessions)
    app.state.assessment_runs = AssessmentRunsInteractor(
        AnalysisRunsAdapter(app.state.analysis)
    )
    app.state.knowledge_import = knowledge_import or KnowledgeImportService(
        database.sessions
    )

    @app.exception_handler(ProviderUnavailableError)
    async def provider_unavailable(request: Request, exc: ProviderUnavailableError):
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content={"detail": "Data source unavailable"},
        )

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

    app.include_router(demo.router)
    app.include_router(viewer.router)
    app.include_router(conversations.router)
    app.include_router(calls.router)
    app.include_router(narration.router)
    app.include_router(knowledge.router)
    app.include_router(analysis_api.router)
    app.include_router(reviews.router)
    app.include_router(knowledge_review.router)
    return app


def _first_line(exc: SQLAlchemyError) -> str:
    cause = getattr(exc, "orig", None) or exc
    lines = str(cause).strip().splitlines()
    return f"{type(cause).__name__}: {lines[0] if lines else ''}"


app = create_app()
