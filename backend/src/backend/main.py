from fastapi import FastAPI, Request, status
from fastapi.responses import JSONResponse

from backend.api import conversations, viewer
from backend.core.config import Settings
from backend.providers import (
    Providers,
    ProviderUnavailableError,
    create_fixture_providers,
)


def create_app(
    providers: Providers | None = None, settings: Settings | None = None
) -> FastAPI:
    app = FastAPI(title="Call Assist")
    # Fixture providers until the database providers (#75) are ready.
    app.state.providers = providers or create_fixture_providers()
    app.state.settings = settings or Settings()

    @app.exception_handler(ProviderUnavailableError)
    async def provider_unavailable(request: Request, exc: ProviderUnavailableError):
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content={"detail": "Data source unavailable"},
        )

    @app.get("/health")
    def health():
        return {"status": "ok"}

    app.include_router(viewer.router)
    app.include_router(conversations.router)
    return app


app = create_app()
