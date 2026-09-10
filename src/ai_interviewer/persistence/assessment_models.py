"""Schema parity for the server-graded Java Q&A runtime."""

from datetime import datetime
from typing import Any
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from ai_interviewer.persistence.base import PersistenceBase


class JavaQuestionRecord(PersistenceBase):
    """Immutable question content with independently managed publication status."""

    __tablename__ = "java_question_bank"
    __table_args__ = (
        CheckConstraint("version > 0", name="ck_java_question_version"),
        CheckConstraint(
            "status IN ('draft', 'published', 'retired')", name="ck_java_question_status"
        ),
    )
    id: Mapped[str] = mapped_column(String(100), primary_key=True)
    version: Mapped[int] = mapped_column(Integer, primary_key=True)
    status: Mapped[str] = mapped_column(String(16))
    content_hash: Mapped[str] = mapped_column(String(64))
    question: Mapped[dict[str, Any]] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class JavaAssessmentRecord(PersistenceBase):
    """Owner-bound assessment with question snapshots and deterministic results."""

    __tablename__ = "java_assessment_sessions"
    __table_args__ = (
        Index("ix_java_assessment_owner", "owner_hash", "created_at"),
        Index("ix_java_assessment_expiry", "expires_at"),
    )
    id: Mapped[UUID] = mapped_column(primary_key=True)
    owner_hash: Mapped[str] = mapped_column(String(64))
    state: Mapped[dict[str, Any]] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class JavaQuestionFeedbackRecord(PersistenceBase):
    """One current rating and issue flag per browser owner and question revision."""

    __tablename__ = "java_question_feedback"
    __table_args__ = (
        CheckConstraint("rating IS NULL OR rating BETWEEN 1 AND 5", name="ck_java_feedback_rating"),
        CheckConstraint(
            "flag IS NULL OR flag IN ('incorrect', 'unclear', 'too_difficult', 'source')",
            name="ck_java_feedback_flag",
        ),
        CheckConstraint("review_status IN ('pending', 'resolved')", name="ck_java_feedback_review"),
        ForeignKeyConstraint(
            ["question_id", "question_version"],
            ["java_question_bank.id", "java_question_bank.version"],
        ),
    )
    owner_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    question_id: Mapped[str] = mapped_column(String(100), primary_key=True)
    question_version: Mapped[int] = mapped_column(Integer, primary_key=True)
    rating: Mapped[int | None] = mapped_column(Integer, nullable=True)
    flag: Mapped[str | None] = mapped_column(String(32), nullable=True)
    review_status: Mapped[str] = mapped_column(String(16), server_default="pending")
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class JavaQuestionImportBatchRecord(PersistenceBase):
    """One immutable extraction report for an operator-supplied source PDF."""

    __tablename__ = "java_question_import_batches"
    __table_args__ = (
        CheckConstraint("source_sha256 ~ '^[0-9a-f]{64}$'", name="ck_java_import_source_digest"),
        CheckConstraint(
            "rights_status IN ('unverified', 'cleared', 'rejected')",
            name="ck_java_import_rights_status",
        ),
        CheckConstraint(
            "status IN ('ready', 'review_required', 'failed')", name="ck_java_import_status"
        ),
        CheckConstraint(
            "page_count > 0 AND question_count >= 0 AND answer_count >= 0 "
            "AND answer_count <= question_count",
            name="ck_java_import_counts",
        ),
        sa.UniqueConstraint(
            "source_sha256", "parser_release", name="uq_java_question_import_source_release"
        ),
    )
    id: Mapped[UUID] = mapped_column(primary_key=True, server_default=sa.text("gen_random_uuid()"))
    source_sha256: Mapped[str] = mapped_column(String(64))
    file_name: Mapped[str] = mapped_column(String(255))
    source_title: Mapped[str] = mapped_column(String(500))
    authors: Mapped[str | None] = mapped_column(String(500), nullable=True)
    publisher: Mapped[str | None] = mapped_column(String(200), nullable=True)
    publication_year: Mapped[int | None] = mapped_column(Integer, nullable=True)
    reference_url: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    parser_release: Mapped[str] = mapped_column(String(64))
    rights_status: Mapped[str] = mapped_column(String(24))
    status: Mapped[str] = mapped_column(String(24))
    page_count: Mapped[int] = mapped_column(Integer)
    question_count: Mapped[int] = mapped_column(Integer)
    answer_count: Mapped[int] = mapped_column(Integer)
    report: Mapped[dict[str, Any]] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class JavaQuestionImportCandidateRecord(PersistenceBase):
    """Private parsed source material pending correctness and rights review."""

    __tablename__ = "java_question_import_candidates"
    __table_args__ = (
        CheckConstraint("question_number > 0", name="question_number"),
        CheckConstraint(
            "page_start > 0 AND page_end >= page_start", name="ck_java_import_page_range"
        ),
        CheckConstraint("normalized_hash ~ '^[0-9a-f]{64}$'", name="normalized_digest"),
        CheckConstraint(
            "parse_status IN ('complete', 'needs_answer', 'needs_review')",
            name="ck_java_import_parse_status",
        ),
        ForeignKeyConstraint(
            ["batch_id"],
            ["java_question_import_batches.id"],
            name="fk_java_question_import_candidates_batch_id_java_question_import_batches",
            ondelete="CASCADE",
        ),
        Index("ix_java_question_import_candidates_hash", "normalized_hash"),
        Index("ix_java_question_import_candidates_status", "batch_id", "parse_status"),
    )
    batch_id: Mapped[UUID] = mapped_column(primary_key=True)
    source_question_key: Mapped[str] = mapped_column(String(160), primary_key=True)
    chapter_number: Mapped[int | None] = mapped_column(Integer, nullable=True)
    chapter_title: Mapped[str] = mapped_column(String(300))
    question_number: Mapped[int] = mapped_column(Integer)
    page_start: Mapped[int] = mapped_column(Integer)
    page_end: Mapped[int] = mapped_column(Integer)
    prompt: Mapped[str] = mapped_column(Text)
    options: Mapped[list[dict[str, str]]] = mapped_column(JSONB)
    correct: Mapped[list[str] | None] = mapped_column(JSONB, nullable=True)
    explanation: Mapped[str | None] = mapped_column(Text, nullable=True)
    normalized_hash: Mapped[str] = mapped_column(String(64))
    parse_status: Mapped[str] = mapped_column(String(24))
    issue_codes: Mapped[list[str]] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
