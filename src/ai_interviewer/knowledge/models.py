"""Relational knowledge-base models; question wording is intentionally not stored."""

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    Float,
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


class KnowledgeSourceRecord(UUIDPrimaryKeyMixin, TimestampMixin, PersistenceBase):
    """Versioned provenance and rights snapshot for one acquired source."""

    __tablename__ = "knowledge_sources"
    __table_args__ = (
        CheckConstraint(
            "source_type IN ('official_site', 'careers_page', 'job_description', "
            "'engineering_blog', 'conference_material', 'public_interview_report', "
            "'user_interview_report', 'role_taxonomy', 'industry_taxonomy', 'candidate_cv')",
            name="source_type_allowed",
        ),
        CheckConstraint(
            "rights_status IN ('permitted_full', 'permitted_derived', 'metadata_only', "
            "'pending', 'prohibited', 'withdrawn')",
            name="rights_status_allowed",
        ),
        CheckConstraint(
            "source_url IS NULL OR source_url ~ '^https://[^[:space:]]{1,2039}$'",
            name="source_url_https",
        ),
        CheckConstraint(
            "source_key ~ '^[a-z][a-z0-9_]{0,95}$'",
            name="source_key_format",
        ),
        CheckConstraint(
            "policy_version ~ '^[a-z][a-z0-9_]{0,95}$'",
            name="policy_version_format",
        ),
        CheckConstraint(
            "independent_group ~ '^[a-z][a-z0-9_]{0,95}$'",
            name="independent_group_format",
        ),
        CheckConstraint(
            "content_sha256 ~ '^[0-9a-f]{64}$'",
            name="content_digest_format",
        ),
        CheckConstraint("source_trust BETWEEN 0 AND 1", name="source_trust_bounded"),
        CheckConstraint(
            "published_at IS NULL OR published_at <= retrieved_at",
            name="publication_before_retrieval",
        ),
        UniqueConstraint("source_key", "policy_version", name="uq_knowledge_source_release"),
        Index("ix_knowledge_sources_rights", "rights_status", "source_type"),
    )

    source_key: Mapped[str] = mapped_column(String(96), nullable=False)
    source_type: Mapped[str] = mapped_column(String(40), nullable=False)
    source_url: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    rights_status: Mapped[str] = mapped_column(String(32), nullable=False)
    policy_version: Mapped[str] = mapped_column(String(96), nullable=False)
    retrieved_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    content_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    source_trust: Mapped[float] = mapped_column(Float, nullable=False)
    independent_group: Mapped[str] = mapped_column(String(96), nullable=False)


class EvidenceSignalRecord(UUIDPrimaryKeyMixin, TimestampMixin, PersistenceBase):
    """Normalized fact or pattern derived from one or more rights-cleared sources."""

    __tablename__ = "knowledge_evidence_signals"
    __table_args__ = (
        CheckConstraint(
            "layer IN ('company_official', 'company_public', 'user_report', "
            "'job_description', 'role_pattern', 'industry_pattern', 'cv_claim')",
            name="layer_allowed",
        ),
        CheckConstraint(
            "evidence_key ~ '^[a-z][a-z0-9_]{0,95}$'",
            name="evidence_key_format",
        ),
        CheckConstraint(
            "competency_key ~ '^[a-z][a-z0-9_]{0,95}$'",
            name="competency_key_format",
        ),
        CheckConstraint("btrim(signal) <> ''", name="signal_nonempty"),
        CheckConstraint("confidence BETWEEN 0 AND 1", name="confidence_bounded"),
        CheckConstraint("frequency BETWEEN 1 AND 100000", name="frequency_bounded"),
        CheckConstraint(
            "layer NOT IN ('company_official', 'company_public') OR company_name IS NOT NULL",
            name="company_layer_identified",
        ),
        CheckConstraint(
            "layer <> 'industry_pattern' OR industry IS NOT NULL",
            name="industry_layer_identified",
        ),
        UniqueConstraint("evidence_key", name="uq_knowledge_evidence_key"),
        Index(
            "ix_knowledge_evidence_retrieval",
            "competency_key",
            "role_family",
            "interview_round",
        ),
        Index("ix_knowledge_evidence_company", "company_name", "competency_key"),
    )

    evidence_key: Mapped[str] = mapped_column(String(96), nullable=False)
    layer: Mapped[str] = mapped_column(String(32), nullable=False)
    competency_key: Mapped[str] = mapped_column(String(96), nullable=False)
    signal: Mapped[str] = mapped_column(Text, nullable=False)
    confidence: Mapped[float] = mapped_column(Float, nullable=False)
    frequency: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("1"))
    company_name: Mapped[str | None] = mapped_column(String(240), nullable=True)
    role_family: Mapped[str | None] = mapped_column(String(32), nullable=True)
    seniority: Mapped[str | None] = mapped_column(String(16), nullable=True)
    interview_round: Mapped[str | None] = mapped_column(String(32), nullable=True)
    industry: Mapped[str | None] = mapped_column(String(240), nullable=True)


class EvidenceSourceLink(PersistenceBase):
    """Many-source corroboration edge for one normalized signal."""

    __tablename__ = "knowledge_evidence_sources"

    evidence_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("knowledge_evidence_signals.id", ondelete="CASCADE"),
        primary_key=True,
    )
    source_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("knowledge_sources.id", ondelete="RESTRICT"),
        primary_key=True,
    )


