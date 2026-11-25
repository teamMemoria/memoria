"""Load the Layer 1 catalogue as pending drafts for the demo."""

import argparse
import asyncio

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.config import get_settings
from backend.entities.policies import AUTHORED_POLICY_PREFIX
from backend.frameworks.data_access.authored_policies import (
    authored_answer,
    load_authored_catalogue,
)
from backend.frameworks.database.models import (
    DraftStatus,
    KnowledgeDraft,
    Organization,
    Topic,
)
from backend.frameworks.database.session import create_database


async def seed_demo_policies(session: AsyncSession, organization_slug: str) -> int:
    """Return the number of new drafts. The caller owns the transaction."""
    catalogue = load_authored_catalogue()
    if catalogue is None:
        raise ValueError("Expected a catalogue of Memoria-authored policies.")
    organization_id = await session.scalar(
        select(Organization.id).where(Organization.slug == organization_slug)
    )
    if organization_id is None:
        raise ValueError(f"Unknown organization: {organization_slug}")

    created = 0
    for policy in catalogue["policies"]:
        if not policy["id"].startswith(AUTHORED_POLICY_PREFIX):
            raise ValueError("A policy ID is outside the Memoria-authored catalogue.")
        topic = {
            "organization_id": organization_id,
            "source_dataset": "Memoria",
            "name": policy["title"],
        }
        topic_id = await session.scalar(
            insert(Topic)
            .values(**topic)
            .on_conflict_do_nothing(index_elements=list(topic))
            .returning(Topic.id)
        )
        if topic_id is None:
            topic_id = (
                await session.execute(select(Topic.id).filter_by(**topic))
            ).scalar_one()

        draft_id = await session.scalar(
            insert(KnowledgeDraft)
            .values(
                organization_id=organization_id,
                topic_id=topic_id,
                source_key=policy["id"],
                question=policy["question"],
                answer_text=authored_answer(policy),
                status=DraftStatus.PENDING,
            )
            .on_conflict_do_nothing(index_elements=["organization_id", "source_key"])
            .returning(KnowledgeDraft.id)
        )
        created += draft_id is not None
    return created


async def run(organization_slug: str) -> None:
    database = create_database(get_settings().database_url)
    try:
        async with database.sessions() as session, session.begin():
            created = await seed_demo_policies(session, organization_slug)
    finally:
        await database.close()

    print(f"Created {created} pending Layer 1 policies in {organization_slug}.")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--organization", default="default", help="Organization slug")
    args = parser.parse_args()
    try:
        asyncio.run(run(args.organization))
    except ValueError as error:
        parser.exit(1, f"{error}\n")


if __name__ == "__main__":
    main()
