from collections import Counter
from pathlib import Path
from typing import Annotated

from fastapi import Depends, HTTPException, Request
from pydantic import TypeAdapter

from backend.schemas import CallReview, Conversation, DemoProfile
from backend.schemas.reviews import TeamConversation


class DemoScorecards:
    """Overlay archived assessments only on conversations authorized by the API."""

    def __init__(self, source: Path):
        cards = TypeAdapter(list[CallReview]).validate_json(source.read_bytes())
        self.by_source = {card.source_id: card for card in cards if card.source_id}
        if (
            len(cards) != 25
            or len(self.by_source) != 25
            or any(
                card.status != "ready"
                or not card.assessment_version
                or card.assessment_version.scoring_method
                != "calibrated-simulation-midpoint-v1"
                or not card.transcript
                or not card.overall_scoring
                or card.overall_scoring.score is None
                or card.findings
                or card.references
                or card.agent_context
                or card.review_request
                or card.decision
                for card in cards
            )
        ):
            raise ValueError("Expected 25 distinct archived simulation scorecards")
        self.counts = Counter(card.agent_name for card in cards)
        self.narration_directory = source.parent / "narration"

    def profiles(self, profiles: list[DemoProfile]) -> list[DemoProfile]:
        return [
            profile
            if profile.role == "manager"
            else profile.model_copy(
                update={"conversation_count": self.counts[profile.display_name]}
            )
            for profile in profiles
            if profile.role == "manager" or self.counts[profile.display_name]
        ]

    def match(self, record: Conversation | CallReview) -> CallReview | None:
        card = self.by_source.get(record.source_id or "")
        return card if card and card.agent_name == record.agent_name else None

    def conversations[Row: Conversation](self, rows: list[Row]) -> list[Row]:
        visible = []
        for row in rows:
            card = self.match(row)
            if card and card.overall_scoring:
                update = {
                    "topic": card.topic,
                    "date": card.date,
                    "simulation_score": card.overall_scoring.score,
                    "overall_scoring": card.overall_scoring,
                    "automated_result": "cannot-assess",
                    "review_status": None,
                }
                if isinstance(row, TeamConversation):
                    update["flag"] = None
                visible.append(row.model_copy(update=update))
        return visible

    def call(self, record: CallReview) -> CallReview:
        card = self.match(record)
        if card is None:
            raise HTTPException(404, "Conversation not found")
        return card.model_copy(
            update={
                "id": record.id,
                "agent_id": record.agent_id,
                "assessment_source": "simulation",
            }
        )


def get_demo_scorecards(request: Request) -> DemoScorecards | None:
    return request.app.state.demo_scorecards


DemoScorecardsDep = Annotated[DemoScorecards | None, Depends(get_demo_scorecards)]


def require_saved_calls(scorecards: DemoScorecardsDep) -> None:
    if scorecards is not None:
        raise HTTPException(405, "Simulation scorecards are read-only")
