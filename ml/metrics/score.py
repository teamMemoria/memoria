"""Pure arithmetic for the template assessment's numeric score and evidence coverage."""

from fractions import Fraction

MIDPOINT_VERSION = "applicable-points-midpoint-v2"


def midpoint_percentage(earned, resolved, possible):
    """Middle of the possible score range, before display rounding."""
    if not 0 <= earned <= resolved <= possible:
        raise ValueError("Inconsistent assessment points")
    if resolved == 0:
        return None
    return 50 * (2 * earned + possible - resolved) / possible


def score_checks(checks):
    """Use allocated points. Unresolved points affect the range but earn no credit."""
    earned = resolved = available = Fraction(0)
    for check in checks:
        points = Fraction(check["maximum"])
        if points <= 0 or isinstance(check["maximum"], bool):
            raise ValueError("A check must have a positive point allocation")
        outcome = check["outcome"]
        if outcome == "not-applicable":
            continue
        available += points
        if outcome in ("supported", "breach"):
            resolved += points
            if outcome == "supported":
                earned += points
        elif outcome != "unresolved":
            raise ValueError("Unsupported scoring outcome")

    score = midpoint_percentage(earned, resolved, available)
    return {
        "score": float(score) if score is not None else None,
        "coverage": float(100 * resolved / available) if available else None,
        "earned": float(earned),
        "assessable": float(resolved),
        "possible": float(available),
    }
