from enum import StrEnum
from typing import TYPE_CHECKING

from sqlalchemy import (
    CheckConstraint,
    ForeignKey,
    ForeignKeyConstraint,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.core.database import Base
from backend.models.columns import str_enum

if TYPE_CHECKING:
    from backend.models.conversation import Agent


class UserRole(StrEnum):
    AGENT = "agent"
    MANAGER = "manager"


class Organization(Base):
    __tablename__ = "organizations"

    id: Mapped[int] = mapped_column(primary_key=True)
    slug: Mapped[str] = mapped_column(String(100), unique=True)
    name: Mapped[str] = mapped_column(String(200))

    memberships: Mapped[list["OrganizationMembership"]] = relationship(
        back_populates="organization", cascade="all, delete-orphan"
    )


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    # Stable identity supplied by the application's authentication provider.
    external_id: Mapped[str] = mapped_column(String(100), unique=True)
    display_name: Mapped[str] = mapped_column(String(200))
    email: Mapped[str | None] = mapped_column(String(320), unique=True)

    memberships: Mapped[list["OrganizationMembership"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )


class OrganizationMembership(Base):
    __tablename__ = "organization_memberships"
    __table_args__ = (
        UniqueConstraint("organization_id", "user_id"),
        UniqueConstraint("organization_id", "id"),
        UniqueConstraint(
            "organization_id", "agent_id", name="uq_organization_memberships_agent"
        ),
        ForeignKeyConstraint(
            ["organization_id", "agent_id"],
            ["agents.organization_id", "agents.id"],
            name="fk_organization_memberships_agent",
        ),
        CheckConstraint(
            "agent_id IS NULL OR role = 'agent'",
            name="ck_organization_memberships_agent_link_role",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), index=True
    )
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    role: Mapped[UserRole] = mapped_column(str_enum(UserRole, "user_role"))
    # The agent record (from the source data) whose calls this person handled.
    # Ownership checks go through this link; only agent memberships have one.
    agent_id: Mapped[int | None] = mapped_column()

    organization: Mapped[Organization] = relationship(back_populates="memberships")
    user: Mapped[User] = relationship(back_populates="memberships")
    # Only agent_id is written through this relationship. The organization is
    # matched in the join and enforced by the composite foreign key, so
    # clearing the link never clears the membership's organization.
    agent: Mapped["Agent | None"] = relationship(
        primaryjoin="and_(Agent.id == foreign(OrganizationMembership.agent_id), "
        "Agent.organization_id == OrganizationMembership.organization_id)",
    )

    @property
    def can_review_feedback(self) -> bool:
        return self.role is UserRole.MANAGER

    @property
    def can_approve_knowledge(self) -> bool:
        return self.role is UserRole.MANAGER
