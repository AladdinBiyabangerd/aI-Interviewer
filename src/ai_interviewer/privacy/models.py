"""Relational privacy-policy, consent, request, retention, and processor records."""

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    LargeBinary,
    String,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PostgreSQLUUID
from sqlalchemy.orm import Mapped, mapped_column

from ai_interviewer.persistence.base import (
    PersistenceBase,
    TimestampMixin,
    UUIDPrimaryKeyMixin,
    VersionedRecordMixin,
)

PolicyStatus = Literal["draft", "active", "retired"]
LegalReviewStatus = Literal["pending", "approved", "superseded"]
ConsentNoticeStatus = Literal["draft", "active", "retired"]
PrivacyRequestType = Literal["access", "export", "deletion"]
PrivacyRequestStatus = Literal[
    "received", "verified", "processing", "completed", "failed", "cancelled"
]
RetentionAction = Literal["delete", "anonymize"]
ProcessorStatus = Literal["active", "suspended", "retired"]
DeletionTaskStatus = Literal["pending", "processing", "completed", "retry", "escalated"]


class PrivacyPolicyVersion(UUIDPrimaryKeyMixin, PersistenceBase):
    """Published policy snapshot selected for a jurisdiction layer."""

    __tablename__ = "privacy_policy_versions"
    __table_args__ = (
        UniqueConstraint("policy_key", "policy_version", name="uq_policy_key_version"),
        CheckConstraint("status IN ('draft', 'active', 'retired')", name="status_allowed"),
        CheckConstraint(
            "legal_review_status IN ('pending', 'approved', 'superseded')",
            name="legal_review_status_allowed",
        ),
        CheckConstraint(
            "status <> 'active' OR legal_review_status = 'approved'",
            name="active_requires_legal_approval",
        ),
        CheckConstraint("minimum_age >= 18 AND minimum_age <= 120", name="minimum_age_valid"),
        CheckConstraint(
            "request_deadline_days >= 1 AND request_deadline_days <= 365",
            name="request_deadline_valid",
        ),
        CheckConstraint("char_length(content_sha256) = 64", name="content_digest_length"),
        Index("ix_privacy_policy_jurisdiction_status", "jurisdiction_code", "status"),
    )

    policy_key: Mapped[str] = mapped_column(String(100), nullable=False)
    policy_version: Mapped[str] = mapped_column(String(64), nullable=False)
    jurisdiction_code: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[PolicyStatus] = mapped_column(String(16), nullable=False)
    legal_review_status: Mapped[LegalReviewStatus] = mapped_column(String(16), nullable=False)
    minimum_age: Mapped[int] = mapped_column(Integer, nullable=False, default=18)
    request_deadline_days: Mapped[int] = mapped_column(Integer, nullable=False)
    notice_uri: Mapped[str] = mapped_column(String(2048), nullable=False)
    content_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    effective_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    retired_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class PrivacyProfile(TimestampMixin, VersionedRecordMixin, PersistenceBase):
    """Self-declared residence and the exact policy routing snapshot applied to an account."""

    __tablename__ = "privacy_profiles"
    __table_args__ = (
        CheckConstraint("char_length(residence_country_code) = 2", name="country_code_length"),
        CheckConstraint(
            "jsonb_array_length(jurisdiction_codes) >= 1",
            name="jurisdictions_nonempty",
        ),
        CheckConstraint("version > 0", name="version_positive"),
    )

    account_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("accounts.id", ondelete="CASCADE"),
        primary_key=True,
    )
    residence_country_code: Mapped[str] = mapped_column(String(2), nullable=False)
    residence_subdivision_code: Mapped[str | None] = mapped_column(String(16), nullable=True)
    jurisdiction_codes: Mapped[list[str]] = mapped_column(JSONB, nullable=False)
    jurisdiction_versions: Mapped[dict[str, str]] = mapped_column(JSONB, nullable=False)
    storage_region: Mapped[str] = mapped_column(String(64), nullable=False)
    adult_attested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    privacy_policy_version_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("privacy_policy_versions.id", ondelete="RESTRICT"),
        nullable=False,
    )


