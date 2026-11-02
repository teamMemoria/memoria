from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.core.database import Base
from backend.models.audit import FindingCategory
from backend.models.columns import str_enum


class EvaluationForm(Base):
    """A named set of quality expectations with immutable versions."""

    __tablename__ = "evaluation_forms"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(200), unique=True)
    description: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()")
    )

    versions: Mapped[list["EvaluationFormVersion"]] = relationship(
        back_populates="form",
        cascade="all, delete-orphan",
        order_by="EvaluationFormVersion.version_number",
    )


class EvaluationFormVersion(Base):
    """A scoring configuration retained for reproducible historical audits."""

    __tablename__ = "evaluation_form_versions"
    __table_args__ = (
        CheckConstraint("version_number > 0", name="ck_form_version_positive"),
        UniqueConstraint("form_id", "version_number"),
        Index(
            "uq_active_evaluation_form_version",
            "form_id",
            unique=True,
            postgresql_where=text("is_active"),
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    form_id: Mapped[int] = mapped_column(
        ForeignKey("evaluation_forms.id", ondelete="CASCADE")
    )
    version_number: Mapped[int] = mapped_column(Integer)
    is_active: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default="false"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()")
    )

    form: Mapped[EvaluationForm] = relationship(back_populates="versions")
    criteria: Mapped[list["EvaluationCriterion"]] = relationship(
        back_populates="form_version",
        cascade="all, delete-orphan",
        order_by="EvaluationCriterion.position",
    )


class EvaluationCriterion(Base):
    """One ordered, weighted category in an evaluation form version."""

    __tablename__ = "evaluation_criteria"
    __table_args__ = (
        CheckConstraint("position > 0", name="ck_criterion_position_positive"),
        CheckConstraint(
            "weight >= 0 AND weight <= 1", name="ck_criterion_weight_range"
        ),
        CheckConstraint(
            "pass_threshold >= 0 AND pass_threshold <= 1",
            name="ck_criterion_pass_threshold_range",
        ),
        UniqueConstraint("form_version_id", "position"),
        UniqueConstraint("form_version_id", "category"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    form_version_id: Mapped[int] = mapped_column(
        ForeignKey("evaluation_form_versions.id", ondelete="CASCADE")
    )
    position: Mapped[int] = mapped_column(Integer)
    category: Mapped[FindingCategory] = mapped_column(
        str_enum(FindingCategory, "evaluation_criterion_category")
    )
    name: Mapped[str] = mapped_column(String(200))
    description: Mapped[str | None] = mapped_column(Text)
    weight: Mapped[Decimal] = mapped_column(Numeric(5, 4))
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    pass_threshold: Mapped[Decimal] = mapped_column(Numeric(5, 4))

    form_version: Mapped[EvaluationFormVersion] = relationship(
        back_populates="criteria"
    )
