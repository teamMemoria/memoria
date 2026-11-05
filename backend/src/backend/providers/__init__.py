"""Replaceable data providers for the read APIs.

Routes depend on the interfaces in ``base``; the fixture implementation lets the
API run without PostgreSQL or ML. A database implementation (#75) can replace it
without touching the routes.
"""

from backend.providers.base import (
    CallReviewProvider,
    ConversationProvider,
    KnowledgeProvider,
    Providers,
    ProviderUnavailableError,
    ViewerProvider,
)
from backend.providers.fixtures import create_fixture_providers

__all__ = [
    "CallReviewProvider",
    "ConversationProvider",
    "KnowledgeProvider",
    "ProviderUnavailableError",
    "Providers",
    "ViewerProvider",
    "create_fixture_providers",
]
