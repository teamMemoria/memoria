from decimal import Decimal

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import selectinload

from backend.models import (
    Agent,
    Audit,
    Conversation,
    EvaluationCriterion,
    EvaluationForm,
    EvaluationFormVersion,
    FindingCategory,
)


def criterion(
    position: int,
    category: FindingCategory,
    weight: str = "0.2500",
    threshold: str = "0.7000",
    enabled: bool = True,
) -> EvaluationCriterion:
    return EvaluationCriterion(
        position=position,
        category=category,
        name=category.value.replace("_", " ").title(),
        weight=Decimal(weight),
        enabled=enabled,
        pass_threshold=Decimal(threshold),
    )


async def test_form_versions_and_ordered_criteria_round_trip(session):
    form = EvaluationForm(
        name="Customer support quality",
        versions=[
            EvaluationFormVersion(
                version_number=1,
                criteria=[
                    criterion(3, FindingCategory.COMPLETENESS),
                    criterion(1, FindingCategory.PROCEDURE),
                    criterion(4, FindingCategory.COMMUNICATION, enabled=False),
                    criterion(2, FindingCategory.ANSWER_SUPPORT),
                ],
            ),
            EvaluationFormVersion(
                version_number=2,
                is_active=True,
                criteria=[
                    criterion(1, FindingCategory.PROCEDURE, weight="0.3000"),
                    criterion(2, FindingCategory.ANSWER_SUPPORT, weight="0.3000"),
                    criterion(3, FindingCategory.COMPLETENESS, weight="0.2000"),
                    criterion(4, FindingCategory.COMMUNICATION, weight="0.2000"),
                ],
            ),
        ],
    )
    session.add(form)
    await session.commit()
    session.expunge_all()

    loaded = await session.scalar(
        select(EvaluationForm)
        .where(EvaluationForm.name == "Customer support quality")
        .options(
            selectinload(EvaluationForm.versions).selectinload(
                EvaluationFormVersion.criteria
            )
        )
    )

    assert [version.version_number for version in loaded.versions] == [1, 2]
    assert [criterion.position for criterion in loaded.versions[0].criteria] == [
        1,
        2,
        3,
        4,
    ]
    assert loaded.versions[0].criteria[-1].enabled is False
    assert loaded.versions[1].is_active is True
    assert loaded.versions[1].criteria[0].weight == Decimal("0.3000")


async def test_only_one_version_of_a_form_can_be_active(session):
    session.add(
        EvaluationForm(
            name="Single active version",
            versions=[
                EvaluationFormVersion(version_number=1, is_active=True),
                EvaluationFormVersion(version_number=2, is_active=True),
            ],
        )
    )

    with pytest.raises(IntegrityError):
        await session.flush()


@pytest.mark.parametrize(
    ("weight", "threshold"),
    [
        ("-0.0001", "0.5000"),
        ("1.0001", "0.5000"),
        ("0.5000", "-0.0001"),
        ("0.5000", "1.0001"),
    ],
)
async def test_invalid_weight_or_threshold_is_rejected(session, weight, threshold):
    session.add(
        EvaluationForm(
            name=f"Invalid {weight} {threshold}",
            versions=[
                EvaluationFormVersion(
                    version_number=1,
                    criteria=[
                        criterion(
                            1,
                            FindingCategory.PROCEDURE,
                            weight=weight,
                            threshold=threshold,
                        )
                    ],
                )
            ],
        )
    )

    with pytest.raises(IntegrityError):
        await session.flush()


async def test_audit_retains_the_form_version_used_for_scoring(session):
    form = EvaluationForm(
        name="Historical scoring",
        versions=[
            EvaluationFormVersion(version_number=1, is_active=True),
            EvaluationFormVersion(version_number=2),
        ],
    )
    conversation = Conversation(
        source_dataset="HarperValleyBank",
        original_id="historical-audit",
        channel="voice",
        agent=Agent(external_id="historical-agent"),
    )
    audit = Audit(
        conversation=conversation,
        evaluation_form_version=form.versions[0],
    )
    session.add(audit)
    await session.flush()
    original_version_id = form.versions[0].id

    form.versions[0].is_active = False
    form.versions[1].is_active = True
    await session.commit()
    session.expunge_all()

    loaded = await session.scalar(
        select(Audit).options(selectinload(Audit.evaluation_form_version))
    )
    assert loaded.evaluation_form_version_id == original_version_id
    assert loaded.evaluation_form_version.version_number == 1
