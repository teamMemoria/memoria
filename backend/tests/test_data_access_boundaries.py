"""SQL adapters implement the existing outward-facing ports."""

from backend.frameworks.data_access.database import create_database_providers
from backend.interface_adapters.ports import (
    CallReviewProvider,
    ConversationProvider,
    DemoProfileProvider,
    FeedbackProvider,
    IdentityProvider,
    KnowledgeProvider,
    KnowledgeReviewProvider,
    ReviewProvider,
    ViewerProvider,
)
from backend.interface_adapters.presenters.profiles import demo_profile, viewer


def test_database_adapters_implement_their_ports_without_opening_a_database():
    providers = create_database_providers(lambda: None)
    contracts = {
        "identities": IdentityProvider,
        "demo_profiles": DemoProfileProvider,
        "viewers": ViewerProvider,
        "conversations": ConversationProvider,
        "calls": CallReviewProvider,
        "knowledge": KnowledgeProvider,
        "feedback": FeedbackProvider,
        "reviews": ReviewProvider,
        "knowledge_review": KnowledgeReviewProvider,
    }
    for name, contract in contracts.items():
        assert isinstance(getattr(providers, name), contract), name


def test_profile_presenters_preserve_the_existing_response_values():
    agent = demo_profile("agent-1", "Alex", True, 3)
    manager = demo_profile("manager-1", "Maya", False, 0)
    identity = viewer("agent-1", "Alex", True)

    assert (agent.id, agent.display_name, agent.role, agent.conversation_count) == (
        "agent-1",
        "Alex",
        "agent",
        3,
    )
    assert (manager.role, manager.conversation_count) == ("manager", None)
    assert (identity.id, identity.display_name, identity.role) == (
        "agent-1",
        "Alex",
        "agent",
    )
