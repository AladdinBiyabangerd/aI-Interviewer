"""Private source-question staging for reviewed question-bank ingestion.

Revision ID: 20260910_0016
Revises: 20260910_0015
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260910_0016"
down_revision: str | None = "20260910_0015"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "java_question_import_batches",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("source_sha256", sa.String(length=64), nullable=False),
        sa.Column("file_name", sa.String(length=255), nullable=False),
        sa.Column("source_title", sa.String(length=500), nullable=False),
        sa.Column("authors", sa.String(length=500), nullable=True),
        sa.Column("publisher", sa.String(length=200), nullable=True),
        sa.Column("publication_year", sa.Integer(), nullable=True),
        sa.Column("reference_url", sa.String(length=2048), nullable=True),
        sa.Column("parser_release", sa.String(length=64), nullable=False),
        sa.Column("rights_status", sa.String(length=24), nullable=False),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("page_count", sa.Integer(), nullable=False),
        sa.Column("question_count", sa.Integer(), nullable=False),
        sa.Column("answer_count", sa.Integer(), nullable=False),
        sa.Column("report", postgresql.JSONB(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint("source_sha256 ~ '^[0-9a-f]{64}$'", name="ck_java_import_source_digest"),
        sa.CheckConstraint(
            "rights_status IN ('unverified', 'cleared', 'rejected')",
            name="ck_java_import_rights_status",
        ),
        sa.CheckConstraint(
            "status IN ('ready', 'review_required', 'failed')",
            name="ck_java_import_status",
        ),
        sa.CheckConstraint(
            "page_count > 0 AND question_count >= 0 AND answer_count >= 0 "
            "AND answer_count <= question_count",
            name="ck_java_import_counts",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_java_question_import_batches")),
        sa.UniqueConstraint(
            "source_sha256",
            "parser_release",
            name="uq_java_question_import_source_release",
        ),
    )
    op.create_table(
        "java_question_import_candidates",
        sa.Column("batch_id", sa.UUID(), nullable=False),
        sa.Column("source_question_key", sa.String(length=160), nullable=False),
        sa.Column("chapter_number", sa.Integer(), nullable=True),
        sa.Column("chapter_title", sa.String(length=300), nullable=False),
        sa.Column("question_number", sa.Integer(), nullable=False),
        sa.Column("page_start", sa.Integer(), nullable=False),
        sa.Column("page_end", sa.Integer(), nullable=False),
        sa.Column("prompt", sa.Text(), nullable=False),
        sa.Column("options", postgresql.JSONB(), nullable=False),
        sa.Column("correct", postgresql.JSONB(), nullable=True),
        sa.Column("explanation", sa.Text(), nullable=True),
        sa.Column("normalized_hash", sa.String(length=64), nullable=False),
        sa.Column("parse_status", sa.String(length=24), nullable=False),
        sa.Column("issue_codes", postgresql.JSONB(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint("question_number > 0", name="question_number"),
        sa.CheckConstraint(
            "page_start > 0 AND page_end >= page_start", name="ck_java_import_page_range"
        ),
        sa.CheckConstraint("normalized_hash ~ '^[0-9a-f]{64}$'", name="normalized_digest"),
        sa.CheckConstraint(
            "parse_status IN ('complete', 'needs_answer', 'needs_review')",
            name="ck_java_import_parse_status",
        ),
        sa.ForeignKeyConstraint(
            ["batch_id"],
            ["java_question_import_batches.id"],
            name=op.f("fk_java_question_import_candidates_batch_id_java_question_import_batches"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint(
            "batch_id", "source_question_key", name=op.f("pk_java_question_import_candidates")
        ),
    )
    op.create_index(
        "ix_java_question_import_candidates_hash",
        "java_question_import_candidates",
        ["normalized_hash"],
        unique=False,
    )
    op.create_index(
        "ix_java_question_import_candidates_status",
        "java_question_import_candidates",
        ["batch_id", "parse_status"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_java_question_import_candidates_status",
        table_name="java_question_import_candidates",
    )
    op.drop_index(
        "ix_java_question_import_candidates_hash",
        table_name="java_question_import_candidates",
    )
    op.drop_table("java_question_import_candidates")
    op.drop_table("java_question_import_batches")
