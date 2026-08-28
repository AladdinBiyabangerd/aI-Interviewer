"""Durable extraction-job lineage for the isolated parser boundary."""

from datetime import datetime
from typing import Literal
from uuid import UUID

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import UUID as PostgreSQLUUID
from sqlalchemy.orm import Mapped, mapped_column

from ai_interviewer.persistence.base import (
    PersistenceBase,
    TimestampMixin,
    UUIDPrimaryKeyMixin,
)

ExtractionJobStatus = Literal["pending", "processing", "retry", "succeeded", "failed"]
ExtractionFailureCode = Literal[
    "input_unsupported",
    "input_corrupt",
    "input_encrypted",
    "input_empty",
    "parser_timeout",
    "resource_exceeded",
    "parser_crashed",
    "source_unavailable",
    "policy_unavailable",
    "internal_failure",
    "lease_expired",
]

MAX_EXTRACTION_ATTEMPTS = 5
EXTRACTION_LEASE_SECONDS = 300
RETRYABLE_EXTRACTION_FAILURES = frozenset(
    {
        "parser_timeout",
        "resource_exceeded",
        "parser_crashed",
        "source_unavailable",
        "internal_failure",
        "lease_expired",
    }
)


class CandidateExtractionJob(UUIDPrimaryKeyMixin, TimestampMixin, PersistenceBase):
    """Owner-bound, policy-snapshotted work item for one exact document version."""

    __tablename__ = "candidate_extraction_jobs"
    __table_args__ = (
        CheckConstraint(
            "status IN ('pending', 'processing', 'retry', 'succeeded', 'failed')",
            name="status_allowed",
        ),
        CheckConstraint(
            "attempts BETWEEN 0 AND 5",
            name="attempts_bounded",
        ),
        CheckConstraint(
            "btrim(parser_adapter) <> ''",
            name="parser_adapter_nonempty",
        ),
        CheckConstraint(
            "btrim(parser_version) <> ''",
            name="parser_version_nonempty",
        ),
        CheckConstraint(
            "btrim(isolation_profile) <> ''",
            name="isolation_profile_nonempty",
        ),
        CheckConstraint(
            "error_code IS NULL OR error_code IN "
            "('input_unsupported', 'input_corrupt', 'input_encrypted', 'input_empty', "
            "'parser_timeout', 'resource_exceeded', 'parser_crashed', 'source_unavailable', "
            "'policy_unavailable', 'internal_failure', 'lease_expired')",
            name="failure_code_allowed",
        ),
        CheckConstraint(
            "content_length > 0",
            name="content_length_positive",
        ),
        CheckConstraint(
            "content_sha256 ~ '^[0-9a-f]{64}$'",
            name="content_digest_format",
        ),
        CheckConstraint(
            "retention_action = 'delete'",
            name="retention_action_delete_only",
        ),
        CheckConstraint(
            "retain_until > created_at",
            name="retention_after_creation",
        ),
        CheckConstraint(
            "btrim(media_type) <> ''",
            name="media_type_nonempty",
        ),
        CheckConstraint(
            "btrim(jurisdiction_code) <> ''",
            name="jurisdiction_nonempty",
        ),
        CheckConstraint(
            "btrim(legal_basis) <> ''",
            name="legal_basis_nonempty",
        ),
        CheckConstraint(
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
            name="state_consistent",
        ),
        UniqueConstraint(
            "document_version_id",
            name="uq_candidate_extraction_jobs_document_version",
        ),
        UniqueConstraint(
            "id",
            "owner_id",
            name="uq_candidate_extraction_jobs_id_owner",
        ),
        ForeignKeyConstraint(
            ["document_version_id", "owner_id"],
            ["candidate_document_versions.id", "candidate_document_versions.owner_id"],
            name="fk_candidate_extraction_jobs_document_version_owner",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["file_asset_id", "owner_id"],
            ["file_assets.id", "file_assets.account_id"],
            name="fk_candidate_extraction_jobs_file_asset_owner",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["source_text_id", "owner_id"],
            ["candidate_source_texts.id", "candidate_source_texts.owner_id"],
            name="fk_candidate_extraction_jobs_source_text_owner",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["owner_id"],
            ["accounts.id"],
            name="fk_candidate_extraction_jobs_owner_id_accounts",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["parser_release_policy_id"],
            ["parser_release_policies.id"],
            name="fk_candidate_extraction_jobs_parser_policy",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["privacy_policy_version_id"],
            ["privacy_policy_versions.id"],
            name="fk_candidate_extraction_jobs_privacy_policy",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["retention_rule_id"],
            ["retention_rules.id"],
            name="fk_candidate_extraction_jobs_retention_rule",
            ondelete="RESTRICT",
        ),
        Index(
            "ix_candidate_extraction_jobs_status_available",
            "status",
            "available_at",
        ),
        Index(
            "ix_candidate_extraction_jobs_owner_created",
            "owner_id",
            "created_at",
        ),
    )

    owner_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        nullable=False,
    )
    document_version_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        nullable=False,
    )
    file_asset_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        nullable=False,
    )
    parser_release_policy_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        nullable=False,
    )
    privacy_policy_version_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        nullable=False,
    )
    retention_rule_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        nullable=False,
    )
    jurisdiction_code: Mapped[str] = mapped_column(String(64), nullable=False)
    legal_basis: Mapped[str] = mapped_column(String(64), nullable=False)
    retain_until: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    retention_action: Mapped[str] = mapped_column(String(16), nullable=False)
    media_type: Mapped[str] = mapped_column(String(255), nullable=False)
    content_length: Mapped[int] = mapped_column(BigInteger, nullable=False)
    content_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    parser_adapter: Mapped[str] = mapped_column(String(100), nullable=False)
    parser_version: Mapped[str] = mapped_column(String(64), nullable=False)
    isolation_profile: Mapped[str] = mapped_column(String(100), nullable=False)
    status: Mapped[ExtractionJobStatus] = mapped_column(String(16), nullable=False)
    attempts: Mapped[int] = mapped_column(
        Integer,
        default=0,
        server_default=text("0"),
        nullable=False,
    )
    available_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    locked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    locked_by: Mapped[str | None] = mapped_column(String(128), nullable=True)
    lease_token: Mapped[UUID | None] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        nullable=True,
    )
    error_code: Mapped[ExtractionFailureCode | None] = mapped_column(
        String(32),
        nullable=True,
    )
    source_text_id: Mapped[UUID | None] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        nullable=True,
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
