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
)


@pytest.fixture
async def finding(session):
    agent = Agent(external_id="hvb-speaker-review")
    conversation = Conversation(
        source_dataset="HarperValleyBank",
        original_id="review-1",
        channel="voice",
        agent=agent,
    )
    finding = Finding(
        category=FindingCategory.PROCEDURE,
        result=FindingResult.NEEDS_WORK,
        feedback="Check identity before discussing the account.",
    )
    session.add(Audit(conversation=conversation, findings=[finding]))
    await session.flush()
    return finding


async def test_agent_flag_and_manager_review_round_trip(session, finding):
    flag = FeedbackFlag(
        finding=finding,
        agent=finding.audit.conversation.agent,
        reason="Identity was verified in a system action.",
        agent_context="The verification happened before the recorded transcript.",
        manager_review=ManagerReview(
            outcome=ManagerReviewOutcome.CORRECTED,
            reviewed_result=FindingResult.PASS,
            reviewer="manager@example.com",
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
    assert loaded.manager_review.reviewer == "manager@example.com"
    assert isinstance(loaded.manager_review.reviewed_at, datetime)


@pytest.mark.parametrize("outcome", list(ManagerReviewOutcome))
async def test_every_manager_review_outcome_is_stored(session, finding, outcome):
    review = ManagerReview(
        outcome=outcome,
        reviewed_result=(
            FindingResult.PASS if outcome == ManagerReviewOutcome.CORRECTED else None
        ),
        reviewer="manager@example.com",
        reason="Reviewed against the available evidence.",
        feedback="Decision recorded for the Agent.",
    )
    session.add(
        FeedbackFlag(
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
    session, finding, outcome, reviewed_result
):
    session.add(
        FeedbackFlag(
            finding=finding,
            agent=finding.audit.conversation.agent,
            reason="Please review this finding.",
            manager_review=ManagerReview(
                outcome=outcome,
                reviewed_result=reviewed_result,
                reviewer="manager@example.com",
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
            FeedbackFlag(finding=finding, agent=agent, reason="First request"),
            FeedbackFlag(finding=finding, agent=agent, reason="Second request"),
        ]
    )

    with pytest.raises(IntegrityError):
        await session.flush()


async def test_flag_can_only_have_one_manager_review(session, finding):
    flag = FeedbackFlag(
        finding=finding,
        agent=finding.audit.conversation.agent,
        reason="Please review this finding.",
    )
    session.add(flag)
    await session.flush()
    session.add_all(
        [
            ManagerReview(
                feedback_flag=flag,
                outcome=ManagerReviewOutcome.CONFIRMED,
                reviewer="first-manager",
                reason="The evidence supports it.",
                feedback="Follow the original coaching.",
            ),
            ManagerReview(
                feedback_flag=flag,
                outcome=ManagerReviewOutcome.DISMISSED,
                reviewer="second-manager",
                reason="The evidence does not support it.",
                feedback="No coaching is needed.",
            ),
        ]
    )

    with pytest.raises(IntegrityError):
        await session.flush()


async def test_unknown_manager_review_outcome_is_rejected(session, finding):
    flag = FeedbackFlag(
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
                outcome="overturned",
                reviewer="manager@example.com",
                reason="Invalid outcome.",
                feedback="Invalid outcome.",
            )
        )
