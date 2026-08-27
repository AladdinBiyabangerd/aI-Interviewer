"""immutable candidate document versions

Revision ID: 20260827_0006
Revises: 20260826_0005
Create Date: 2026-08-27 00:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260827_0006"
down_revision: str | None = "20260826_0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_unique_constraint(
        "uq_candidate_preparations_id_owner",
        "candidate_preparations",
        ["id", "owner_id"],
    )
    op.create_unique_constraint(
        "uq_file_assets_id_account",
        "file_assets",
        ["id", "account_id"],
    )
    op.create_table(
        "candidate_documents",
        sa.Column("owner_id", sa.UUID(), nullable=False),
        sa.Column("preparation_id", sa.UUID(), nullable=False),
        sa.Column("document_type", sa.String(length=24), nullable=False),
        sa.Column("latest_version_number", sa.Integer(), nullable=False),
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
            name=op.f("ck_candidate_documents_document_type_allowed"),
        ),
        sa.CheckConstraint(
            "latest_version_number > 0",
            name=op.f("ck_candidate_documents_latest_version_number_positive"),
        ),
        sa.CheckConstraint(
            "version > 0",
            name=op.f("ck_candidate_documents_version_positive"),
        ),
        sa.ForeignKeyConstraint(
            ["owner_id"],
            ["accounts.id"],
            name=op.f("fk_candidate_documents_owner_id_accounts"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["preparation_id", "owner_id"],
            ["candidate_preparations.id", "candidate_preparations.owner_id"],
            name="fk_candidate_documents_preparation_owner",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_candidate_documents")),
        sa.UniqueConstraint(
            "id",
            "owner_id",
            name="uq_candidate_documents_id_owner",
        ),
        sa.UniqueConstraint(
            "preparation_id",
            "document_type",
            name="uq_candidate_documents_preparation_type",
        ),
    )
    op.create_index(
        "ix_candidate_documents_owner_preparation",
        "candidate_documents",
        ["owner_id", "preparation_id"],
        unique=False,
    )
    op.create_table(
        "candidate_document_versions",
        sa.Column("owner_id", sa.UUID(), nullable=False),
        sa.Column("document_id", sa.UUID(), nullable=False),
        sa.Column("file_asset_id", sa.UUID(), nullable=False),
        sa.Column("version_number", sa.Integer(), nullable=False),
        sa.Column("source_kind", sa.String(length=16), nullable=False),
        sa.Column("media_type", sa.String(length=255), nullable=False),
        sa.Column("content_length", sa.BigInteger(), nullable=False),
        sa.Column("content_sha256", sa.String(length=64), nullable=False),
        sa.Column("parser_release_policy_id", sa.UUID(), nullable=False),
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
        sa.CheckConstraint(
            "version_number > 0",
            name=op.f("ck_candidate_document_versions_version_number_positive"),
        ),
        sa.CheckConstraint(
            "source_kind IN ('upload', 'paste')",
            name=op.f("ck_candidate_document_versions_source_kind_allowed"),
        ),
        sa.CheckConstraint(
            "btrim(media_type) <> ''",
            name=op.f("ck_candidate_document_versions_media_type_nonempty"),
        ),
        sa.CheckConstraint(
            "content_length > 0",
            name=op.f("ck_candidate_document_versions_content_length_positive"),
        ),
        sa.CheckConstraint(
            "content_sha256 ~ '^[0-9a-f]{64}$'",
            name=op.f("ck_candidate_document_versions_content_digest_format"),
        ),
        sa.CheckConstraint(
            "retain_until > created_at",
            name=op.f("ck_candidate_document_versions_retention_after_creation"),
        ),
        sa.CheckConstraint(
            "retention_action = 'delete'",
            name=op.f("ck_candidate_document_versions_retention_action_delete_only"),
        ),
        sa.ForeignKeyConstraint(
            ["document_id", "owner_id"],
            ["candidate_documents.id", "candidate_documents.owner_id"],
            name="fk_candidate_document_versions_document_owner",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["file_asset_id", "owner_id"],
            ["file_assets.id", "file_assets.account_id"],
            name="fk_candidate_document_versions_file_asset_owner",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["owner_id"],
            ["accounts.id"],
            name=op.f("fk_candidate_document_versions_owner_id_accounts"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["parser_release_policy_id"],
            ["parser_release_policies.id"],
            name=op.f(
                "fk_candidate_document_versions_parser_release_policy_id_parser_release_policies"
            ),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["privacy_policy_version_id"],
            ["privacy_policy_versions.id"],
            name=op.f(
                "fk_candidate_document_versions_privacy_policy_version_id_privacy_policy_versions"
            ),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["retention_rule_id"],
            ["retention_rules.id"],
            name=op.f("fk_candidate_document_versions_retention_rule_id_retention_rules"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_candidate_document_versions")),
        sa.UniqueConstraint(
            "document_id",
            "version_number",
            name="uq_candidate_document_versions_document_number",
        ),
        sa.UniqueConstraint(
            "file_asset_id",
            name="uq_candidate_document_versions_file_asset",
        ),
    )
    op.create_index(
        "ix_candidate_document_versions_document_created",
        "candidate_document_versions",
        ["document_id", "created_at"],
        unique=False,
    )
    op.execute(
        """
        CREATE FUNCTION reject_candidate_document_version_update()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        BEGIN
            RAISE EXCEPTION 'candidate document versions are immutable'
                USING ERRCODE = '55000';
        END;
        $$
        """
    )
    op.execute(
        """
        CREATE TRIGGER candidate_document_versions_reject_update
        BEFORE UPDATE ON candidate_document_versions
        FOR EACH ROW
        EXECUTE FUNCTION reject_candidate_document_version_update()
        """
    )


def downgrade() -> None:
    op.execute(
        "DROP TRIGGER candidate_document_versions_reject_update ON candidate_document_versions"
    )
    op.execute("DROP FUNCTION reject_candidate_document_version_update()")
    op.drop_index(
        "ix_candidate_document_versions_document_created",
        table_name="candidate_document_versions",
    )
    op.drop_table("candidate_document_versions")
    op.drop_index(
        "ix_candidate_documents_owner_preparation",
        table_name="candidate_documents",
    )
    op.drop_table("candidate_documents")
    op.drop_constraint(
        "uq_file_assets_id_account",
        "file_assets",
        type_="unique",
    )
    op.drop_constraint(
        "uq_candidate_preparations_id_owner",
        "candidate_preparations",
        type_="unique",
    )
