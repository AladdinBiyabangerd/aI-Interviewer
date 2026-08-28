"""encrypted candidate source text

Revision ID: 20260827_0008
Revises: 20260827_0007
Create Date: 2026-08-27 00:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260827_0008"
down_revision: str | None = "20260827_0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_unique_constraint(
        "uq_candidate_document_versions_id_owner",
        "candidate_document_versions",
        ["id", "owner_id"],
    )
    op.create_table(
        "candidate_source_texts",
        sa.Column("owner_id", sa.UUID(), nullable=False),
        sa.Column("document_version_id", sa.UUID(), nullable=False),
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
            "latest_version_number > 0",
            name=op.f("ck_candidate_source_texts_latest_version_number_positive"),
        ),
        sa.CheckConstraint(
            "version > 0",
            name=op.f("ck_candidate_source_texts_version_positive"),
        ),
        sa.ForeignKeyConstraint(
            ["owner_id"],
            ["accounts.id"],
            name=op.f("fk_candidate_source_texts_owner_id_accounts"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["document_version_id", "owner_id"],
            ["candidate_document_versions.id", "candidate_document_versions.owner_id"],
            name="fk_candidate_source_texts_document_version_owner",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_candidate_source_texts")),
        sa.UniqueConstraint(
            "document_version_id",
            name="uq_candidate_source_texts_document_version",
        ),
        sa.UniqueConstraint(
            "id",
            "owner_id",
            name="uq_candidate_source_texts_id_owner",
        ),
    )
    op.create_index(
        "ix_candidate_source_texts_owner_document_version",
        "candidate_source_texts",
        ["owner_id", "document_version_id"],
        unique=False,
    )
    op.create_table(
        "candidate_source_text_versions",
        sa.Column("owner_id", sa.UUID(), nullable=False),
        sa.Column("source_text_id", sa.UUID(), nullable=False),
        sa.Column("version_number", sa.Integer(), nullable=False),
        sa.Column("origin", sa.String(length=24), nullable=False),
        sa.Column("previous_version_id", sa.UUID(), nullable=True),
        sa.Column("parser_release_policy_id", sa.UUID(), nullable=True),
        sa.Column("parser_adapter", sa.String(length=100), nullable=True),
        sa.Column("parser_version", sa.String(length=64), nullable=True),
        sa.Column("isolation_profile", sa.String(length=100), nullable=True),
        sa.Column("character_count", sa.Integer(), nullable=False),
        sa.Column("utf8_byte_count", sa.Integer(), nullable=False),
        sa.Column("line_count", sa.Integer(), nullable=False),
        sa.Column("content_digest", sa.String(length=64), nullable=False),
        sa.Column("content_digest_key_id", sa.String(length=64), nullable=False),
        sa.Column("content_ciphertext", sa.LargeBinary(), nullable=False),
        sa.Column("content_nonce", sa.LargeBinary(length=12), nullable=False),
        sa.Column("content_encryption_key_id", sa.String(length=64), nullable=False),
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "version_number > 0",
            name=op.f("ck_candidate_source_text_versions_version_number_positive"),
        ),
        sa.CheckConstraint(
            "origin IN ('parser_extraction', 'user_correction')",
            name=op.f("ck_candidate_source_text_versions_origin_allowed"),
        ),
        sa.CheckConstraint(
            "(origin = 'parser_extraction' AND version_number = 1 "
            "AND previous_version_id IS NULL AND parser_release_policy_id IS NOT NULL "
            "AND parser_adapter IS NOT NULL AND parser_version IS NOT NULL "
            "AND isolation_profile IS NOT NULL) OR "
            "(origin = 'user_correction' AND version_number > 1 "
            "AND previous_version_id IS NOT NULL AND parser_release_policy_id IS NULL "
            "AND parser_adapter IS NULL AND parser_version IS NULL "
            "AND isolation_profile IS NULL)",
            name=op.f("ck_candidate_source_text_versions_origin_provenance_consistent"),
        ),
        sa.CheckConstraint(
            "parser_adapter IS NULL OR btrim(parser_adapter) <> ''",
            name=op.f("ck_candidate_source_text_versions_parser_adapter_nonempty"),
        ),
        sa.CheckConstraint(
            "parser_version IS NULL OR btrim(parser_version) <> ''",
            name=op.f("ck_candidate_source_text_versions_parser_version_nonempty"),
        ),
        sa.CheckConstraint(
            "isolation_profile IS NULL OR btrim(isolation_profile) <> ''",
            name=op.f("ck_candidate_source_text_versions_isolation_profile_nonempty"),
        ),
        sa.CheckConstraint(
            "character_count BETWEEN 1 AND 500000",
            name=op.f("ck_candidate_source_text_versions_character_count_bounded"),
        ),
        sa.CheckConstraint(
            "utf8_byte_count BETWEEN 1 AND 2000000",
            name=op.f("ck_candidate_source_text_versions_utf8_byte_count_bounded"),
        ),
        sa.CheckConstraint(
            "line_count BETWEEN 1 AND character_count + 1",
            name=op.f("ck_candidate_source_text_versions_line_count_bounded"),
        ),
        sa.CheckConstraint(
            "content_digest ~ '^[0-9a-f]{64}$'",
            name=op.f("ck_candidate_source_text_versions_content_digest_format"),
        ),
        sa.CheckConstraint(
            "btrim(content_digest_key_id) <> ''",
            name=op.f("ck_candidate_source_text_versions_digest_key_nonempty"),
        ),
        sa.CheckConstraint(
            "btrim(content_encryption_key_id) <> ''",
            name=op.f("ck_candidate_source_text_versions_encryption_key_nonempty"),
        ),
        sa.CheckConstraint(
            "octet_length(content_nonce) = 12",
            name=op.f("ck_candidate_source_text_versions_content_nonce_length"),
        ),
        sa.CheckConstraint(
            "octet_length(content_ciphertext) BETWEEN 17 AND 2000016",
            name=op.f("ck_candidate_source_text_versions_content_ciphertext_bounded"),
        ),
        sa.ForeignKeyConstraint(
            ["owner_id"],
            ["accounts.id"],
            name=op.f("fk_candidate_source_text_versions_owner_id_accounts"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["source_text_id", "owner_id"],
            ["candidate_source_texts.id", "candidate_source_texts.owner_id"],
            name="fk_candidate_source_text_versions_source_owner",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["previous_version_id", "source_text_id"],
            ["candidate_source_text_versions.id", "candidate_source_text_versions.source_text_id"],
            name="fk_candidate_source_text_versions_previous_source",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["parser_release_policy_id"],
            ["parser_release_policies.id"],
            name="fk_candidate_source_text_versions_parser_policy",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_candidate_source_text_versions")),
        sa.UniqueConstraint(
            "source_text_id",
            "version_number",
            name="uq_candidate_source_text_versions_source_number",
        ),
        sa.UniqueConstraint(
            "id",
            "source_text_id",
            name="uq_candidate_source_text_versions_id_source",
        ),
    )
    op.create_index(
        "ix_candidate_source_text_versions_source_created",
        "candidate_source_text_versions",
        ["source_text_id", "created_at"],
        unique=False,
    )
    op.execute(
        """
        CREATE FUNCTION protect_candidate_source_text_identity()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        BEGIN
            IF NEW.id IS DISTINCT FROM OLD.id
                OR NEW.owner_id IS DISTINCT FROM OLD.owner_id
                OR NEW.document_version_id IS DISTINCT FROM OLD.document_version_id
                OR NEW.created_at IS DISTINCT FROM OLD.created_at THEN
                RAISE EXCEPTION 'candidate source-text identity is immutable'
                    USING ERRCODE = '55000';
            END IF;
            RETURN NEW;
        END;
        $$
        """
    )
    op.execute(
        """
        CREATE TRIGGER candidate_source_texts_protect_identity
        BEFORE UPDATE ON candidate_source_texts
        FOR EACH ROW
        EXECUTE FUNCTION protect_candidate_source_text_identity()
        """
    )
    op.execute(
        """
        CREATE FUNCTION reject_candidate_source_text_version_update()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        BEGIN
            RAISE EXCEPTION 'candidate source-text versions are immutable'
                USING ERRCODE = '55000';
        END;
        $$
        """
    )
    op.execute(
        """
        CREATE TRIGGER candidate_source_text_versions_reject_update
        BEFORE UPDATE ON candidate_source_text_versions
        FOR EACH ROW
        EXECUTE FUNCTION reject_candidate_source_text_version_update()
        """
    )
    op.execute(
        """
        CREATE FUNCTION validate_candidate_source_text_version_chain()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        DECLARE
            previous_number integer;
        BEGIN
            IF NEW.version_number = 1 THEN
                RETURN NEW;
            END IF;
            SELECT version_number
            INTO previous_number
            FROM candidate_source_text_versions
            WHERE id = NEW.previous_version_id
                AND source_text_id = NEW.source_text_id;
            IF previous_number IS DISTINCT FROM NEW.version_number - 1 THEN
                RAISE EXCEPTION 'candidate source-text version chain is invalid'
                    USING ERRCODE = '23514';
            END IF;
            RETURN NEW;
        END;
        $$
        """
    )
    op.execute(
        """
        CREATE TRIGGER candidate_source_text_versions_validate_chain
        BEFORE INSERT ON candidate_source_text_versions
        FOR EACH ROW
        EXECUTE FUNCTION validate_candidate_source_text_version_chain()
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (SELECT 1 FROM candidate_source_texts LIMIT 1) THEN
                RAISE EXCEPTION
                    'Cannot downgrade while encrypted candidate source text exists';
            END IF;
        END;
        $$
        """
    )
    op.execute(
        "DROP TRIGGER candidate_source_text_versions_validate_chain "
        "ON candidate_source_text_versions"
    )
    op.execute("DROP FUNCTION validate_candidate_source_text_version_chain()")
    op.execute(
        "DROP TRIGGER candidate_source_text_versions_reject_update "
        "ON candidate_source_text_versions"
    )
    op.execute("DROP FUNCTION reject_candidate_source_text_version_update()")
    op.execute("DROP TRIGGER candidate_source_texts_protect_identity ON candidate_source_texts")
    op.execute("DROP FUNCTION protect_candidate_source_text_identity()")
    op.drop_index(
        "ix_candidate_source_text_versions_source_created",
        table_name="candidate_source_text_versions",
    )
    op.drop_table("candidate_source_text_versions")
    op.drop_index(
        "ix_candidate_source_texts_owner_document_version",
        table_name="candidate_source_texts",
    )
    op.drop_table("candidate_source_texts")
    op.drop_constraint(
        "uq_candidate_document_versions_id_owner",
        "candidate_document_versions",
        type_="unique",
    )
