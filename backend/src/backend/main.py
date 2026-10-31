from fastapi import FastAPI

from backend.providers import Providers, create_fixture_providers


def create_app(providers: Providers | None = None) -> FastAPI:
    app = FastAPI(title="Call Assist")
    # Fixture providers until the database providers (#75) are ready.
    app.state.providers = providers or create_fixture_providers()

    @app.get("/health")
    def health():
        return {"status": "ok"}

    return app


app = create_app()
