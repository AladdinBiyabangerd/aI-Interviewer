"""durable fenced candidate profiling jobs

Revision ID: 20260901_0011
Revises: 20260831_0010
Create Date: 2026-09-01 00:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260901_0011"
down_revision: str | None = "20260831_0010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "candidate_profiling_jobs",
        sa.Column("owner_id", sa.UUID(), nullable=False),
        sa.Column("preparation_id", sa.UUID(), nullable=False),
        sa.Column("document_version_id", sa.UUID(), nullable=False),
        sa.Column("source_text_id", sa.UUID(), nullable=False),
        sa.Column("source_text_version_id", sa.UUID(), nullable=False),
        sa.Column("document_type", sa.String(length=24), nullable=False),
        sa.Column("privacy_policy_version_id", sa.UUID(), nullable=False),
        sa.Column("retention_rule_id", sa.UUID(), nullable=False),
        sa.Column("jurisdiction_code", sa.String(length=64), nullable=False),
        sa.Column("legal_basis", sa.String(length=64), nullable=False),
        sa.Column("retain_until", sa.DateTime(timezone=True), nullable=False),
        sa.Column("retention_action", sa.String(length=16), nullable=False),
        sa.Column("model_provider", sa.String(length=128), nullable=False),
        sa.Column("model_id", sa.String(length=128), nullable=False),
        sa.Column("model_version", sa.String(length=128), nullable=False),
        sa.Column("prompt_id", sa.String(length=128), nullable=False),
        sa.Column("prompt_version", sa.String(length=128), nullable=False),
        sa.Column("schema_id", sa.String(length=128), nullable=False),
        sa.Column("schema_version", sa.String(length=128), nullable=False),
        sa.Column("instructions_sha256", sa.String(length=64), nullable=False),
        sa.Column("output_schema_sha256", sa.String(length=64), nullable=False),
        sa.Column("max_output_tokens", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("attempts", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("available_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("locked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("locked_by", sa.String(length=128), nullable=True),
        sa.Column("lease_token", sa.UUID(), nullable=True),
        sa.Column("error_code", sa.String(length=32), nullable=True),
        sa.Column("profile_id", sa.UUID(), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
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
        sa.CheckConstraint(
            "document_type IN ('cv', 'job_description')",
            name=op.f("ck_candidate_profiling_jobs_document_type_allowed"),
        ),
        sa.CheckConstraint(
            "status IN ('pending', 'processing', 'retry', 'succeeded', 'dead_letter')",
            name=op.f("ck_candidate_profiling_jobs_status_allowed"),
        ),
        sa.CheckConstraint(
            "attempts BETWEEN 0 AND 5",
            name=op.f("ck_candidate_profiling_jobs_attempts_bounded"),
        ),
        sa.CheckConstraint(
            "error_code IS NULL OR error_code IN "
            "('rate_limited', 'provider_timeout', 'provider_unavailable', "
            "'provider_rejected', 'provider_failure', 'model_identity_mismatch', "
            "'invalid_output', 'output_too_large', 'incomplete_output', "
            "'content_filtered', 'source_unavailable', 'policy_unavailable', "
            "'persistence_conflict', 'internal_failure', 'lease_expired')",
            name=op.f("ck_candidate_profiling_jobs_failure_code_allowed"),
        ),
        sa.CheckConstraint(
            "((status = 'pending' AND attempts = 0 AND error_code IS NULL "
            "AND locked_at IS NULL AND locked_by IS NULL AND lease_token IS NULL "
            "AND completed_at IS NULL AND profile_id IS NULL) OR "
            "(status = 'retry' AND attempts BETWEEN 1 AND 4 AND error_code IS NOT NULL "
            "AND locked_at IS NULL AND locked_by IS NULL AND lease_token IS NULL "
            "AND completed_at IS NULL AND profile_id IS NULL) OR "
            "(status = 'processing' AND attempts BETWEEN 1 AND 5 AND error_code IS NULL "
            "AND locked_at IS NOT NULL AND locked_by IS NOT NULL AND lease_token IS NOT NULL "
            "AND completed_at IS NULL AND profile_id IS NULL) OR "
            "(status = 'succeeded' AND attempts BETWEEN 1 AND 5 AND error_code IS NULL "
            "AND locked_at IS NULL AND locked_by IS NULL AND lease_token IS NULL "
            "AND completed_at IS NOT NULL AND profile_id IS NOT NULL) OR "
            "(status = 'dead_letter' AND attempts BETWEEN 0 AND 5 "
            "AND error_code IS NOT NULL AND locked_at IS NULL AND locked_by IS NULL "
            "AND lease_token IS NULL AND completed_at IS NOT NULL AND profile_id IS NULL))",
            name=op.f("ck_candidate_profiling_jobs_state_consistent"),
        ),
        sa.CheckConstraint(
            "(document_type = 'cv' AND schema_id = 'cv-profile') OR "
            "(document_type = 'job_description' "
            "AND schema_id = 'job-description-profile')",
            name=op.f("ck_candidate_profiling_jobs_schema_matches_document_type"),
        ),
        sa.CheckConstraint(
            "schema_version = '1.0.0'",
            name=op.f("ck_candidate_profiling_jobs_schema_version_supported"),
        ),
        sa.CheckConstraint(
            "model_provider ~ '^[A-Za-z0-9][A-Za-z0-9._:/-]{0,127}$'",
            name=op.f("ck_candidate_profiling_jobs_model_provider_format"),
        ),
        sa.CheckConstraint(
            "model_id ~ '^[A-Za-z0-9][A-Za-z0-9._:/-]{0,127}$'",
            name=op.f("ck_candidate_profiling_jobs_model_id_format"),
        ),
        sa.CheckConstraint(
            "model_version ~ '^[A-Za-z0-9][A-Za-z0-9._:/-]{0,127}$'",
            name=op.f("ck_candidate_profiling_jobs_model_version_format"),
        ),
        sa.CheckConstraint(
            "prompt_id ~ '^[A-Za-z0-9][A-Za-z0-9._:/-]{0,127}$'",
            name=op.f("ck_candidate_profiling_jobs_prompt_id_format"),
        ),
        sa.CheckConstraint(
            "prompt_version ~ '^[A-Za-z0-9][A-Za-z0-9._:/-]{0,127}$'",
            name=op.f("ck_candidate_profiling_jobs_prompt_version_format"),
        ),
        sa.CheckConstraint(
            "instructions_sha256 ~ '^[0-9a-f]{64}$'",
            name=op.f("ck_candidate_profiling_jobs_instructions_digest_format"),
        ),
        sa.CheckConstraint(
            "output_schema_sha256 ~ '^[0-9a-f]{64}$'",
            name=op.f("ck_candidate_profiling_jobs_output_schema_digest_format"),
        ),
        sa.CheckConstraint(
            "max_output_tokens BETWEEN 1 AND 32768",
            name=op.f("ck_candidate_profiling_jobs_max_output_tokens_bounded"),
        ),
        sa.CheckConstraint(
            "btrim(jurisdiction_code) <> ''",
            name=op.f("ck_candidate_profiling_jobs_jurisdiction_nonempty"),
        ),
        sa.CheckConstraint(
            "btrim(legal_basis) <> ''",
            name=op.f("ck_candidate_profiling_jobs_legal_basis_nonempty"),
        ),
        sa.CheckConstraint(
            "retention_action = 'delete'",
            name=op.f("ck_candidate_profiling_jobs_retention_action_delete_only"),
        ),
        sa.CheckConstraint(
            "retain_until > created_at",
            name=op.f("ck_candidate_profiling_jobs_retention_after_creation"),
        ),
        sa.ForeignKeyConstraint(
            ["owner_id"],
            ["accounts.id"],
            name="fk_candidate_profiling_jobs_owner",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["preparation_id", "owner_id"],
            ["candidate_preparations.id", "candidate_preparations.owner_id"],
            name="fk_candidate_profiling_jobs_preparation_owner",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["document_version_id", "owner_id"],
            ["candidate_document_versions.id", "candidate_document_versions.owner_id"],
            name="fk_candidate_profiling_jobs_document_version_owner",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["source_text_id", "owner_id"],
            ["candidate_source_texts.id", "candidate_source_texts.owner_id"],
            name="fk_candidate_profiling_jobs_source_text_owner",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["source_text_version_id", "source_text_id"],
            ["candidate_source_text_versions.id", "candidate_source_text_versions.source_text_id"],
            name="fk_candidate_profiling_jobs_source_version",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["profile_id", "owner_id"],
            ["candidate_profiles.id", "candidate_profiles.owner_id"],
            name="fk_candidate_profiling_jobs_profile_owner",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["privacy_policy_version_id"],
            ["privacy_policy_versions.id"],
            name="fk_candidate_profiling_jobs_privacy_policy",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["retention_rule_id"],
            ["retention_rules.id"],
            name="fk_candidate_profiling_jobs_retention_rule",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_candidate_profiling_jobs")),
        sa.UniqueConstraint(
            "source_text_version_id",
            name="uq_candidate_profiling_jobs_source_text_version",
        ),
        sa.UniqueConstraint(
            "id",
            "owner_id",
            name="uq_candidate_profiling_jobs_id_owner",
        ),
    )
    op.create_index(
        "ix_candidate_profiling_jobs_status_available",
        "candidate_profiling_jobs",
        ["status", "available_at"],
        unique=False,
    )
    op.create_index(
        "ix_candidate_profiling_jobs_owner_created",
        "candidate_profiling_jobs",
        ["owner_id", "created_at"],
        unique=False,
    )
    op.execute(
        """
        CREATE FUNCTION validate_candidate_profiling_job_snapshot()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        DECLARE
            preparation_snapshot candidate_preparations%ROWTYPE;
            document_snapshot candidate_documents%ROWTYPE;
            document_version_snapshot candidate_document_versions%ROWTYPE;
            source_snapshot candidate_source_texts%ROWTYPE;
            source_version_snapshot candidate_source_text_versions%ROWTYPE;
        BEGIN
            SELECT * INTO preparation_snapshot
            FROM candidate_preparations
            WHERE id = NEW.preparation_id AND owner_id = NEW.owner_id;
            SELECT * INTO document_version_snapshot
            FROM candidate_document_versions
            WHERE id = NEW.document_version_id AND owner_id = NEW.owner_id;
            IF document_version_snapshot.id IS NOT NULL THEN
                SELECT * INTO document_snapshot
                FROM candidate_documents
                WHERE id = document_version_snapshot.document_id
                    AND owner_id = NEW.owner_id;
            END IF;
            SELECT * INTO source_snapshot
            FROM candidate_source_texts
            WHERE id = NEW.source_text_id AND owner_id = NEW.owner_id;
            SELECT * INTO source_version_snapshot
            FROM candidate_source_text_versions
            WHERE id = NEW.source_text_version_id
                AND source_text_id = NEW.source_text_id
                AND owner_id = NEW.owner_id;
            IF preparation_snapshot.id IS NULL
                OR document_snapshot.id IS NULL
                OR document_version_snapshot.id IS NULL
                OR source_snapshot.id IS NULL
                OR source_version_snapshot.id IS NULL
                OR document_snapshot.preparation_id IS DISTINCT FROM NEW.preparation_id
                OR document_snapshot.document_type IS DISTINCT FROM NEW.document_type
                OR document_snapshot.latest_version_number
                    IS DISTINCT FROM document_version_snapshot.version_number
                OR source_snapshot.document_version_id IS DISTINCT FROM NEW.document_version_id
                OR source_snapshot.latest_version_number
                    IS DISTINCT FROM source_version_snapshot.version_number
                OR document_version_snapshot.privacy_policy_version_id
                    IS DISTINCT FROM NEW.privacy_policy_version_id
                OR document_version_snapshot.retention_rule_id
                    IS DISTINCT FROM NEW.retention_rule_id
                OR document_version_snapshot.jurisdiction_code
                    IS DISTINCT FROM NEW.jurisdiction_code
                OR document_version_snapshot.legal_basis IS DISTINCT FROM NEW.legal_basis
                OR document_version_snapshot.retain_until IS DISTINCT FROM NEW.retain_until
                OR document_version_snapshot.retention_action
                    IS DISTINCT FROM NEW.retention_action THEN
                RAISE EXCEPTION 'candidate profiling job snapshot is inconsistent'
                    USING ERRCODE = '23514';
            END IF;
            RETURN NEW;
        END;
        $$
        """
    )
    op.execute(
        """
        CREATE TRIGGER candidate_profiling_jobs_validate_snapshot
        BEFORE INSERT ON candidate_profiling_jobs
        FOR EACH ROW
        EXECUTE FUNCTION validate_candidate_profiling_job_snapshot()
        """
    )
    op.execute(
        """
        CREATE FUNCTION protect_candidate_profiling_job_snapshot()
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
    op.execute(
        """
        CREATE TRIGGER candidate_profiling_jobs_protect_snapshot
        BEFORE UPDATE ON candidate_profiling_jobs
        FOR EACH ROW
        EXECUTE FUNCTION protect_candidate_profiling_job_snapshot()
        """
    )
    op.execute(
        """
        CREATE FUNCTION validate_candidate_profiling_job_transition()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        BEGIN
            IF OLD.status IN ('succeeded', 'dead_letter') THEN
                RAISE EXCEPTION 'terminal candidate profiling job is immutable'
                    USING ERRCODE = '55000';
            END IF;
            IF NOT (
                (OLD.status IN ('pending', 'retry') AND NEW.status = 'processing'
                    AND NEW.attempts = OLD.attempts + 1)
                OR (OLD.status = 'processing' AND NEW.status = 'processing'
                    AND NEW.attempts = OLD.attempts + 1
                    AND NEW.lease_token IS DISTINCT FROM OLD.lease_token)
                OR (OLD.status = 'processing' AND NEW.status IN ('retry', 'succeeded')
                    AND NEW.attempts = OLD.attempts)
                OR (NEW.status = 'dead_letter' AND NEW.attempts = OLD.attempts)
            ) THEN
                RAISE EXCEPTION 'candidate profiling job transition is invalid'
                    USING ERRCODE = '23514';
            END IF;
            RETURN NEW;
        END;
        $$
        """
    )
    op.execute(
        """
        CREATE TRIGGER candidate_profiling_jobs_validate_transition
        BEFORE UPDATE ON candidate_profiling_jobs
        FOR EACH ROW
        EXECUTE FUNCTION validate_candidate_profiling_job_transition()
        """
    )
    op.execute(
        """
        CREATE FUNCTION validate_candidate_profiling_job_result()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        DECLARE
            profile_snapshot candidate_profiles%ROWTYPE;
            version_snapshot candidate_profile_versions%ROWTYPE;
        BEGIN
            IF NEW.status <> 'succeeded' THEN
                RETURN NEW;
            END IF;
            SELECT * INTO profile_snapshot
            FROM candidate_profiles
            WHERE id = NEW.profile_id AND owner_id = NEW.owner_id;
            SELECT * INTO version_snapshot
            FROM candidate_profile_versions
            WHERE profile_id = NEW.profile_id AND version_number = 1;
            IF profile_snapshot.id IS NULL
                OR version_snapshot.id IS NULL
                OR profile_snapshot.source_text_id IS DISTINCT FROM NEW.source_text_id
                OR profile_snapshot.source_text_version_id
                    IS DISTINCT FROM NEW.source_text_version_id
                OR profile_snapshot.document_version_id
                    IS DISTINCT FROM NEW.document_version_id
                OR profile_snapshot.document_type IS DISTINCT FROM NEW.document_type
                OR profile_snapshot.privacy_policy_version_id
                    IS DISTINCT FROM NEW.privacy_policy_version_id
                OR profile_snapshot.retention_rule_id IS DISTINCT FROM NEW.retention_rule_id
                OR profile_snapshot.jurisdiction_code IS DISTINCT FROM NEW.jurisdiction_code
                OR profile_snapshot.legal_basis IS DISTINCT FROM NEW.legal_basis
                OR profile_snapshot.retain_until IS DISTINCT FROM NEW.retain_until
                OR profile_snapshot.retention_action IS DISTINCT FROM NEW.retention_action
                OR version_snapshot.origin <> 'model_generation'
                OR version_snapshot.model_provider IS DISTINCT FROM NEW.model_provider
                OR version_snapshot.model_id IS DISTINCT FROM NEW.model_id
                OR version_snapshot.model_version IS DISTINCT FROM NEW.model_version
                OR version_snapshot.prompt_id IS DISTINCT FROM NEW.prompt_id
                OR version_snapshot.prompt_version IS DISTINCT FROM NEW.prompt_version
                OR version_snapshot.schema_id IS DISTINCT FROM NEW.schema_id
                OR version_snapshot.schema_version IS DISTINCT FROM NEW.schema_version
                OR version_snapshot.instructions_sha256
                    IS DISTINCT FROM NEW.instructions_sha256
                OR version_snapshot.output_schema_sha256
                    IS DISTINCT FROM NEW.output_schema_sha256 THEN
                RAISE EXCEPTION 'candidate profiling job result is inconsistent'
                    USING ERRCODE = '23514';
            END IF;
            RETURN NEW;
        END;
        $$
        """
    )
    op.execute(
        """
        CREATE TRIGGER candidate_profiling_jobs_validate_result
        BEFORE UPDATE ON candidate_profiling_jobs
        FOR EACH ROW
        EXECUTE FUNCTION validate_candidate_profiling_job_result()
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (SELECT 1 FROM candidate_profiling_jobs LIMIT 1) THEN
                RAISE EXCEPTION 'Cannot downgrade while candidate profiling jobs exist';
            END IF;
        END;
        $$
        """
    )
    op.execute("DROP TRIGGER candidate_profiling_jobs_validate_result ON candidate_profiling_jobs")
    op.execute("DROP FUNCTION validate_candidate_profiling_job_result()")
    op.execute(
        "DROP TRIGGER candidate_profiling_jobs_validate_transition ON candidate_profiling_jobs"
    )
    op.execute("DROP FUNCTION validate_candidate_profiling_job_transition()")
    op.execute("DROP TRIGGER candidate_profiling_jobs_protect_snapshot ON candidate_profiling_jobs")
    op.execute("DROP FUNCTION protect_candidate_profiling_job_snapshot()")
    op.execute(
        "DROP TRIGGER candidate_profiling_jobs_validate_snapshot ON candidate_profiling_jobs"
    )
    op.execute("DROP FUNCTION validate_candidate_profiling_job_snapshot()")
    op.drop_index(
        "ix_candidate_profiling_jobs_owner_created",
        table_name="candidate_profiling_jobs",
    )
    op.drop_index(
        "ix_candidate_profiling_jobs_status_available",
        table_name="candidate_profiling_jobs",
    )
    op.drop_table("candidate_profiling_jobs")
