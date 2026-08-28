"""durable candidate extraction jobs

Revision ID: 20260828_0009
Revises: 20260827_0008
Create Date: 2026-08-28 00:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260828_0009"
down_revision: str | None = "20260827_0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "candidate_extraction_jobs",
        sa.Column("owner_id", sa.UUID(), nullable=False),
        sa.Column("document_version_id", sa.UUID(), nullable=False),
        sa.Column("file_asset_id", sa.UUID(), nullable=False),
        sa.Column("parser_release_policy_id", sa.UUID(), nullable=False),
        sa.Column("privacy_policy_version_id", sa.UUID(), nullable=False),
        sa.Column("retention_rule_id", sa.UUID(), nullable=False),
        sa.Column("jurisdiction_code", sa.String(length=64), nullable=False),
        sa.Column("legal_basis", sa.String(length=64), nullable=False),
        sa.Column("retain_until", sa.DateTime(timezone=True), nullable=False),
        sa.Column("retention_action", sa.String(length=16), nullable=False),
        sa.Column("media_type", sa.String(length=255), nullable=False),
        sa.Column("content_length", sa.BigInteger(), nullable=False),
        sa.Column("content_sha256", sa.String(length=64), nullable=False),
        sa.Column("parser_adapter", sa.String(length=100), nullable=False),
        sa.Column("parser_version", sa.String(length=64), nullable=False),
        sa.Column("isolation_profile", sa.String(length=100), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("attempts", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("available_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("locked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("locked_by", sa.String(length=128), nullable=True),
        sa.Column("lease_token", sa.UUID(), nullable=True),
        sa.Column("error_code", sa.String(length=32), nullable=True),
        sa.Column("source_text_id", sa.UUID(), nullable=True),
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
            "status IN ('pending', 'processing', 'retry', 'succeeded', 'failed')",
            name=op.f("ck_candidate_extraction_jobs_status_allowed"),
        ),
        sa.CheckConstraint(
            "attempts BETWEEN 0 AND 5",
            name=op.f("ck_candidate_extraction_jobs_attempts_bounded"),
        ),
        sa.CheckConstraint(
            "btrim(parser_adapter) <> ''",
            name=op.f("ck_candidate_extraction_jobs_parser_adapter_nonempty"),
        ),
        sa.CheckConstraint(
            "btrim(parser_version) <> ''",
            name=op.f("ck_candidate_extraction_jobs_parser_version_nonempty"),
        ),
        sa.CheckConstraint(
            "btrim(isolation_profile) <> ''",
            name=op.f("ck_candidate_extraction_jobs_isolation_profile_nonempty"),
        ),
        sa.CheckConstraint(
            "error_code IS NULL OR error_code IN "
            "('input_unsupported', 'input_corrupt', 'input_encrypted', 'input_empty', "
            "'parser_timeout', 'resource_exceeded', 'parser_crashed', 'source_unavailable', "
            "'policy_unavailable', 'internal_failure', 'lease_expired')",
            name=op.f("ck_candidate_extraction_jobs_failure_code_allowed"),
        ),
        sa.CheckConstraint(
            "content_length > 0",
            name=op.f("ck_candidate_extraction_jobs_content_length_positive"),
        ),
        sa.CheckConstraint(
            "content_sha256 ~ '^[0-9a-f]{64}$'",
            name=op.f("ck_candidate_extraction_jobs_content_digest_format"),
        ),
        sa.CheckConstraint(
            "retention_action = 'delete'",
            name=op.f("ck_candidate_extraction_jobs_retention_action_delete_only"),
        ),
        sa.CheckConstraint(
            "retain_until > created_at",
            name=op.f("ck_candidate_extraction_jobs_retention_after_creation"),
        ),
        sa.CheckConstraint(
            "btrim(media_type) <> ''",
            name=op.f("ck_candidate_extraction_jobs_media_type_nonempty"),
        ),
        sa.CheckConstraint(
            "btrim(jurisdiction_code) <> ''",
            name=op.f("ck_candidate_extraction_jobs_jurisdiction_nonempty"),
        ),
        sa.CheckConstraint(
            "btrim(legal_basis) <> ''",
            name=op.f("ck_candidate_extraction_jobs_legal_basis_nonempty"),
        ),
        sa.CheckConstraint(
            "((status = 'pending' AND error_code IS NULL AND locked_at IS NULL "
            "AND locked_by IS NULL AND lease_token IS NULL AND completed_at IS NULL "
            "AND source_text_id IS NULL) OR "
            "(status = 'retry' AND error_code IS NOT NULL AND locked_at IS NULL "
            "AND locked_by IS NULL AND lease_token IS NULL AND completed_at IS NULL "
            "AND source_text_id IS NULL) OR "
            "(status = 'processing' AND locked_at IS NOT NULL AND locked_by IS NOT NULL "
            "AND lease_token IS NOT NULL AND error_code IS NULL AND completed_at IS NULL "
            "AND source_text_id IS NULL) OR "
            "(status = 'succeeded' AND error_code IS NULL AND locked_at IS NULL "
            "AND locked_by IS NULL AND lease_token IS NULL AND completed_at IS NOT NULL "
            "AND source_text_id IS NOT NULL) OR "
            "(status = 'failed' AND error_code IS NOT NULL AND locked_at IS NULL "
            "AND locked_by IS NULL AND lease_token IS NULL AND completed_at IS NOT NULL "
            "AND source_text_id IS NULL))",
            name=op.f("ck_candidate_extraction_jobs_state_consistent"),
        ),
        sa.ForeignKeyConstraint(
            ["owner_id"],
            ["accounts.id"],
            name="fk_candidate_extraction_jobs_owner_id_accounts",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["document_version_id", "owner_id"],
            ["candidate_document_versions.id", "candidate_document_versions.owner_id"],
            name="fk_candidate_extraction_jobs_document_version_owner",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["file_asset_id", "owner_id"],
            ["file_assets.id", "file_assets.account_id"],
            name="fk_candidate_extraction_jobs_file_asset_owner",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["source_text_id", "owner_id"],
            ["candidate_source_texts.id", "candidate_source_texts.owner_id"],
            name="fk_candidate_extraction_jobs_source_text_owner",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["parser_release_policy_id"],
            ["parser_release_policies.id"],
            name="fk_candidate_extraction_jobs_parser_policy",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["privacy_policy_version_id"],
            ["privacy_policy_versions.id"],
            name="fk_candidate_extraction_jobs_privacy_policy",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["retention_rule_id"],
            ["retention_rules.id"],
            name="fk_candidate_extraction_jobs_retention_rule",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_candidate_extraction_jobs")),
        sa.UniqueConstraint(
            "document_version_id",
            name="uq_candidate_extraction_jobs_document_version",
        ),
        sa.UniqueConstraint(
            "id",
            "owner_id",
            name="uq_candidate_extraction_jobs_id_owner",
        ),
    )
    op.create_index(
        "ix_candidate_extraction_jobs_status_available",
        "candidate_extraction_jobs",
        ["status", "available_at"],
        unique=False,
    )
    op.create_index(
        "ix_candidate_extraction_jobs_owner_created",
        "candidate_extraction_jobs",
        ["owner_id", "created_at"],
        unique=False,
    )
    op.execute(
        """
        CREATE FUNCTION validate_candidate_extraction_job_snapshot()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        DECLARE
            document_snapshot candidate_document_versions%ROWTYPE;
            policy_snapshot parser_release_policies%ROWTYPE;
        BEGIN
            SELECT *
            INTO document_snapshot
            FROM candidate_document_versions
            WHERE id = NEW.document_version_id
                AND owner_id = NEW.owner_id;
            SELECT *
            INTO policy_snapshot
            FROM parser_release_policies
            WHERE id = NEW.parser_release_policy_id;
            IF NOT FOUND
                OR document_snapshot.file_asset_id IS DISTINCT FROM NEW.file_asset_id
                OR document_snapshot.parser_release_policy_id
                    IS DISTINCT FROM NEW.parser_release_policy_id
                OR document_snapshot.privacy_policy_version_id
                    IS DISTINCT FROM NEW.privacy_policy_version_id
                OR document_snapshot.retention_rule_id IS DISTINCT FROM NEW.retention_rule_id
                OR document_snapshot.jurisdiction_code IS DISTINCT FROM NEW.jurisdiction_code
                OR document_snapshot.legal_basis IS DISTINCT FROM NEW.legal_basis
                OR document_snapshot.retain_until IS DISTINCT FROM NEW.retain_until
                OR document_snapshot.retention_action IS DISTINCT FROM NEW.retention_action
                OR document_snapshot.media_type IS DISTINCT FROM NEW.media_type
                OR document_snapshot.content_length IS DISTINCT FROM NEW.content_length
                OR document_snapshot.content_sha256 IS DISTINCT FROM NEW.content_sha256
                OR policy_snapshot.parser_adapter IS DISTINCT FROM NEW.parser_adapter
                OR policy_snapshot.parser_version IS DISTINCT FROM NEW.parser_version
                OR policy_snapshot.isolation_profile IS DISTINCT FROM NEW.isolation_profile THEN
                RAISE EXCEPTION 'candidate extraction job snapshot is inconsistent'
                    USING ERRCODE = '23514';
            END IF;
            RETURN NEW;
        END;
        $$
        """
    )
    op.execute(
        """
        CREATE TRIGGER candidate_extraction_jobs_validate_snapshot
        BEFORE INSERT ON candidate_extraction_jobs
        FOR EACH ROW
        EXECUTE FUNCTION validate_candidate_extraction_job_snapshot()
        """
    )
    op.execute(
        """
        CREATE FUNCTION protect_candidate_extraction_job_identity()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        BEGIN
            IF NEW.id IS DISTINCT FROM OLD.id
                OR NEW.owner_id IS DISTINCT FROM OLD.owner_id
                OR NEW.document_version_id IS DISTINCT FROM OLD.document_version_id
                OR NEW.file_asset_id IS DISTINCT FROM OLD.file_asset_id
                OR NEW.parser_release_policy_id IS DISTINCT FROM OLD.parser_release_policy_id
                OR NEW.privacy_policy_version_id IS DISTINCT FROM OLD.privacy_policy_version_id
                OR NEW.retention_rule_id IS DISTINCT FROM OLD.retention_rule_id
                OR NEW.jurisdiction_code IS DISTINCT FROM OLD.jurisdiction_code
                OR NEW.legal_basis IS DISTINCT FROM OLD.legal_basis
                OR NEW.retain_until IS DISTINCT FROM OLD.retain_until
                OR NEW.retention_action IS DISTINCT FROM OLD.retention_action
                OR NEW.media_type IS DISTINCT FROM OLD.media_type
                OR NEW.content_length IS DISTINCT FROM OLD.content_length
                OR NEW.content_sha256 IS DISTINCT FROM OLD.content_sha256
                OR NEW.parser_adapter IS DISTINCT FROM OLD.parser_adapter
                OR NEW.parser_version IS DISTINCT FROM OLD.parser_version
                OR NEW.isolation_profile IS DISTINCT FROM OLD.isolation_profile
                OR NEW.created_at IS DISTINCT FROM OLD.created_at THEN
                RAISE EXCEPTION 'candidate extraction job identity is immutable'
                    USING ERRCODE = '55000';
            END IF;
            RETURN NEW;
        END;
        $$
        """
    )
    op.execute(
        """
        CREATE TRIGGER candidate_extraction_jobs_protect_identity
        BEFORE UPDATE ON candidate_extraction_jobs
        FOR EACH ROW
        EXECUTE FUNCTION protect_candidate_extraction_job_identity()
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (SELECT 1 FROM candidate_extraction_jobs LIMIT 1) THEN
                RAISE EXCEPTION
                    'Cannot downgrade while candidate extraction jobs exist';
            END IF;
        END;
        $$
        """
    )
    op.execute(
        "DROP TRIGGER candidate_extraction_jobs_validate_snapshot ON candidate_extraction_jobs"
    )
    op.execute("DROP FUNCTION validate_candidate_extraction_job_snapshot()")
    op.execute(
        "DROP TRIGGER candidate_extraction_jobs_protect_identity ON candidate_extraction_jobs"
    )
    op.execute("DROP FUNCTION protect_candidate_extraction_job_identity()")
    op.drop_index(
        "ix_candidate_extraction_jobs_owner_created",
        table_name="candidate_extraction_jobs",
    )
    op.drop_index(
        "ix_candidate_extraction_jobs_status_available",
        table_name="candidate_extraction_jobs",
    )
    op.drop_table("candidate_extraction_jobs")
