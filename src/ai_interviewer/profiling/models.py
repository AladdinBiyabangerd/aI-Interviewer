"""Encrypted immutable CV/JD profile lineage."""

from datetime import datetime
from typing import Literal
from uuid import UUID

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    LargeBinary,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import UUID as PostgreSQLUUID
from sqlalchemy.orm import Mapped, mapped_column

from ai_interviewer.candidate_inputs.document_models import CandidateDocumentType
from ai_interviewer.persistence.base import (
    PersistenceBase,
    TimestampMixin,
    UUIDPrimaryKeyMixin,
    VersionedRecordMixin,
)

CandidateProfileOrigin = Literal["model_generation", "user_correction"]

MAX_PROFILE_JSON_UTF8_BYTES = 1_000_000
MAX_PROFILE_CLAIMS = 360
MAX_PROFILE_EVIDENCE_SPANS = 1_800


class CandidateProfile(
    UUIDPrimaryKeyMixin,
    TimestampMixin,
    VersionedRecordMixin,
    PersistenceBase,
):
    """Stable profile identity for one exact immutable source-text revision."""

    __tablename__ = "candidate_profiles"
    __table_args__ = (
        CheckConstraint(
            "document_type IN ('cv', 'job_description')",
            name="document_type_allowed",
        ),
        CheckConstraint("latest_version_number > 0", name="latest_version_number_positive"),
        CheckConstraint("version > 0", name="version_positive"),
        CheckConstraint("btrim(jurisdiction_code) <> ''", name="jurisdiction_nonempty"),
        CheckConstraint("btrim(legal_basis) <> ''", name="legal_basis_nonempty"),
        CheckConstraint("retention_action = 'delete'", name="retention_action_delete_only"),
        CheckConstraint("retain_until > created_at", name="retention_after_creation"),
        UniqueConstraint(
            "source_text_version_id",
            name="uq_candidate_profiles_source_text_version",
        ),
        UniqueConstraint("id", "owner_id", name="uq_candidate_profiles_id_owner"),
        ForeignKeyConstraint(
            ["source_text_id", "owner_id"],
            ["candidate_source_texts.id", "candidate_source_texts.owner_id"],
            name="fk_candidate_profiles_source_text_owner",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["source_text_version_id", "source_text_id"],
            ["candidate_source_text_versions.id", "candidate_source_text_versions.source_text_id"],
            name="fk_candidate_profiles_source_version",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["document_version_id", "owner_id"],
            ["candidate_document_versions.id", "candidate_document_versions.owner_id"],
            name="fk_candidate_profiles_document_version_owner",
            ondelete="CASCADE",
        ),
        Index(
            "ix_candidate_profiles_owner_document_version",
            "owner_id",
            "document_version_id",
        ),
    )

    owner_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("accounts.id", ondelete="CASCADE"),
        nullable=False,
    )
    source_text_id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), nullable=False)
    source_text_version_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True), nullable=False
    )
    document_version_id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), nullable=False)
    document_type: Mapped[CandidateDocumentType] = mapped_column(String(24), nullable=False)
    latest_version_number: Mapped[int] = mapped_column(Integer, nullable=False)
    privacy_policy_version_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("privacy_policy_versions.id", ondelete="RESTRICT"),
        nullable=False,
    )
    retention_rule_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("retention_rules.id", ondelete="RESTRICT"),
        nullable=False,
    )
    jurisdiction_code: Mapped[str] = mapped_column(String(64), nullable=False)
    legal_basis: Mapped[str] = mapped_column(String(64), nullable=False)
    retain_until: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    retention_action: Mapped[str] = mapped_column(String(16), nullable=False)


