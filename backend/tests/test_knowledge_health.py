from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError
from sqlalchemy.exc import IntegrityError

from backend.core.config import Settings
from backend.frameworks.data_access.knowledge_health import (
    find_stale_entries,
    find_supported_conflicts,
    mark_topic_disputed,
    resolve_knowledge_conflict,
)
from backend.frameworks.database.models import (
    Agent,
    Conversation,
    DraftStatus,
    KnowledgeConflict,
    KnowledgeDraft,
    KnowledgeEntry,
    KnowledgeReview,
    Organization,
    OrganizationMembership,
    ReviewAction,
    Topic,
    User,
    UserRole,
)

NOW = datetime(2026, 11, 17, 12, tzinfo=UTC)


@pytest.fixture
async def health(session):
    org = Organization(slug="health", name="Health")
    topic = Topic(organization=org, source_dataset="test", name="Delivery")
    manager = OrganizationMembership(
        organization=org,
        user=User(external_id="health-manager", display_name="Manager"),
        role=UserRole.MANAGER,
    )
    original = KnowledgeDraft(
        organization=org,
        topic=topic,
        answer_text="Old policy",
        status=DraftStatus.APPROVED,
    )
    entry = KnowledgeEntry(
        organization=org,
        topic=topic,
        answer_text="Old policy",
        approved_review=KnowledgeReview(
            organization=org,
            draft=original,
            reviewer_membership=manager,
            action=ReviewAction.APPROVED,
            reviewed_at=NOW - timedelta(days=90),
        ),
    )
    draft = KnowledgeDraft(
        organization=org,
        topic=topic,
        answer_text="New policy",
        supporting_conversations=[],
    )
    agent = Agent(organization=org, external_id="health-agent")
    session.add_all([entry, draft, agent])
    await session.flush()
    conflict = KnowledgeConflict(
        organization_id=org.id,
        source_key="delivery",
        kind="conflict",
        status="possible_conflict",
        explanation="Policies disagree",
        draft_id=draft.id,
        other_entry_id=entry.id,
    )
    session.add(conflict)
    await session.flush()
    return org, topic, manager, entry, draft, agent, conflict


async def add_support(session, health, days):
    org, topic, _, _, draft, agent, _ = health
    calls = [
        Conversation(
            organization=org,
            agent=agent,
            topic=topic,
            channel="voice",
            source_dataset="test",
            original_id=f"health-{index}",
            synthetic_started_at=NOW - timedelta(days=day),
        )
        for index, day in enumerate(days)
    ]
    draft.supporting_conversations = calls
    await session.flush()


async def test_conflict_counts_only_recent_distinct_calls_and_links_right_entry(
    session, health
):
    org, _, _, entry, draft, _, conflict = health
    await add_support(session, health, [0, 1, 2, 29, 30, 31, -1])
    rows = await find_supported_conflicts(session, organization_id=org.id, now=NOW)
    assert len(rows) == 1
    assert (
        rows[0].conflict_id,
        rows[0].draft_id,
        rows[0].entry_id,
        rows[0].recent_calls,
        rows[0].threshold,
    ) == (
        conflict.id,
        draft.id,
        entry.id,
        5,
        5,
    )
    assert not await find_supported_conflicts(
        session,
        organization_id=org.id,
        now=NOW,
        settings=Settings(knowledge_draft_threshold=11),
    )
    assert not await find_supported_conflicts(
        session,
        organization_id=org.id,
        now=NOW,
        settings=Settings(knowledge_recent_call_days=1),
    )
    assert await find_supported_conflicts(
        session,
        organization_id=org.id,
        now=NOW,
        settings=Settings(knowledge_conflict_threshold_override=2),
    )
    assert not await find_supported_conflicts(
        session, organization_id=org.id + 10000, now=NOW
    )
    draft.status = DraftStatus.REJECTED
    await session.flush()
    assert not await find_supported_conflicts(session, organization_id=org.id, now=NOW)


