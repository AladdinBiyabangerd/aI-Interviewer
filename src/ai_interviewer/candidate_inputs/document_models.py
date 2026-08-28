"""Immutable candidate CV/JD version lineage introduced in Phase 1A-B."""

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
    func,
)
from sqlalchemy.dialects.postgresql import UUID as PostgreSQLUUID
from sqlalchemy.orm import Mapped, mapped_column

from ai_interviewer.persistence.base import (
    PersistenceBase,
    TimestampMixin,
    UUIDPrimaryKeyMixin,
    VersionedRecordMixin,
)

CandidateDocumentType = Literal["cv", "job_description"]
CandidateDocumentSource = Literal["upload", "paste"]

DOCUMENT_TYPES = frozenset({"cv", "job_description"})
DOCUMENT_SOURCES = frozenset({"upload", "paste"})


class CandidateDocument(
    UUIDPrimaryKeyMixin,
    TimestampMixin,
    VersionedRecordMixin,
    PersistenceBase,
):
    """Stable logical CV or JD identity within one preparation."""

    __tablename__ = "candidate_documents"
    __table_args__ = (
        CheckConstraint(
            "document_type IN ('cv', 'job_description')",
            name="document_type_allowed",
        ),
        CheckConstraint("latest_version_number > 0", name="latest_version_number_positive"),
        CheckConstraint("version > 0", name="version_positive"),
        UniqueConstraint(
            "preparation_id",
            "document_type",
            name="uq_candidate_documents_preparation_type",
        ),
        UniqueConstraint(
            "id",
            "owner_id",
            name="uq_candidate_documents_id_owner",
        ),
        ForeignKeyConstraint(
            ["preparation_id", "owner_id"],
            ["candidate_preparations.id", "candidate_preparations.owner_id"],
            name="fk_candidate_documents_preparation_owner",
            ondelete="CASCADE",
        ),
        Index(
            "ix_candidate_documents_owner_preparation",
            "owner_id",
            "preparation_id",
        ),
    )

    owner_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("accounts.id", ondelete="CASCADE"),
        nullable=False,
    )
    preparation_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        nullable=False,
    )
    document_type: Mapped[CandidateDocumentType] = mapped_column(String(24), nullable=False)
    latest_version_number: Mapped[int] = mapped_column(Integer, nullable=False)


class CandidateDocumentVersion(UUIDPrimaryKeyMixin, PersistenceBase):
    """Immutable metadata snapshot for one released file-asset version."""

    __tablename__ = "candidate_document_versions"
    __table_args__ = (
        CheckConstraint("version_number > 0", name="version_number_positive"),
        CheckConstraint(
            "source_kind IN ('upload', 'paste')",
            name="source_kind_allowed",
        ),
        CheckConstraint("btrim(media_type) <> ''", name="media_type_nonempty"),
        CheckConstraint("content_length > 0", name="content_length_positive"),
        CheckConstraint(
            "content_sha256 ~ '^[0-9a-f]{64}$'",
            name="content_digest_format",
        ),
        CheckConstraint("retain_until > created_at", name="retention_after_creation"),
        CheckConstraint("retention_action = 'delete'", name="retention_action_delete_only"),
        UniqueConstraint(
            "document_id",
            "version_number",
            name="uq_candidate_document_versions_document_number",
        ),
        UniqueConstraint(
            "file_asset_id",
            name="uq_candidate_document_versions_file_asset",
        ),
        UniqueConstraint(
            "id",
            "owner_id",
            name="uq_candidate_document_versions_id_owner",
        ),
        ForeignKeyConstraint(
            ["document_id", "owner_id"],
            ["candidate_documents.id", "candidate_documents.owner_id"],
            name="fk_candidate_document_versions_document_owner",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["file_asset_id", "owner_id"],
            ["file_assets.id", "file_assets.account_id"],
            name="fk_candidate_document_versions_file_asset_owner",
            ondelete="RESTRICT",
        ),
        Index(
            "ix_candidate_document_versions_document_created",
            "document_id",
            "created_at",
        ),
    )

    owner_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("accounts.id", ondelete="CASCADE"),
        nullable=False,
    )
    document_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        nullable=False,
    )
    file_asset_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        nullable=False,
    )
    version_number: Mapped[int] = mapped_column(Integer, nullable=False)
    source_kind: Mapped[CandidateDocumentSource] = mapped_column(String(16), nullable=False)
    media_type: Mapped[str] = mapped_column(String(255), nullable=False)
    content_length: Mapped[int] = mapped_column(BigInteger, nullable=False)
    content_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    parser_release_policy_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("parser_release_policies.id", ondelete="RESTRICT"),
        nullable=False,
    )
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
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
