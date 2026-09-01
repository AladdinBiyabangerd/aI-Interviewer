"""Durable fenced profiling work for one exact corrected-source revision."""

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
    String,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import UUID as PostgreSQLUUID
from sqlalchemy.orm import Mapped, mapped_column

from ai_interviewer.persistence.base import PersistenceBase, TimestampMixin, UUIDPrimaryKeyMixin

ProfilingJobStatus = Literal[
    "pending",
    "processing",
    "retry",
    "succeeded",
    "dead_letter",
]
ProfilingFailureCode = Literal[
    "rate_limited",
    "provider_timeout",
    "provider_unavailable",
    "provider_rejected",
    "provider_failure",
    "model_identity_mismatch",
    "invalid_output",
    "output_too_large",
    "incomplete_output",
    "content_filtered",
    "source_unavailable",
    "policy_unavailable",
    "persistence_conflict",
    "internal_failure",
    "lease_expired",
]

MAX_PROFILING_ATTEMPTS = 5
PROFILING_LEASE_SECONDS = 300
RETRYABLE_PROFILING_FAILURES = frozenset(
    {
        "rate_limited",
        "provider_timeout",
        "provider_unavailable",
        "provider_failure",
        "source_unavailable",
        "internal_failure",
        "lease_expired",
    }
)