async def test_staleness_uses_confirmation_or_approval_and_configurable_window(
    session, health
):
    org, _, _, entry, *_ = health
    assert await find_stale_entries(session, organization_id=org.id, now=NOW) == [entry]
    entry.last_confirmed_at = NOW - timedelta(days=60)
    await session.flush()
    assert not await find_stale_entries(session, organization_id=org.id, now=NOW)
    assert await find_stale_entries(
        session,
        organization_id=org.id,
        now=NOW,
        settings=Settings(knowledge_stale_entry_days=59),
    ) == [entry]
    entry.last_confirmed_at = NOW - timedelta(days=1)
    await session.flush()
    assert not await find_stale_entries(session, organization_id=org.id, now=NOW)
    assert not await find_stale_entries(
        session, organization_id=org.id + 10000, now=NOW
    )


async def test_explicit_dispute_and_resolution_keep_history(session, health):
    org, topic, manager, _, _, _, conflict = health
    assert not topic.disputed
    await mark_topic_disputed(session, manager, topic_id=topic.id)
    assert topic.disputed
    await resolve_knowledge_conflict(session, manager, conflict_id=conflict.id, now=NOW)
    assert conflict.lifecycle_status == "resolved" and conflict.resolved_at == NOW
    assert not topic.disputed
    assert conflict.created_at is not None
    assert await session.get(KnowledgeConflict, conflict.id) is conflict
    assert not await find_supported_conflicts(session, organization_id=org.id, now=NOW)
    await resolve_knowledge_conflict(
        session, manager, conflict_id=conflict.id, now=NOW + timedelta(days=1)
    )
    assert conflict.resolved_at == NOW


async def test_dispute_remains_until_all_conflicts_are_resolved(session, health):
    org, topic, manager, entry, draft, _, conflict = health
    another = KnowledgeConflict(
        organization_id=org.id,
        source_key="another",
        kind="conflict",
        status="unresolved",
        explanation="Another disagreement",
        draft_id=draft.id,
        other_entry_id=entry.id,
    )
    session.add(another)
    await session.flush()
    await mark_topic_disputed(session, manager, topic_id=topic.id)
    await resolve_knowledge_conflict(session, manager, conflict_id=conflict.id, now=NOW)
    assert topic.disputed
    await resolve_knowledge_conflict(session, manager, conflict_id=another.id, now=NOW)
    assert not topic.disputed


async def test_dispute_actions_require_reviewer_and_organization_scope(session, health):
    _org, topic, manager, *_ = health
    manager.role = UserRole.AGENT
    with pytest.raises(PermissionError):
        await mark_topic_disputed(session, manager, topic_id=topic.id)
    manager.role = UserRole.MANAGER
    with pytest.raises(ValueError, match="organization"):
        await mark_topic_disputed(session, manager, topic_id=topic.id + 10000)
    with pytest.raises(ValueError, match="organization"):
        await resolve_knowledge_conflict(session, manager, conflict_id=1000000, now=NOW)


async def test_invalid_conflict_lifecycle_is_rejected(session, health):
    *_, conflict = health
    conflict.lifecycle_status = "resolved"
    with pytest.raises(IntegrityError):
        await session.flush()


def test_health_settings_defaults_derivation_and_environment(monkeypatch):
    settings = Settings(_env_file=None)
    assert (
        settings.knowledge_draft_threshold,
        settings.knowledge_conflict_threshold,
        settings.knowledge_recent_call_days,
        settings.knowledge_stale_entry_days,
    ) == (10, 5, 30, 60)
    monkeypatch.setenv("KNOWLEDGE_DRAFT_THRESHOLD", "11")
    assert Settings().knowledge_conflict_threshold == 6
    monkeypatch.setenv("KNOWLEDGE_CONFLICT_THRESHOLD_OVERRIDE", "3")
    monkeypatch.setenv("KNOWLEDGE_RECENT_CALL_DAYS", "14")
    monkeypatch.setenv("KNOWLEDGE_STALE_ENTRY_DAYS", "45")
    configured = Settings()
    assert (
        configured.knowledge_conflict_threshold,
        configured.knowledge_recent_call_days,
        configured.knowledge_stale_entry_days,
    ) == (3, 14, 45)
    with pytest.raises(ValidationError):
        Settings(knowledge_recent_call_days=0)
