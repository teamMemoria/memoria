import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Annotated

from fastapi import Depends, FastAPI, HTTPException, Request, status
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from backend.api import analysis as analysis_api
from backend.api import (
    calls,
    conversations,
    demo,
    knowledge,
    knowledge_review,
    reviews,
    viewer,
)
from backend.core.config import Settings
from backend.db import session as db_session
from backend.db.session import get_db_session
from backend.providers import (
    Providers,
    ProviderUnavailableError,
    create_fixture_providers,
)
from backend.providers.database import create_database_providers
from backend.services.analysis import AnalysisService
from backend.services.knowledge_import import KnowledgeImportService

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    yield
    # Close pooled connections so reloads and test runs don't leak them.
    await db_session.engine.dispose()


def create_app(
    providers: Providers | None = None,
    settings: Settings | None = None,
    analysis: AnalysisService | None = None,
    knowledge_import: KnowledgeImportService | None = None,
) -> FastAPI:
    app = FastAPI(title="Call Assist", lifespan=lifespan)
    settings = settings or Settings()
    if providers is None:
        providers = (
            create_database_providers(db_session.async_session_factory)
            if settings.data_source == "database"
            else create_fixture_providers()
        )
    app.state.providers = providers
    app.state.settings = settings
    # Analysis always reads and writes PostgreSQL; tests inject their own adapter.
    if analysis is None and settings.analysis_engine == "rules":
        from backend.services.rule_assessment import LocalRuleAdapter, load_rule_context

        analysis = AnalysisService(
            db_session.async_session_factory,
            adapter=LocalRuleAdapter(),
            scoring_context=load_rule_context(),
        )
    app.state.analysis = analysis or AnalysisService(db_session.async_session_factory)
    if knowledge_import is None and settings.knowledge_engine == "rules":
        import json
        from pathlib import Path

        from ml.knowledge_candidates import generate_candidates

        cohort = json.loads(
            (Path(__file__).resolve().parents[3] / "ml/rule_cohort.json").read_text()
        )
        knowledge_import = KnowledgeImportService(
            db_session.async_session_factory,
            generate=generate_candidates,
            source_ids=tuple(row["id"] for row in cohort["conversations"]),
        )
    app.state.knowledge_import = knowledge_import or KnowledgeImportService(
        db_session.async_session_factory
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
