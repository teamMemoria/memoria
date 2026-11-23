"""Combine metric scores using a configured weight profile or evaluation form."""

from collections.abc import Callable
from dataclasses import dataclass
from math import fsum, isfinite

from backend.entities.assessments import CRITERION_IDS


@dataclass(frozen=True)
class PercentagePolicy:
    version: str
    calculate: Callable[[float, float, float], float | None]


def form_weights(criteria):
    """Only the four enabled criteria in the selected evaluation form may supply weights."""
    enabled = [item for item in criteria if item["enabled"]]
    weights = {item["category"]: float(item["weight"]) for item in enabled}
    if len(enabled) != len(CRITERION_IDS) or set(weights) != set(CRITERION_IDS):
        return None
    if any(not isfinite(w) or w < 0 for w in weights.values()):
        return None
    total = sum(weights.values())
    return {k: 100 * w / total for k, w in weights.items()} if total else None


def weighted_percentage(values, weights):
    if not weights or any(values[k] is None for k in weights):
        return None
    return fsum(values[k] * w / 100 for k, w in weights.items())


def overall_for_form(criteria, version, scores, coverage):
    return _overall(
        form_weights(criteria), "evaluation-form", str(version), scores, coverage
    )


def overall_for_profile(profile, scores, coverage):
    return _overall(profile.weights, profile.id, profile.version, scores, coverage)


def _overall(weights, profile_id, profile_version, scores, coverage):
    score = weighted_percentage(scores, weights)
    reason = None
    if not weights:
        reason = "The evaluation form needs weights for all four metrics."
    elif score is None:
        reason = "An overall score requires four metric scores."
    return {
        "score": score,
        "coverage": weighted_percentage(coverage, weights),
        "weights": dict(weights) if weights is not None else None,
        "profile_id": profile_id if weights else None,
        "profile_version": profile_version if weights else None,
        "reason": reason,
    }
