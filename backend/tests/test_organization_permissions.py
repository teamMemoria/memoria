import pytest
from sqlalchemy.exc import IntegrityError

from backend.models import (
    Agent,
    Audit,
    Conversation,
    FeedbackFlag,
    Finding,
    FindingCategory,
    FindingResult,
    KnowledgeDraft,
    KnowledgeEntry,
    KnowledgeReview,
    ManagerReview,
    ManagerReviewOutcome,
    Organization,
    OrganizationMembership,
    ReviewAction,
    Topic,
    User,
    UserRole,
)
from backend.services.feedback_review import record_manager_review
from backend.services.knowledge_approval import approve_draft
from backend.services.organization_scope import (
    conversations_for,
    knowledge_drafts_for,
    knowledge_entries_for,
)


def organization(slug: str) -> Organization:
    return Organization(slug=slug, name=slug.title())


def membership(org: Organization, external_id: str, role: UserRole):
    return OrganizationMembership(
        organization=org,
        user=User(external_id=external_id, display_name=external_id),
        role=role,
    )


def conversation(org: Organization, suffix: str) -> Conversation:
    return Conversation(
        organization=org,
        source_dataset="HarperValleyBank",
        original_id=f"conversation-{suffix}",
        channel="voice",
        agent=Agent(organization=org, external_id=f"agent-{suffix}"),
    )


async def test_agent_and_manager_have_the_expected_capabilities(session):
    org = organization("northwind")
    agent = membership(org, "agent-alex", UserRole.AGENT)
    manager = membership(org, "manager-maya", UserRole.MANAGER)
    session.add_all([agent, manager])
    await session.flush()

    assert not agent.can_review_feedback
    assert not agent.can_approve_knowledge
    assert manager.can_review_feedback
    assert manager.can_approve_knowledge


async def test_user_has_only_one_membership_per_organization(session):
    org = organization("northwind")
    user = User(external_id="agent-alex", display_name="Alex")
    session.add_all(
        [
            OrganizationMembership(organization=org, user=user, role=UserRole.AGENT),
            OrganizationMembership(organization=org, user=user, role=UserRole.MANAGER),
        ]
    )

    with pytest.raises(IntegrityError):
        await session.flush()


async def test_scoped_queries_do_not_return_another_organizations_records(session):
    northwind = organization("northwind")
    harbor = organization("harbor")
    northwind_manager = membership(northwind, "manager-northwind", UserRole.MANAGER)
    harbor_manager = membership(harbor, "manager-harbor", UserRole.MANAGER)
    northwind_topic = Topic(
        organization=northwind,
        source_dataset="HarperValleyBank",
        name="Card replacement",
    )
    harbor_topic = Topic(
        organization=harbor,
        source_dataset="HarperValleyBank",
        name="Card replacement",
    )
    northwind_conversation = conversation(northwind, "northwind")
    harbor_conversation = conversation(harbor, "harbor")
    northwind_draft = KnowledgeDraft(
        organization=northwind,
        topic=northwind_topic,
        answer_text="Northwind draft",
    )
    harbor_draft = KnowledgeDraft(
        organization=harbor,
        topic=harbor_topic,
        answer_text="Harbor draft",
    )
    northwind_review = KnowledgeReview(
        organization=northwind,
        draft=northwind_draft,
        reviewer_membership=northwind_manager,
        action=ReviewAction.APPROVED,
    )
    harbor_review = KnowledgeReview(
        organization=harbor,
        draft=harbor_draft,
        reviewer_membership=harbor_manager,
        action=ReviewAction.APPROVED,
    )
    northwind_entry = KnowledgeEntry(
        organization=northwind,
        topic=northwind_topic,
        approved_review=northwind_review,
        answer_text="Northwind answer",
    )
    harbor_entry = KnowledgeEntry(
        organization=harbor,
        topic=harbor_topic,
        approved_review=harbor_review,
        answer_text="Harbor answer",
    )
    session.add_all(
        [
            northwind_conversation,
            harbor_conversation,
            northwind_entry,
            harbor_entry,
        ]
    )
    await session.flush()

    conversations = (await session.scalars(conversations_for(northwind.id))).all()
    drafts = (await session.scalars(knowledge_drafts_for(northwind.id))).all()
    entries = (await session.scalars(knowledge_entries_for(northwind.id))).all()

    assert conversations == [northwind_conversation]
    assert drafts == [northwind_draft]
    assert entries == [northwind_entry]


async def test_conversation_cannot_reference_an_agent_from_another_org(session):
    northwind = organization("northwind")
    harbor = organization("harbor")
    harbor_agent = Agent(organization=harbor, external_id="agent-harbor")
    session.add_all([northwind, harbor_agent])
    await session.flush()
    session.add(
        Conversation(
            organization_id=northwind.id,
            source_dataset="HarperValleyBank",
            original_id="cross-org",
            channel="voice",
            agent_id=harbor_agent.id,
        )
    )

    with pytest.raises(IntegrityError):
        await session.flush()