class CandidateProfileVersion(UUIDPrimaryKeyMixin, PersistenceBase):
    """Append-only encrypted model result or later owner correction."""

    __tablename__ = "candidate_profile_versions"
    __table_args__ = (
        CheckConstraint("version_number > 0", name="version_number_positive"),
        CheckConstraint(
            "origin IN ('model_generation', 'user_correction')",
            name="origin_allowed",
        ),
        CheckConstraint(
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
            name="origin_provenance_consistent",
        ),
        CheckConstraint("btrim(schema_id) <> ''", name="schema_id_nonempty"),
        CheckConstraint("btrim(schema_version) <> ''", name="schema_version_nonempty"),
        CheckConstraint(
            "model_provider IS NULL OR btrim(model_provider) <> ''",
            name="model_provider_nonempty",
        ),
        CheckConstraint("model_id IS NULL OR btrim(model_id) <> ''", name="model_id_nonempty"),
        CheckConstraint(
            "model_version IS NULL OR btrim(model_version) <> ''",
            name="model_version_nonempty",
        ),
        CheckConstraint("prompt_id IS NULL OR btrim(prompt_id) <> ''", name="prompt_id_nonempty"),
        CheckConstraint(
            "prompt_version IS NULL OR btrim(prompt_version) <> ''",
            name="prompt_version_nonempty",
        ),
        CheckConstraint(
            "instructions_sha256 IS NULL OR instructions_sha256 ~ '^[0-9a-f]{64}$'",
            name="instructions_digest_format",
        ),
        CheckConstraint(
            "output_schema_sha256 IS NULL OR output_schema_sha256 ~ '^[0-9a-f]{64}$'",
            name="output_schema_digest_format",
        ),
        CheckConstraint(
            "model_attempts IS NULL OR model_attempts BETWEEN 1 AND 5",
            name="model_attempts_bounded",
        ),
        CheckConstraint(
            f"claim_count BETWEEN 1 AND {MAX_PROFILE_CLAIMS}",
            name="claim_count_bounded",
        ),
        CheckConstraint(
            f"evidence_span_count BETWEEN 1 AND {MAX_PROFILE_EVIDENCE_SPANS}",
            name="evidence_span_count_bounded",
        ),
        CheckConstraint(
            "evidence_character_count BETWEEN 1 AND 500000",
            name="evidence_character_count_bounded",
        ),
        CheckConstraint(
            f"profile_json_utf8_bytes BETWEEN 2 AND {MAX_PROFILE_JSON_UTF8_BYTES}",
            name="profile_json_bytes_bounded",
        ),
        CheckConstraint(
            "profile_digest ~ '^[0-9a-f]{64}$'",
            name="profile_digest_format",
        ),
        CheckConstraint("btrim(profile_digest_key_id) <> ''", name="digest_key_nonempty"),
        CheckConstraint(
            "btrim(profile_encryption_key_id) <> ''",
            name="encryption_key_nonempty",
        ),
        CheckConstraint("octet_length(profile_nonce) = 12", name="profile_nonce_length"),
        CheckConstraint(
            f"octet_length(profile_ciphertext) BETWEEN 18 AND {MAX_PROFILE_JSON_UTF8_BYTES + 16}",
            name="profile_ciphertext_bounded",
        ),
        UniqueConstraint(
            "profile_id",
            "version_number",
            name="uq_candidate_profile_versions_profile_number",
        ),
        UniqueConstraint(
            "id",
            "profile_id",
            name="uq_candidate_profile_versions_id_profile",
        ),
        ForeignKeyConstraint(
            ["profile_id", "owner_id"],
            ["candidate_profiles.id", "candidate_profiles.owner_id"],
            name="fk_candidate_profile_versions_profile_owner",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["previous_version_id", "profile_id"],
            ["candidate_profile_versions.id", "candidate_profile_versions.profile_id"],
            name="fk_candidate_profile_versions_previous_profile",
            ondelete="CASCADE",
        ),
        Index(
            "ix_candidate_profile_versions_profile_created",
            "profile_id",
            "created_at",
        ),
    )

    owner_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("accounts.id", ondelete="CASCADE"),
        nullable=False,
    )
    profile_id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), nullable=False)
    version_number: Mapped[int] = mapped_column(Integer, nullable=False)
    origin: Mapped[CandidateProfileOrigin] = mapped_column(String(24), nullable=False)
    previous_version_id: Mapped[UUID | None] = mapped_column(
        PostgreSQLUUID(as_uuid=True), nullable=True
    )
    schema_id: Mapped[str] = mapped_column(String(128), nullable=False)
    schema_version: Mapped[str] = mapped_column(String(128), nullable=False)
    model_provider: Mapped[str | None] = mapped_column(String(128), nullable=True)
    model_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    model_version: Mapped[str | None] = mapped_column(String(128), nullable=True)
    prompt_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    prompt_version: Mapped[str | None] = mapped_column(String(128), nullable=True)
    instructions_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    output_schema_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    model_attempts: Mapped[int | None] = mapped_column(Integer, nullable=True)
    claim_count: Mapped[int] = mapped_column(Integer, nullable=False)
    evidence_span_count: Mapped[int] = mapped_column(Integer, nullable=False)
    evidence_character_count: Mapped[int] = mapped_column(Integer, nullable=False)
    profile_json_utf8_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    profile_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    profile_digest_key_id: Mapped[str] = mapped_column(String(64), nullable=False)
    profile_ciphertext: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    profile_nonce: Mapped[bytes] = mapped_column(LargeBinary(12), nullable=False)
    profile_encryption_key_id: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
