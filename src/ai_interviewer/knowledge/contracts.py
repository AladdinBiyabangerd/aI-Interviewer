"""Canonical interview-knowledge contracts with explicit provenance and rights."""

from __future__ import annotations

import re
from datetime import datetime
from typing import Annotated, Literal, Self

from pydantic import AfterValidator, Field, StringConstraints, field_validator, model_validator

from ai_interviewer.candidate_inputs.models import InterviewRound, RoleFamily, Seniority
from ai_interviewer.model_gateway import StrictModelOutput

EvidenceLayer = Literal[
    "company_official",
    "company_public",
    "user_report",
    "job_description",
    "role_pattern",
    "industry_pattern",
    "cv_claim",
]
SourceType = Literal[
    "official_site",
    "careers_page",
    "job_description",
    "engineering_blog",
    "conference_material",
    "public_interview_report",
    "user_interview_report",
    "role_taxonomy",
    "industry_taxonomy",
    "candidate_cv",
]
RightsStatus = Literal[
    "permitted_full",
    "permitted_derived",
    "metadata_only",
    "pending",
    "prohibited",
    "withdrawn",
]
Difficulty = Literal["foundation", "medium", "advanced"]
Specificity = Literal["high", "medium", "limited"]


def _validate_clean_text(value: str) -> str:
    if value != value.strip() or any(ord(character) < 32 for character in value):
        raise ValueError("knowledge text must be trimmed and contain no control characters")
    return value


Identifier = Annotated[str, StringConstraints(pattern=r"^[a-z][a-z0-9_]{0,95}$")]
ShortText = Annotated[
    str,
    StringConstraints(min_length=1, max_length=240),
    AfterValidator(_validate_clean_text),
]
LongText = Annotated[
    str,
    StringConstraints(min_length=1, max_length=1_000),
    AfterValidator(_validate_clean_text),
]
Sha256Digest = Annotated[str, StringConstraints(pattern=r"^[a-f0-9]{64}$")]
HttpsUrl = Annotated[str, StringConstraints(pattern=r"^https://[^\s]{1,2039}$")]


class KnowledgeSource(StrictModelOutput):
    """One source snapshot. Public visibility does not imply reuse permission."""

    source_id: Identifier
    source_type: SourceType
    source_url: HttpsUrl | None = None
    rights_status: RightsStatus
    policy_version: Identifier
    retrieved_at: datetime
    published_at: datetime | None = None
    content_sha256: Sha256Digest
    source_trust: float = Field(ge=0.0, le=1.0)
    independent_group: Identifier

    @model_validator(mode="after")
    def validate_dates(self) -> Self:
        if self.published_at is not None and self.published_at > self.retrieved_at:
            raise ValueError("source publication date cannot be after retrieval")
        return self

    @property
    def permits_derived_facts(self) -> bool:
        return self.rights_status in {"permitted_full", "permitted_derived"}


class EvidenceSignal(StrictModelOutput):
    """A normalized signal, not a copied interview question."""

    evidence_id: Identifier
    layer: EvidenceLayer
    competency_key: Identifier
    signal: LongText
    sources: tuple[KnowledgeSource, ...] = Field(min_length=1, max_length=50)
    confidence: float = Field(ge=0.0, le=1.0)
    frequency: int = Field(default=1, ge=1, le=100_000)
    company_name: ShortText | None = None
    role_family: RoleFamily | None = None
    seniority: Seniority | None = None
    interview_round: InterviewRound | None = None
    industry: ShortText | None = None

    @model_validator(mode="after")
    def validate_provenance(self) -> Self:
        source_ids = [source.source_id for source in self.sources]
        if len(source_ids) != len(set(source_ids)):
            raise ValueError("evidence sources must be unique")
        if self.layer.startswith("company_") and self.company_name is None:
            raise ValueError("company evidence must identify the company")
        if self.layer == "industry_pattern" and self.industry is None:
            raise ValueError("industry evidence must identify the industry")
        return self

    @property
    def eligible_sources(self) -> tuple[KnowledgeSource, ...]:
        return tuple(source for source in self.sources if source.permits_derived_facts)

    @property
    def independent_source_count(self) -> int:
        return len({source.independent_group for source in self.eligible_sources})


