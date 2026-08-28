"""Encrypted immutable source-text lineage for exact candidate document versions."""

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

from ai_interviewer.persistence.base import (
    PersistenceBase,
    TimestampMixin,
    UUIDPrimaryKeyMixin,
    VersionedRecordMixin,
)

CandidateSourceTextOrigin = Literal["parser_extraction", "user_correction"]

MAX_SOURCE_TEXT_CHARACTERS = 500_000
MAX_SOURCE_TEXT_UTF8_BYTES = 2_000_000


class CandidateSourceText(
    UUIDPrimaryKeyMixin,
    TimestampMixin,
    VersionedRecordMixin,
    PersistenceBase,
):
    """Stable owner-bound text identity for one immutable document version."""

    __tablename__ = "candidate_source_texts"
    __table_args__ = (
        CheckConstraint("latest_version_number > 0", name="latest_version_number_positive"),
        CheckConstraint("version > 0", name="version_positive"),
        UniqueConstraint(
            "document_version_id",
            name="uq_candidate_source_texts_document_version",
        ),
        UniqueConstraint("id", "owner_id", name="uq_candidate_source_texts_id_owner"),
        ForeignKeyConstraint(
            ["document_version_id", "owner_id"],
            ["candidate_document_versions.id", "candidate_document_versions.owner_id"],
            name="fk_candidate_source_texts_document_version_owner",
            ondelete="CASCADE",
        ),
        Index(
            "ix_candidate_source_texts_owner_document_version",
            "owner_id",
            "document_version_id",
        ),
    )

    owner_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("accounts.id", ondelete="CASCADE"),
        nullable=False,
    )
    document_version_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        nullable=False,
    )
    latest_version_number: Mapped[int] = mapped_column(Integer, nullable=False)


class CandidateSourceTextVersion(UUIDPrimaryKeyMixin, PersistenceBase):
    """Immutable encrypted parser output or later owner correction."""

    __tablename__ = "candidate_source_text_versions"
    __table_args__ = (
        CheckConstraint("version_number > 0", name="version_number_positive"),
        CheckConstraint(
            "origin IN ('parser_extraction', 'user_correction')",
            name="origin_allowed",
        ),
        CheckConstraint(
            "(origin = 'parser_extraction' AND version_number = 1 "
            "AND previous_version_id IS NULL AND parser_release_policy_id IS NOT NULL "
            "AND parser_adapter IS NOT NULL AND parser_version IS NOT NULL "
            "AND isolation_profile IS NOT NULL) OR "
            "(origin = 'user_correction' AND version_number > 1 "
            "AND previous_version_id IS NOT NULL AND parser_release_policy_id IS NULL "
            "AND parser_adapter IS NULL AND parser_version IS NULL "
            "AND isolation_profile IS NULL)",
            name="origin_provenance_consistent",
        ),
        CheckConstraint(
            "parser_adapter IS NULL OR btrim(parser_adapter) <> ''",
            name="parser_adapter_nonempty",
        ),
        CheckConstraint(
            "parser_version IS NULL OR btrim(parser_version) <> ''",
            name="parser_version_nonempty",
        ),
        CheckConstraint(
            "isolation_profile IS NULL OR btrim(isolation_profile) <> ''",
            name="isolation_profile_nonempty",
        ),
        CheckConstraint(
            "character_count BETWEEN 1 AND 500000",
            name="character_count_bounded",
        ),
        CheckConstraint(
            "utf8_byte_count BETWEEN 1 AND 2000000",
            name="utf8_byte_count_bounded",
        ),
        CheckConstraint(
            "line_count BETWEEN 1 AND character_count + 1",
            name="line_count_bounded",
        ),
        CheckConstraint(
            "content_digest ~ '^[0-9a-f]{64}$'",
            name="content_digest_format",
        ),
        CheckConstraint(
            "btrim(content_digest_key_id) <> ''",
            name="digest_key_nonempty",
        ),
        CheckConstraint(
            "btrim(content_encryption_key_id) <> ''",
            name="encryption_key_nonempty",
        ),
        CheckConstraint(
            "octet_length(content_nonce) = 12",
            name="content_nonce_length",
        ),
        CheckConstraint(
            "octet_length(content_ciphertext) BETWEEN 17 AND 2000016",
            name="content_ciphertext_bounded",
        ),
        UniqueConstraint(
            "source_text_id",
            "version_number",
            name="uq_candidate_source_text_versions_source_number",
        ),
        UniqueConstraint(
            "id",
            "source_text_id",
            name="uq_candidate_source_text_versions_id_source",
        ),
        ForeignKeyConstraint(
            ["source_text_id", "owner_id"],
            ["candidate_source_texts.id", "candidate_source_texts.owner_id"],
            name="fk_candidate_source_text_versions_source_owner",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["previous_version_id", "source_text_id"],
            ["candidate_source_text_versions.id", "candidate_source_text_versions.source_text_id"],
            name="fk_candidate_source_text_versions_previous_source",
            ondelete="CASCADE",
        ),
        Index(
            "ix_candidate_source_text_versions_source_created",
            "source_text_id",
            "created_at",
        ),
    )

    owner_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("accounts.id", ondelete="CASCADE"),
        nullable=False,
    )
    source_text_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        nullable=False,
    )
    version_number: Mapped[int] = mapped_column(Integer, nullable=False)
    origin: Mapped[CandidateSourceTextOrigin] = mapped_column(String(24), nullable=False)
    previous_version_id: Mapped[UUID | None] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        nullable=True,
    )
    parser_release_policy_id: Mapped[UUID | None] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey(
            "parser_release_policies.id",
            name="fk_candidate_source_text_versions_parser_policy",
            ondelete="RESTRICT",
        ),
        nullable=True,
    )
    parser_adapter: Mapped[str | None] = mapped_column(String(100), nullable=True)
    parser_version: Mapped[str | None] = mapped_column(String(64), nullable=True)
    isolation_profile: Mapped[str | None] = mapped_column(String(100), nullable=True)
    character_count: Mapped[int] = mapped_column(Integer, nullable=False)
    utf8_byte_count: Mapped[int] = mapped_column(Integer, nullable=False)
    line_count: Mapped[int] = mapped_column(Integer, nullable=False)
    content_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    content_digest_key_id: Mapped[str] = mapped_column(String(64), nullable=False)
    content_ciphertext: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    content_nonce: Mapped[bytes] = mapped_column(LargeBinary(12), nullable=False)
    content_encryption_key_id: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
