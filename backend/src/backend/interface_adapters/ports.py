from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable

from backend.entities.identity import DEV_IDENTITIES, CurrentUser
from backend.entities.progress import DateRange, ProgressPeriod
from backend.errors import (
    ConflictError,
    ProviderUnavailableError,
    RecordNotFoundError,
)
from backend.schemas import (
    AgentContext,
    CallReview,
    Conversation,
    DemoProfile,
    KnowledgeEntry,
    ReviewRequest,
    Viewer,
)
from backend.schemas.knowledge_review import (
    DraftQueueStatus,
    KnowledgeDecisionInput,
    KnowledgeDraft,
    KnowledgeQueueCounts,
    KnowledgeReviewDetail,
)
from backend.schemas.progress import AgentProgress
from backend.schemas.reviews import (
    FindingReviewDetail,
    QueueStatus,
    TeamConversation,
)
from backend.use_cases.record_review_decision import ReviewDecisionRepository

# Every read is scoped to one organization. Methods mirror the frontend's
# ViewerApi, ConversationsApi, CallApi and ApprovedKnowledgeApi, and return None
# when the record does not exist or is not visible to that agent.


@runtime_checkable
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
    """The fixed development identities in backend.entities.identity."""

    async def resolve(self, subject, organization_id=None):
        user = DEV_IDENTITIES.get(subject)
        if user is None or organization_id not in (None, user.organization_id):
            return None
        return user


@runtime_checkable
class DemoProfileProvider(Protocol):
    async def list_profiles(self) -> list[DemoProfile]:
        """Profiles the demo entry screen offers. Only served in development and test."""
        ...


@runtime_checkable
class ViewerProvider(Protocol):
    async def get_viewer(self, organization_id: str, user_id: str) -> Viewer | None: ...


@runtime_checkable
class ConversationProvider(Protocol):
    async def list_for_agent(
        self, organization_id: str, agent_id: str
    ) -> list[Conversation]: ...


@runtime_checkable
class CallReviewProvider(Protocol):
    async def get_for_agent(
        self, organization_id: str, agent_id: str, conversation_id: str
    ) -> CallReview | None: ...


@runtime_checkable
class KnowledgeProvider(Protocol):
    async def list_for_agent(
        self, organization_id: str, agent_id: str
    ) -> list[KnowledgeEntry]: ...

    async def get_for_agent(
        self, organization_id: str, agent_id: str, entry_id: str
    ) -> KnowledgeEntry | None: ...


@runtime_checkable
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


@runtime_checkable
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

    def decision_repository(
        self,
        organization_id: str,
        manager_id: str,
        conversation_id: str,
        finding_id: str,
    ) -> AbstractAsyncContextManager[ReviewDecisionRepository]: ...


@runtime_checkable
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

    async def decide(
        self,
        organization_id: str,
        user_id: str,
        draft_id: str,
        outcome: str,
        decision: KnowledgeDecisionInput,
    ) -> KnowledgeDraft: ...


@runtime_checkable
class ProgressProvider(Protocol):
    """An agent's results over time. None when the agent is not visible."""

    async def for_agent(
        self,
        organization_id: str,
        user_id: str,
        dates: DateRange,
        period: ProgressPeriod,
    ) -> AgentProgress | None:
        """The requester's own progress; None unless they are an agent."""
        ...

    async def for_manager(
        self,
        organization_id: str,
        manager_id: str,
        agent_id: str,
        dates: DateRange,
        period: ProgressPeriod,
    ) -> AgentProgress | None:
        """Any agent's progress in the Manager's own organization."""
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
    reviews: ReviewProvider | None = None
    knowledge_review: KnowledgeReviewProvider | None = None
    demo_profiles: DemoProfileProvider | None = None
    progress: ProgressProvider | None = None


__all__ = ["ConflictError", "ProviderUnavailableError", "RecordNotFoundError"]