class ConsentNotice(UUIDPrimaryKeyMixin, PersistenceBase):
    """Immutable meaning of one explicit, versioned consent choice."""

    __tablename__ = "consent_notices"
    __table_args__ = (
        UniqueConstraint(
            "privacy_policy_version_id",
            "notice_key",
            "notice_version",
            name="uq_consent_notice_policy_key_version",
        ),
        CheckConstraint("status IN ('draft', 'active', 'retired')", name="status_allowed"),
        CheckConstraint("char_length(content_sha256) = 64", name="content_digest_length"),
        Index("ix_consent_notices_lookup", "notice_key", "status", "effective_at"),
    )

    privacy_policy_version_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("privacy_policy_versions.id", ondelete="RESTRICT"),
        nullable=False,
    )
    notice_key: Mapped[str] = mapped_column(String(100), nullable=False)
    notice_version: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[ConsentNoticeStatus] = mapped_column(String(16), nullable=False)
    purpose: Mapped[str] = mapped_column(String(100), nullable=False)
    data_category: Mapped[str] = mapped_column(String(100), nullable=False)
    document_uri: Mapped[str] = mapped_column(String(2048), nullable=False)
    content_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    effective_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    retired_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class ConsentRecord(
    UUIDPrimaryKeyMixin,
    TimestampMixin,
    VersionedRecordMixin,
    PersistenceBase,
):
    """Exact notice grant with explicit withdrawal and bounded evidence retention."""

    __tablename__ = "consent_records"
    __table_args__ = (
        CheckConstraint(
            "withdrawn_at IS NULL OR withdrawn_at >= granted_at",
            name="withdrawal_order",
        ),
        CheckConstraint("retain_until > granted_at", name="retention_after_grant"),
        CheckConstraint("version > 0", name="version_positive"),
        Index(
            "uq_consent_records_active_notice",
            "account_id",
            "consent_notice_id",
            unique=True,
            postgresql_where=text("withdrawn_at IS NULL"),
        ),
        Index("ix_consent_records_account_created", "account_id", "created_at"),
        Index("ix_consent_records_retention", "retain_until"),
    )

    account_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("accounts.id", ondelete="CASCADE"),
        nullable=False,
    )
    consent_notice_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("consent_notices.id", ondelete="RESTRICT"),
        nullable=False,
    )
    granted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    withdrawn_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    retain_until: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    retention_action: Mapped[RetentionAction] = mapped_column(String(16), nullable=False)
    request_id: Mapped[str | None] = mapped_column(String(128), nullable=True)


class ProcessingRule(UUIDPrimaryKeyMixin, PersistenceBase):
    """Narrow allow/deny rule for one purpose and data category."""

    __tablename__ = "processing_rules"
    __table_args__ = (
        UniqueConstraint(
            "privacy_policy_version_id",
            "jurisdiction_code",
            "data_category",
            "purpose",
            name="uq_processing_rule_context",
        ),
        CheckConstraint("btrim(legal_basis) <> ''", name="legal_basis_nonempty"),
        Index("ix_processing_rules_resolution", "privacy_policy_version_id", "jurisdiction_code"),
    )

    privacy_policy_version_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("privacy_policy_versions.id", ondelete="RESTRICT"),
        nullable=False,
    )
    jurisdiction_code: Mapped[str] = mapped_column(String(64), nullable=False)
    data_category: Mapped[str] = mapped_column(String(100), nullable=False)
    purpose: Mapped[str] = mapped_column(String(100), nullable=False)
    allowed: Mapped[bool] = mapped_column(Boolean, nullable=False)
    legal_basis: Mapped[str] = mapped_column(String(100), nullable=False)
    consent_notice_id: Mapped[UUID | None] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("consent_notices.id", ondelete="RESTRICT"),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class RetentionRule(UUIDPrimaryKeyMixin, PersistenceBase):
    """Category-specific retention applied when a record is created."""

    __tablename__ = "retention_rules"
    __table_args__ = (
        UniqueConstraint(
            "privacy_policy_version_id",
            "jurisdiction_code",
            "data_category",
            "purpose",
            name="uq_retention_rule_context",
        ),
        CheckConstraint("retention_days >= 1 AND retention_days <= 36500", name="days_valid"),
        CheckConstraint("action IN ('delete', 'anonymize')", name="action_allowed"),
        Index("ix_retention_rules_resolution", "privacy_policy_version_id", "jurisdiction_code"),
    )

    privacy_policy_version_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("privacy_policy_versions.id", ondelete="RESTRICT"),
        nullable=False,
    )
    jurisdiction_code: Mapped[str] = mapped_column(String(64), nullable=False)
    data_category: Mapped[str] = mapped_column(String(100), nullable=False)
    purpose: Mapped[str] = mapped_column(String(100), nullable=False)
    retention_days: Mapped[int] = mapped_column(Integer, nullable=False)
    action: Mapped[RetentionAction] = mapped_column(String(16), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class PrivacyRequest(
    UUIDPrimaryKeyMixin,
    TimestampMixin,
    VersionedRecordMixin,
    PersistenceBase,
):
    """Verified data-subject request with an explicit lifecycle and deadline."""

    __tablename__ = "privacy_requests"
    __table_args__ = (
        CheckConstraint("request_type IN ('access', 'export', 'deletion')", name="type_allowed"),
        CheckConstraint(
            "status IN ('received', 'verified', 'processing', 'completed', 'failed', 'cancelled')",
            name="status_allowed",
        ),
        CheckConstraint("char_length(idempotency_key_hash) = 64", name="idempotency_digest_length"),
        CheckConstraint("due_at >= requested_at", name="due_after_request"),
        CheckConstraint("retain_until > requested_at", name="retention_after_request"),
        CheckConstraint("attempts >= 0", name="attempts_nonnegative"),
        CheckConstraint("version > 0", name="version_positive"),
        UniqueConstraint(
            "account_id",
            "idempotency_key_hash",
            name="uq_privacy_request_idempotency",
        ),
        Index("ix_privacy_requests_account_created", "account_id", "created_at"),
        Index("ix_privacy_requests_status_due", "status", "due_at"),
        Index("ix_privacy_requests_retention", "retain_until"),
    )

    account_id: Mapped[UUID | None] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("accounts.id", ondelete="SET NULL"),
        nullable=True,
    )
    request_type: Mapped[PrivacyRequestType] = mapped_column(String(16), nullable=False)
    status: Mapped[PrivacyRequestStatus] = mapped_column(String(16), nullable=False)
    privacy_policy_version_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("privacy_policy_versions.id", ondelete="RESTRICT"),
        nullable=False,
    )
    jurisdiction_code: Mapped[str] = mapped_column(String(64), nullable=False)
    idempotency_key_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    requested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    due_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    processing_started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    retain_until: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    retention_action: Mapped[RetentionAction] = mapped_column(String(16), nullable=False)
    attempts: Mapped[int] = mapped_column(
        BigInteger, default=0, server_default=text("0"), nullable=False
    )
    last_error_code: Mapped[str | None] = mapped_column(String(100), nullable=True)


