"""Engine-independent evidence import and the final assessment storage gate.

Scoring adapters supply a policy-aware report_parser to AnalysisService. This
module never chooses checks, grants approvals, or loads a scorer or rule catalogue.
"""

from copy import deepcopy

from sqlalchemy import select
from sqlalchemy.orm import selectinload

from backend.frameworks.database.models import Agent, Conversation, Speaker, Turn
from backend.interface_adapters.controllers.assessments import validate_payload


def validate_prepared(evidence):
    from ml.abcd import validate_evidence

    validate_evidence(evidence)
    if len(evidence["conversations"]) != 1:
        raise ValueError("Import one prepared conversation at a time")
    conversation = evidence["conversations"][0]
    if conversation["split"] != "train":
        raise ValueError("The prepared ABCD import accepts training evidence only")
    return conversation


__all__ = ["validate_payload"]


async def import_prepared(session, organization_id, agent_id, evidence):
    """Import versioned training evidence; ownership is supplied, never inferred."""
    source = validate_prepared(evidence)
    agent = await session.get(Agent, agent_id)
    if agent is None or agent.organization_id != organization_id:
        raise ValueError("The agent must belong to the importing organization")
    existing = await session.scalar(
        select(Conversation)
        .where(
            Conversation.organization_id == organization_id,
            Conversation.source_dataset == "ABCD",
            Conversation.original_id == source["id"],
        )
        .options(selectinload(Conversation.turns))
    )
    if existing is not None:
        if existing.agent_id != agent_id or existing.canonical_evidence != evidence:
            raise ValueError(
                "An existing conversation has different evidence or ownership"
            )
        return existing
    speaker = {
        "agent": Speaker.AGENT,
        "customer": Speaker.CUSTOMER,
        "action": Speaker.SYSTEM_ACTION,
    }
    conversation = Conversation(
        organization_id=organization_id,
        agent_id=agent_id,
        source_dataset="ABCD",
        original_id=source["id"],
        channel="text",
        canonical_evidence=deepcopy(evidence),
        source_fields={},
        turns=[
            Turn(
                line_number=e["turn_id"], speaker=speaker[e["speaker"]], text=e["text"]
            )
            for e in source["events"]
        ],
    )
    session.add(conversation)
    await session.flush()
    return conversation
