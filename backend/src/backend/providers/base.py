from dataclasses import dataclass, field
from typing import Protocol

from backend.core.auth import DEV_IDENTITIES, CurrentUser
from backend.schemas import (
    AgentContext,
    CallReview,
    Conversation,
    KnowledgeEntry,
    ReviewRequest,
    Viewer,
)


class ProviderUnavailableError(Exception):
    """The data source could not be reached. Routes turn this into a 503, not an empty result."""


class RecordNotFoundError(Exception):
    """The record does not exist or is not visible to the requester (a 404)."""


# Every read is scoped to one organization. Methods mirror the frontend's
# ViewerApi, ConversationsApi, CallApi and ApprovedKnowledgeApi, and return None
# when the record does not exist or is not visible to that agent.


class IdentityProvider(Protocol):
    async def resolve(
        self, subject: str, organization_id: str | None = None
    ) -> CurrentUser | None:
        """The requester's organization and permissions, or None if unknown.

        ``subject`` is a user ID that has already been authenticated; this only
        looks up what that user may do. ``organization_id`` picks one of the
        user's own memberships when they belong to more than one organization.
        """
        ...


class FixtureIdentityProvider:
    """The fixed development identities in backend.core.auth."""

    async def resolve(self, subject, organization_id=None):
        user = DEV_IDENTITIES.get(subject)
        if user is None or organization_id not in (None, user.organization_id):
            return None
        return user


class ViewerProvider(Protocol):
    async def get_viewer(self, organization_id: str, user_id: str) -> Viewer | None: ...


class ConversationProvider(Protocol):
    async def list_for_agent(
        self, organization_id: str, agent_id: str
    ) -> list[Conversation]: ...


class CallReviewProvider(Protocol):
    async def get_for_agent(
        self, organization_id: str, agent_id: str, conversation_id: str
    ) -> CallReview | None: ...


class KnowledgeProvider(Protocol):
    async def list_for_agent(
        self, organization_id: str, agent_id: str
    ) -> list[KnowledgeEntry]: ...

    async def get_for_agent(
        self, organization_id: str, agent_id: str, entry_id: str
    ) -> KnowledgeEntry | None: ...


class FeedbackProvider(Protocol):
    """An agent's own writes on their calls."""

    async def save_context(
        self, organization_id: str, agent_id: str, conversation_id: str, text: str
    ) -> AgentContext:
        """Save the agent's note on a call. Never creates a review request."""
        ...

    async def request_review(
        self,
        organization_id: str,
        agent_id: str,
        conversation_id: str,
        finding_id: str,
        reason: str,
    ) -> tuple[ReviewRequest, bool]:
        """Ask a Manager to review one finding; returns (request, created).

        A finding has at most one review request. Asking again returns the
        existing one unchanged with created=False.
        """
        ...


@dataclass(frozen=True)
class Providers:
    viewers: ViewerProvider
    conversations: ConversationProvider
    calls: CallReviewProvider
    knowledge: KnowledgeProvider
    identities: IdentityProvider = field(default_factory=FixtureIdentityProvider)
    # Writes need the database; with fixtures their routes answer 503.
    feedback: FeedbackProvider | None = None
