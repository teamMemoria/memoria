"""Decode and reject invalid assessment outputs before persistence."""

from backend.entities.assessments import ReportRejectedError


def validate_payload(request, parsed, *, policy=None):
    """Validate wire shape first, then apply the unchanged domain evidence gate."""
    from backend.entities.scoring import validate_scoring
    from backend.schemas.call_review import CategoryScoring, OverallScoring

    report = parsed.assessment_report
    categories = {
        row["category"]: CategoryScoring.model_validate(row["scoring"])
        for row in report["categories"]
    }
    overall = OverallScoring.model_validate(report["overall"])
    validate_scoring(request, parsed, categories, overall, policy=policy)


def validate_report_payload(request, parsed, *, policy=None):
    try:
        validate_payload(request, parsed, policy=policy)
    except (TypeError, ValueError, KeyError, AttributeError) as error:
        raise ReportRejectedError(
            "invalid-assessment", "Assessment contract validation failed"
        ) from error
