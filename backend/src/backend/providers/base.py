from dataclasses import dataclass
from typing import Protocol

from backend.schemas import CallReview, Conversation, KnowledgeEntry, Viewer


class ProviderUnavailableError(Exception):
    """The data source could not be reached. Routes turn this into a 503, not an empty result."""


# Every read is scoped to one organization. Methods mirror the frontend's
# ViewerApi, ConversationsApi, CallApi and ApprovedKnowledgeApi, and return None
# when the record does not exist or is not visible to that agent.


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


@dataclass(frozen=True)
class Providers:
    viewers: ViewerProvider
    conversations: ConversationProvider
    calls: CallReviewProvider
    knowledge: KnowledgeProvider
