"""Durable authenticated upload/paste intake state for Phase 1A-C."""

from datetime import datetime
from typing import Literal
from uuid import UUID

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import UUID as PostgreSQLUUID
from sqlalchemy.orm import Mapped, mapped_column

from ai_interviewer.candidate_inputs.document_models import (
    CandidateDocumentSource,
    CandidateDocumentType,
)
from ai_interviewer.persistence.base import (
    PersistenceBase,
    TimestampMixin,
    UUIDPrimaryKeyMixin,
    VersionedRecordMixin,
)

CandidateDocumentIntakeStatus = Literal[
    "processing",
    "scan_failed",
    "rejected",
    "completed",
]


class CandidateDocumentIntake(
    UUIDPrimaryKeyMixin,
    TimestampMixin,
    VersionedRecordMixin,
    PersistenceBase,
):
    """Idempotent, recoverable coordination state; never stores document bytes."""

    __tablename__ = "candidate_document_intakes"
    __table_args__ = (
        CheckConstraint(
            "document_type IN ('cv', 'job_description')",
            name="document_type_allowed",
        ),
        CheckConstraint("source_kind IN ('upload', 'paste')", name="source_kind_allowed"),
        CheckConstraint(
            "status IN ('processing', 'scan_failed', 'rejected', 'completed')",
            name="status_allowed",
        ),
        CheckConstraint("btrim(declared_media_type) <> ''", name="media_type_nonempty"),
        CheckConstraint("content_length > 0", name="content_length_positive"),
        CheckConstraint(
            "idempotency_key_hash ~ '^[0-9a-f]{64}$'",
            name="idempotency_digest_format",
        ),
        CheckConstraint(
            "request_digest ~ '^[0-9a-f]{64}$'",
            name="request_digest_format",
        ),
        CheckConstraint(
            "(source_kind = 'paste' AND declared_media_type = 'text/plain') OR "
            "source_kind = 'upload'",
            name="paste_media_type_consistent",
        ),
        CheckConstraint(
            "file_asset_id IS NULL OR file_asset_id = reserved_file_asset_id",
            name="file_asset_reservation_consistent",
        ),
        CheckConstraint("attempts >= 0", name="attempts_nonnegative"),
        CheckConstraint(
            "(status = 'processing' AND processing_lease_until IS NOT NULL "
            "AND processing_token IS NOT NULL) OR "
            "(status <> 'processing' AND processing_lease_until IS NULL "
            "AND processing_token IS NULL)",
            name="processing_lease_consistent",
        ),
        CheckConstraint(
            "(status IN ('scan_failed', 'rejected') AND last_error_code IS NOT NULL "
            "AND btrim(last_error_code) <> '') OR "
            "(status NOT IN ('scan_failed', 'rejected') AND last_error_code IS NULL)",
            name="error_state_consistent",
        ),
        CheckConstraint(
            "(status = 'completed' AND completed_at IS NOT NULL) OR "
            "(status <> 'completed' AND completed_at IS NULL)",
            name="completion_state_consistent",
        ),
        CheckConstraint("retain_until > created_at", name="retention_after_creation"),
        CheckConstraint("retention_action = 'delete'", name="retention_action_delete_only"),
        CheckConstraint("version > 0", name="version_positive"),
        UniqueConstraint(
            "owner_id",
            "idempotency_key_hash",
            name="uq_candidate_document_intakes_owner_idempotency",
        ),
        UniqueConstraint(
            "reserved_file_asset_id",
            name="uq_candidate_document_intakes_reserved_asset",
        ),
        UniqueConstraint("file_asset_id", name="uq_candidate_document_intakes_file_asset"),
        UniqueConstraint(
            "document_version_id",
            name="uq_candidate_document_intakes_document_version",
        ),
        ForeignKeyConstraint(
            ["preparation_id", "owner_id"],
            ["candidate_preparations.id", "candidate_preparations.owner_id"],
            name="fk_candidate_document_intakes_preparation_owner",
            ondelete="CASCADE",
        ),
        Index(
            "ix_candidate_document_intakes_owner_preparation",
            "owner_id",
            "preparation_id",
            "created_at",
        ),
        Index(
            "ix_candidate_document_intakes_status_lease",
            "status",
            "processing_lease_until",
        ),
        Index("ix_candidate_document_intakes_retention", "retain_until"),
    )

    owner_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("accounts.id", ondelete="CASCADE"),
        nullable=False,
    )
    preparation_id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), nullable=False)
    document_type: Mapped[CandidateDocumentType] = mapped_column(String(24), nullable=False)
    source_kind: Mapped[CandidateDocumentSource] = mapped_column(String(16), nullable=False)
    status: Mapped[CandidateDocumentIntakeStatus] = mapped_column(String(24), nullable=False)
    idempotency_key_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    request_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    declared_media_type: Mapped[str] = mapped_column(String(255), nullable=False)
    content_length: Mapped[int] = mapped_column(BigInteger, nullable=False)
    reserved_file_asset_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True), nullable=False
    )
    file_asset_id: Mapped[UUID | None] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("file_assets.id", ondelete="SET NULL"),
        nullable=True,
    )
    document_id: Mapped[UUID | None] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("candidate_documents.id", ondelete="SET NULL"),
        nullable=True,
    )
    document_version_id: Mapped[UUID | None] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("candidate_document_versions.id", ondelete="SET NULL"),
        nullable=True,
    )
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    processing_lease_until: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    processing_token: Mapped[UUID | None] = mapped_column(
        PostgreSQLUUID(as_uuid=True), nullable=True
    )
    last_error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    privacy_policy_version_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("privacy_policy_versions.id", ondelete="RESTRICT"),
        nullable=False,
    )
    jurisdiction_code: Mapped[str] = mapped_column(String(64), nullable=False)
    legal_basis: Mapped[str] = mapped_column(String(64), nullable=False)
    retention_rule_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("retention_rules.id", ondelete="RESTRICT"),
        nullable=False,
    )
    retain_until: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    retention_action: Mapped[str] = mapped_column(String(16), nullable=False)