class CandidateProfilingJob(UUIDPrimaryKeyMixin, TimestampMixin, PersistenceBase):
    """Immutable execution snapshot plus a fenced mutable job state."""

    __tablename__ = "candidate_profiling_jobs"
    __table_args__ = (
        CheckConstraint(
            "document_type IN ('cv', 'job_description')",
            name="document_type_allowed",
        ),
        CheckConstraint(
            "status IN ('pending', 'processing', 'retry', 'succeeded', 'dead_letter')",
            name="status_allowed",
        ),
        CheckConstraint("attempts BETWEEN 0 AND 5", name="attempts_bounded"),
        CheckConstraint(
            "error_code IS NULL OR error_code IN "
            "('rate_limited', 'provider_timeout', 'provider_unavailable', "
            "'provider_rejected', 'provider_failure', 'model_identity_mismatch', "
            "'invalid_output', 'output_too_large', 'incomplete_output', "
            "'content_filtered', 'source_unavailable', 'policy_unavailable', "
            "'persistence_conflict', 'internal_failure', 'lease_expired')",
            name="failure_code_allowed",
        ),
        CheckConstraint(
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
            name="state_consistent",
        ),
        CheckConstraint(
            "(document_type = 'cv' AND schema_id = 'cv-profile') OR "
            "(document_type = 'job_description' "
            "AND schema_id = 'job-description-profile')",
            name="schema_matches_document_type",
        ),
        CheckConstraint("schema_version = '1.0.0'", name="schema_version_supported"),
        CheckConstraint(
            "model_provider ~ '^[A-Za-z0-9][A-Za-z0-9._:/-]{0,127}$'",
            name="model_provider_format",
        ),
        CheckConstraint(
            "model_id ~ '^[A-Za-z0-9][A-Za-z0-9._:/-]{0,127}$'",
            name="model_id_format",
        ),
        CheckConstraint(
            "model_version ~ '^[A-Za-z0-9][A-Za-z0-9._:/-]{0,127}$'",
            name="model_version_format",
        ),
        CheckConstraint(
            "prompt_id ~ '^[A-Za-z0-9][A-Za-z0-9._:/-]{0,127}$'",
            name="prompt_id_format",
        ),
        CheckConstraint(
            "prompt_version ~ '^[A-Za-z0-9][A-Za-z0-9._:/-]{0,127}$'",
            name="prompt_version_format",
        ),
        CheckConstraint(
            "instructions_sha256 ~ '^[0-9a-f]{64}$'",
            name="instructions_digest_format",
        ),
        CheckConstraint(
            "output_schema_sha256 ~ '^[0-9a-f]{64}$'",
            name="output_schema_digest_format",
        ),
        CheckConstraint(
            "max_output_tokens BETWEEN 1 AND 32768",
            name="max_output_tokens_bounded",
        ),
        CheckConstraint("btrim(jurisdiction_code) <> ''", name="jurisdiction_nonempty"),
        CheckConstraint("btrim(legal_basis) <> ''", name="legal_basis_nonempty"),
        CheckConstraint("retention_action = 'delete'", name="retention_action_delete_only"),
        CheckConstraint("retain_until > created_at", name="retention_after_creation"),
        UniqueConstraint(
            "source_text_version_id",
            name="uq_candidate_profiling_jobs_source_text_version",
        ),
        UniqueConstraint("id", "owner_id", name="uq_candidate_profiling_jobs_id_owner"),
        ForeignKeyConstraint(
            ["owner_id"],
            ["accounts.id"],
            name="fk_candidate_profiling_jobs_owner",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["preparation_id", "owner_id"],
            ["candidate_preparations.id", "candidate_preparations.owner_id"],
            name="fk_candidate_profiling_jobs_preparation_owner",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["document_version_id", "owner_id"],
            ["candidate_document_versions.id", "candidate_document_versions.owner_id"],
            name="fk_candidate_profiling_jobs_document_version_owner",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["source_text_id", "owner_id"],
            ["candidate_source_texts.id", "candidate_source_texts.owner_id"],
            name="fk_candidate_profiling_jobs_source_text_owner",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["source_text_version_id", "source_text_id"],
            ["candidate_source_text_versions.id", "candidate_source_text_versions.source_text_id"],
            name="fk_candidate_profiling_jobs_source_version",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["profile_id", "owner_id"],
            ["candidate_profiles.id", "candidate_profiles.owner_id"],
            name="fk_candidate_profiling_jobs_profile_owner",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["privacy_policy_version_id"],
            ["privacy_policy_versions.id"],
            name="fk_candidate_profiling_jobs_privacy_policy",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["retention_rule_id"],
            ["retention_rules.id"],
            name="fk_candidate_profiling_jobs_retention_rule",
            ondelete="RESTRICT",
        ),
        Index(
            "ix_candidate_profiling_jobs_status_available",
            "status",
            "available_at",
        ),
        Index(
            "ix_candidate_profiling_jobs_owner_created",
            "owner_id",
            "created_at",
        ),
    )

    owner_id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), nullable=False)
    preparation_id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), nullable=False)
    document_version_id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), nullable=False)
    source_text_id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), nullable=False)
    source_text_version_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True), nullable=False
    )
    processor_activity_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("processor_activities.id", ondelete="RESTRICT"),
        nullable=False,
    )
    document_type: Mapped[str] = mapped_column(String(24), nullable=False)
    privacy_policy_version_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True), nullable=False
    )
    retention_rule_id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), nullable=False)
    jurisdiction_code: Mapped[str] = mapped_column(String(64), nullable=False)
    legal_basis: Mapped[str] = mapped_column(String(64), nullable=False)
    retain_until: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    retention_action: Mapped[str] = mapped_column(String(16), nullable=False)
    model_provider: Mapped[str] = mapped_column(String(128), nullable=False)
    model_id: Mapped[str] = mapped_column(String(128), nullable=False)
    model_version: Mapped[str] = mapped_column(String(128), nullable=False)
    prompt_id: Mapped[str] = mapped_column(String(128), nullable=False)
    prompt_version: Mapped[str] = mapped_column(String(128), nullable=False)
    schema_id: Mapped[str] = mapped_column(String(128), nullable=False)
    schema_version: Mapped[str] = mapped_column(String(128), nullable=False)
    instructions_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    output_schema_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    max_output_tokens: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[ProfilingJobStatus] = mapped_column(String(16), nullable=False)
    attempts: Mapped[int] = mapped_column(
        Integer,
        default=0,
        server_default=text("0"),
        nullable=False,
    )
    available_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    locked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    locked_by: Mapped[str | None] = mapped_column(String(128), nullable=True)
    lease_token: Mapped[UUID | None] = mapped_column(PostgreSQLUUID(as_uuid=True), nullable=True)
    error_code: Mapped[ProfilingFailureCode | None] = mapped_column(String(32), nullable=True)
    profile_id: Mapped[UUID | None] = mapped_column(PostgreSQLUUID(as_uuid=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
