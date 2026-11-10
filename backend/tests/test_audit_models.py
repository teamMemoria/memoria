import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import selectinload

from backend.models import (
    Agent,
    Audit,
    Conversation,
    Finding,
    FindingCategory,
    FindingResult,
    KnowledgeDraft,
    KnowledgeEntry,
    KnowledgeReview,
    Organization,
    OrganizationMembership,
    ReviewAction,
    Speaker,
    Topic,
    Turn,
    User,
    UserRole,
)


@pytest.fixture
async def organization(session):
    org = Organization(slug="audit-tests", name="Audit Tests")
    session.add(org)
    await session.flush()
    return org


@pytest.fixture
async def conversation(session, organization):
    c = Conversation(
        organization=organization,
        source_dataset="HarperValleyBank",
        original_id="abc",
        channel="voice",
        agent=Agent(organization=organization, external_id="hvb-speaker-1"),
        turns=[
            Turn(line_number=n, speaker=Speaker.AGENT, text=f"line {n}")
            for n in range(1, 6)
        ],
    )
    session.add(c)
    await session.flush()
    return c


@pytest.fixture
async def evaluation_version(default_evaluation_version):
    return default_evaluation_version


async def make_entry(session, organization) -> KnowledgeEntry:
    topic = Topic(
        organization=organization,
        source_dataset="HarperValleyBank",
        name="Card replacement",
    )
    draft = KnowledgeDraft(
        organization=organization,
        topic=topic,
        answer_text="5 to 7 business days",
    )
    manager = OrganizationMembership(
        organization=organization,
        user=User(external_id="manager-alex", display_name="Alex"),
        role=UserRole.MANAGER,
    )
    entry = KnowledgeEntry(
        organization=organization,
        topic=topic,
        answer_text=draft.answer_text,
        approved_review=KnowledgeReview(
            organization=organization,
            draft=draft,
            action=ReviewAction.APPROVED,
            reviewer_membership=manager,
        ),
    )
    session.add(entry)
    await session.flush()
    return entry


async def test_audit_with_four_findings_and_evidence_round_trips(
    session, organization, conversation, evaluation_version
):
    entry = await make_entry(session, organization)
    turns = {t.line_number: t for t in conversation.turns}
    audit = Audit(
        organization=organization,
        conversation=conversation,
        evaluation_form_version=evaluation_version,
        findings=[
            Finding(
                organization=organization,
                category=FindingCategory.PROCEDURE,
                result=FindingResult.PASS,
                feedback="Verified identity first.",
                evidence=[turns[2], turns[1]],
            ),
            Finding(
                organization=organization,
                category=FindingCategory.ANSWER_SUPPORT,
                result=FindingResult.NEEDS_WORK,
                feedback="Quoted the wrong delivery time.",
                evidence=[turns[4]],
                knowledge_entry=entry,
            ),
            Finding(
                organization=organization,
                category=FindingCategory.COMPLETENESS,
                result=FindingResult.CANNOT_ASSESS,
                feedback="Call ended before the request was resolved.",
            ),
            Finding(
                organization=organization,
                category=FindingCategory.COMMUNICATION,
                result=FindingResult.PASS,
                feedback="Clear and polite.",
                evidence=[turns[5]],
            ),
        ],
    )
    session.add(audit)
    await session.commit()
    session.expunge_all()

    loaded = await session.scalar(
        select(Audit)
        .where(Audit.conversation_id == conversation.id)
        .options(
            selectinload(Audit.findings).selectinload(Finding.evidence),
            selectinload(Audit.findings).selectinload(Finding.knowledge_entry),
        )
    )

    by_category = {f.category: f for f in loaded.findings}
    assert set(by_category) == set(FindingCategory)
    assert [t.line_number for t in by_category[FindingCategory.PROCEDURE].evidence] == [
        1,
        2,
    ]
    assert by_category[FindingCategory.ANSWER_SUPPORT].knowledge_entry.id == entry.id
    assert by_category[FindingCategory.PROCEDURE].knowledge_entry is None
    assert by_category[FindingCategory.COMPLETENESS].evidence == []


