"""Relational records for encrypted file quarantine and deletion orchestration."""

from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import UUID as PostgreSQLUUID
from sqlalchemy.orm import Mapped, mapped_column

from ai_interviewer.persistence.base import (
    PersistenceBase,
    TimestampMixin,
    UUIDPrimaryKeyMixin,
    VersionedRecordMixin,
)
from ai_interviewer.privacy.models import RetentionAction

FileAssetStatus = Literal[
    "upload_pending",
    "quarantined",
    "scan_failed",
    "clean",
    "released",
    "deletion_pending",
]
ScanStatus = Literal["clean", "infected", "error"]
FileDeletionStatus = Literal["pending", "processing", "retry", "escalated", "completed"]


class ParserReleasePolicy(UUIDPrimaryKeyMixin, TimestampMixin, PersistenceBase):
    """Reviewed parser boundary; clean content cannot cross without an active version."""

    __tablename__ = "parser_release_policies"
    __table_args__ = (
        CheckConstraint("status IN ('active', 'suspended', 'retired')", name="status_allowed"),
        CheckConstraint("maximum_bytes >= 1024", name="maximum_bytes_positive"),
        CheckConstraint("btrim(parser_adapter) <> ''", name="parser_adapter_nonempty"),
        CheckConstraint("btrim(parser_version) <> ''", name="parser_version_nonempty"),
        CheckConstraint("btrim(isolation_profile) <> ''", name="isolation_profile_nonempty"),
        UniqueConstraint("policy_key", "policy_version", name="uq_parser_policy_key_version"),
        Index(
            "ix_parser_release_policies_resolution",
            "privacy_policy_version_id",
            "data_category",
            "purpose",
            "media_type",
            "status",
        ),
    )

    policy_key: Mapped[str] = mapped_column(String(100), nullable=False)
    policy_version: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    privacy_policy_version_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("privacy_policy_versions.id", ondelete="RESTRICT"),
        nullable=False,
    )
    data_category: Mapped[str] = mapped_column(String(100), nullable=False)
    purpose: Mapped[str] = mapped_column(String(100), nullable=False)
    media_type: Mapped[str] = mapped_column(String(255), nullable=False)
    maximum_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    malware_scan_required: Mapped[bool] = mapped_column(Boolean, nullable=False)
    parser_adapter: Mapped[str] = mapped_column(String(100), nullable=False)
    parser_version: Mapped[str] = mapped_column(String(64), nullable=False)
    isolation_profile: Mapped[str] = mapped_column(String(100), nullable=False)
    approved_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    retired_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class FileAsset(
    UUIDPrimaryKeyMixin,
    TimestampMixin,
    VersionedRecordMixin,
    PersistenceBase,
):
    """Minimal owner-bound metadata for one encrypted object and its release state."""

    __tablename__ = "file_assets"
    __table_args__ = (
        CheckConstraint(
            "status IN ('upload_pending', 'quarantined', 'scan_failed', 'clean', "
            "'released', 'deletion_pending')",
            name="status_allowed",
        ),
        CheckConstraint("content_length >= 1", name="content_length_positive"),
        CheckConstraint("char_length(content_sha256) = 64", name="content_digest_length"),
        CheckConstraint("retain_until > created_at", name="retention_after_creation"),
        CheckConstraint(
            "retention_action IN ('delete', 'anonymize')", name="retention_action_allowed"
        ),
        CheckConstraint(
            "status IN ('upload_pending', 'deletion_pending') OR quarantine_version_id IS NOT NULL",
            name="uploaded_state_requires_version",
        ),
        CheckConstraint(
            "status <> 'released' OR (released_object_key IS NOT NULL AND "
            "released_version_id IS NOT NULL AND parser_release_policy_id IS NOT NULL)",
            name="released_state_complete",
        ),
        UniqueConstraint("bucket", "quarantine_object_key", name="uq_file_asset_quarantine_key"),
        UniqueConstraint("id", "account_id", name="uq_file_assets_id_account"),
        Index("ix_file_assets_owner_created", "account_id", "created_at"),
        Index("ix_file_assets_status_updated", "status", "updated_at"),
        Index("ix_file_assets_retention", "retain_until"),
    )

    account_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("accounts.id", ondelete="RESTRICT"),
        nullable=False,
    )
    privacy_policy_version_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("privacy_policy_versions.id", ondelete="RESTRICT"),
        nullable=False,
    )
    jurisdiction_code: Mapped[str] = mapped_column(String(64), nullable=False)
    data_category: Mapped[str] = mapped_column(String(100), nullable=False)
    purpose: Mapped[str] = mapped_column(String(100), nullable=False)
    status: Mapped[FileAssetStatus] = mapped_column(String(24), nullable=False)
    bucket: Mapped[str] = mapped_column(String(255), nullable=False)
    quarantine_object_key: Mapped[str] = mapped_column(String(512), nullable=False)
    quarantine_version_id: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    released_object_key: Mapped[str | None] = mapped_column(String(512), nullable=True)
    released_version_id: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    kms_key_id: Mapped[str] = mapped_column(String(255), nullable=False)
    media_type: Mapped[str] = mapped_column(String(255), nullable=False)
    content_length: Mapped[int] = mapped_column(BigInteger, nullable=False)
    content_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    parser_release_policy_id: Mapped[UUID | None] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("parser_release_policies.id", ondelete="RESTRICT"),
        nullable=True,
    )
    released_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    retain_until: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    retention_action: Mapped[RetentionAction] = mapped_column(String(16), nullable=False)


