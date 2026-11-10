"""add evaluation forms and criteria

Revision ID: 84b37f614ac2
Revises: b7e2f4a91c3d
Create Date: 2026-11-01
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "84b37f614ac2"
down_revision: str | Sequence[str] | None = "b7e2f4a91c3d"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "evaluation_forms",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("name"),
    )
    op.create_table(
        "evaluation_form_versions",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("form_id", sa.Integer(), nullable=False),
        sa.Column("version_number", sa.Integer(), nullable=False),
        sa.Column(
            "is_active", sa.Boolean(), server_default=sa.text("false"), nullable=False
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint("version_number > 0", name="ck_form_version_positive"),
        sa.ForeignKeyConstraint(
            ["form_id"], ["evaluation_forms.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("form_id", "version_number"),
    )
    op.create_index(
        "uq_active_evaluation_form_version",
        "evaluation_form_versions",
        ["form_id"],
        unique=True,
        postgresql_where=sa.text("is_active"),
    )
    op.create_table(
        "evaluation_criteria",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("form_version_id", sa.Integer(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column(
            "category",
            sa.Enum(
                "procedure",
                "answer_support",
                "completeness",
                "communication",
                name="evaluation_criterion_category",
                native_enum=False,
                create_constraint=True,
                length=20,
            ),
            nullable=False,
        ),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("weight", sa.Numeric(precision=5, scale=4), nullable=False),
        sa.Column(
            "enabled", sa.Boolean(), server_default=sa.text("true"), nullable=False
        ),
        sa.Column("pass_threshold", sa.Numeric(precision=5, scale=4), nullable=False),
        sa.CheckConstraint("position > 0", name="ck_criterion_position_positive"),
        sa.CheckConstraint(
            "weight >= 0 AND weight <= 1", name="ck_criterion_weight_range"
        ),
        sa.CheckConstraint(
            "pass_threshold >= 0 AND pass_threshold <= 1",
            name="ck_criterion_pass_threshold_range",
        ),
        sa.ForeignKeyConstraint(
            ["form_version_id"], ["evaluation_form_versions.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("form_version_id", "category"),
        sa.UniqueConstraint("form_version_id", "position"),
    )
    bind = op.get_bind()
    form_id = bind.execute(
        sa.text(
            "INSERT INTO evaluation_forms (name, description) "
            "VALUES ('Default quality form', 'Initial four-category rubric') "
            "RETURNING id"
        )
    ).scalar_one()
    version_id = bind.execute(
        sa.text(
            "INSERT INTO evaluation_form_versions (form_id, version_number, is_active) "
            "VALUES (:form_id, 1, true) RETURNING id"
        ),
        {"form_id": form_id},
    ).scalar_one()
    bind.execute(
        sa.text(
            "INSERT INTO evaluation_criteria "
            "(form_version_id, position, category, name, weight, pass_threshold) "
            "VALUES "
            "(:version_id, 1, 'procedure', 'Procedure', 0.2500, 0.7000), "
            "(:version_id, 2, 'answer_support', 'Answer Support', 0.2500, 0.7000), "
            "(:version_id, 3, 'completeness', 'Completeness', 0.2500, 0.7000), "
            "(:version_id, 4, 'communication', 'Communication', 0.2500, 0.7000)"
        ),
        {"version_id": version_id},
    )
    op.add_column(
        "audits", sa.Column("evaluation_form_version_id", sa.Integer(), nullable=True)
    )
    bind.execute(
        sa.text("UPDATE audits SET evaluation_form_version_id = :version_id"),
        {"version_id": version_id},
    )
    op.alter_column("audits", "evaluation_form_version_id", nullable=False)
    op.create_foreign_key(
        "fk_audits_evaluation_form_version_id",
        "audits",
        "evaluation_form_versions",
        ["evaluation_form_version_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_index(
        op.f("ix_audits_evaluation_form_version_id"),
        "audits",
        ["evaluation_form_version_id"],
        unique=False,
    )
    op.execute(
        """
        CREATE FUNCTION protect_used_evaluation_criterion() RETURNS trigger AS $$
        BEGIN
            IF TG_OP = 'INSERT' THEN
                IF EXISTS (SELECT 1 FROM audits WHERE evaluation_form_version_id = NEW.form_version_id) THEN
                    RAISE EXCEPTION 'Cannot change criteria of a form version used by an audit';
                END IF;
            ELSIF TG_OP = 'DELETE' THEN
                IF EXISTS (SELECT 1 FROM audits WHERE evaluation_form_version_id = OLD.form_version_id) THEN
                    RAISE EXCEPTION 'Cannot change criteria of a form version used by an audit';
                END IF;
            ELSIF EXISTS (
                SELECT 1 FROM audits
                WHERE evaluation_form_version_id IN (OLD.form_version_id, NEW.form_version_id)
            ) THEN
                RAISE EXCEPTION 'Cannot change criteria of a form version used by an audit';
            END IF;
            IF TG_OP = 'DELETE' THEN
                RETURN OLD;
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql
        """
    )
    op.execute(
        """
        CREATE TRIGGER protect_used_evaluation_criterion
        BEFORE INSERT OR UPDATE OR DELETE ON evaluation_criteria
        FOR EACH ROW EXECUTE FUNCTION protect_used_evaluation_criterion()
        """
    )
    op.execute(
        """
        CREATE FUNCTION protect_used_evaluation_form_version() RETURNS trigger AS $$
        BEGIN
            IF (OLD.form_id, OLD.version_number, OLD.created_at)
                IS DISTINCT FROM (NEW.form_id, NEW.version_number, NEW.created_at)
                AND EXISTS (SELECT 1 FROM audits WHERE evaluation_form_version_id = OLD.id) THEN
                RAISE EXCEPTION 'Cannot change a form version used by an audit';
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql
        """
    )
    op.execute(
        """
        CREATE TRIGGER protect_used_evaluation_form_version
        BEFORE UPDATE ON evaluation_form_versions
        FOR EACH ROW EXECUTE FUNCTION protect_used_evaluation_form_version()
        """
    )


def downgrade() -> None:
    op.execute(
        "DROP TRIGGER protect_used_evaluation_form_version ON evaluation_form_versions"
    )
    op.execute("DROP FUNCTION protect_used_evaluation_form_version()")
    op.execute("DROP TRIGGER protect_used_evaluation_criterion ON evaluation_criteria")
    op.execute("DROP FUNCTION protect_used_evaluation_criterion()")
    op.drop_index(op.f("ix_audits_evaluation_form_version_id"), table_name="audits")
    op.drop_constraint(
        "fk_audits_evaluation_form_version_id", "audits", type_="foreignkey"
    )
    op.drop_column("audits", "evaluation_form_version_id")
    op.drop_table("evaluation_criteria")
    op.drop_index(
        "uq_active_evaluation_form_version", table_name="evaluation_form_versions"
    )
    op.drop_table("evaluation_form_versions")
    op.drop_table("evaluation_forms")
