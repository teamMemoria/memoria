from datetime import datetime

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import selectinload

from backend.models import (
    Agent,
    Audit,
    Conversation,
    FeedbackFlag,
    Finding,
    FindingCategory,
    FindingResult,
    ManagerReview,
    ManagerReviewOutcome,
    Organization,
    OrganizationMembership,
    User,
    UserRole,
)


@pytest.fixture
async def finding(session):
    org = Organization(slug="feedback-tests", name="Feedback tests")
    agent = Agent(organization=org, external_id="hvb-speaker-review")
    conversation = Conversation(
        organization=org,
        source_dataset="HarperValleyBank",
        original_id="review-1",
        channel="voice",
        agent=agent,
    )
    finding = Finding(
        organization=org,
        category=FindingCategory.PROCEDURE,
        result=FindingResult.NEEDS_WORK,
        feedback="Check identity before discussing the account.",
    )
    session.add(Audit(organization=org, conversation=conversation, findings=[finding]))
    await session.flush()
    return finding


@pytest.fixture
async def manager(session, finding):
    member = OrganizationMembership(
        organization=finding.organization,
        user=User(external_id="feedback-manager", display_name="manager@example.com"),
        role=UserRole.MANAGER,
    )
    session.add(member)
    await session.flush()
    return member


async def test_agent_flag_and_manager_review_round_trip(session, finding, manager):
    flag = FeedbackFlag(
        organization=finding.organization,
        finding=finding,
        agent=finding.audit.conversation.agent,
        reason="Identity was verified in a system action.",
        agent_context="The verification happened before the recorded transcript.",
        manager_review=ManagerReview(
            organization=finding.organization,
            outcome=ManagerReviewOutcome.CORRECTED,
            reviewed_result=FindingResult.PASS,
            reviewer_membership=manager,
            reason="The system log confirms the verification.",
            feedback="The procedure passed; no coaching is needed.",
        ),
    )
    session.add(flag)
    await session.commit()
    session.expunge_all()

    loaded = await session.scalar(
        select(FeedbackFlag)
        .where(FeedbackFlag.id == flag.id)
        .options(
            selectinload(FeedbackFlag.finding),
            selectinload(FeedbackFlag.agent),
            selectinload(FeedbackFlag.manager_review),
        )
    )

    assert loaded.finding.result == FindingResult.NEEDS_WORK
    assert loaded.finding.feedback == "Check identity before discussing the account."
    assert loaded.agent.external_id == "hvb-speaker-review"
    assert loaded.reason == "Identity was verified in a system action."
    assert loaded.agent_context == (
        "The verification happened before the recorded transcript."
    )
    assert isinstance(loaded.flagged_at, datetime)
    assert loaded.manager_review.outcome == ManagerReviewOutcome.CORRECTED
    assert loaded.manager_review.reviewed_result == FindingResult.PASS
    assert loaded.manager_review.reviewer_membership_id == manager.id
    assert isinstance(loaded.manager_review.reviewed_at, datetime)


@pytest.mark.parametrize("outcome", list(ManagerReviewOutcome))
async def test_every_manager_review_outcome_is_stored(
    session, finding, manager, outcome
):
    review = ManagerReview(
        organization=finding.organization,
        outcome=outcome,
        reviewed_result=(
            FindingResult.PASS if outcome == ManagerReviewOutcome.CORRECTED else None
        ),
        reviewer_membership=manager,
        reason="Reviewed against the available evidence.",
        feedback="Decision recorded for the Agent.",
    )
    session.add(
        FeedbackFlag(
            organization=finding.organization,
            finding=finding,
            agent=finding.audit.conversation.agent,
            reason="Please review this finding.",
            manager_review=review,
        )
    )
    await session.flush()

    assert review.outcome == outcome


@pytest.mark.parametrize(
    ("outcome", "reviewed_result"),
    [
        (ManagerReviewOutcome.CORRECTED, None),
        (ManagerReviewOutcome.CONFIRMED, FindingResult.PASS),
    ],
)
async def test_reviewed_result_is_required_only_for_corrections(
    session, finding, manager, outcome, reviewed_result
):
    session.add(
        FeedbackFlag(
            organization=finding.organization,
            finding=finding,
            agent=finding.audit.conversation.agent,
            reason="Please review this finding.",
            manager_review=ManagerReview(
                organization=finding.organization,
                outcome=outcome,
                reviewed_result=reviewed_result,
                reviewer_membership=manager,
                reason="Reviewed against the available evidence.",
                feedback="Decision recorded for the Agent.",
            ),
        )
    )

    with pytest.raises(IntegrityError):
        await session.flush()


async def test_finding_can_only_be_flagged_once(session, finding):
    agent = finding.audit.conversation.agent
    session.add_all(
        [
            FeedbackFlag(
                organization=finding.organization,
                finding=finding,
                agent=agent,
                reason="First request",
            ),
            FeedbackFlag(
                organization=finding.organization,
                finding=finding,
                agent=agent,
                reason="Second request",
            ),
        ]
    )

    with pytest.raises(IntegrityError):
        await session.flush()


async def test_flag_can_only_have_one_manager_review(session, finding, manager):
    flag = FeedbackFlag(
        organization=finding.organization,
        finding=finding,
        agent=finding.audit.conversation.agent,
        reason="Please review this finding.",
    )
    session.add(flag)
    await session.flush()
    session.add_all(
        [
            ManagerReview(
                organization=finding.organization,
                feedback_flag=flag,
                outcome=ManagerReviewOutcome.CONFIRMED,
                reviewer_membership=manager,
                reason="The evidence supports it.",
                feedback="Follow the original coaching.",
            ),
            ManagerReview(
                organization=finding.organization,
                feedback_flag=flag,
                outcome=ManagerReviewOutcome.DISMISSED,
                reviewer_membership=manager,
                reason="The evidence does not support it.",
                feedback="No coaching is needed.",
            ),
        ]
    )

    with pytest.raises(IntegrityError):
        await session.flush()


async def test_unknown_manager_review_outcome_is_rejected(session, finding, manager):
    flag = FeedbackFlag(
        organization=finding.organization,
        finding=finding,
        agent=finding.audit.conversation.agent,
        reason="Please review this finding.",
    )
    session.add(flag)
    await session.flush()

    with pytest.raises(IntegrityError):
        await session.execute(
            ManagerReview.__table__.insert().values(
                feedback_flag_id=flag.id,
                organization_id=finding.organization_id,
                outcome="overturned",
                reviewer_membership_id=manager.id,
                reason="Invalid outcome.",
                feedback="Invalid outcome.",
            )
        )
