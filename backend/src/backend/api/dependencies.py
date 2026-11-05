from typing import Annotated

from fastapi import Depends, Request

from backend.providers import Providers


def get_providers(request: Request) -> Providers:
    """The providers the app was started with. Tests override this to inject their own."""
    return request.app.state.providers


ProvidersDep = Annotated[Providers, Depends(get_providers)]
