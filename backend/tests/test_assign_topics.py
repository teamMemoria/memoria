import pytest
from sqlalchemy import func, select

from backend.data.assign_topics import (
    UnmappedLabelError,
    assign_topics,
    load_mapping,
    topic_counts,
    topic_for,
)
from backend.models import Agent, Conversation, Organization, Topic

MAPPING = load_mapping()

HVB_TASKS = [
    "check balance",
    "get branch hours",
    "order checks",
    "pay bill",
    "replace card",
    "reset password",
    "schedule appointment",
    "transfer money",
]
ABCD_FLOWS = [
    "account_access",
    "manage_account",
    "order_issue",
    "product_defect",
    "purchase_dispute",
    "shipping_issue",
    "single_item_query",
    "storewide_query",
    "subscription_inquiry",
    "troubleshoot_site",
]


def test_shipped_mapping_covers_every_hvb_task_and_abcd_flow():
    assert sorted(MAPPING["HarperValleyBank"]["task_assigned"]) == HVB_TASKS
    assert sorted(MAPPING["ABCD"]["flow"]) == ABCD_FLOWS


def test_hvb_topic_comes_from_task_assigned():
    fields = {"task_assigned": ["replace card"], "task_logged_by_agent": ["pay bill"]}
    assert topic_for("HarperValleyBank", fields, MAPPING) == "Card replacement"


def test_hvb_repeated_task_counts_once():
    fields = {"task_assigned": ["check balance", "check balance"]}
    assert topic_for("HarperValleyBank", fields, MAPPING) == "Account balance"


def test_abcd_subflow_override_wins_over_flow():
    assert (
        topic_for(
            "ABCD", {"flow": "product_defect", "subflow": "refund_status"}, MAPPING
        )
        == "Refunds"
    )
    assert (
        topic_for("ABCD", {"flow": "product_defect", "subflow": "return_size"}, MAPPING)
        == "Returns"
    )
    assert (
        topic_for("ABCD", {"flow": "shipping_issue", "subflow": "cost"}, MAPPING)
        == "Shipping"
    )


@pytest.mark.parametrize(
    "dataset, fields",
    [
        ("HarperValleyBank", {"task_assigned": ["open account"]}),
        ("HarperValleyBank", {"task_assigned": ["pay bill", "replace card"]}),
        ("HarperValleyBank", {}),
        ("ABCD", {"flow": "new_flow", "subflow": "x"}),
        ("twcs", {"brand": "x"}),
    ],
)
def test_unmapped_labels_raise(dataset, fields):
    with pytest.raises(UnmappedLabelError):
        topic_for(dataset, fields, MAPPING)


def conversation(organization, dataset, original_id, agent, **fields):
    return Conversation(
        organization=organization,
        source_dataset=dataset,
        original_id=original_id,
        channel="voice",
        agent=agent,
        source_fields=fields,
    )


@pytest.fixture
async def imported(session):
    organization = Organization(slug="topic-tests", name="Topic Tests")
    hvb, abcd = (
        Agent(organization=organization, external_id="hvb-speaker-1"),
        Agent(organization=organization, external_id="abcd-unknown-agent"),
    )
    session.add_all(
        [
            conversation(
                organization,
                "HarperValleyBank",
                "1",
                hvb,
                task_assigned=["pay bill"],
            ),
            conversation(
                organization,
                "HarperValleyBank",
                "2",
                hvb,
                task_assigned=["pay bill"],
            ),
            conversation(
                organization,
                "HarperValleyBank",
                "3",
                hvb,
                task_assigned=["replace card"],
            ),
            conversation(
                organization,
                "ABCD",
                "1",
                abcd,
                flow="product_defect",
                subflow="refund_initiate",
            ),
            conversation(
                organization,
                "ABCD",
                "2",
                abcd,
                flow="shipping_issue",
                subflow="status",
            ),
        ]
    )
    await session.flush()
    return organization


async def test_every_conversation_gets_exactly_one_topic(session, imported):
    await assign_topics(session, MAPPING, imported.id)

    assert (
        await session.scalar(
            select(func.count()).where(Conversation.topic_id.is_(None))
        )
        == 0
    )
    assert await topic_counts(session, imported.id) == {
        ("HarperValleyBank", "Bill payment"): 2,
        ("HarperValleyBank", "Card replacement"): 1,
        ("ABCD", "Refunds"): 1,
        ("ABCD", "Shipping"): 1,
    }


async def test_rerun_reuses_existing_topics(session, imported):
    await assign_topics(session, MAPPING, imported.id)
    first = (
        await session.execute(select(Topic.id, Topic.name).order_by(Topic.id))
    ).all()
    await assign_topics(session, MAPPING, imported.id)
    assert (
        await session.execute(select(Topic.id, Topic.name).order_by(Topic.id))
    ).all() == first


async def test_unmapped_label_writes_nothing(session, imported):
    agent = await session.scalar(
        select(Agent).where(Agent.external_id == "hvb-speaker-1")
    )
    session.add(
        conversation(
            imported,
            "HarperValleyBank",
            "4",
            agent,
            task_assigned=["open account"],
        )
    )
    await session.flush()

    with pytest.raises(UnmappedLabelError, match="open account"):
        await assign_topics(session, MAPPING, imported.id)
    assert await session.scalar(select(func.count(Topic.id))) == 0
