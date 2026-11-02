"""A small organization in PostgreSQL that mirrors the fixture scenarios.

Two organizations, three agents with linked agent records, a Manager, and calls
in each state the API distinguishes (assessed, processing, undated, reviewed,
another agent's, another organization's). Tests read the generated IDs from the
returned ``Seed``.
"""

from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import UTC, date, datetime

from sqlalchemy.ext.asyncio import AsyncSession

from backend.models import (
    Agent,
    Audit,
    Conversation,
    DraftStatus,
    EntryStatus,
    EvaluationForm,
    EvaluationFormVersion,
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
    Speaker,
    Topic,
    Turn,
    User,
    UserRole,
)

NORTHWIND = "org-northwind"
HARBOR = "org-harbor"
ALEX = "agent-alex-morgan"
SAM = "agent-sam-rivera"
MAYA = "manager-maya-chen"
RILEY = "agent-riley-chen"
UNLINKED = "agent-new-starter"


def sessions_for(session: AsyncSession):
    """A provider session factory that hands out the test's own session."""

    @asynccontextmanager
    async def factory():
        yield session

    return factory


@dataclass
class Seed:
    northwind: Organization
    harbor: Organization
    form_version: EvaluationFormVersion
    alex_agent: Agent
    sam_agent: Agent
    maya: OrganizationMembership
    # Alex's calls
    assessed: Conversation
    processing: Conversation
    undated: Conversation
    reviewed: Conversation
    # Someone else's calls
    sam_call: Conversation
    harbor_call: Conversation
    # Knowledge
    approved_entry: KnowledgeEntry
    stale_entry: KnowledgeEntry
    disputed_entry: KnowledgeEntry
    harbor_entry: KnowledgeEntry
    # Assessed call details
    procedure_finding: Finding
    reviewed_finding: Finding

    def id(self, record) -> str:
        return str(record.id)


def _member(org, external_id, name, role, agent=None):
    return OrganizationMembership(
        organization=org,
        user=User(external_id=external_id, display_name=name),
        role=role,
        agent=agent,
    )


def _conversation(org, agent, original_id, topic, when, turns):
    # topic=None would also clear organization_id through the composite key,
    # so an untopiced conversation simply leaves the relationship unset.
    extra = {"topic": topic} if topic is not None else {}
    return Conversation(
        organization=org,
        agent=agent,
        **extra,
        source_dataset="Synthetic",
        original_id=original_id,
        channel="chat",
        conversation_date=when,
        turns=[
            Turn(line_number=number, speaker=speaker, text=text)
            for number, speaker, text in turns
        ],
    )


TURNS = [
    (1, Speaker.CUSTOMER, "My jacket arrived torn and I would like a refund."),
    (2, Speaker.AGENT, "I can refund that to your original card."),
    (4, Speaker.CUSTOMER, "Yes, the card I paid with."),
    (5, Speaker.SYSTEM_ACTION, "order lookup"),
    (7, Speaker.AGENT, "I have checked the order and the refund is on its way."),
]


def _entry(org, topic, text, status, reviewer, *, confirmed=None):
    draft = KnowledgeDraft(
        organization=org, topic=topic, answer_text=text, status=DraftStatus.APPROVED
    )
    return KnowledgeEntry(
        organization=org,
        topic=topic,
        answer_text=text,
        status=status,
        last_confirmed_at=confirmed,
        approved_review=KnowledgeReview(
            organization=org,
            draft=draft,
            action=ReviewAction.APPROVED,
            reviewer_membership=reviewer,
            reviewed_at=datetime(2026, 9, 1, 12, 0, tzinfo=UTC),
        ),
    )


def four_findings(**overrides):
    findings = {
        FindingCategory.PROCEDURE: Finding(
            category=FindingCategory.PROCEDURE,
            result=FindingResult.PASS,
            feedback="Steps were followed in order.",
        ),
        FindingCategory.ANSWER_SUPPORT: Finding(
            category=FindingCategory.ANSWER_SUPPORT,
            result=FindingResult.PASS,
            feedback="The answer matches approved guidance.",
        ),
        FindingCategory.COMPLETENESS: Finding(
            category=FindingCategory.COMPLETENESS,
            result=FindingResult.PASS,
            feedback="Every request was handled.",
        ),
        FindingCategory.COMMUNICATION: Finding(
            category=FindingCategory.COMMUNICATION,
            result=FindingResult.PASS,
            feedback="Clear and polite.",
        ),
    }
    findings.update(overrides)
    return list(findings.values())


