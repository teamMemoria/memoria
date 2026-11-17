"""Review permissions are separate from automated findings."""


def require_reviewer(
    can_review: bool, member_organization: int, record_organization: int
) -> None:
    if not can_review:
        raise PermissionError("Manager role required for feedback review")
    if member_organization != record_organization:
        raise PermissionError("Feedback review must stay within one organization")
