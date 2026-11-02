import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import selectinload

from backend.models import (
    Agent,
    Audit,
    Conversation,
    EvaluationForm,
    EvaluationFormVersion,
    Finding,
    FindingCategory,
    FindingResult,
    KnowledgeDraft,
    KnowledgeEntry,
    KnowledgeReview,
    ReviewAction,
    Speaker,
    Topic,
    Turn,
)


@pytest.fixture
async def conversation(session):
    c = Conversation(
        source_dataset="HarperValleyBank",
        original_id="abc",
        channel="voice",
        agent=Agent(external_id="hvb-speaker-1"),
        turns=[
            Turn(line_number=n, speaker=Speaker.AGENT, text=f"line {n}")
            for n in range(1, 6)
        ],
    )
    session.add(c)
    await session.flush()
    return c


@pytest.fixture
async def evaluation_version(session):
    version = EvaluationFormVersion(
        form=EvaluationForm(name="Default quality form"),
        version_number=1,
        is_active=True,
    )
    session.add(version)
    await session.flush()
    return version


async def make_entry(session) -> KnowledgeEntry:
    topic = Topic(source_dataset="HarperValleyBank", name="Card replacement")
    draft = KnowledgeDraft(topic=topic, answer_text="5 to 7 business days")
    entry = KnowledgeEntry(
        topic=topic,
        answer_text=draft.answer_text,
        approved_review=KnowledgeReview(
            draft=draft, action=ReviewAction.APPROVED, reviewer="alex"
        ),
    )
    session.add(entry)
    await session.flush()
    return entry


async def test_audit_with_four_findings_and_evidence_round_trips(
    session, conversation, evaluation_version
):
    entry = await make_entry(session)
    turns = {t.line_number: t for t in conversation.turns}
    audit = Audit(
        conversation=conversation,
        evaluation_form_version=evaluation_version,
        findings=[
            Finding(
                category=FindingCategory.PROCEDURE,
                result=FindingResult.PASS,
                feedback="Verified identity first.",
                evidence=[turns[2], turns[1]],
            ),
            Finding(
                category=FindingCategory.ANSWER_SUPPORT,
                result=FindingResult.NEEDS_WORK,
                feedback="Quoted the wrong delivery time.",
                evidence=[turns[4]],
                knowledge_entry=entry,
            ),
            Finding(
                category=FindingCategory.COMPLETENESS,
                result=FindingResult.CANNOT_ASSESS,
                feedback="Call ended before the request was resolved.",
            ),
            Finding(
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
    session, conversation, evaluation_version
):
    audit = Audit(
        conversation=conversation,
        evaluation_form_version=evaluation_version,
        findings=[
            Finding(
                category=FindingCategory.PROCEDURE,
                result=FindingResult.NEEDS_WORK,
                feedback="a",
            ),
            Finding(
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


async def test_one_audit_per_conversation(session, conversation, evaluation_version):
    session.add_all(
        [
            Audit(
                conversation=conversation,
                evaluation_form_version=evaluation_version,
            ),
            Audit(
                conversation=conversation,
                evaluation_form_version=evaluation_version,
            ),
        ]
    )
    with pytest.raises(IntegrityError):
        await session.flush()


async def test_one_finding_per_category_per_audit(
    session, conversation, evaluation_version
):
    session.add(
        Audit(
            conversation=conversation,
            evaluation_form_version=evaluation_version,
            findings=[
                Finding(
                    category=FindingCategory.PROCEDURE,
                    result=FindingResult.PASS,
                    feedback="a",
                ),
                Finding(
                    category=FindingCategory.PROCEDURE,
                    result=FindingResult.PASS,
                    feedback="b",
                ),
            ],
        )
    )
    with pytest.raises(IntegrityError):
        await session.flush()


async def test_unknown_result_is_rejected(session, conversation, evaluation_version):
    audit = Audit(conversation=conversation, evaluation_form_version=evaluation_version)
    session.add(audit)
    await session.flush()
    with pytest.raises(IntegrityError):
        await session.execute(
            Finding.__table__.insert().values(
                audit_id=audit.id, category="procedure", result="fail", feedback="x"
            )
        )