async def test_cannot_assess_is_stored_separately_from_needs_work(
    session, organization, conversation, evaluation_version
):
    audit = Audit(
        organization=organization,
        conversation=conversation,
        evaluation_form_version=evaluation_version,
        findings=[
            Finding(
                organization=organization,
                category=FindingCategory.PROCEDURE,
                result=FindingResult.NEEDS_WORK,
                feedback="a",
            ),
            Finding(
                organization=organization,
                category=FindingCategory.COMPLETENESS,
                result=FindingResult.CANNOT_ASSESS,
                feedback="b",
            ),
        ],
    )
    session.add(audit)
    await session.flush()

    raw = (
        await session.execute(
            select(Finding.__table__.c.category, Finding.__table__.c.result).order_by(
                "category"
            )
        )
    ).all()
    assert raw == [("completeness", "cannot_assess"), ("procedure", "needs_work")]

    failures = await session.scalars(
        select(Finding).where(Finding.result == FindingResult.NEEDS_WORK)
    )
    assert [f.category for f in failures] == [FindingCategory.PROCEDURE]


async def test_one_audit_per_conversation(
    session, organization, conversation, evaluation_version
):
    session.add_all(
        [
            Audit(
                organization=organization,
                conversation=conversation,
                evaluation_form_version=evaluation_version,
            ),
            Audit(
                organization=organization,
                conversation=conversation,
                evaluation_form_version=evaluation_version,
            ),
        ]
    )
    with pytest.raises(IntegrityError):
        await session.flush()


async def test_one_finding_per_category_per_audit(
    session, organization, conversation, evaluation_version
):
    session.add(
        Audit(
            organization=organization,
            conversation=conversation,
            evaluation_form_version=evaluation_version,
            findings=[
                Finding(
                    organization=organization,
                    category=FindingCategory.PROCEDURE,
                    result=FindingResult.PASS,
                    feedback="a",
                ),
                Finding(
                    organization=organization,
                    category=FindingCategory.PROCEDURE,
                    result=FindingResult.PASS,
                    feedback="b",
                ),
            ],
        )
    )
    with pytest.raises(IntegrityError):
        await session.flush()


async def test_unknown_result_is_rejected(
    session, organization, conversation, evaluation_version
):
    audit = Audit(
        organization=organization,
        conversation=conversation,
        evaluation_form_version=evaluation_version,
    )
    session.add(audit)
    await session.flush()
    with pytest.raises(IntegrityError):
        await session.execute(
            Finding.__table__.insert().values(
                organization_id=organization.id,
                audit_id=audit.id,
                category="procedure",
                result="fail",
                feedback="x",
            )
        )


async def test_finding_cannot_reference_knowledge_from_another_org(
    session, evaluation_version
):
    northwind = Organization(slug="northwind", name="Northwind")
    harbor = Organization(slug="harbor", name="Harbor")
    northwind_conversation = Conversation(
        organization=northwind,
        source_dataset="HarperValleyBank",
        original_id="northwind-call",
        channel="voice",
        agent=Agent(organization=northwind, external_id="northwind-agent"),
    )
    harbor_entry = await make_entry(session, harbor)
    session.add(northwind_conversation)
    await session.flush()
    session.add(
        Audit(
            organization=northwind,
            conversation=northwind_conversation,
            evaluation_form_version=evaluation_version,
            findings=[
                Finding(
                    organization=northwind,
                    category=FindingCategory.ANSWER_SUPPORT,
                    result=FindingResult.NEEDS_WORK,
                    feedback="Cross-organization knowledge must be rejected.",
                    knowledge_entry=harbor_entry,
                )
            ],
        )
    )

    with pytest.raises(IntegrityError):
        await session.flush()
