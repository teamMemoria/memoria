from dataclasses import dataclass

from backend.providers.base import Providers
from backend.providers.fixture_data import CALLS, CONVERSATIONS, KNOWLEDGE, VIEWERS
from backend.schemas import (
    CallReview,
    Conversation,
    DemoProfile,
    KnowledgeEntry,
    Viewer,
)


@dataclass(frozen=True)
class FixtureData:
    """Validated fixture records, keyed by organization ID."""

    viewers: dict[str, list[Viewer]]
    conversations: dict[str, list[Conversation]]
    calls: dict[str, list[CallReview]]
    knowledge: dict[str, list[KnowledgeEntry]]


def load_fixture_data() -> FixtureData:
    """Validate the raw fixtures against the response schemas. Fails loudly on any mismatch."""

    def load(model, raw):
        return {
            org: [model.model_validate(item) for item in items]
            for org, items in raw.items()
        }

    return FixtureData(
        viewers=load(Viewer, VIEWERS),
        conversations=load(Conversation, CONVERSATIONS),
        calls=load(CallReview, CALLS),
        knowledge=load(KnowledgeEntry, KNOWLEDGE),
    )


# Each method returns copies so a caller can never change the shared fixtures.


class FixtureViewerProvider:
    def __init__(self, data: FixtureData):
        self._data = data

    async def get_viewer(self, organization_id, user_id):
        for viewer in self._data.viewers.get(organization_id, []):
            if viewer.id == user_id:
                return viewer.model_copy(deep=True)
        return None


class FixtureDemoProfileProvider:
    """Every fixture viewer, so each one can be picked on the entry screen."""

    def __init__(self, data: FixtureData):
        self._data = data

    async def list_profiles(self):
        profiles = []
        for organization_id, viewers in self._data.viewers.items():
            conversations = self._data.conversations.get(organization_id, [])
            for viewer in viewers:
                count = None
                if viewer.role == "agent":
                    count = sum(1 for c in conversations if c.agent_id == viewer.id)
                profiles.append(
                    DemoProfile(
                        id=viewer.id,
                        display_name=viewer.display_name,
                        role=viewer.role,
                        conversation_count=count,
                    )
                )
        return profiles


class FixtureConversationProvider:
    def __init__(self, data: FixtureData):
        self._data = data

    async def list_for_agent(self, organization_id, agent_id):
        conversations = [
            conversation.model_copy(deep=True)
            for conversation in self._data.conversations.get(organization_id, [])
            if conversation.agent_id == agent_id
        ]
        # Newest first, same order as getAgentConversations in the frontend.
        # Undated conversations go last.
        return sorted(
            conversations,
            key=lambda conversation: (
                conversation.date is not None,
                conversation.date or "",
            ),
            reverse=True,
        )


class FixtureCallReviewProvider:
    def __init__(self, data: FixtureData):
        self._data = data

    async def get_for_agent(self, organization_id, agent_id, conversation_id):
        for call in self._data.calls.get(organization_id, []):
            if call.id == conversation_id and call.agent_id == agent_id:
                return call.model_copy(deep=True)
        return None


class FixtureKnowledgeProvider:
    def __init__(self, data: FixtureData):
        self._data = data

    async def list_for_agent(self, organization_id, agent_id):
        return [
            entry.model_copy(deep=True)
            for entry in self._data.knowledge.get(organization_id, [])
            if entry.readable_by(agent_id)
        ]

    async def get_for_agent(self, organization_id, agent_id, entry_id):
        # Uses the same rule as the list, so a direct request cannot reach a hidden entry.
        for entry in await self.list_for_agent(organization_id, agent_id):
            if entry.id == entry_id:
                return entry
        return None


def create_fixture_providers(data: FixtureData | None = None) -> Providers:
    data = data or load_fixture_data()
    return Providers(
        viewers=FixtureViewerProvider(data),
        conversations=FixtureConversationProvider(data),
        calls=FixtureCallReviewProvider(data),
        knowledge=FixtureKnowledgeProvider(data),
        demo_profiles=FixtureDemoProfileProvider(data),
    )