async def seed(session: AsyncSession) -> Seed:
    northwind = Organization(slug=NORTHWIND, name="Northwind Support")
    harbor = Organization(slug=HARBOR, name="Harbor Retail")
    alex_agent = Agent(organization=northwind, external_id="speaker-11", name="A11")
    sam_agent = Agent(organization=northwind, external_id="speaker-12", name="A12")
    riley_agent = Agent(organization=harbor, external_id="speaker-11", name="H11")
    maya = _member(northwind, MAYA, "Maya Chen", UserRole.MANAGER)
    session.add_all(
        [
            _member(northwind, ALEX, "Alex Morgan", UserRole.AGENT, alex_agent),
            _member(northwind, SAM, "Sam Rivera", UserRole.AGENT, sam_agent),
            maya,
            _member(northwind, UNLINKED, "New Starter", UserRole.AGENT),
            _member(harbor, RILEY, "Riley Chen", UserRole.AGENT, riley_agent),
        ]
    )
    refunds = Topic(organization=northwind, source_dataset="Synthetic", name="Refunds")
    harbor_topic = Topic(
        organization=harbor, source_dataset="Synthetic", name="Refunds"
    )

    stale_entry = _entry(
        northwind, refunds, "Old refund rule.", EntryStatus.STALE, maya
    )
    approved_entry = _entry(
        northwind,
        refunds,
        "Refunds go to the original card.\n\nThey take 5 to 7 business days.",
        EntryStatus.APPROVED,
        maya,
        confirmed=datetime(2026, 10, 1, tzinfo=UTC),
    )
    disputed_entry = _entry(
        northwind, refunds, "Disputed rule.", EntryStatus.DISPUTED, maya
    )
    harbor_entry = _entry(
        harbor,
        harbor_topic,
        "Harbor refunds.",
        EntryStatus.APPROVED,
        _member(harbor, "manager-harbor", "Harbor Manager", UserRole.MANAGER),
    )

    form_version = EvaluationFormVersion(
        form=EvaluationForm(name="Seeded quality form"),
        version_number=1,
        is_active=True,
    )

    assessed = _conversation(
        northwind, alex_agent, "assessed", refunds, date(2026, 10, 8), TURNS
    )
    processing = _conversation(
        northwind, alex_agent, "processing", refunds, date(2026, 10, 14), TURNS
    )
    undated = _conversation(northwind, alex_agent, "undated", None, None, TURNS)
    reviewed = _conversation(
        northwind, alex_agent, "reviewed", refunds, date(2026, 10, 10), TURNS
    )
    sam_call = _conversation(
        northwind, sam_agent, "sam", refunds, date(2026, 10, 12), TURNS
    )
    harbor_call = _conversation(
        harbor, riley_agent, "harbor", harbor_topic, date(2026, 10, 9), TURNS
    )
    session.add_all(
        [assessed, processing, undated, reviewed, sam_call, harbor_call, stale_entry]
    )
    session.add_all([approved_entry, disputed_entry, harbor_entry])
    await session.flush()

    turns = {turn.line_number: turn for turn in assessed.turns}
    procedure_finding = Finding(
        category=FindingCategory.PROCEDURE,
        result=FindingResult.NEEDS_WORK,
        feedback="The refund was offered before the order was checked.",
        evidence=[turns[7], turns[2], turns[5]],
        knowledge_entry=stale_entry,
    )
    session.add(
        Audit(
            conversation=assessed,
            evaluation_form_version=form_version,
            findings=four_findings(
                **{
                    FindingCategory.PROCEDURE: procedure_finding,
                    FindingCategory.COMPLETENESS: Finding(
                        category=FindingCategory.COMPLETENESS,
                        result=FindingResult.CANNOT_ASSESS,
                        feedback="The call ended before the request was settled.",
                    ),
                }
            ),
        )
    )
    session.add(
        Audit(
            conversation=undated,
            evaluation_form_version=form_version,
            findings=four_findings(),
        )
    )
    reviewed_turns = {turn.line_number: turn for turn in reviewed.turns}
    reviewed_finding = Finding(
        category=FindingCategory.PROCEDURE,
        result=FindingResult.NEEDS_WORK,
        feedback="Identity was not checked.",
        evidence=[reviewed_turns[2]],
    )
    session.add(
        Audit(
            conversation=reviewed,
            evaluation_form_version=form_version,
            findings=four_findings(**{FindingCategory.PROCEDURE: reviewed_finding}),
        )
    )
    session.add(
        FeedbackFlag(
            finding=reviewed_finding,
            agent=alex_agent,
            reason="Identity was checked before the transcript starts.",
            manager_review=ManagerReview(
                outcome=ManagerReviewOutcome.CANNOT_ASSESS,
                reviewer="Maya Chen",
                reason="The recording starts after the identity check.",
                feedback="Nothing to change; the evidence is incomplete.",
                reviewed_at=datetime(2026, 10, 13, 15, 20, tzinfo=UTC),
            ),
        )
    )
    sam_turns = {turn.line_number: turn for turn in sam_call.turns}
    session.add(
        Audit(
            conversation=sam_call,
            evaluation_form_version=form_version,
            findings=four_findings(
                **{
                    FindingCategory.PROCEDURE: Finding(
                        category=FindingCategory.PROCEDURE,
                        result=FindingResult.NEEDS_WORK,
                        feedback="Sam skipped a step.",
                        evidence=[sam_turns[2]],
                    )
                }
            ),
        )
    )
    await session.commit()
    result = Seed(
        northwind=northwind,
        harbor=harbor,
        form_version=form_version,
        alex_agent=alex_agent,
        sam_agent=sam_agent,
        maya=maya,
        assessed=assessed,
        processing=processing,
        undated=undated,
        reviewed=reviewed,
        sam_call=sam_call,
        harbor_call=harbor_call,
        approved_entry=approved_entry,
        stale_entry=stale_entry,
        disputed_entry=disputed_entry,
        harbor_entry=harbor_entry,
        procedure_finding=procedure_finding,
        reviewed_finding=reviewed_finding,
    )
    # Providers must read what is stored, not objects cached in this session.
    session.expunge_all()
    return result
