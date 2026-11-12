from typing import Any, Literal, Self

from pydantic import Field, model_validator

from backend.schemas.base import ApiModel
from backend.schemas.knowledge import KnowledgeEntry

# Matches frontend/src/types/callReview.ts.
AuditResult = Literal["needs-review", "meets-criteria", "cannot-assess"]
CriterionId = Literal[
    "procedure", "answer-support", "completeness", "communication-style"
]
CRITERION_IDS: tuple[CriterionId, ...] = (
    "procedure",
    "answer-support",
    "completeness",
    "communication-style",
)


class TranscriptTurn(ApiModel):
    number: int  # original turn number; gaps are allowed and must be kept
    speaker: Literal["Agent", "Customer", "System action"]
    text: str
    time: str | None


class Transcript(ApiModel):
    complete: bool
    turns: list[TranscriptTurn]
    unavailable_reason: str | None

    @model_validator(mode="after")
    def turns_are_unique_and_ordered(self) -> Self:
        numbers = [turn.number for turn in self.turns]
        if numbers != sorted(set(numbers)):
            raise ValueError("transcript turn numbers must be unique and ascending")
        return self


class ScoringCheck(ApiModel):
    id: str
    rule_id: str
    requirement: str
    outcome: Literal["supported", "breach", "unresolved", "not-applicable"]
    earned: Literal[0, 1] | None
    maximum: Literal[1]
    explanation: str
    advice: str
    citations: list[dict[str, Any]]
    critical: bool


class CategoryScoring(ApiModel):
    score: float | None
    coverage: float | None
    earned: int
    assessable: int
    possible: int | None
    checks: list[ScoringCheck]
    limitations: list[str]
    processing_error: str | None
    interpretation_limits: list[str]
    inventory_complete: bool = True


class OverallScoring(ApiModel):
    score: float | None
    coverage: float | None
    profile_id: str | None
    profile_version: str | None
    reason: str | None
    weights: dict[CriterionId, float] | None


class AuditCriterion(ApiModel):
    id: CriterionId
    title: str
    result: AuditResult
    explanation: str
    evidence_turn_numbers: list[int]
    finding_id: str | None
    reference_id: str | None
    scoring: CategoryScoring | None = None


class ProcedureStep(ApiModel):
    label: str
    status: Literal["observed", "not-visible", "cannot-assess"]
    turn_numbers: list[int]
    note: str | None


class CallFinding(ApiModel):
    id: str
    title: str
    criterion_id: CriterionId
    explanation: str
    suggestion: str
    evidence_turn_numbers: list[int]
    reference_id: str | None
    reference_step: int | None
    procedure_steps: list[ProcedureStep]
    critical: bool = False


class AgentContext(ApiModel):
    """The agent's own note on the call. Saving it never requests a review."""

    text: str
    saved_at: str


class ReviewRequest(ApiModel):
    """An agent's request for a Manager to review one finding."""

    finding_id: str
    reason: str
    requested_at: str
    status: Literal["requested", "complete"]


class ManagerDecision(ApiModel):
    outcome: Literal["confirmed", "corrected", "dismissed", "cannot-assess"]
    reason: str
    feedback: str
    manager_name: str
    decided_at: str


class AssessmentVersion(ApiModel):
    source_id: str
    as_of: str
    rules: str
    transcript: str


class RequestLink(ApiModel):
    id: str
    text: str
    state: Literal["active", "answered", "refused", "promised", "changed", "withdrawn"]
    request_turns: list[int]
    response_turns: list[int]
    limitations: list[str]


class CallReview(ApiModel):
    source_id: str | None = None
    id: str
    agent_id: str
    agent_name: str
    topic: str
    # None when the source recorded no date or length; never guessed.
    date: str | None
    duration: str | None
    summary: str
    status: Literal["ready", "processing", "unavailable"]
    criteria: list[AuditCriterion]
    findings: list[CallFinding]
    transcript: Transcript | None
    references: list[KnowledgeEntry]
    agent_context: AgentContext | None
    review_request: ReviewRequest | None
    # The Manager decision lives beside the automated assessment, never inside it.
    decision: ManagerDecision | None
    overall_scoring: OverallScoring | None = None
    assessment_version: AssessmentVersion | None = None
    request_links: list[RequestLink] = Field(default_factory=list)

    @model_validator(mode="after")
    def check_assessment_shape(self) -> Self:
        if self.status in ("processing", "unavailable"):
            if self.criteria or self.findings or self.decision or self.review_request:
                raise ValueError("a processing call has no assessment or decision yet")
            return self

        ids = [criterion.id for criterion in self.criteria]
        if sorted(ids) != sorted(CRITERION_IDS):
            raise ValueError(
                f"a ready call needs exactly one result per criterion {CRITERION_IDS}"
            )
        return self

    @model_validator(mode="after")
    def check_evidence_references(self) -> Self:
        turns = (
            {turn.number for turn in self.transcript.turns}
            if self.transcript
            else set()
        )
        finding_ids = {finding.id for finding in self.findings}
        reference_ids = {reference.id for reference in self.references}

        def check_turns(where: str, numbers: list[int]) -> None:
            missing = sorted(set(numbers) - turns)
            if missing:
                raise ValueError(
                    f"{where} cites turns {missing} that are not in the transcript"
                )

        def check_reference(where: str, reference_id: str | None) -> None:
            if reference_id is not None and reference_id not in reference_ids:
                raise ValueError(
                    f"{where} cites reference {reference_id!r} that is not included"
                )

        for criterion in self.criteria:
            where = f"criterion {criterion.id!r}"
            # Missing evidence means "cannot assess", never an agent failure.
            if (
                criterion.result == "needs-review"
                and not criterion.evidence_turn_numbers
            ):
                raise ValueError(f"{where} is needs-review but cites no evidence turns")
            check_turns(where, criterion.evidence_turn_numbers)
            check_reference(where, criterion.reference_id)
            if (
                criterion.finding_id is not None
                and criterion.finding_id not in finding_ids
            ):
                raise ValueError(
                    f"{where} cites unknown finding {criterion.finding_id!r}"
                )

        if (
            self.review_request is not None
            and self.review_request.finding_id not in finding_ids
        ):
            raise ValueError(
                f"review request cites unknown finding {self.review_request.finding_id!r}"
            )

        for finding in self.findings:
            where = f"finding {finding.id!r}"
            check_turns(where, finding.evidence_turn_numbers)
            check_reference(where, finding.reference_id)
            for step in finding.procedure_steps:
                check_turns(f"{where} step {step.label!r}", step.turn_numbers)
        return self
