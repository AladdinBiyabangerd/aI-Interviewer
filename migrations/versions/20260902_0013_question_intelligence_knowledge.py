"""question intelligence knowledge foundation

Revision ID: 20260902_0013
Revises: 20260901_0012
Create Date: 2026-09-02 17:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260902_0013"
down_revision: str | None = "20260901_0012"
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
        "knowledge_sources",
        sa.Column("source_key", sa.String(length=96), nullable=False),
        sa.Column("source_type", sa.String(length=40), nullable=False),
        sa.Column("source_url", sa.String(length=2048), nullable=True),
        sa.Column("rights_status", sa.String(length=32), nullable=False),
        sa.Column("policy_version", sa.String(length=96), nullable=False),
        sa.Column("retrieved_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("content_sha256", sa.String(length=64), nullable=False),
        sa.Column("source_trust", sa.Float(), nullable=False),
        sa.Column("independent_group", sa.String(length=96), nullable=False),
        *_timestamps(),
        sa.CheckConstraint(
            "source_type IN ('official_site', 'careers_page', 'job_description', "
            "'engineering_blog', 'conference_material', 'public_interview_report', "
            "'user_interview_report', 'role_taxonomy', 'industry_taxonomy', 'candidate_cv')",
            name=op.f("ck_knowledge_sources_source_type_allowed"),
        ),
        sa.CheckConstraint(
            "rights_status IN ('permitted_full', 'permitted_derived', 'metadata_only', "
            "'pending', 'prohibited', 'withdrawn')",
            name=op.f("ck_knowledge_sources_rights_status_allowed"),
        ),
        sa.CheckConstraint(
            "source_url IS NULL OR source_url ~ '^https://[^[:space:]]{1,2039}$'",
            name=op.f("ck_knowledge_sources_source_url_https"),
        ),
        sa.CheckConstraint(
            "source_key ~ '^[a-z][a-z0-9_]{0,95}$'",
            name=op.f("ck_knowledge_sources_source_key_format"),
        ),
        sa.CheckConstraint(
            "policy_version ~ '^[a-z][a-z0-9_]{0,95}$'",
            name=op.f("ck_knowledge_sources_policy_version_format"),
        ),
        sa.CheckConstraint(
            "independent_group ~ '^[a-z][a-z0-9_]{0,95}$'",
            name=op.f("ck_knowledge_sources_independent_group_format"),
        ),
        sa.CheckConstraint(
            "content_sha256 ~ '^[0-9a-f]{64}$'",
            name=op.f("ck_knowledge_sources_content_digest_format"),
        ),
        sa.CheckConstraint(
            "source_trust BETWEEN 0 AND 1",
            name=op.f("ck_knowledge_sources_source_trust_bounded"),
        ),
        sa.CheckConstraint(
            "published_at IS NULL OR published_at <= retrieved_at",
            name=op.f("ck_knowledge_sources_publication_before_retrieval"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_knowledge_sources")),
        sa.UniqueConstraint("source_key", "policy_version", name="uq_knowledge_source_release"),
    )
    op.create_index(
        "ix_knowledge_sources_rights",
        "knowledge_sources",
        ["rights_status", "source_type"],
        unique=False,
    )

    op.create_table(
        "knowledge_evidence_signals",
        sa.Column("evidence_key", sa.String(length=96), nullable=False),
        sa.Column("layer", sa.String(length=32), nullable=False),
        sa.Column("competency_key", sa.String(length=96), nullable=False),
        sa.Column("signal", sa.Text(), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("frequency", sa.Integer(), server_default=sa.text("1"), nullable=False),
        sa.Column("company_name", sa.String(length=240), nullable=True),
        sa.Column("role_family", sa.String(length=32), nullable=True),
        sa.Column("seniority", sa.String(length=16), nullable=True),
        sa.Column("interview_round", sa.String(length=32), nullable=True),
        sa.Column("industry", sa.String(length=240), nullable=True),
        *_timestamps(),
        sa.CheckConstraint(
            "layer IN ('company_official', 'company_public', 'user_report', "
            "'job_description', 'role_pattern', 'industry_pattern', 'cv_claim')",
            name=op.f("ck_knowledge_evidence_signals_layer_allowed"),
        ),
        sa.CheckConstraint(
            "evidence_key ~ '^[a-z][a-z0-9_]{0,95}$'",
            name=op.f("ck_knowledge_evidence_signals_evidence_key_format"),
        ),
        sa.CheckConstraint(
            "competency_key ~ '^[a-z][a-z0-9_]{0,95}$'",
            name=op.f("ck_knowledge_evidence_signals_competency_key_format"),
        ),
        sa.CheckConstraint(
            "btrim(signal) <> ''",
            name=op.f("ck_knowledge_evidence_signals_signal_nonempty"),
        ),
        sa.CheckConstraint(
            "confidence BETWEEN 0 AND 1",
            name=op.f("ck_knowledge_evidence_signals_confidence_bounded"),
        ),
        sa.CheckConstraint(
            "frequency BETWEEN 1 AND 100000",
            name=op.f("ck_knowledge_evidence_signals_frequency_bounded"),
        ),
        sa.CheckConstraint(
            "layer NOT IN ('company_official', 'company_public') OR company_name IS NOT NULL",
            name=op.f("ck_knowledge_evidence_signals_company_layer_identified"),
        ),
        sa.CheckConstraint(
            "layer <> 'industry_pattern' OR industry IS NOT NULL",
            name=op.f("ck_knowledge_evidence_signals_industry_layer_identified"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_knowledge_evidence_signals")),
        sa.UniqueConstraint("evidence_key", name="uq_knowledge_evidence_key"),
    )
    op.create_index(
        "ix_knowledge_evidence_retrieval",
        "knowledge_evidence_signals",
        ["competency_key", "role_family", "interview_round"],
        unique=False,
    )
    op.create_index(
        "ix_knowledge_evidence_company",
        "knowledge_evidence_signals",
        ["company_name", "competency_key"],
        unique=False,
    )

    op.create_table(
        "knowledge_evidence_sources",
        sa.Column("evidence_id", sa.UUID(), nullable=False),
        sa.Column("source_id", sa.UUID(), nullable=False),
        sa.ForeignKeyConstraint(
            ["evidence_id"],
            ["knowledge_evidence_signals.id"],
            name=op.f("fk_knowledge_evidence_sources_evidence_id_knowledge_evidence_signals"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["source_id"],
            ["knowledge_sources.id"],
            name=op.f("fk_knowledge_evidence_sources_source_id_knowledge_sources"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint(
            "evidence_id", "source_id", name=op.f("pk_knowledge_evidence_sources")
        ),
    )

    op.create_table(
        "question_concepts",
        sa.Column("concept_key", sa.String(length=96), nullable=False),
        sa.Column("catalog_version", sa.String(length=96), nullable=False),
        sa.Column("competency_key", sa.String(length=96), nullable=False),
        sa.Column("subtopic", sa.String(length=96), nullable=False),
        sa.Column("role_families", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("seniorities", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("interview_rounds", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("difficulty", sa.String(length=16), nullable=False),
        sa.Column("question_intent", sa.Text(), nullable=False),
        sa.Column("possible_probes", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        *_timestamps(),
        sa.CheckConstraint(
            "concept_key ~ '^[a-z][a-z0-9_]{0,95}$'",
            name=op.f("ck_question_concepts_concept_key_format"),
        ),
        sa.CheckConstraint(
            "competency_key ~ '^[a-z][a-z0-9_]{0,95}$'",
            name=op.f("ck_question_concepts_competency_key_format"),
        ),
        sa.CheckConstraint(
            "subtopic ~ '^[a-z][a-z0-9_]{0,95}$'",
            name=op.f("ck_question_concepts_subtopic_format"),
        ),
        sa.CheckConstraint(
            "difficulty IN ('foundation', 'medium', 'advanced')",
            name=op.f("ck_question_concepts_difficulty_allowed"),
        ),
        sa.CheckConstraint(
            "btrim(question_intent) <> ''",
            name=op.f("ck_question_concepts_intent_nonempty"),
        ),
        sa.CheckConstraint(
            "jsonb_array_length(role_families) > 0",
            name=op.f("ck_question_concepts_role_families_nonempty"),
        ),
        sa.CheckConstraint(
            "jsonb_array_length(seniorities) > 0",
            name=op.f("ck_question_concepts_seniorities_nonempty"),
        ),
        sa.CheckConstraint(
            "jsonb_array_length(interview_rounds) > 0",
            name=op.f("ck_question_concepts_interview_rounds_nonempty"),
        ),
        sa.CheckConstraint(
            "jsonb_array_length(possible_probes) > 0",
            name=op.f("ck_question_concepts_probes_nonempty"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_question_concepts")),
        sa.UniqueConstraint("concept_key", "catalog_version", name="uq_question_concept_release"),
    )
    op.create_index(
        "ix_question_concepts_retrieval",
        "question_concepts",
        ["competency_key", "subtopic", "active"],
        unique=False,
    )

    op.create_table(
        "question_concept_evidence",
        sa.Column("concept_id", sa.UUID(), nullable=False),
        sa.Column("evidence_id", sa.UUID(), nullable=False),
        sa.ForeignKeyConstraint(
            ["concept_id"],
            ["question_concepts.id"],
            name=op.f("fk_question_concept_evidence_concept_id_question_concepts"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["evidence_id"],
            ["knowledge_evidence_signals.id"],
            name=op.f("fk_question_concept_evidence_evidence_id_knowledge_evidence_signals"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint(
            "concept_id", "evidence_id", name=op.f("pk_question_concept_evidence")
        ),
    )

    op.create_table(
        "company_interview_fingerprints",
        sa.Column("company_name", sa.String(length=240), nullable=False),
        sa.Column("role_family", sa.String(length=32), nullable=False),
        sa.Column("seniority", sa.String(length=16), nullable=False),
        sa.Column("country_code", sa.String(length=2), nullable=False),
        sa.Column("office", sa.String(length=240), nullable=True),
        sa.Column("interview_round", sa.String(length=32), nullable=False),
        sa.Column("fingerprint_version", sa.String(length=96), nullable=False),
        sa.Column(
            "competency_distribution",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
        sa.Column("evidence_count", sa.Integer(), nullable=False),
        sa.Column("independent_source_count", sa.Integer(), nullable=False),
        sa.Column("specificity", sa.String(length=16), nullable=False),
        *_timestamps(),
        sa.CheckConstraint(
            "btrim(company_name) <> ''",
            name=op.f("ck_company_interview_fingerprints_company_name_nonempty"),
        ),
        sa.CheckConstraint(
            "country_code ~ '^[A-Z]{2}$'",
            name=op.f("ck_company_interview_fingerprints_country_code_format"),
        ),
        sa.CheckConstraint(
            "specificity IN ('high', 'medium', 'limited')",
            name=op.f("ck_company_interview_fingerprints_specificity_allowed"),
        ),
        sa.CheckConstraint(
            "evidence_count > 0",
            name=op.f("ck_company_interview_fingerprints_evidence_count_positive"),
        ),
        sa.CheckConstraint(
            "independent_source_count > 0 AND independent_source_count <= evidence_count",
            name=op.f("ck_company_interview_fingerprints_independent_sources_valid"),
        ),
        sa.CheckConstraint(
            "specificity <> 'high' OR independent_source_count >= 2",
            name=op.f("ck_company_interview_fingerprints_high_specificity_corroborated"),
        ),
        sa.CheckConstraint(
            "jsonb_array_length(competency_distribution) > 0",
            name=op.f("ck_company_interview_fingerprints_distribution_nonempty"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_company_interview_fingerprints")),
    )
    op.create_index(
        "uq_company_interview_fingerprint_slice",
        "company_interview_fingerprints",
        [
            "company_name",
            "role_family",
            "seniority",
            "country_code",
            "office",
            "interview_round",
            "fingerprint_version",
        ],
        unique=True,
        postgresql_nulls_not_distinct=True,
    )
    op.create_index(
        "ix_company_interview_fingerprints_lookup",
        "company_interview_fingerprints",
        ["company_name", "role_family", "interview_round"],
        unique=False,
    )

    op.create_table(
        "company_fingerprint_evidence",
        sa.Column("fingerprint_id", sa.UUID(), nullable=False),
        sa.Column("evidence_id", sa.UUID(), nullable=False),
        sa.ForeignKeyConstraint(
            ["fingerprint_id"],
            ["company_interview_fingerprints.id"],
            name=op.f(
                "fk_company_fingerprint_evidence_fingerprint_id_company_interview_fingerprints"
            ),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["evidence_id"],
            ["knowledge_evidence_signals.id"],
            name=op.f("fk_company_fingerprint_evidence_evidence_id_knowledge_evidence_signals"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint(
            "fingerprint_id", "evidence_id", name=op.f("pk_company_fingerprint_evidence")
        ),
    )


def downgrade() -> None:
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (SELECT 1 FROM knowledge_sources LIMIT 1)
                OR EXISTS (SELECT 1 FROM knowledge_evidence_signals LIMIT 1)
                OR EXISTS (SELECT 1 FROM question_concepts LIMIT 1)
                OR EXISTS (SELECT 1 FROM company_interview_fingerprints LIMIT 1) THEN
                RAISE EXCEPTION 'Cannot downgrade while question intelligence data exists';
            END IF;
        END;
        $$
        """
    )
    op.drop_table("company_fingerprint_evidence")
    op.drop_index(
        "ix_company_interview_fingerprints_lookup",
        table_name="company_interview_fingerprints",
    )
    op.drop_index(
        "uq_company_interview_fingerprint_slice",
        table_name="company_interview_fingerprints",
        postgresql_nulls_not_distinct=True,
    )
    op.drop_table("company_interview_fingerprints")
    op.drop_table("question_concept_evidence")
    op.drop_index("ix_question_concepts_retrieval", table_name="question_concepts")
    op.drop_table("question_concepts")
    op.drop_table("knowledge_evidence_sources")
    op.drop_index("ix_knowledge_evidence_company", table_name="knowledge_evidence_signals")
    op.drop_index("ix_knowledge_evidence_retrieval", table_name="knowledge_evidence_signals")
    op.drop_table("knowledge_evidence_signals")
    op.drop_index("ix_knowledge_sources_rights", table_name="knowledge_sources")
    op.drop_table("knowledge_sources")
