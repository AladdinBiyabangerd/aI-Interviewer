"""Strict evidence-linked CV and job-description profile contracts."""

from __future__ import annotations

import unicodedata
from typing import Annotated, Literal, Self

from pydantic import AfterValidator, Field, StringConstraints, model_validator

from ai_interviewer.candidate_inputs.document_models import CandidateDocumentType
from ai_interviewer.candidate_inputs.source_text_models import MAX_SOURCE_TEXT_CHARACTERS
from ai_interviewer.model_gateway import StrictModelOutput

MAX_EVIDENCE_QUOTE_CHARACTERS = 4_000
MAX_EVIDENCE_SPANS_PER_CLAIM = 5
CV_PROFILE_SCHEMA_ID = "cv-profile"
JOB_DESCRIPTION_PROFILE_SCHEMA_ID = "job-description-profile"
PROFILE_SCHEMA_VERSION = "1.0.0"

DocumentLanguage = Literal["az", "en"]
AssertionKind = Literal["explicit", "inferred"]
SkillCategory = Literal[
    "programming_language",
    "framework_library",
    "database",
    "cloud_platform",
    "devops_tooling",
    "data_ai",
    "security",
    "testing_quality",
    "architecture",
    "product_design",
    "methodology",
    "domain_knowledge",
    "soft_skill",
    "other",
]
CareerClaimType = Literal[
    "achievement",
    "employment",
    "education",
    "certification",
    "leadership",
    "domain_experience",
    "other",
]
RequirementCategory = Literal[
    "skill",
    "experience",
    "education",
    "certification",
    "language",
    "location",
    "domain_knowledge",
    "behavioral",
    "other",
]
ProfileSeniority = Literal[
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
]


def _validate_derived_text(value: str) -> str:
    if value != value.strip():
        raise ValueError("derived profile text must not have surrounding whitespace")
    if any(
        unicodedata.category(character) in {"Cc", "Cf", "Cs", "Zl", "Zp"} for character in value
    ):
        raise ValueError("derived profile text contains an unsafe Unicode character")
    return value


ClaimId = Annotated[
    str,
    StringConstraints(pattern=r"^[a-z][a-z0-9_]{0,63}$"),
]
ShortText = Annotated[
    str,
    StringConstraints(min_length=1, max_length=200),
    AfterValidator(_validate_derived_text),
]
LongText = Annotated[
    str,
    StringConstraints(min_length=1, max_length=1_000),
    AfterValidator(_validate_derived_text),
]
EvidenceQuote = Annotated[
    str,
    StringConstraints(min_length=1, max_length=MAX_EVIDENCE_QUOTE_CHARACTERS),
]


class SourceSpan(StrictModelOutput):
    """Python Unicode-code-point offsets and the exact source substring."""

    start: int = Field(ge=0, lt=MAX_SOURCE_TEXT_CHARACTERS)
    end: int = Field(gt=0, le=MAX_SOURCE_TEXT_CHARACTERS)
    quote: EvidenceQuote

    @model_validator(mode="after")
    def validate_span_shape(self) -> Self:
        if self.end <= self.start:
            raise ValueError("source span end must be greater than start")
        if self.end - self.start != len(self.quote):
            raise ValueError("source span length must equal quote length")
        return self


EvidenceSpans = Annotated[
    tuple[SourceSpan, ...],
    Field(min_length=1, max_length=MAX_EVIDENCE_SPANS_PER_CLAIM),
]
DocumentLanguages = Annotated[
    tuple[DocumentLanguage, ...],
    Field(min_length=1, max_length=2),
]


class EvidenceLinkedClaim(StrictModelOutput):
    """Shared shape for one model-derived assertion with mandatory evidence."""

    claim_id: ClaimId
    statement: LongText
    assertion_kind: AssertionKind
    evidence: EvidenceSpans

    @model_validator(mode="after")
    def validate_unique_evidence(self) -> Self:
        coordinates = [(span.start, span.end) for span in self.evidence]
        if len(coordinates) != len(set(coordinates)):
            raise ValueError("claim evidence spans must be unique")
        return self


class CvSkillClaim(EvidenceLinkedClaim):
    name: ShortText
    category: SkillCategory


