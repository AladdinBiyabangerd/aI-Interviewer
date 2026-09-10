"""Versioned Java assessment bank, owner sessions and question feedback.

Revision ID: 20260910_0015
Revises: 20260902_0014
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260910_0015"
down_revision: str | None = "20260902_0014"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "java_question_bank",
        sa.Column("id", sa.String(100), primary_key=True),
        sa.Column("version", sa.Integer(), primary_key=True),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column("question", postgresql.JSONB(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint("version > 0", name="ck_java_question_version"),
        sa.CheckConstraint(
            "status IN ('draft', 'published', 'retired')", name="ck_java_question_status"
        ),
    )
    op.create_table(
        "java_assessment_sessions",
        sa.Column("id", sa.UUID(), primary_key=True),
        sa.Column("owner_hash", sa.String(64), nullable=False),
        sa.Column("state", postgresql.JSONB(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "ix_java_assessment_owner", "java_assessment_sessions", ["owner_hash", "created_at"]
    )
    op.create_index("ix_java_assessment_expiry", "java_assessment_sessions", ["expires_at"])
    op.create_table(
        "java_question_feedback",
        sa.Column("owner_hash", sa.String(64), primary_key=True),
        sa.Column("question_id", sa.String(100), primary_key=True),
        sa.Column("question_version", sa.Integer(), primary_key=True),
        sa.Column("rating", sa.Integer(), nullable=True),
        sa.Column("flag", sa.String(32), nullable=True),
        sa.Column("review_status", sa.String(16), server_default="pending", nullable=False),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "rating IS NULL OR rating BETWEEN 1 AND 5", name="ck_java_feedback_rating"
        ),
        sa.CheckConstraint(
            "flag IS NULL OR flag IN ('incorrect', 'unclear', 'too_difficult', 'source')",
            name="ck_java_feedback_flag",
        ),
        sa.CheckConstraint(
            "review_status IN ('pending', 'resolved')", name="ck_java_feedback_review"
        ),
        sa.ForeignKeyConstraint(
            ["question_id", "question_version"],
            ["java_question_bank.id", "java_question_bank.version"],
        ),
    )


def downgrade() -> None:
    op.drop_table("java_question_feedback")
    op.drop_index("ix_java_assessment_expiry", table_name="java_assessment_sessions")
    op.drop_index("ix_java_assessment_owner", table_name="java_assessment_sessions")
    op.drop_table("java_assessment_sessions")
    op.drop_table("java_question_bank")
