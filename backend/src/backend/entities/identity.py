"""Who is making the request, and what they are allowed to do."""

from dataclasses import dataclass
from enum import StrEnum


class Permission(StrEnum):
    CONVERSATIONS_READ_OWN = "conversations:read-own"
    KNOWLEDGE_READ = "knowledge:read"
    FEEDBACK_REVIEW = "feedback:review"
    # Separate from FEEDBACK_REVIEW: reviewing an agent's feedback does not let
    # a Manager approve knowledge, and approving knowledge does not let an
    # approver review feedback.
    KNOWLEDGE_APPROVE = "knowledge:approve"


AGENT_PERMISSIONS = frozenset(
    {Permission.CONVERSATIONS_READ_OWN, Permission.KNOWLEDGE_READ}
)
MANAGER_PERMISSIONS = frozenset({Permission.FEEDBACK_REVIEW, Permission.KNOWLEDGE_READ})
KNOWLEDGE_APPROVER_PERMISSIONS = frozenset(
    {Permission.KNOWLEDGE_APPROVE, Permission.KNOWLEDGE_READ}
)


@dataclass(frozen=True)
class CurrentUser:
    user_id: str
    organization_id: str
    permissions: frozenset[Permission]

    def has(self, permission: Permission) -> bool:
        return permission in self.permissions


def permissions_for_membership(
    *, is_agent: bool, can_review_feedback: bool, can_approve_knowledge: bool
) -> frozenset[Permission]:
    """Permissions granted by a stored organization membership.

    Every member can read approved guidance. Only agents read their own calls.
    Feedback review and knowledge approval each come from their own capability
    on the membership, so they stay separate even if one role holds both.
    """
    permissions = {Permission.KNOWLEDGE_READ}
    if is_agent:
        permissions.add(Permission.CONVERSATIONS_READ_OWN)
    if can_review_feedback:
        permissions.add(Permission.FEEDBACK_REVIEW)
    if can_approve_knowledge:
        permissions.add(Permission.KNOWLEDGE_APPROVE)
    return frozenset(permissions)


def same_organization(user: CurrentUser, organization_id: str) -> bool:
    return user.organization_id == organization_id


def can_read_agent_record(
    user: CurrentUser, organization_id: str, agent_id: str
) -> bool:
    """An agent may read records that belong to them, inside their own organization."""
    return (
        same_organization(user, organization_id)
        and user.has(Permission.CONVERSATIONS_READ_OWN)
        and user.user_id == agent_id
    )


# Fixed identities for local development and tests, until a login system exists.
# They match the people in backend/providers/fixture_data.py.
DEV_IDENTITIES = {
    identity.user_id: identity
    for identity in [
        CurrentUser("agent-alex-morgan", "org-northwind", AGENT_PERMISSIONS),
        CurrentUser("agent-sam-rivera", "org-northwind", AGENT_PERMISSIONS),
        CurrentUser("manager-maya-chen", "org-northwind", MANAGER_PERMISSIONS),
        CurrentUser(
            "approver-devon-park", "org-northwind", KNOWLEDGE_APPROVER_PERMISSIONS
        ),
        CurrentUser("agent-riley-chen", "org-harbor", AGENT_PERMISSIONS),
    ]
}