class CvProjectClaim(EvidenceLinkedClaim):
    name: ShortText | None = None
    technologies: tuple[ShortText, ...] = Field(default=(), max_length=25)

    @model_validator(mode="after")
    def validate_unique_technologies(self) -> Self:
        normalized = [technology.casefold() for technology in self.technologies]
        if len(normalized) != len(set(normalized)):
            raise ValueError("project technologies must be unique")
        return self


class ResponsibilityClaim(EvidenceLinkedClaim):
    pass


class CareerClaim(EvidenceLinkedClaim):
    claim_type: CareerClaimType


class SeniorityHint(EvidenceLinkedClaim):
    seniority: ProfileSeniority


class JobRequirementClaim(EvidenceLinkedClaim):
    category: RequirementCategory


def _validate_profile(
    languages: DocumentLanguages,
    claims: tuple[EvidenceLinkedClaim, ...],
) -> None:
    if len(languages) != len(set(languages)):
        raise ValueError("profile languages must be unique")
    if not claims:
        raise ValueError("profile must contain at least one evidence-linked claim")
    claim_ids = [claim.claim_id for claim in claims]
    if len(claim_ids) != len(set(claim_ids)):
        raise ValueError("profile claim IDs must be unique")


class CvProfileOutput(StrictModelOutput):
    """Minimal CV-derived facts; direct contact/identity fields are intentionally absent."""

    document_type: Literal["cv"]
    languages: DocumentLanguages
    skills: tuple[CvSkillClaim, ...] = Field(default=(), max_length=100)
    projects: tuple[CvProjectClaim, ...] = Field(default=(), max_length=50)
    responsibilities: tuple[ResponsibilityClaim, ...] = Field(default=(), max_length=100)
    claims: tuple[CareerClaim, ...] = Field(default=(), max_length=100)
    seniority_hints: tuple[SeniorityHint, ...] = Field(default=(), max_length=10)

    def evidence_claims(self) -> tuple[EvidenceLinkedClaim, ...]:
        claims: list[EvidenceLinkedClaim] = []
        claims.extend(self.skills)
        claims.extend(self.projects)
        claims.extend(self.responsibilities)
        claims.extend(self.claims)
        claims.extend(self.seniority_hints)
        return tuple(claims)

    @model_validator(mode="after")
    def validate_profile_contract(self) -> Self:
        _validate_profile(self.languages, self.evidence_claims())
        skill_names = [skill.name.casefold() for skill in self.skills]
        if len(skill_names) != len(set(skill_names)):
            raise ValueError("CV skill names must be unique")
        return self


class JobDescriptionProfileOutput(StrictModelOutput):
    """JD requirements split by priority without unsupported company assertions."""

    document_type: Literal["job_description"]
    languages: DocumentLanguages
    must_have: tuple[JobRequirementClaim, ...] = Field(default=(), max_length=100)
    nice_to_have: tuple[JobRequirementClaim, ...] = Field(default=(), max_length=100)
    responsibilities: tuple[ResponsibilityClaim, ...] = Field(default=(), max_length=100)
    seniority_hints: tuple[SeniorityHint, ...] = Field(default=(), max_length=10)

    def evidence_claims(self) -> tuple[EvidenceLinkedClaim, ...]:
        claims: list[EvidenceLinkedClaim] = []
        claims.extend(self.must_have)
        claims.extend(self.nice_to_have)
        claims.extend(self.responsibilities)
        claims.extend(self.seniority_hints)
        return tuple(claims)

    @model_validator(mode="after")
    def validate_profile_contract(self) -> Self:
        _validate_profile(self.languages, self.evidence_claims())
        requirements = [*self.must_have, *self.nice_to_have]
        statements = [requirement.statement.casefold() for requirement in requirements]
        if len(statements) != len(set(statements)):
            raise ValueError("JD requirements must be unique across priority groups")
        return self


CandidateProfileOutput = CvProfileOutput | JobDescriptionProfileOutput


def profile_output_type(
    document_type: CandidateDocumentType,
) -> type[CvProfileOutput] | type[JobDescriptionProfileOutput]:
    """Select the one application-owned schema permitted for a document type."""
    if document_type == "cv":
        return CvProfileOutput
    if document_type == "job_description":
        return JobDescriptionProfileOutput
    raise ValueError("profile document type is not supported")
