"""authenticated document intakes

Revision ID: 20260827_0007
Revises: 20260827_0006
Create Date: 2026-08-27 20:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260827_0007"
down_revision: str | None = "20260827_0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "candidate_document_intakes",
        sa.Column("owner_id", sa.UUID(), nullable=False),
        sa.Column("preparation_id", sa.UUID(), nullable=False),
        sa.Column("document_type", sa.String(length=24), nullable=False),
        sa.Column("source_kind", sa.String(length=16), nullable=False),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("idempotency_key_hash", sa.String(length=64), nullable=False),
        sa.Column("request_digest", sa.String(length=64), nullable=False),
        sa.Column("declared_media_type", sa.String(length=255), nullable=False),
        sa.Column("content_length", sa.BigInteger(), nullable=False),
        sa.Column("reserved_file_asset_id", sa.UUID(), nullable=False),
        sa.Column("file_asset_id", sa.UUID(), nullable=True),
        sa.Column("document_id", sa.UUID(), nullable=True),
        sa.Column("document_version_id", sa.UUID(), nullable=True),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("processing_lease_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("processing_token", sa.UUID(), nullable=True),
        sa.Column("last_error_code", sa.String(length=64), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("privacy_policy_version_id", sa.UUID(), nullable=False),
        sa.Column("jurisdiction_code", sa.String(length=64), nullable=False),
        sa.Column("legal_basis", sa.String(length=64), nullable=False),
        sa.Column("retention_rule_id", sa.UUID(), nullable=False),
        sa.Column("retain_until", sa.DateTime(timezone=True), nullable=False),
        sa.Column("retention_action", sa.String(length=16), nullable=False),
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
            "document_type IN ('cv', 'job_description')",
            name=op.f("ck_candidate_document_intakes_document_type_allowed"),
        ),
        sa.CheckConstraint(
            "source_kind IN ('upload', 'paste')",
            name=op.f("ck_candidate_document_intakes_source_kind_allowed"),
        ),
        sa.CheckConstraint(
            "status IN ('processing', 'scan_failed', 'rejected', 'completed')",
            name=op.f("ck_candidate_document_intakes_status_allowed"),
        ),
        sa.CheckConstraint(
            "btrim(declared_media_type) <> ''",
            name=op.f("ck_candidate_document_intakes_media_type_nonempty"),
        ),
        sa.CheckConstraint(
            "content_length > 0",
            name=op.f("ck_candidate_document_intakes_content_length_positive"),
        ),
        sa.CheckConstraint(
            "idempotency_key_hash ~ '^[0-9a-f]{64}$'",
            name=op.f("ck_candidate_document_intakes_idempotency_digest_format"),
        ),
        sa.CheckConstraint(
            "request_digest ~ '^[0-9a-f]{64}$'",
            name=op.f("ck_candidate_document_intakes_request_digest_format"),
        ),
        sa.CheckConstraint(
            "(source_kind = 'paste' AND declared_media_type = 'text/plain') OR "
            "source_kind = 'upload'",
            name=op.f("ck_candidate_document_intakes_paste_media_type_consistent"),
        ),
        sa.CheckConstraint(
            "file_asset_id IS NULL OR file_asset_id = reserved_file_asset_id",
            name=op.f("ck_candidate_document_intakes_file_asset_reservation_consistent"),
        ),
        sa.CheckConstraint(
            "attempts >= 0",
            name=op.f("ck_candidate_document_intakes_attempts_nonnegative"),
        ),
        sa.CheckConstraint(
            "(status = 'processing' AND processing_lease_until IS NOT NULL "
            "AND processing_token IS NOT NULL) OR "
            "(status <> 'processing' AND processing_lease_until IS NULL "
            "AND processing_token IS NULL)",
            name=op.f("ck_candidate_document_intakes_processing_lease_consistent"),
        ),
        sa.CheckConstraint(
            "(status IN ('scan_failed', 'rejected') AND last_error_code IS NOT NULL "
            "AND btrim(last_error_code) <> '') OR "
            "(status NOT IN ('scan_failed', 'rejected') AND last_error_code IS NULL)",
            name=op.f("ck_candidate_document_intakes_error_state_consistent"),
        ),
        sa.CheckConstraint(
            "(status = 'completed' AND completed_at IS NOT NULL) OR "
            "(status <> 'completed' AND completed_at IS NULL)",
            name=op.f("ck_candidate_document_intakes_completion_state_consistent"),
        ),
        sa.CheckConstraint(
            "retain_until > created_at",
            name=op.f("ck_candidate_document_intakes_retention_after_creation"),
        ),
        sa.CheckConstraint(
            "retention_action = 'delete'",
            name=op.f("ck_candidate_document_intakes_retention_action_delete_only"),
        ),
        sa.CheckConstraint(
            "version > 0",
            name=op.f("ck_candidate_document_intakes_version_positive"),
        ),
        sa.ForeignKeyConstraint(
            ["owner_id"],
            ["accounts.id"],
            name=op.f("fk_candidate_document_intakes_owner_id_accounts"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["preparation_id", "owner_id"],
            ["candidate_preparations.id", "candidate_preparations.owner_id"],
            name="fk_candidate_document_intakes_preparation_owner",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["file_asset_id"],
            ["file_assets.id"],
            name=op.f("fk_candidate_document_intakes_file_asset_id_file_assets"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["document_id"],
            ["candidate_documents.id"],
            name=op.f("fk_candidate_document_intakes_document_id_candidate_documents"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["document_version_id"],
            ["candidate_document_versions.id"],
            name=op.f(
                "fk_candidate_document_intakes_document_version_id_candidate_document_versions"
            ),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["privacy_policy_version_id"],
            ["privacy_policy_versions.id"],
            name=op.f(
                "fk_candidate_document_intakes_privacy_policy_version_id_privacy_policy_versions"
            ),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["retention_rule_id"],
            ["retention_rules.id"],
            name=op.f("fk_candidate_document_intakes_retention_rule_id_retention_rules"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_candidate_document_intakes")),
        sa.UniqueConstraint(
            "owner_id",
            "idempotency_key_hash",
            name="uq_candidate_document_intakes_owner_idempotency",
        ),
        sa.UniqueConstraint(
            "reserved_file_asset_id",
            name="uq_candidate_document_intakes_reserved_asset",
        ),
        sa.UniqueConstraint(
            "file_asset_id",
            name="uq_candidate_document_intakes_file_asset",
        ),
        sa.UniqueConstraint(
            "document_version_id",
            name="uq_candidate_document_intakes_document_version",
        ),
    )
    op.create_index(
        "ix_candidate_document_intakes_owner_preparation",
        "candidate_document_intakes",
        ["owner_id", "preparation_id", "created_at"],
        unique=False,
    )
    op.create_index(
        "ix_candidate_document_intakes_status_lease",
        "candidate_document_intakes",
        ["status", "processing_lease_until"],
        unique=False,
    )
    op.create_index(
        "ix_candidate_document_intakes_retention",
        "candidate_document_intakes",
        ["retain_until"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_candidate_document_intakes_retention",
        table_name="candidate_document_intakes",
    )
    op.drop_index(
        "ix_candidate_document_intakes_status_lease",
        table_name="candidate_document_intakes",
    )
    op.drop_index(
        "ix_candidate_document_intakes_owner_preparation",
        table_name="candidate_document_intakes",
    )
    op.drop_table("candidate_document_intakes")