class QuestionConceptRecord(UUIDPrimaryKeyMixin, TimestampMixin, PersistenceBase):
    """Canonical question intent; rendered question text is outside this boundary."""

    __tablename__ = "question_concepts"
    __table_args__ = (
        CheckConstraint(
            "concept_key ~ '^[a-z][a-z0-9_]{0,95}$'",
            name="concept_key_format",
        ),
        CheckConstraint(
            "competency_key ~ '^[a-z][a-z0-9_]{0,95}$'",
            name="competency_key_format",
        ),
        CheckConstraint(
            "subtopic ~ '^[a-z][a-z0-9_]{0,95}$'",
            name="subtopic_format",
        ),
        CheckConstraint(
            "difficulty IN ('foundation', 'medium', 'advanced')",
            name="difficulty_allowed",
        ),
        CheckConstraint("btrim(question_intent) <> ''", name="intent_nonempty"),
        CheckConstraint("jsonb_array_length(role_families) > 0", name="role_families_nonempty"),
        CheckConstraint("jsonb_array_length(seniorities) > 0", name="seniorities_nonempty"),
        CheckConstraint(
            "jsonb_array_length(interview_rounds) > 0",
            name="interview_rounds_nonempty",
        ),
        CheckConstraint("jsonb_array_length(possible_probes) > 0", name="probes_nonempty"),
        UniqueConstraint("concept_key", "catalog_version", name="uq_question_concept_release"),
        Index("ix_question_concepts_retrieval", "competency_key", "subtopic", "active"),
    )

    concept_key: Mapped[str] = mapped_column(String(96), nullable=False)
    catalog_version: Mapped[str] = mapped_column(String(96), nullable=False)
    competency_key: Mapped[str] = mapped_column(String(96), nullable=False)
    subtopic: Mapped[str] = mapped_column(String(96), nullable=False)
    role_families: Mapped[list[str]] = mapped_column(JSONB, nullable=False)
    seniorities: Mapped[list[str]] = mapped_column(JSONB, nullable=False)
    interview_rounds: Mapped[list[str]] = mapped_column(JSONB, nullable=False)
    difficulty: Mapped[str] = mapped_column(String(16), nullable=False)
    question_intent: Mapped[str] = mapped_column(Text, nullable=False)
    possible_probes: Mapped[list[str]] = mapped_column(JSONB, nullable=False)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))


class QuestionConceptEvidenceLink(PersistenceBase):
    """Auditable support edge from a concept to normalized evidence."""

    __tablename__ = "question_concept_evidence"

    concept_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("question_concepts.id", ondelete="CASCADE"),
        primary_key=True,
    )
    evidence_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("knowledge_evidence_signals.id", ondelete="RESTRICT"),
        primary_key=True,
    )


class CompanyInterviewFingerprintRecord(UUIDPrimaryKeyMixin, TimestampMixin, PersistenceBase):
    """Materialized, evidence-derived distribution for one company interview slice."""

    __tablename__ = "company_interview_fingerprints"
    __table_args__ = (
        CheckConstraint("btrim(company_name) <> ''", name="company_name_nonempty"),
        CheckConstraint("country_code ~ '^[A-Z]{2}$'", name="country_code_format"),
        CheckConstraint(
            "specificity IN ('high', 'medium', 'limited')",
            name="specificity_allowed",
        ),
        CheckConstraint("evidence_count > 0", name="evidence_count_positive"),
        CheckConstraint(
            "independent_source_count > 0 AND independent_source_count <= evidence_count",
            name="independent_sources_valid",
        ),
        CheckConstraint(
            "specificity <> 'high' OR independent_source_count >= 2",
            name="high_specificity_corroborated",
        ),
        CheckConstraint(
            "jsonb_array_length(competency_distribution) > 0",
            name="distribution_nonempty",
        ),
        Index(
            "uq_company_interview_fingerprint_slice",
            "company_name",
            "role_family",
            "seniority",
            "country_code",
            "office",
            "interview_round",
            "fingerprint_version",
            unique=True,
            postgresql_nulls_not_distinct=True,
        ),
        Index(
            "ix_company_interview_fingerprints_lookup",
            "company_name",
            "role_family",
            "interview_round",
        ),
    )

    company_name: Mapped[str] = mapped_column(String(240), nullable=False)
    role_family: Mapped[str] = mapped_column(String(32), nullable=False)
    seniority: Mapped[str] = mapped_column(String(16), nullable=False)
    country_code: Mapped[str] = mapped_column(String(2), nullable=False)
    office: Mapped[str | None] = mapped_column(String(240), nullable=True)
    interview_round: Mapped[str] = mapped_column(String(32), nullable=False)
    fingerprint_version: Mapped[str] = mapped_column(String(96), nullable=False)
    competency_distribution: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False)
    evidence_count: Mapped[int] = mapped_column(Integer, nullable=False)
    independent_source_count: Mapped[int] = mapped_column(Integer, nullable=False)
    specificity: Mapped[str] = mapped_column(String(16), nullable=False)


class CompanyFingerprintEvidenceLink(PersistenceBase):
    """Evidence lineage for every materialized company fingerprint."""

    __tablename__ = "company_fingerprint_evidence"

    fingerprint_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("company_interview_fingerprints.id", ondelete="CASCADE"),
        primary_key=True,
    )
    evidence_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("knowledge_evidence_signals.id", ondelete="RESTRICT"),
        primary_key=True,
    )
