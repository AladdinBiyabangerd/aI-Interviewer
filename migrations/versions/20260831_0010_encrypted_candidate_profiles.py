"""encrypted candidate profiles

Revision ID: 20260831_0010
Revises: 20260828_0009
Create Date: 2026-08-31 00:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260831_0010"
down_revision: str | None = "20260828_0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "candidate_profiles",
        sa.Column("owner_id", sa.UUID(), nullable=False),
        sa.Column("source_text_id", sa.UUID(), nullable=False),
        sa.Column("source_text_version_id", sa.UUID(), nullable=False),
        sa.Column("document_version_id", sa.UUID(), nullable=False),
        sa.Column("document_type", sa.String(length=24), nullable=False),
        sa.Column("latest_version_number", sa.Integer(), nullable=False),
        sa.Column("privacy_policy_version_id", sa.UUID(), nullable=False),
        sa.Column("retention_rule_id", sa.UUID(), nullable=False),
        sa.Column("jurisdiction_code", sa.String(length=64), nullable=False),
        sa.Column("legal_basis", sa.String(length=64), nullable=False),
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
            name=op.f("ck_candidate_profiles_document_type_allowed"),
        ),
        sa.CheckConstraint(
            "latest_version_number > 0",
            name=op.f("ck_candidate_profiles_latest_version_number_positive"),
        ),
        sa.CheckConstraint(
            "version > 0",
            name=op.f("ck_candidate_profiles_version_positive"),
        ),
        sa.CheckConstraint(
            "btrim(jurisdiction_code) <> ''",
            name=op.f("ck_candidate_profiles_jurisdiction_nonempty"),
        ),
        sa.CheckConstraint(
            "btrim(legal_basis) <> ''",
            name=op.f("ck_candidate_profiles_legal_basis_nonempty"),
        ),
        sa.CheckConstraint(
            "retention_action = 'delete'",
            name=op.f("ck_candidate_profiles_retention_action_delete_only"),
        ),
        sa.CheckConstraint(
            "retain_until > created_at",
            name=op.f("ck_candidate_profiles_retention_after_creation"),
        ),
        sa.ForeignKeyConstraint(
            ["owner_id"],
            ["accounts.id"],
            name=op.f("fk_candidate_profiles_owner_id_accounts"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["source_text_id", "owner_id"],
            ["candidate_source_texts.id", "candidate_source_texts.owner_id"],
            name="fk_candidate_profiles_source_text_owner",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["source_text_version_id", "source_text_id"],
            ["candidate_source_text_versions.id", "candidate_source_text_versions.source_text_id"],
            name="fk_candidate_profiles_source_version",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["document_version_id", "owner_id"],
            ["candidate_document_versions.id", "candidate_document_versions.owner_id"],
            name="fk_candidate_profiles_document_version_owner",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["privacy_policy_version_id"],
            ["privacy_policy_versions.id"],
            name=op.f("fk_candidate_profiles_privacy_policy_version_id_privacy_policy_versions"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["retention_rule_id"],
            ["retention_rules.id"],
            name=op.f("fk_candidate_profiles_retention_rule_id_retention_rules"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_candidate_profiles")),
        sa.UniqueConstraint(
            "source_text_version_id",
            name="uq_candidate_profiles_source_text_version",
        ),
        sa.UniqueConstraint("id", "owner_id", name="uq_candidate_profiles_id_owner"),
    )
    op.create_index(
        "ix_candidate_profiles_owner_document_version",
        "candidate_profiles",
        ["owner_id", "document_version_id"],
        unique=False,
    )
    op.create_table(
        "candidate_profile_versions",
        sa.Column("owner_id", sa.UUID(), nullable=False),
        sa.Column("profile_id", sa.UUID(), nullable=False),
        sa.Column("version_number", sa.Integer(), nullable=False),
        sa.Column("origin", sa.String(length=24), nullable=False),
        sa.Column("previous_version_id", sa.UUID(), nullable=True),
        sa.Column("schema_id", sa.String(length=128), nullable=False),
        sa.Column("schema_version", sa.String(length=128), nullable=False),
        sa.Column("model_provider", sa.String(length=128), nullable=True),
        sa.Column("model_id", sa.String(length=128), nullable=True),
        sa.Column("model_version", sa.String(length=128), nullable=True),
        sa.Column("prompt_id", sa.String(length=128), nullable=True),
        sa.Column("prompt_version", sa.String(length=128), nullable=True),
        sa.Column("instructions_sha256", sa.String(length=64), nullable=True),
        sa.Column("output_schema_sha256", sa.String(length=64), nullable=True),
        sa.Column("model_attempts", sa.Integer(), nullable=True),
        sa.Column("claim_count", sa.Integer(), nullable=False),
        sa.Column("evidence_span_count", sa.Integer(), nullable=False),
        sa.Column("evidence_character_count", sa.Integer(), nullable=False),
        sa.Column("profile_json_utf8_bytes", sa.Integer(), nullable=False),
        sa.Column("profile_digest", sa.String(length=64), nullable=False),
        sa.Column("profile_digest_key_id", sa.String(length=64), nullable=False),
        sa.Column("profile_ciphertext", sa.LargeBinary(), nullable=False),
        sa.Column("profile_nonce", sa.LargeBinary(length=12), nullable=False),
        sa.Column("profile_encryption_key_id", sa.String(length=64), nullable=False),
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "version_number > 0",
            name=op.f("ck_candidate_profile_versions_version_number_positive"),
        ),
        sa.CheckConstraint(
            "origin IN ('model_generation', 'user_correction')",
            name=op.f("ck_candidate_profile_versions_origin_allowed"),
        ),
        sa.CheckConstraint(
            "(origin = 'model_generation' AND version_number = 1 "
            "AND previous_version_id IS NULL AND model_provider IS NOT NULL "
            "AND model_id IS NOT NULL AND model_version IS NOT NULL "
            "AND prompt_id IS NOT NULL AND prompt_version IS NOT NULL "
            "AND instructions_sha256 IS NOT NULL AND output_schema_sha256 IS NOT NULL "
            "AND model_attempts IS NOT NULL) OR "
            "(origin = 'user_correction' AND version_number > 1 "
            "AND previous_version_id IS NOT NULL AND model_provider IS NULL "
            "AND model_id IS NULL AND model_version IS NULL "
            "AND prompt_id IS NULL AND prompt_version IS NULL "
            "AND instructions_sha256 IS NULL AND output_schema_sha256 IS NULL "
            "AND model_attempts IS NULL)",
            name=op.f("ck_candidate_profile_versions_origin_provenance_consistent"),
        ),
        sa.CheckConstraint(
            "btrim(schema_id) <> ''",
            name=op.f("ck_candidate_profile_versions_schema_id_nonempty"),
        ),
        sa.CheckConstraint(
            "btrim(schema_version) <> ''",
            name=op.f("ck_candidate_profile_versions_schema_version_nonempty"),
        ),
        sa.CheckConstraint(
            "model_provider IS NULL OR btrim(model_provider) <> ''",
            name=op.f("ck_candidate_profile_versions_model_provider_nonempty"),
        ),
        sa.CheckConstraint(
            "model_id IS NULL OR btrim(model_id) <> ''",
            name=op.f("ck_candidate_profile_versions_model_id_nonempty"),
        ),
        sa.CheckConstraint(
            "model_version IS NULL OR btrim(model_version) <> ''",
            name=op.f("ck_candidate_profile_versions_model_version_nonempty"),
        ),
        sa.CheckConstraint(
            "prompt_id IS NULL OR btrim(prompt_id) <> ''",
            name=op.f("ck_candidate_profile_versions_prompt_id_nonempty"),
        ),
        sa.CheckConstraint(
            "prompt_version IS NULL OR btrim(prompt_version) <> ''",
            name=op.f("ck_candidate_profile_versions_prompt_version_nonempty"),
        ),
        sa.CheckConstraint(
            "instructions_sha256 IS NULL OR instructions_sha256 ~ '^[0-9a-f]{64}$'",
            name=op.f("ck_candidate_profile_versions_instructions_digest_format"),
        ),
        sa.CheckConstraint(
            "output_schema_sha256 IS NULL OR output_schema_sha256 ~ '^[0-9a-f]{64}$'",
            name=op.f("ck_candidate_profile_versions_output_schema_digest_format"),
        ),
        sa.CheckConstraint(
            "model_attempts IS NULL OR model_attempts BETWEEN 1 AND 5",
            name=op.f("ck_candidate_profile_versions_model_attempts_bounded"),
        ),
        sa.CheckConstraint(
            "claim_count BETWEEN 1 AND 360",
            name=op.f("ck_candidate_profile_versions_claim_count_bounded"),
        ),
        sa.CheckConstraint(
            "evidence_span_count BETWEEN 1 AND 1800",
            name=op.f("ck_candidate_profile_versions_evidence_span_count_bounded"),
        ),
        sa.CheckConstraint(
            "evidence_character_count BETWEEN 1 AND 500000",
            name=op.f("ck_candidate_profile_versions_evidence_character_count_bounded"),
        ),
        sa.CheckConstraint(
            "profile_json_utf8_bytes BETWEEN 2 AND 1000000",
            name=op.f("ck_candidate_profile_versions_profile_json_bytes_bounded"),
        ),
        sa.CheckConstraint(
            "profile_digest ~ '^[0-9a-f]{64}$'",
            name=op.f("ck_candidate_profile_versions_profile_digest_format"),
        ),
        sa.CheckConstraint(
            "btrim(profile_digest_key_id) <> ''",
            name=op.f("ck_candidate_profile_versions_digest_key_nonempty"),
        ),
        sa.CheckConstraint(
            "btrim(profile_encryption_key_id) <> ''",
            name=op.f("ck_candidate_profile_versions_encryption_key_nonempty"),
        ),
        sa.CheckConstraint(
            "octet_length(profile_nonce) = 12",
            name=op.f("ck_candidate_profile_versions_profile_nonce_length"),
        ),
        sa.CheckConstraint(
            "octet_length(profile_ciphertext) BETWEEN 18 AND 1000016",
            name=op.f("ck_candidate_profile_versions_profile_ciphertext_bounded"),
        ),
        sa.ForeignKeyConstraint(
            ["owner_id"],
            ["accounts.id"],
            name=op.f("fk_candidate_profile_versions_owner_id_accounts"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["profile_id", "owner_id"],
            ["candidate_profiles.id", "candidate_profiles.owner_id"],
            name="fk_candidate_profile_versions_profile_owner",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["previous_version_id", "profile_id"],
            ["candidate_profile_versions.id", "candidate_profile_versions.profile_id"],
            name="fk_candidate_profile_versions_previous_profile",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_candidate_profile_versions")),
        sa.UniqueConstraint(
            "profile_id",
            "version_number",
            name="uq_candidate_profile_versions_profile_number",
        ),
        sa.UniqueConstraint(
            "id",
            "profile_id",
            name="uq_candidate_profile_versions_id_profile",
        ),
    )
    op.create_index(
        "ix_candidate_profile_versions_profile_created",
        "candidate_profile_versions",
        ["profile_id", "created_at"],
        unique=False,
    )
    op.execute(
        """
        CREATE FUNCTION validate_candidate_profile_snapshot()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        DECLARE
            source_snapshot candidate_source_texts%ROWTYPE;
            source_version_snapshot candidate_source_text_versions%ROWTYPE;
            document_version_snapshot candidate_document_versions%ROWTYPE;
            document_snapshot candidate_documents%ROWTYPE;
        BEGIN
            SELECT * INTO source_snapshot
            FROM candidate_source_texts
            WHERE id = NEW.source_text_id AND owner_id = NEW.owner_id;
            SELECT * INTO source_version_snapshot
            FROM candidate_source_text_versions
            WHERE id = NEW.source_text_version_id AND source_text_id = NEW.source_text_id;
            SELECT * INTO document_version_snapshot
            FROM candidate_document_versions
            WHERE id = NEW.document_version_id AND owner_id = NEW.owner_id;
            IF document_version_snapshot.id IS NOT NULL THEN
                SELECT * INTO document_snapshot
                FROM candidate_documents
                WHERE id = document_version_snapshot.document_id AND owner_id = NEW.owner_id;
            END IF;
            IF source_snapshot.id IS NULL
                OR source_version_snapshot.id IS NULL
                OR document_version_snapshot.id IS NULL
                OR document_snapshot.id IS NULL
                OR source_snapshot.document_version_id IS DISTINCT FROM NEW.document_version_id
                OR document_snapshot.document_type IS DISTINCT FROM NEW.document_type
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
                RAISE EXCEPTION 'candidate profile snapshot is inconsistent'
                    USING ERRCODE = '23514';
            END IF;
            RETURN NEW;
        END;
        $$
        """
    )
    op.execute(
        """
        CREATE TRIGGER candidate_profiles_validate_snapshot
        BEFORE INSERT ON candidate_profiles
        FOR EACH ROW
        EXECUTE FUNCTION validate_candidate_profile_snapshot()
        """
    )
    op.execute(
        """
        CREATE FUNCTION protect_candidate_profile_identity()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        BEGIN
            IF NEW.id IS DISTINCT FROM OLD.id
                OR NEW.owner_id IS DISTINCT FROM OLD.owner_id
                OR NEW.source_text_id IS DISTINCT FROM OLD.source_text_id
                OR NEW.source_text_version_id IS DISTINCT FROM OLD.source_text_version_id
                OR NEW.document_version_id IS DISTINCT FROM OLD.document_version_id
                OR NEW.document_type IS DISTINCT FROM OLD.document_type
                OR NEW.privacy_policy_version_id IS DISTINCT FROM OLD.privacy_policy_version_id
                OR NEW.retention_rule_id IS DISTINCT FROM OLD.retention_rule_id
                OR NEW.jurisdiction_code IS DISTINCT FROM OLD.jurisdiction_code
                OR NEW.legal_basis IS DISTINCT FROM OLD.legal_basis
                OR NEW.retain_until IS DISTINCT FROM OLD.retain_until
                OR NEW.retention_action IS DISTINCT FROM OLD.retention_action
                OR NEW.created_at IS DISTINCT FROM OLD.created_at THEN
                RAISE EXCEPTION 'candidate profile identity is immutable'
                    USING ERRCODE = '55000';
            END IF;
            RETURN NEW;
        END;
        $$
        """
    )
    op.execute(
        """
        CREATE TRIGGER candidate_profiles_protect_identity
        BEFORE UPDATE ON candidate_profiles
        FOR EACH ROW
        EXECUTE FUNCTION protect_candidate_profile_identity()
        """
    )
    op.execute(
        """
        CREATE FUNCTION reject_candidate_profile_version_update()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        BEGIN
            RAISE EXCEPTION 'candidate profile versions are immutable'
                USING ERRCODE = '55000';
        END;
        $$
        """
    )
    op.execute(
        """
        CREATE TRIGGER candidate_profile_versions_reject_update
        BEFORE UPDATE ON candidate_profile_versions
        FOR EACH ROW
        EXECUTE FUNCTION reject_candidate_profile_version_update()
        """
    )
    op.execute(
        """
        CREATE FUNCTION validate_candidate_profile_version_chain()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        DECLARE
            previous_number integer;
        BEGIN
            IF NEW.version_number = 1 THEN
                RETURN NEW;
            END IF;
            SELECT version_number INTO previous_number
            FROM candidate_profile_versions
            WHERE id = NEW.previous_version_id AND profile_id = NEW.profile_id;
            IF previous_number IS DISTINCT FROM NEW.version_number - 1 THEN
                RAISE EXCEPTION 'candidate profile version chain is invalid'
                    USING ERRCODE = '23514';
            END IF;
            RETURN NEW;
        END;
        $$
        """
    )
    op.execute(
        """
        CREATE TRIGGER candidate_profile_versions_validate_chain
        BEFORE INSERT ON candidate_profile_versions
        FOR EACH ROW
        EXECUTE FUNCTION validate_candidate_profile_version_chain()
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (SELECT 1 FROM candidate_profiles LIMIT 1) THEN
                RAISE EXCEPTION 'Cannot downgrade while encrypted candidate profiles exist';
            END IF;
        END;
        $$
        """
    )
    op.execute(
        "DROP TRIGGER candidate_profile_versions_validate_chain ON candidate_profile_versions"
    )
    op.execute("DROP FUNCTION validate_candidate_profile_version_chain()")
    op.execute(
        "DROP TRIGGER candidate_profile_versions_reject_update ON candidate_profile_versions"
    )
    op.execute("DROP FUNCTION reject_candidate_profile_version_update()")
    op.execute("DROP TRIGGER candidate_profiles_protect_identity ON candidate_profiles")
    op.execute("DROP FUNCTION protect_candidate_profile_identity()")
    op.execute("DROP TRIGGER candidate_profiles_validate_snapshot ON candidate_profiles")
    op.execute("DROP FUNCTION validate_candidate_profile_snapshot()")
    op.drop_index(
        "ix_candidate_profile_versions_profile_created",
        table_name="candidate_profile_versions",
    )
    op.drop_table("candidate_profile_versions")
    op.drop_index(
        "ix_candidate_profiles_owner_document_version",
        table_name="candidate_profiles",
    )
    op.drop_table("candidate_profiles")
