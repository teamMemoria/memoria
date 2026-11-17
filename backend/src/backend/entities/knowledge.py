"""Knowledge decision requirements, independent of SQL and HTTP."""

from dataclasses import dataclass
from urllib.parse import urlparse


class KnowledgeDecisionRejected(ValueError):
    pass


@dataclass(frozen=True)
class KnowledgeInput:
    outcome: str
    version: str
    verified_reference_url: str | None
    reason: str | None


@dataclass(frozen=True)
class DraftDecisionState:
    pending: bool
    version: str
    reference: dict | None
    has_conflict: bool
    duplicate: bool


def validate_decision(draft: DraftDecisionState, decision: KnowledgeInput):
    if not draft.pending or decision.version != draft.version:
        raise KnowledgeDecisionRejected(
            "Draft changed or already decided. Reload before reviewing."
        )
    if decision.outcome == "approved":
        reference = draft.reference
        if (
            not reference
            or urlparse(reference.get("url", "")).scheme not in {"http", "https"}
            or reference["url"] != decision.verified_reference_url
        ):
            raise KnowledgeDecisionRejected(
                "Check the stored authoritative reference before approval."
            )
        if draft.has_conflict or draft.duplicate:
            raise KnowledgeDecisionRejected(
                "Resolve the draft's conflict or duplicate before approval."
            )
    elif decision.outcome == "rejected":
        if not decision.reason or not decision.reason.strip():
            raise KnowledgeDecisionRejected("A rejection reason is required.")
    else:
        raise KnowledgeDecisionRejected("Unknown decision.")


def require_approver(
    can_approve: bool, member_organization: int, record_organization: int
):
    if not can_approve:
        raise PermissionError("Manager role required for knowledge approval")
    if member_organization != record_organization:
        raise PermissionError("Knowledge approval must stay within one organization")
