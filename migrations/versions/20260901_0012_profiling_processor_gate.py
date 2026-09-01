"""bind profiling jobs to an approved processor activity

Revision ID: 20260901_0012
Revises: 20260901_0011
Create Date: 2026-09-01 01:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260901_0012"
down_revision: str | None = "20260901_0011"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _replace_snapshot_protection(*, include_processor_activity: bool) -> None:
    processor_guard = (
        "\n                OR NEW.processor_activity_id IS DISTINCT FROM OLD.processor_activity_id"
        if include_processor_activity
        else ""
    )
    op.execute(
        f"""
        CREATE OR REPLACE FUNCTION protect_candidate_profiling_job_snapshot()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        BEGIN
            IF NEW.id IS DISTINCT FROM OLD.id
                OR NEW.owner_id IS DISTINCT FROM OLD.owner_id
                OR NEW.preparation_id IS DISTINCT FROM OLD.preparation_id
                OR NEW.document_version_id IS DISTINCT FROM OLD.document_version_id
                OR NEW.source_text_id IS DISTINCT FROM OLD.source_text_id
                OR NEW.source_text_version_id IS DISTINCT FROM OLD.source_text_version_id
                {processor_guard}
                OR NEW.document_type IS DISTINCT FROM OLD.document_type
                OR NEW.privacy_policy_version_id IS DISTINCT FROM OLD.privacy_policy_version_id
                OR NEW.retention_rule_id IS DISTINCT FROM OLD.retention_rule_id
                OR NEW.jurisdiction_code IS DISTINCT FROM OLD.jurisdiction_code
                OR NEW.legal_basis IS DISTINCT FROM OLD.legal_basis
                OR NEW.retain_until IS DISTINCT FROM OLD.retain_until
                OR NEW.retention_action IS DISTINCT FROM OLD.retention_action
                OR NEW.model_provider IS DISTINCT FROM OLD.model_provider
                OR NEW.model_id IS DISTINCT FROM OLD.model_id
                OR NEW.model_version IS DISTINCT FROM OLD.model_version
                OR NEW.prompt_id IS DISTINCT FROM OLD.prompt_id
                OR NEW.prompt_version IS DISTINCT FROM OLD.prompt_version
                OR NEW.schema_id IS DISTINCT FROM OLD.schema_id
                OR NEW.schema_version IS DISTINCT FROM OLD.schema_version
                OR NEW.instructions_sha256 IS DISTINCT FROM OLD.instructions_sha256
                OR NEW.output_schema_sha256 IS DISTINCT FROM OLD.output_schema_sha256
                OR NEW.max_output_tokens IS DISTINCT FROM OLD.max_output_tokens
                OR NEW.created_at IS DISTINCT FROM OLD.created_at THEN
                RAISE EXCEPTION 'candidate profiling job snapshot is immutable'
                    USING ERRCODE = '55000';
            END IF;
            RETURN NEW;
        END;
        $$
        """
    )


def upgrade() -> None:
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (SELECT 1 FROM candidate_profiling_jobs) THEN
                RAISE EXCEPTION
                    'cannot add processor authorization to existing candidate profiling jobs';
            END IF;
        END;
        $$
        """
    )
    op.add_column(
        "candidate_profiling_jobs",
        sa.Column("processor_activity_id", sa.UUID(), nullable=False),
    )
    op.create_foreign_key(
        op.f("fk_candidate_profiling_jobs_processor_activity_id_processor_activities"),
        "candidate_profiling_jobs",
        "processor_activities",
        ["processor_activity_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    _replace_snapshot_protection(include_processor_activity=True)


def downgrade() -> None:
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (SELECT 1 FROM candidate_profiling_jobs) THEN
                RAISE EXCEPTION
                    'cannot remove processor authorization while candidate profiling jobs exist';
            END IF;
        END;
        $$
        """
    )
    op.drop_constraint(
        op.f("fk_candidate_profiling_jobs_processor_activity_id_processor_activities"),
        "candidate_profiling_jobs",
        type_="foreignkey",
    )
    op.drop_column("candidate_profiling_jobs", "processor_activity_id")
    _replace_snapshot_protection(include_processor_activity=False)
