"""Durable records used by the Vercel text-interview runtime."""

from datetime import datetime
from typing import Any
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
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PostgreSQLUUID
from sqlalchemy.orm import Mapped, mapped_column

from ai_interviewer.persistence.base import PersistenceBase, TimestampMixin, UUIDPrimaryKeyMixin


class InterviewCvUploadRecord(UUIDPrimaryKeyMixin, TimestampMixin, PersistenceBase):
    """Owner-bound metadata for a private, short-retention CV blob."""

    __tablename__ = "interview_cv_uploads"
    __table_args__ = (
        CheckConstraint("owner_hash ~ '^[0-9a-f]{64}$'", name="owner_hash_format"),
        CheckConstraint(
            "content_type IN ('application/pdf', "
            "'application/vnd.openxmlformats-officedocument.wordprocessingml.document')",
            name="content_type_allowed",
        ),
        CheckConstraint(
            "size_bytes IS NULL OR size_bytes BETWEEN 1 AND 10485760",
            name="size_bounded",
        ),
        CheckConstraint(
            "status IN ('pending', 'ready', 'consumed')",
            name="status_allowed",
        ),
        UniqueConstraint("pathname", name="uq_interview_cv_upload_pathname"),
        Index("ix_interview_cv_uploads_owner_status", "owner_hash", "status", "expires_at"),
    )

    owner_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    pathname: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    blob_url: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    file_name: Mapped[str] = mapped_column(String(240), nullable=False)
    content_type: Mapped[str] = mapped_column(String(128), nullable=False)
    size_bytes: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    status: Mapped[str] = mapped_column(
        String(16), default="pending", server_default=text("'pending'"), nullable=False
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class InterviewPreparationRecord(UUIDPrimaryKeyMixin, TimestampMixin, PersistenceBase):
    """Persistent asynchronous research job and normalized question result."""

    __tablename__ = "interview_preparations"
    __table_args__ = (
        CheckConstraint(
            "owner_hash ~ '^[0-9a-f]{64}$' AND requester_hash ~ '^[0-9a-f]{64}$'",
            name="hashes_format",
        ),
        CheckConstraint(
            "status IN ('queued', 'in_progress', 'completed', 'failed')",
            name="status_allowed",
        ),
        Index("ix_interview_preparations_owner_created", "owner_hash", "created_at"),
        Index("ix_interview_preparations_request_rate", "requester_hash", "created_at"),
        Index(
            "ix_interview_preparations_provider_responses",
            "research_response_id",
            "cv_response_id",
        ),
    )

    owner_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    requester_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(
        String(16), default="queued", server_default=text("'queued'"), nullable=False
    )
    input: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    analysis: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    research_response_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    cv_response_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    provider_file_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    cv_upload_id: Mapped[UUID | None] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("interview_cv_uploads.id", ondelete="SET NULL"),
        nullable=True,
    )
    error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class InterviewPracticeSessionRecord(UUIDPrimaryKeyMixin, TimestampMixin, PersistenceBase):
    """Owner-scoped practice state and generated final report."""

    __tablename__ = "interview_practice_sessions"
    __table_args__ = (
        CheckConstraint("owner_hash ~ '^[0-9a-f]{64}$'", name="owner_hash_format"),
        CheckConstraint("mode IN ('Real Interview', 'Practice')", name="mode_allowed"),
        CheckConstraint(
            "focus IN ('Full Interview', 'Technical', 'HR / Behavioral', 'CV Deep Dive')",
            name="focus_allowed",
        ),
        CheckConstraint("duration_minutes IN (15, 30, 45)", name="duration_allowed"),
        CheckConstraint(
            "jsonb_array_length(question_ids) BETWEEN 1 AND 20",
            name="questions_bounded",
        ),
        CheckConstraint("current_index BETWEEN 0 AND 20", name="current_index_bounded"),
        CheckConstraint("status IN ('active', 'completed')", name="status_allowed"),
        Index("ix_interview_practice_sessions_owner_created", "owner_hash", "created_at"),
    )

    preparation_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("interview_preparations.id", ondelete="CASCADE"),
        nullable=False,
    )
    owner_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    mode: Mapped[str] = mapped_column(String(24), nullable=False)
    focus: Mapped[str] = mapped_column(String(32), nullable=False)
    duration_minutes: Mapped[int] = mapped_column(Integer, nullable=False)
    question_ids: Mapped[list[str]] = mapped_column(JSONB, nullable=False)
    current_index: Mapped[int] = mapped_column(
        Integer, default=0, server_default=text("0"), nullable=False
    )
    awaiting_follow_up: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default=text("false"), nullable=False
    )
    pending_follow_up: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(
        String(16), default="active", server_default=text("'active'"), nullable=False
    )
    report: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class InterviewPracticeTurnRecord(UUIDPrimaryKeyMixin, TimestampMixin, PersistenceBase):
    """One immutable candidate answer and its answer-specific feedback."""

    __tablename__ = "interview_practice_turns"
    __table_args__ = (
        CheckConstraint("sequence BETWEEN 0 AND 40", name="sequence_bounded"),
        CheckConstraint("kind IN ('question', 'follow_up')", name="kind_allowed"),
        CheckConstraint("char_length(answer) BETWEEN 30 AND 2500", name="answer_bounded"),
        UniqueConstraint(
            "session_id",
            "sequence",
            name="uq_interview_practice_turn_sequence",
        ),
    )

    session_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("interview_practice_sessions.id", ondelete="CASCADE"),
        nullable=False,
    )
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    question_id: Mapped[str] = mapped_column(String(128), nullable=False)
    kind: Mapped[str] = mapped_column(String(16), nullable=False)
    prompt: Mapped[str] = mapped_column(Text, nullable=False)
    answer: Mapped[str] = mapped_column(Text, nullable=False)
    feedback: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
