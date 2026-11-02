"""Replaceable data providers for the read APIs.

Routes depend on the interfaces in ``base``. The fixture implementation lets the
API run without PostgreSQL or ML; ``database`` reads the same records from
PostgreSQL. Routes cannot tell them apart.
"""

from backend.providers.base import (
    CallReviewProvider,
    ConversationProvider,
    FeedbackProvider,
    FixtureIdentityProvider,
    IdentityProvider,
    KnowledgeProvider,
    Providers,
    ProviderUnavailableError,
    RecordNotFoundError,
    ViewerProvider,
)
from backend.providers.fixtures import create_fixture_providers

__all__ = [
    "CallReviewProvider",
    "ConversationProvider",
    "FeedbackProvider",
    "FixtureIdentityProvider",
    "IdentityProvider",
    "KnowledgeProvider",
    "ProviderUnavailableError",
    "Providers",
    "RecordNotFoundError",
    "ViewerProvider",
    "create_fixture_providers",
]