class Processor(
    UUIDPrimaryKeyMixin,
    TimestampMixin,
    VersionedRecordMixin,
    PersistenceBase,
):
    """Versioned vendor inventory entry without credentials or personal payloads."""

    __tablename__ = "processors"
    __table_args__ = (
        UniqueConstraint("processor_key", "inventory_version", name="uq_processor_key_version"),
        CheckConstraint("status IN ('active', 'suspended', 'retired')", name="status_allowed"),
        CheckConstraint("version > 0", name="version_positive"),
    )

    processor_key: Mapped[str] = mapped_column(String(100), nullable=False)
    inventory_version: Mapped[str] = mapped_column(String(64), nullable=False)
    legal_name: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[ProcessorStatus] = mapped_column(String(16), nullable=False)
    privacy_uri: Mapped[str] = mapped_column(String(2048), nullable=False)
    contract_reference: Mapped[str] = mapped_column(String(255), nullable=False)
    operating_countries: Mapped[list[str]] = mapped_column(JSONB, nullable=False)
    subprocessors: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB, default=list, server_default=text("'[]'::jsonb"), nullable=False
    )


class ProcessorActivity(UUIDPrimaryKeyMixin, PersistenceBase):
    """Approved purpose/category/region use of a processor."""

    __tablename__ = "processor_activities"
    __table_args__ = (
        CheckConstraint("status IN ('active', 'suspended', 'retired')", name="status_allowed"),
        CheckConstraint(
            "NOT cross_border OR btrim(transfer_mechanism) <> ''",
            name="cross_border_requires_mechanism",
        ),
        CheckConstraint(
            "deletion_sla_days >= 1 AND deletion_sla_days <= 365",
            name="deletion_sla_valid",
        ),
        Index("ix_processor_activities_policy", "privacy_policy_version_id", "status"),
    )

    processor_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("processors.id", ondelete="RESTRICT"),
        nullable=False,
    )
    privacy_policy_version_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("privacy_policy_versions.id", ondelete="RESTRICT"),
        nullable=False,
    )
    status: Mapped[ProcessorStatus] = mapped_column(String(16), nullable=False)
    data_category: Mapped[str] = mapped_column(String(100), nullable=False)
    purpose: Mapped[str] = mapped_column(String(100), nullable=False)
    origin_region: Mapped[str] = mapped_column(String(64), nullable=False)
    processing_region: Mapped[str] = mapped_column(String(64), nullable=False)
    storage_region: Mapped[str] = mapped_column(String(64), nullable=False)
    cross_border: Mapped[bool] = mapped_column(Boolean, nullable=False)
    transfer_mechanism: Mapped[str | None] = mapped_column(String(255), nullable=True)
    deletion_mechanism: Mapped[str] = mapped_column(String(100), nullable=False)
    deletion_sla_days: Mapped[int] = mapped_column(Integer, nullable=False)
    approved_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class ProcessorUsage(UUIDPrimaryKeyMixin, PersistenceBase):
    """Minimal per-account locator required to propagate vendor deletion."""

    __tablename__ = "processor_usages"
    __table_args__ = (
        UniqueConstraint(
            "account_id",
            "processor_activity_id",
            "processor_subject_digest",
            name="uq_processor_usage_locator",
        ),
        CheckConstraint(
            "(processor_subject_reference IS NOT NULL AND processor_subject_ciphertext IS NULL "
            "AND processor_subject_nonce IS NULL AND processor_subject_key_id IS NULL) OR "
            "(processor_subject_reference IS NULL AND processor_subject_ciphertext IS NOT NULL "
            "AND processor_subject_nonce IS NOT NULL AND processor_subject_key_id IS NOT NULL)",
            name="locator_representation_complete",
        ),
        CheckConstraint(
            "char_length(processor_subject_digest) = 64",
            name="locator_digest_length",
        ),
        Index("ix_processor_usages_account", "account_id"),
    )

    account_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("accounts.id", ondelete="CASCADE"),
        nullable=False,
    )
    processor_activity_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("processor_activities.id", ondelete="RESTRICT"),
        nullable=False,
    )
    processor_subject_reference: Mapped[str | None] = mapped_column(String(255), nullable=True)
    processor_subject_ciphertext: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    processor_subject_nonce: Mapped[bytes | None] = mapped_column(LargeBinary(12), nullable=True)
    processor_subject_key_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    processor_subject_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    registered_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class ProcessorDeletionTask(UUIDPrimaryKeyMixin, PersistenceBase):
    """Retryable processor erasure work; locator is cleared after acknowledgement."""

    __tablename__ = "processor_deletion_tasks"
    __table_args__ = (
        CheckConstraint(
            "status IN ('pending', 'processing', 'completed', 'retry', 'escalated')",
            name="status_allowed",
        ),
        CheckConstraint("attempts >= 0", name="attempts_nonnegative"),
        CheckConstraint(
            "status NOT IN ('pending', 'processing', 'retry') OR "
            "processor_subject_reference IS NOT NULL OR processor_subject_ciphertext IS NOT NULL",
            name="active_task_requires_locator",
        ),
        CheckConstraint(
            "processor_subject_ciphertext IS NULL OR "
            "(processor_subject_nonce IS NOT NULL AND processor_subject_key_id IS NOT NULL)",
            name="encrypted_locator_complete",
        ),
        UniqueConstraint("privacy_request_id", "processor_usage_id", name="uq_deletion_task_usage"),
        Index("ix_processor_deletion_tasks_available", "status", "available_at"),
    )

    privacy_request_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("privacy_requests.id", ondelete="CASCADE"),
        nullable=False,
    )
    processor_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("processors.id", ondelete="RESTRICT"),
        nullable=False,
    )
    processor_usage_id: Mapped[UUID | None] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("processor_usages.id", ondelete="SET NULL"),
        nullable=True,
    )
    account_id: Mapped[UUID | None] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("accounts.id", ondelete="SET NULL"),
        nullable=True,
    )
    processor_subject_reference: Mapped[str | None] = mapped_column(String(255), nullable=True)
    processor_subject_ciphertext: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    processor_subject_nonce: Mapped[bytes | None] = mapped_column(LargeBinary(12), nullable=True)
    processor_subject_key_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    status: Mapped[DeletionTaskStatus] = mapped_column(String(16), nullable=False)
    attempts: Mapped[int] = mapped_column(
        BigInteger, default=0, server_default=text("0"), nullable=False
    )
    available_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    locked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    locked_by: Mapped[str | None] = mapped_column(String(128), nullable=True)
    last_error_code: Mapped[str | None] = mapped_column(String(100), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    retain_until: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    retention_action: Mapped[RetentionAction] = mapped_column(String(16), nullable=False)


class BackupDeletionMarker(UUIDPrimaryKeyMixin, PersistenceBase):
    """Portable erasure marker replayed before a restored database may serve traffic."""

    __tablename__ = "backup_deletion_markers"
    __table_args__ = (
        UniqueConstraint("account_id", "cutoff_at", name="uq_backup_marker_account_cutoff"),
        CheckConstraint("char_length(subject_fingerprint) = 64", name="subject_digest_length"),
        CheckConstraint("backups_expire_at > cutoff_at", name="backup_expiry_after_cutoff"),
        Index("ix_backup_deletion_markers_expiry", "backups_expire_at"),
    )

    account_id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), nullable=False)
    subject_key_id: Mapped[str] = mapped_column(
        String(64),
        default="legacy-v1",
        server_default=text("'legacy-v1'"),
        nullable=False,
    )
    subject_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    privacy_request_id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), nullable=False)
    privacy_policy_version_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True), nullable=False
    )
    cutoff_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    backups_expire_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
