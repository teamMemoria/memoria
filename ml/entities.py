"""Stable metric vocabulary; no I/O or runtime dependencies."""

CATEGORIES = ("procedure", "answer-support", "completeness", "communication-style")
RESULTS = ("meets-criteria", "needs-review", "cannot-assess")
CRITERIA_IDS = {
    "clarity": "memoria-wording-clarity",
    "respect": "memoria-wording-respect",
    "acknowledgement": "memoria-wording-acknowledgement",
}
