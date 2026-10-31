from typing import Literal

from backend.schemas.base import ApiModel

# Matches frontend/src/types/knowledge.ts.
KnowledgeKind = Literal["procedure", "knowledge"]
KnowledgeStatus = Literal["approved", "draft", "disputed", "stale", "rejected"]


class KnowledgeSource(ApiModel):
    title: str
    url: str | None


class KnowledgeStep(ApiModel):
    number: int
    text: str


class KnowledgeEntry(ApiModel):
    id: str
    title: str
    topic: str
    kind: KnowledgeKind
    status: KnowledgeStatus
    available_to_agent_ids: list[str]
    version: str
    # Unknown dates stay None; never fill them with a guess.
    approved_at: str | None
    approved_by: str | None
    effective_at: str | None
    last_confirmed_at: str | None
    owner: str | None
    source: KnowledgeSource | None
    paragraphs: list[str]
    steps: list[KnowledgeStep]

    def readable_by(self, agent_id: str) -> bool:
        """Same rule as canReadKnowledge in the frontend."""
        return self.status == "approved" and agent_id in self.available_to_agent_ids
