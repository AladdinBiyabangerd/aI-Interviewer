"""Stable contracts for deterministic interview-question retrieval and coverage."""

from __future__ import annotations

from typing import Literal, Self

from pydantic import Field, model_validator

from ai_interviewer.candidate_inputs.models import (
    InterviewLanguage,
    InterviewRound,
    RoleFamily,
    Seniority,
)
from ai_interviewer.knowledge import EvidenceSignal, QuestionConcept
from ai_interviewer.model_gateway import StrictModelOutput
from ai_interviewer.profiling import CvProfileOutput, JobDescriptionProfileOutput

QuestionOrigin = Literal[
    "vacancy_driven",
    "role_derived",
    "industry_derived",
    "cv_probe",
    "company_supported",
]
LikelihoodLabel = Literal["high_likelihood", "strong_match", "worth_preparing"]
Specificity = Literal["high", "medium", "limited"]


class RankingWeights(StrictModelOutput):
    """Configurable scoring policy; fields deliberately mirror auditable score components."""

    vacancy_importance: float = Field(default=0.26, ge=0.0, le=1.0)
    role_relevance: float = Field(default=0.12, ge=0.0, le=1.0)
    company_evidence: float = Field(default=0.12, ge=0.0, le=1.0)
    round_relevance: float = Field(default=0.10, ge=0.0, le=1.0)
    seniority_relevance: float = Field(default=0.08, ge=0.0, le=1.0)
    industry_relevance: float = Field(default=0.08, ge=0.0, le=1.0)
    cv_relevance: float = Field(default=0.10, ge=0.0, le=1.0)
    source_confidence: float = Field(default=0.06, ge=0.0, le=1.0)
    frequency: float = Field(default=0.03, ge=0.0, le=1.0)
    recency: float = Field(default=0.02, ge=0.0, le=1.0)
    corroboration: float = Field(default=0.03, ge=0.0, le=1.0)

    @model_validator(mode="after")
    def validate_total(self) -> Self:
        if abs(sum(self.model_dump().values()) - 1.0) > 0.000_001:
            raise ValueError("ranking weights must sum to one")
        return self


class InterviewIntelligenceRequest(StrictModelOutput):
    company_name: str = Field(min_length=1, max_length=200)
    role_title: str = Field(min_length=1, max_length=200)
    role_family: RoleFamily
    seniority: Seniority
    interview_round: InterviewRound
    interview_language: InterviewLanguage
    country_code: str = Field(pattern=r"^[A-Z]{2}$")
    industry: str | None = Field(default=None, min_length=1, max_length=200)
    question_budget: int = Field(default=10, ge=5, le=50)
    jd_profile: JobDescriptionProfileOutput | None = None
    cv_profile: CvProfileOutput | None = None
    evidence: tuple[EvidenceSignal, ...] = Field(default=(), max_length=2_000)


class CompetencyActivation(StrictModelOutput):
    competency_key: str
    label: str
    target_share: float = Field(ge=0.0, le=1.0)
    jd_importance: float = Field(ge=0.0, le=1.0)
    industry_relevance: float = Field(default=0.0, ge=0.0, le=1.0)
    company_relevance: float = Field(default=0.0, ge=0.0, le=1.0)
    matched_jd_claim_ids: tuple[str, ...] = ()
    matched_cv_claim_ids: tuple[str, ...] = ()


class ScoreBreakdown(StrictModelOutput):
    vacancy_importance: float = Field(ge=0.0, le=1.0)
    role_relevance: float = Field(ge=0.0, le=1.0)
    company_evidence: float = Field(ge=0.0, le=1.0)
    round_relevance: float = Field(ge=0.0, le=1.0)
    seniority_relevance: float = Field(ge=0.0, le=1.0)
    industry_relevance: float = Field(ge=0.0, le=1.0)
    cv_relevance: float = Field(ge=0.0, le=1.0)
    source_confidence: float = Field(ge=0.0, le=1.0)
    frequency: float = Field(ge=0.0, le=1.0)
    recency: float = Field(ge=0.0, le=1.0)
    corroboration: float = Field(ge=0.0, le=1.0)


class RankedQuestionConcept(StrictModelOutput):
    concept: QuestionConcept
    score: float = Field(ge=0.0, le=1.0)
    score_breakdown: ScoreBreakdown
    origins: tuple[QuestionOrigin, ...] = Field(min_length=1, max_length=5)
    evidence_ids: tuple[str, ...] = ()
    likelihood: LikelihoodLabel
    rationale: str = Field(min_length=1, max_length=500)


class BlueprintMetrics(StrictModelOutput):
    question_jd_relevance: float = Field(ge=0.0, le=1.0)
    question_role_relevance: float = Field(ge=0.0, le=1.0)
    question_round_relevance: float = Field(ge=0.0, le=1.0)
    company_specificity_precision: float = Field(ge=0.0, le=1.0)
    question_diversity: float = Field(ge=0.0, le=1.0)
    duplicate_rate: float = Field(ge=0.0, le=1.0)
    retrieval_precision_at_budget: float = Field(ge=0.0, le=1.0)
    source_confidence: float = Field(ge=0.0, le=1.0)
    major_jd_competency_coverage: float = Field(ge=0.0, le=1.0)


class InterviewQuestionBlueprint(StrictModelOutput):
    questions: tuple[RankedQuestionConcept, ...] = Field(min_length=1, max_length=50)
    competency_plan: tuple[CompetencyActivation, ...] = Field(min_length=1, max_length=100)
    specificity: Specificity
    cold_start: bool
    fallback_path: tuple[str, ...] = Field(min_length=1, max_length=10)
    weights: RankingWeights
    metrics: BlueprintMetrics
    user_notice: str