class CompetencyNode(StrictModelOutput):
    """Reusable competency with aliases used to activate it from JD/CV claims."""

    key: Identifier
    label: ShortText
    aliases: tuple[ShortText, ...] = Field(min_length=1, max_length=30)
    subtopics: tuple[Identifier, ...] = Field(default=(), max_length=40)
    default_weight: float = Field(gt=0.0, le=1.0)

    @model_validator(mode="after")
    def validate_unique_terms(self) -> Self:
        aliases = [alias.casefold() for alias in self.aliases]
        if len(aliases) != len(set(aliases)) or len(self.subtopics) != len(set(self.subtopics)):
            raise ValueError("competency aliases and subtopics must be unique")
        return self


class RoleCompetencyGraph(StrictModelOutput):
    """Versioned role-family graph used when company evidence is sparse."""

    graph_id: Identifier
    graph_version: Identifier
    role_family: RoleFamily
    nodes: tuple[CompetencyNode, ...] = Field(min_length=1, max_length=100)

    @model_validator(mode="after")
    def validate_unique_nodes(self) -> Self:
        keys = [node.key for node in self.nodes]
        if len(keys) != len(set(keys)):
            raise ValueError("competency graph node keys must be unique")
        return self


class QuestionConcept(StrictModelOutput):
    """Question intent and probes, deliberately separated from rendered wording."""

    concept_id: Identifier
    role_families: tuple[RoleFamily, ...] = Field(min_length=1, max_length=10)
    competency_key: Identifier
    subtopic: Identifier
    seniorities: tuple[Seniority, ...] = Field(min_length=1, max_length=12)
    interview_rounds: tuple[InterviewRound, ...] = Field(min_length=1, max_length=12)
    difficulty: Difficulty
    question_intent: LongText
    possible_probes: tuple[ShortText, ...] = Field(min_length=1, max_length=20)

    @model_validator(mode="after")
    def validate_unique_mappings(self) -> Self:
        collections = (self.role_families, self.seniorities, self.interview_rounds)
        if any(len(values) != len(set(values)) for values in collections):
            raise ValueError("question concept mappings must be unique")
        probes = [probe.casefold() for probe in self.possible_probes]
        if len(probes) != len(set(probes)):
            raise ValueError("question concept probes must be unique")
        return self


class FingerprintDistribution(StrictModelOutput):
    competency_key: Identifier
    share: float = Field(gt=0.0, le=1.0)


class CompanyInterviewFingerprint(StrictModelOutput):
    """Evidence-derived company/role/round distribution; never a free-form LLM guess."""

    company_name: ShortText
    role_family: RoleFamily
    seniority: Seniority
    country_code: str
    interview_round: InterviewRound
    competency_distribution: tuple[FingerprintDistribution, ...] = Field(
        min_length=1, max_length=100
    )
    evidence_ids: tuple[Identifier, ...] = Field(min_length=1, max_length=10_000)
    evidence_count: int = Field(ge=1)
    independent_source_count: int = Field(ge=1)
    specificity: Specificity

    @field_validator("country_code")
    @classmethod
    def validate_country_code(cls, value: str) -> str:
        if re.fullmatch(r"[A-Z]{2}", value) is None:
            raise ValueError("country code must be ISO alpha-2 uppercase")
        return value

    @model_validator(mode="after")
    def validate_derived_shape(self) -> Self:
        keys = [item.competency_key for item in self.competency_distribution]
        if len(keys) != len(set(keys)):
            raise ValueError("fingerprint competencies must be unique")
        if abs(sum(item.share for item in self.competency_distribution) - 1.0) > 0.001:
            raise ValueError("fingerprint competency shares must sum to one")
        if self.evidence_count < len(self.evidence_ids):
            raise ValueError("fingerprint evidence count cannot be smaller than its evidence IDs")
        if self.specificity == "high" and self.independent_source_count < 2:
            raise ValueError("high specificity requires corroboration")
        return self
