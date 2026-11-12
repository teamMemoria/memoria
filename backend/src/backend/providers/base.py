from dataclasses import dataclass, field
from typing import Protocol

from backend.core.auth import DEV_IDENTITIES, CurrentUser
from backend.schemas import (
    AgentContext,
    CallReview,
    Conversation,
    KnowledgeEntry,
    ManagerDecision,
    ReviewRequest,
    Viewer,
)
from backend.schemas.knowledge_review import (
    DraftQueueStatus,
    KnowledgeDraft,
    KnowledgeQueueCounts,
    KnowledgeReviewDetail,
)
from backend.schemas.reviews import (
    DecisionInput,
    FindingReviewDetail,
    QueueStatus,
    TeamConversation,
)


class ProviderUnavailableError(Exception):
    """The data source could not be reached. Routes turn this into a 503, not an empty result."""


class RecordNotFoundError(Exception):
    """The record does not exist or is not visible to the requester (a 404)."""


class ConflictError(Exception):
    """The write disagrees with what is already stored (a 409)."""


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


class ReviewProvider(Protocol):
    """A Manager's review queue and decisions, scoped to their organization."""

    async def list_for_manager(
        self,
        organization_id: str,
        manager_id: str,
        status: QueueStatus = "all",
        query: str = "",
    ) -> list[TeamConversation]: ...

    async def get_for_manager(
        self, organization_id: str, manager_id: str, conversation_id: str
    ) -> FindingReviewDetail | None: ...

    async def decide(
        self,
        organization_id: str,
        manager_id: str,
        conversation_id: str,
        finding_id: str,
        decision: DecisionInput,
    ) -> tuple[ManagerDecision, bool]:
        """Record a decision on a review request; returns (decision, created).

        Repeating the same decision returns the stored one with created=False.
        A different decision on an already decided request is a ConflictError.
        """
        ...


class KnowledgeReviewProvider(Protocol):
    """Knowledge drafts for an authorized reviewer (knowledge:approve)."""

    async def list_for_approver(
        self,
        organization_id: str,
        user_id: str,
        status: DraftQueueStatus = "all",
        query: str = "",
        possible_conflicts_only: bool = False,
    ) -> list[KnowledgeDraft]: ...

    async def counts(
        self, organization_id: str, user_id: str
    ) -> KnowledgeQueueCounts: ...

    async def get_for_approver(
        self, organization_id: str, user_id: str, draft_id: str
    ) -> KnowledgeReviewDetail | None: ...


@dataclass(frozen=True)
class Providers:
    viewers: ViewerProvider
    conversations: ConversationProvider
    calls: CallReviewProvider
    knowledge: KnowledgeProvider
    identities: IdentityProvider = field(default_factory=FixtureIdentityProvider)
    # Writes need the database; with fixtures their routes answer 503.
    feedback: FeedbackProvider | None = None
    reviews: ReviewProvider | None = None
    knowledge_review: KnowledgeReviewProvider | None = None