async def test_knowledge_review_cannot_use_another_organizations_manager(session):
    northwind = organization("northwind")
    harbor = organization("harbor")
    northwind_topic = Topic(
        organization=northwind,
        source_dataset="HarperValleyBank",
        name="Card replacement",
    )
    northwind_draft = KnowledgeDraft(
        organization=northwind,
        topic=northwind_topic,
        answer_text="Northwind draft",
    )
    harbor_manager = membership(harbor, "manager-harbor", UserRole.MANAGER)
    session.add_all([northwind_draft, harbor_manager])
    await session.flush()
    session.add(
        KnowledgeReview(
            organization_id=northwind.id,
            draft_id=northwind_draft.id,
            reviewer_membership_id=harbor_manager.id,
            action=ReviewAction.APPROVED,
        )
    )

    with pytest.raises(IntegrityError):
        await session.flush()


async def test_agent_cannot_approve_knowledge(session):
    org = organization("northwind")
    agent = membership(org, "agent-alex", UserRole.AGENT)
    draft = KnowledgeDraft(
        organization=org,
        topic=Topic(
            organization=org,
            source_dataset="HarperValleyBank",
            name="Card replacement",
        ),
        answer_text="A replacement arrives in 5 to 7 business days.",
    )
    session.add_all([agent, draft])
    await session.flush()

    with pytest.raises(PermissionError, match="knowledge approval"):
        await approve_draft(session, draft, agent)


async def test_manager_can_approve_knowledge(session):
    org = organization("northwind")
    manager = membership(org, "manager-maya", UserRole.MANAGER)
    draft = KnowledgeDraft(
        organization=org,
        topic=Topic(
            organization=org,
            source_dataset="HarperValleyBank",
            name="Card replacement",
        ),
        answer_text="A replacement arrives in 5 to 7 business days.",
    )
    session.add_all([manager, draft])
    await session.flush()

    entry = await approve_draft(session, draft, manager)

    assert draft.status.value == "approved"
    assert entry.approved_review.reviewer_membership is manager
    assert entry.answer_text == draft.answer_text


async def test_feedback_flag_cannot_reference_another_organizations_agent(
    session, default_evaluation_version
):
    northwind = organization("northwind")
    harbor = organization("harbor")
    northwind_conversation = conversation(northwind, "northwind")
    harbor_agent = Agent(organization=harbor, external_id="agent-harbor")
    finding = Finding(
        organization=northwind,
        category=FindingCategory.PROCEDURE,
        result=FindingResult.NEEDS_WORK,
        feedback="Check identity",
    )
    session.add_all(
        [
            Audit(
                organization=northwind,
                conversation=northwind_conversation,
                evaluation_form_version=default_evaluation_version,
                findings=[finding],
            ),
            harbor_agent,
        ]
    )
    await session.flush()
    session.add(
        FeedbackFlag(
            organization_id=northwind.id,
            finding_id=finding.id,
            agent_id=harbor_agent.id,
            reason="Please review",
        )
    )
    with pytest.raises(IntegrityError):
        await session.flush()


async def test_non_manager_cannot_record_feedback_review(
    session, default_evaluation_version
):
    org = organization("northwind")
    agent_member = membership(org, "agent-alex", UserRole.AGENT)
    call = conversation(org, "feedback")
    finding = Finding(
        organization=org,
        category=FindingCategory.PROCEDURE,
        result=FindingResult.NEEDS_WORK,
        feedback="Check identity",
    )
    flag = FeedbackFlag(
        organization=org,
        finding=finding,
        agent=call.agent,
        reason="Please review",
    )
    session.add_all(
        [
            agent_member,
            Audit(
                organization=org,
                conversation=call,
                evaluation_form_version=default_evaluation_version,
                findings=[finding],
            ),
            flag,
        ]
    )
    await session.flush()
    with pytest.raises(PermissionError, match="feedback review"):
        await record_manager_review(
            session,
            flag,
            agent_member,
            outcome=ManagerReviewOutcome.CONFIRMED,
            reviewed_result=None,
            reason="Reviewed",
            feedback="Confirmed",
        )


async def test_manager_review_cannot_use_another_organizations_manager(
    session, default_evaluation_version
):
    northwind = organization("northwind")
    harbor = organization("harbor")
    call = conversation(northwind, "review")
    harbor_manager = membership(harbor, "manager-harbor", UserRole.MANAGER)
    finding = Finding(
        organization=northwind,
        category=FindingCategory.PROCEDURE,
        result=FindingResult.NEEDS_WORK,
        feedback="Check identity",
    )
    flag = FeedbackFlag(
        organization=northwind,
        finding=finding,
        agent=call.agent,
        reason="Please review",
    )
    session.add_all(
        [
            harbor_manager,
            Audit(
                organization=northwind,
                conversation=call,
                evaluation_form_version=default_evaluation_version,
                findings=[finding],
            ),
            flag,
        ]
    )
    await session.flush()
    session.add(
        ManagerReview(
            organization_id=northwind.id,
            feedback_flag_id=flag.id,
            reviewer_membership_id=harbor_manager.id,
            outcome=ManagerReviewOutcome.CONFIRMED,
            reason="Reviewed",
            feedback="Confirmed",
        )
    )
    with pytest.raises(IntegrityError):
        await session.flush()
