"""candidate preparation context

Revision ID: 20260826_0005
Revises: 20260824_0004
Create Date: 2026-08-26 00:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260826_0005"
down_revision: str | None = "20260824_0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "candidate_preparations",
        sa.Column("owner_id", sa.UUID(), nullable=False),
        sa.Column("company_name", sa.String(length=200), nullable=False),
        sa.Column("role_family", sa.String(length=32), nullable=False),
        sa.Column("role_family_other", sa.String(length=100), nullable=True),
        sa.Column("role_title", sa.String(length=200), nullable=False),
        sa.Column("seniority", sa.String(length=16), nullable=False),
        sa.Column("seniority_other", sa.String(length=100), nullable=True),
        sa.Column("target_country_code", sa.String(length=2), nullable=False),
        sa.Column("target_office", sa.String(length=200), nullable=True),
        sa.Column("interview_round", sa.String(length=32), nullable=False),
        sa.Column("interview_round_other", sa.String(length=100), nullable=True),
        sa.Column("interview_language", sa.String(length=8), nullable=False),
        sa.Column("status", sa.String(length=16), server_default="draft", nullable=False),
        sa.Column("privacy_policy_version_id", sa.UUID(), nullable=False),
        sa.Column("jurisdiction_code", sa.String(length=64), nullable=False),
        sa.Column("legal_basis", sa.String(length=64), nullable=False),
        sa.Column("retention_rule_id", sa.UUID(), nullable=False),
        sa.Column("retain_until", sa.DateTime(timezone=True), nullable=False),
        sa.Column("retention_action", sa.String(length=16), nullable=False),
        sa.Column("idempotency_key_hash", sa.String(length=64), nullable=False),
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("version", sa.BigInteger(), server_default=sa.text("1"), nullable=False),
        sa.CheckConstraint(
            "btrim(company_name) <> ''",
            name=op.f("ck_candidate_preparations_company_name_nonempty"),
        ),
        sa.CheckConstraint(
            "btrim(role_title) <> ''",
            name=op.f("ck_candidate_preparations_role_title_nonempty"),
        ),
        sa.CheckConstraint(
            "role_family IN ('software_engineering', 'data_and_ai', 'product', 'design', "
            "'quality_assurance', 'security', 'cloud_and_devops', "
            "'business_and_operations', 'other')",
            name=op.f("ck_candidate_preparations_role_family_allowed"),
        ),
        sa.CheckConstraint(
            "(role_family = 'other' AND role_family_other IS NOT NULL AND "
            "btrim(role_family_other) <> '') OR "
            "(role_family <> 'other' AND role_family_other IS NULL)",
            name=op.f("ck_candidate_preparations_role_family_fallback_consistent"),
        ),
        sa.CheckConstraint(
            "seniority IN ('intern', 'entry', 'junior', 'mid', 'senior', 'lead', "
            "'staff', 'principal', 'manager', 'director', 'executive', 'other')",
            name=op.f("ck_candidate_preparations_seniority_allowed"),
        ),
        sa.CheckConstraint(
            "(seniority = 'other' AND seniority_other IS NOT NULL AND "
            "btrim(seniority_other) <> '') OR "
            "(seniority <> 'other' AND seniority_other IS NULL)",
            name=op.f("ck_candidate_preparations_seniority_fallback_consistent"),
        ),
        sa.CheckConstraint(
            "target_country_code ~ '^[A-Z]{2}$'",
            name=op.f("ck_candidate_preparations_target_country_code_format"),
        ),
        sa.CheckConstraint(
            "target_office IS NULL OR btrim(target_office) <> ''",
            name=op.f("ck_candidate_preparations_target_office_nonempty"),
        ),
        sa.CheckConstraint(
            "interview_round IN ('recruiter_screen', 'hiring_manager', "
            "'technical_screen', 'coding', 'system_design', 'behavioral', "
            "'case_study', 'take_home_review', 'panel', 'final', 'other')",
            name=op.f("ck_candidate_preparations_interview_round_allowed"),
        ),
        sa.CheckConstraint(
            "(interview_round = 'other' AND interview_round_other IS NOT NULL AND "
            "btrim(interview_round_other) <> '') OR "
            "(interview_round <> 'other' AND interview_round_other IS NULL)",
            name=op.f("ck_candidate_preparations_interview_round_fallback_consistent"),
        ),
        sa.CheckConstraint(
            "interview_language IN ('az', 'en')",
            name=op.f("ck_candidate_preparations_interview_language_allowed"),
        ),
        sa.CheckConstraint(
            "status IN ('draft', 'archived')",
            name=op.f("ck_candidate_preparations_status_allowed"),
        ),
        sa.CheckConstraint(
            "version > 0",
            name=op.f("ck_candidate_preparations_version_positive"),
        ),
        sa.CheckConstraint(
            "char_length(idempotency_key_hash) = 64",
            name=op.f("ck_candidate_preparations_idempotency_digest_length"),
        ),
        sa.CheckConstraint(
            "retain_until > created_at",
            name=op.f("ck_candidate_preparations_retention_after_creation"),
        ),
        sa.CheckConstraint(
            "retention_action = 'delete'",
            name=op.f("ck_candidate_preparations_retention_action_delete_only"),
        ),
        sa.ForeignKeyConstraint(
            ["owner_id"],
            ["accounts.id"],
            name=op.f("fk_candidate_preparations_owner_id_accounts"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["privacy_policy_version_id"],
            ["privacy_policy_versions.id"],
            name=op.f(
                "fk_candidate_preparations_privacy_policy_version_id_privacy_policy_versions"
            ),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["retention_rule_id"],
            ["retention_rules.id"],
            name=op.f("fk_candidate_preparations_retention_rule_id_retention_rules"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_candidate_preparations")),
        sa.UniqueConstraint(
            "owner_id",
            "idempotency_key_hash",
            name="uq_candidate_preparations_owner_idempotency",
        ),
    )
    op.create_index(
        "ix_candidate_preparations_owner_id",
        "candidate_preparations",
        ["owner_id", "id"],
        unique=False,
    )
    op.create_index(
        "ix_candidate_preparations_retention",
        "candidate_preparations",
        ["retain_until"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_candidate_preparations_retention", table_name="candidate_preparations")
    op.drop_index("ix_candidate_preparations_owner_id", table_name="candidate_preparations")
    op.drop_table("candidate_preparations")
