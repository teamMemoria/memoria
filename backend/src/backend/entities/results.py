"""Stable stored result vocabulary, independent of persistence."""

from enum import StrEnum


class FindingCategory(StrEnum):
    PROCEDURE = "procedure"
    ANSWER_SUPPORT = "answer_support"
    COMPLETENESS = "completeness"
    COMMUNICATION = "communication"


class FindingResult(StrEnum):
    PASS = "pass"
    NEEDS_WORK = "needs_work"
    # Not enough in the transcript to judge. Not a failure.
    CANNOT_ASSESS = "cannot_assess"


class ManagerReviewOutcome(StrEnum):
    CONFIRMED = "confirmed"
    CORRECTED = "corrected"
    DISMISSED = "dismissed"
    CANNOT_ASSESS = "cannot_assess"


CRITERION_FOR_CATEGORY = {
    FindingCategory.PROCEDURE: "procedure",
    FindingCategory.ANSWER_SUPPORT: "answer-support",
    FindingCategory.COMPLETENESS: "completeness",
    FindingCategory.COMMUNICATION: "communication-style",
}
CATEGORY_FOR_CRITERION = {value: key for key, value in CRITERION_FOR_CATEGORY.items()}
CRITERION_TITLES = {
    "procedure": "Procedure",
    "answer-support": "Answer support",
    "completeness": "Completeness",
    "communication-style": "Communication style",
}
RESULT_NAMES = {
    FindingResult.PASS: "meets-criteria",
    FindingResult.NEEDS_WORK: "needs-review",
    FindingResult.CANNOT_ASSESS: "cannot-assess",
}
OUTCOME_NAMES = {
    ManagerReviewOutcome.CONFIRMED: "confirmed",
    ManagerReviewOutcome.CORRECTED: "corrected",
    ManagerReviewOutcome.DISMISSED: "dismissed",
    ManagerReviewOutcome.CANNOT_ASSESS: "cannot-assess",
}


class Speaker(StrEnum):
    AGENT = "agent"
    CUSTOMER = "customer"
    SYSTEM_ACTION = "system_action"


class EntryStatus(StrEnum):
    APPROVED = "approved"
    DISPUTED = "disputed"
    STALE = "stale"
    WITHDRAWN = "withdrawn"


class DraftStatus(StrEnum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"


class ReviewAction(StrEnum):
    APPROVED = "approved"
    EDITED = "edited"
    REJECTED = "rejected"
    UNAPPROVED = "unapproved"
