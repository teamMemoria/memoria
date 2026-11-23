"""Infer Layer 2 knowledge candidates from company calls."""

from typing import Protocol

from backend.entities.inferred_knowledge import DEFAULT, Claim, Settings, Topic, learn


class ClaimSource(Protocol):
    def claims(self) -> list[Claim]: ...


class InferCandidates:
    def __init__(self, source: ClaimSource, settings: Settings = DEFAULT):
        self.source = source
        self.settings = settings

    def execute(self) -> list[Topic]:
        claims = self.source.claims()
        if not claims:
            raise ValueError("none of the calls gave a value to learn from")
        return learn(claims, self.settings)
