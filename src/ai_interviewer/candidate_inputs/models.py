"""Relational candidate-preparation context introduced in Phase 1A-A."""

from datetime import datetime
from typing import Literal
from uuid import UUID

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID as PostgreSQLUUID
from sqlalchemy.orm import Mapped, mapped_column

from ai_interviewer.persistence.base import (
    PersistenceBase,
    TimestampMixin,
    UUIDPrimaryKeyMixin,
    VersionedRecordMixin,
)

RoleFamily = Literal[
    "software_engineering",
    "data_and_ai",
    "product",
    "design",
    "quality_assurance",
    "security",
    "cloud_and_devops",
    "business_and_operations",
    "other",
]
Seniority = Literal[
    "intern",
    "entry",
    "junior",
    "mid",
    "senior",
    "lead",
    "staff",
    "principal",
    "manager",
    "director",
    "executive",
    "other",
]
InterviewRound = Literal[
    "recruiter_screen",
    "hiring_manager",
    "technical_screen",
    "coding",
    "system_design",
    "behavioral",
    "case_study",
    "take_home_review",
    "panel",
    "final",
    "other",
]
InterviewLanguage = Literal["az", "en"]
PreparationStatus = Literal["draft", "archived"]

ROLE_FAMILIES = frozenset(
    {
        "software_engineering",
        "data_and_ai",
        "product",
        "design",
        "quality_assurance",
        "security",
        "cloud_and_devops",
        "business_and_operations",
        "other",
    }
)
SENIORITY_LEVELS = frozenset(
    {
        "intern",
        "entry",
        "junior",
        "mid",
        "senior",
        "lead",
        "staff",
        "principal",
        "manager",
        "director",
        "executive",
        "other",
    }
)
INTERVIEW_ROUNDS = frozenset(
    {
        "recruiter_screen",
        "hiring_manager",
        "technical_screen",
        "coding",
        "system_design",
        "behavioral",
        "case_study",
        "take_home_review",
        "panel",
        "final",
        "other",
    }
)
INTERVIEW_LANGUAGES = frozenset({"az", "en"})


class CandidatePreparation(
    UUIDPrimaryKeyMixin,
    TimestampMixin,
    VersionedRecordMixin,
    PersistenceBase,
):
    """One owner-controlled target interview context; no CV/JD content is stored here."""

    __tablename__ = "candidate_preparations"
    __table_args__ = (
        CheckConstraint("btrim(company_name) <> ''", name="company_name_nonempty"),
        CheckConstraint("btrim(role_title) <> ''", name="role_title_nonempty"),
        CheckConstraint(
            "role_family IN ('software_engineering', 'data_and_ai', 'product', 'design', "
            "'quality_assurance', 'security', 'cloud_and_devops', "
            "'business_and_operations', 'other')",
            name="role_family_allowed",
        ),
        CheckConstraint(
            "(role_family = 'other' AND role_family_other IS NOT NULL AND "
            "btrim(role_family_other) <> '') OR "
            "(role_family <> 'other' AND role_family_other IS NULL)",
            name="role_family_fallback_consistent",
        ),
        CheckConstraint(
            "seniority IN ('intern', 'entry', 'junior', 'mid', 'senior', 'lead', "
            "'staff', 'principal', 'manager', 'director', 'executive', 'other')",
            name="seniority_allowed",
        ),
        CheckConstraint(
            "(seniority = 'other' AND seniority_other IS NOT NULL AND "
            "btrim(seniority_other) <> '') OR "
            "(seniority <> 'other' AND seniority_other IS NULL)",
            name="seniority_fallback_consistent",
        ),
        CheckConstraint(
            "target_country_code ~ '^[A-Z]{2}$'",
            name="target_country_code_format",
        ),
        CheckConstraint(
            "target_office IS NULL OR btrim(target_office) <> ''",
            name="target_office_nonempty",
        ),
        CheckConstraint(
            "interview_round IN ('recruiter_screen', 'hiring_manager', "
            "'technical_screen', 'coding', 'system_design', 'behavioral', "
            "'case_study', 'take_home_review', 'panel', 'final', 'other')",
            name="interview_round_allowed",
        ),
        CheckConstraint(
            "(interview_round = 'other' AND interview_round_other IS NOT NULL AND "
            "btrim(interview_round_other) <> '') OR "
            "(interview_round <> 'other' AND interview_round_other IS NULL)",
            name="interview_round_fallback_consistent",
        ),
        CheckConstraint(
            "interview_language IN ('az', 'en')",
            name="interview_language_allowed",
        ),
        CheckConstraint("status IN ('draft', 'archived')", name="status_allowed"),
        CheckConstraint("version > 0", name="version_positive"),
        CheckConstraint("char_length(idempotency_key_hash) = 64", name="idempotency_digest_length"),
        CheckConstraint("retain_until > created_at", name="retention_after_creation"),
        CheckConstraint("retention_action = 'delete'", name="retention_action_delete_only"),
        UniqueConstraint(
            "owner_id",
            "idempotency_key_hash",
            name="uq_candidate_preparations_owner_idempotency",
        ),
        UniqueConstraint(
            "id",
            "owner_id",
            name="uq_candidate_preparations_id_owner",
        ),
        Index("ix_candidate_preparations_owner_id", "owner_id", "id"),
        Index("ix_candidate_preparations_retention", "retain_until"),
    )

    owner_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("accounts.id", ondelete="CASCADE"),
        nullable=False,
    )
    company_name: Mapped[str] = mapped_column(String(200), nullable=False)
    role_family: Mapped[RoleFamily] = mapped_column(String(32), nullable=False)
    role_family_other: Mapped[str | None] = mapped_column(String(100), nullable=True)
    role_title: Mapped[str] = mapped_column(String(200), nullable=False)
    seniority: Mapped[Seniority] = mapped_column(String(16), nullable=False)
    seniority_other: Mapped[str | None] = mapped_column(String(100), nullable=True)
    target_country_code: Mapped[str] = mapped_column(String(2), nullable=False)
    target_office: Mapped[str | None] = mapped_column(String(200), nullable=True)
    interview_round: Mapped[InterviewRound] = mapped_column(String(32), nullable=False)
    interview_round_other: Mapped[str | None] = mapped_column(String(100), nullable=True)
    interview_language: Mapped[InterviewLanguage] = mapped_column(String(8), nullable=False)
    status: Mapped[PreparationStatus] = mapped_column(
        String(16),
        default="draft",
        server_default="draft",
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
    idempotency_key_hash: Mapped[str] = mapped_column(String(64), nullable=False)