class FileScanAttempt(UUIDPrimaryKeyMixin, PersistenceBase):
    """Minimal scan evidence; malware names are retained only as a digest."""

    __tablename__ = "file_scan_attempts"
    __table_args__ = (
        CheckConstraint("attempt_number >= 1", name="attempt_number_positive"),
        CheckConstraint("status IN ('clean', 'infected', 'error')", name="status_allowed"),
        CheckConstraint(
            "malware_signature_sha256 IS NULL OR char_length(malware_signature_sha256) = 64",
            name="malware_digest_length",
        ),
        CheckConstraint(
            "(status = 'error' AND error_code IS NOT NULL) OR "
            "(status <> 'error' AND error_code IS NULL)",
            name="error_state_consistent",
        ),
        UniqueConstraint("file_asset_id", "attempt_number", name="uq_file_scan_attempt_number"),
        Index("ix_file_scan_attempts_asset_scanned", "file_asset_id", "scanned_at"),
    )

    file_asset_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("file_assets.id", ondelete="CASCADE"),
        nullable=False,
    )
    attempt_number: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[ScanStatus] = mapped_column(String(16), nullable=False)
    scanner_engine_version: Mapped[str | None] = mapped_column(String(64), nullable=True)
    scanner_signature_version: Mapped[str | None] = mapped_column(String(64), nullable=True)
    scanner_signature_date: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    malware_signature_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(100), nullable=True)
    scanned_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )


class FileDeletionTask(UUIDPrimaryKeyMixin, PersistenceBase):
    """Durable, idempotent removal of every object version for an asset."""

    __tablename__ = "file_deletion_tasks"
    __table_args__ = (
        CheckConstraint(
            "task_kind IN ('quarantine_cleanup', 'asset_deletion')",
            name="task_kind_allowed",
        ),
        CheckConstraint(
            "status IN ('pending', 'processing', 'retry', 'escalated', 'completed')",
            name="status_allowed",
        ),
        CheckConstraint("attempts >= 0", name="attempts_nonnegative"),
        CheckConstraint(
            "status = 'completed' OR quarantine_object_key IS NOT NULL OR "
            "released_object_key IS NOT NULL",
            name="active_task_requires_object_key",
        ),
        CheckConstraint("retain_until > created_at", name="retention_after_creation"),
        CheckConstraint(
            "retention_action IN ('delete', 'anonymize')", name="retention_action_allowed"
        ),
        UniqueConstraint(
            "file_asset_id",
            "task_kind",
            name="uq_file_deletion_task_asset_kind",
        ),
        Index("ix_file_deletion_tasks_available", "status", "available_at"),
        Index("ix_file_deletion_tasks_request", "privacy_request_id", "status"),
        Index("ix_file_deletion_tasks_retention", "retain_until"),
    )

    file_asset_id: Mapped[UUID | None] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("file_assets.id", ondelete="SET NULL"),
        nullable=True,
    )
    privacy_request_id: Mapped[UUID | None] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        nullable=True,
    )
    account_id: Mapped[UUID | None] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("accounts.id", ondelete="SET NULL"),
        nullable=True,
    )
    task_kind: Mapped[str] = mapped_column(String(24), nullable=False)
    bucket: Mapped[str] = mapped_column(String(255), nullable=False)
    quarantine_object_key: Mapped[str | None] = mapped_column(String(512), nullable=True)
    released_object_key: Mapped[str | None] = mapped_column(String(512), nullable=True)
    status: Mapped[FileDeletionStatus] = mapped_column(String(16), nullable=False)
    attempts: Mapped[int] = mapped_column(
        BigInteger,
        default=0,
        server_default=text("0"),
        nullable=False,
    )
    available_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    locked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    locked_by: Mapped[str | None] = mapped_column(String(128), nullable=True)
    last_error_code: Mapped[str | None] = mapped_column(String(100), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    retain_until: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    retention_action: Mapped[RetentionAction] = mapped_column(String(16), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
