"""vercel interview runtime

Revision ID: 20260902_0014
Revises: 20260902_0013
Create Date: 2026-09-02 21:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260902_0014"
down_revision: str | None = "20260902_0013"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _timestamps() -> tuple[sa.Column[object], sa.Column[object], sa.Column[object]]:
    return (
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )


def upgrade() -> None:
    op.create_table(
        "interview_cv_uploads",
        sa.Column("owner_hash", sa.String(length=64), nullable=False),
        sa.Column("pathname", sa.String(length=1024), nullable=True),
        sa.Column("blob_url", sa.String(length=2048), nullable=True),
        sa.Column("file_name", sa.String(length=240), nullable=False),
        sa.Column("content_type", sa.String(length=128), nullable=False),
        sa.Column("size_bytes", sa.BigInteger(), nullable=True),
        sa.Column("status", sa.String(length=16), server_default="pending", nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        *_timestamps(),
        sa.CheckConstraint(
            "owner_hash ~ '^[0-9a-f]{64}$'",
            name=op.f("ck_interview_cv_uploads_owner_hash_format"),
        ),
        sa.CheckConstraint(
            "content_type IN ('application/pdf', "
            "'application/vnd.openxmlformats-officedocument.wordprocessingml.document')",
            name=op.f("ck_interview_cv_uploads_content_type_allowed"),
        ),
        sa.CheckConstraint(
            "size_bytes IS NULL OR size_bytes BETWEEN 1 AND 10485760",
            name=op.f("ck_interview_cv_uploads_size_bounded"),
        ),
        sa.CheckConstraint(
            "status IN ('pending', 'ready', 'consumed')",
            name=op.f("ck_interview_cv_uploads_status_allowed"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_interview_cv_uploads")),
        sa.UniqueConstraint("pathname", name="uq_interview_cv_upload_pathname"),
    )
    op.create_index(
        "ix_interview_cv_uploads_owner_status",
        "interview_cv_uploads",
        ["owner_hash", "status", "expires_at"],
        unique=False,
    )

    op.create_table(
        "interview_preparations",
        sa.Column("owner_hash", sa.String(length=64), nullable=False),
        sa.Column("requester_hash", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=16), server_default="queued", nullable=False),
        sa.Column("input", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("analysis", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("research_response_id", sa.String(length=128), nullable=True),
        sa.Column("cv_response_id", sa.String(length=128), nullable=True),
        sa.Column("provider_file_id", sa.String(length=128), nullable=True),
        sa.Column("cv_upload_id", sa.UUID(), nullable=True),
        sa.Column("error_code", sa.String(length=64), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        *_timestamps(),
        sa.CheckConstraint(
            "owner_hash ~ '^[0-9a-f]{64}$' AND requester_hash ~ '^[0-9a-f]{64}$'",
            name=op.f("ck_interview_preparations_hashes_format"),
        ),
        sa.CheckConstraint(
            "status IN ('queued', 'in_progress', 'completed', 'failed')",
            name=op.f("ck_interview_preparations_status_allowed"),
        ),
        sa.ForeignKeyConstraint(
            ["cv_upload_id"],
            ["interview_cv_uploads.id"],
            name=op.f("fk_interview_preparations_cv_upload_id_interview_cv_uploads"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_interview_preparations")),
    )
    op.create_index(
        "ix_interview_preparations_owner_created",
        "interview_preparations",
        ["owner_hash", "created_at"],
        unique=False,
    )
    op.create_index(
        "ix_interview_preparations_request_rate",
        "interview_preparations",
        ["requester_hash", "created_at"],
        unique=False,
    )
    op.create_index(
        "ix_interview_preparations_provider_responses",
        "interview_preparations",
        ["research_response_id", "cv_response_id"],
        unique=False,
    )

    op.create_table(
        "interview_practice_sessions",
        sa.Column("preparation_id", sa.UUID(), nullable=False),
        sa.Column("owner_hash", sa.String(length=64), nullable=False),
        sa.Column("mode", sa.String(length=24), nullable=False),
        sa.Column("focus", sa.String(length=32), nullable=False),
        sa.Column("duration_minutes", sa.Integer(), nullable=False),
        sa.Column("question_ids", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("current_index", sa.Integer(), server_default="0", nullable=False),
        sa.Column(
            "awaiting_follow_up",
            sa.Boolean(),
            server_default=sa.text("false"),
            nullable=False,
        ),
        sa.Column("pending_follow_up", sa.Text(), nullable=True),
        sa.Column("status", sa.String(length=16), server_default="active", nullable=False),
        sa.Column("report", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        *_timestamps(),
        sa.CheckConstraint(
            "owner_hash ~ '^[0-9a-f]{64}$'",
            name=op.f("ck_interview_practice_sessions_owner_hash_format"),
        ),
        sa.CheckConstraint(
            "mode IN ('Real Interview', 'Practice')",
            name=op.f("ck_interview_practice_sessions_mode_allowed"),
        ),
        sa.CheckConstraint(
            "focus IN ('Full Interview', 'Technical', 'HR / Behavioral', 'CV Deep Dive')",
            name=op.f("ck_interview_practice_sessions_focus_allowed"),
        ),
        sa.CheckConstraint(
            "duration_minutes IN (15, 30, 45)",
            name=op.f("ck_interview_practice_sessions_duration_allowed"),
        ),
        sa.CheckConstraint(
            "jsonb_array_length(question_ids) BETWEEN 1 AND 20",
            name=op.f("ck_interview_practice_sessions_questions_bounded"),
        ),
        sa.CheckConstraint(
            "current_index BETWEEN 0 AND 20",
            name=op.f("ck_interview_practice_sessions_current_index_bounded"),
        ),
        sa.CheckConstraint(
            "status IN ('active', 'completed')",
            name=op.f("ck_interview_practice_sessions_status_allowed"),
        ),
        sa.ForeignKeyConstraint(
            ["preparation_id"],
            ["interview_preparations.id"],
            name=op.f("fk_interview_practice_sessions_preparation_id_interview_preparations"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_interview_practice_sessions")),
    )
    op.create_index(
        "ix_interview_practice_sessions_owner_created",
        "interview_practice_sessions",
        ["owner_hash", "created_at"],
        unique=False,
    )

    op.create_table(
        "interview_practice_turns",
        sa.Column("session_id", sa.UUID(), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("question_id", sa.String(length=128), nullable=False),
        sa.Column("kind", sa.String(length=16), nullable=False),
        sa.Column("prompt", sa.Text(), nullable=False),
        sa.Column("answer", sa.Text(), nullable=False),
        sa.Column("feedback", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        *_timestamps(),
        sa.CheckConstraint(
            "sequence BETWEEN 0 AND 40",
            name=op.f("ck_interview_practice_turns_sequence_bounded"),
        ),
        sa.CheckConstraint(
            "kind IN ('question', 'follow_up')",
            name=op.f("ck_interview_practice_turns_kind_allowed"),
        ),
        sa.CheckConstraint(
            "char_length(answer) BETWEEN 30 AND 2500",
            name=op.f("ck_interview_practice_turns_answer_bounded"),
        ),
        sa.ForeignKeyConstraint(
            ["session_id"],
            ["interview_practice_sessions.id"],
            name=op.f("fk_interview_practice_turns_session_id_interview_practice_sessions"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_interview_practice_turns")),
        sa.UniqueConstraint("session_id", "sequence", name="uq_interview_practice_turn_sequence"),
    )


def downgrade() -> None:
    op.drop_table("interview_practice_turns")
    op.drop_index(
        "ix_interview_practice_sessions_owner_created",
        table_name="interview_practice_sessions",
    )
    op.drop_table("interview_practice_sessions")
    op.drop_index(
        "ix_interview_preparations_provider_responses",
        table_name="interview_preparations",
    )
    op.drop_index(
        "ix_interview_preparations_request_rate",
        table_name="interview_preparations",
    )
    op.drop_index(
        "ix_interview_preparations_owner_created",
        table_name="interview_preparations",
    )
    op.drop_table("interview_preparations")
    op.drop_index(
        "ix_interview_cv_uploads_owner_status",
        table_name="interview_cv_uploads",
    )
    op.drop_table("interview_cv_uploads")
