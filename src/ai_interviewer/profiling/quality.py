"""Deterministic, content-safe quality gate for labeled CV/JD profile results."""

from __future__ import annotations

import hashlib
import json
from collections import Counter, defaultdict
from collections.abc import Sequence
from datetime import datetime
from pathlib import Path
from typing import Annotated, Literal, Self

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    model_validator,
)

from ai_interviewer.candidate_inputs.document_models import CandidateDocumentType
from ai_interviewer.candidate_inputs.source_text_models import MAX_SOURCE_TEXT_CHARACTERS
from ai_interviewer.model_gateway import ModelReleaseIdentity
from ai_interviewer.profiling.contracts import (
    CvProfileOutput,
    EvidenceLinkedClaim,
    JobDescriptionProfileOutput,
)
from ai_interviewer.profiling.evidence import ProfileEvidenceError, validate_profile_evidence
from ai_interviewer.profiling.prompts import candidate_profile_prompt

QUALITY_CONTRACT_VERSION = "1b-d-v1"
QUALITY_POLICY_VERSION = "1.0.0"
MAX_QUALITY_EVIDENCE_BYTES = 32 * 1024 * 1024

MIN_QUALITY_FIXTURES = 40
MIN_PRIMARY_SLICE_FIXTURES = 8
MIN_RISK_SLICE_FIXTURES = 4
MIN_FIELD_GOLD_CLAIMS = 4
MIN_OVERALL_PRECISION = 0.90
MIN_OVERALL_RECALL = 0.85
MIN_FIELD_PRECISION = 0.80
MIN_FIELD_RECALL = 0.75
MIN_SLICE_PRECISION = 0.85
MIN_SLICE_RECALL = 0.80
MIN_PREDICTION_SUCCESS_RATE = 0.95
MIN_SOURCE_SPAN_COVERAGE = 1.0
MIN_OWNER_REVIEW_COVERAGE = 1.0
MAX_OWNER_CORRECTION_RATE = 0.15

QualityField = Literal[
    "languages",
    "cv_skills",
    "cv_projects",
    "cv_responsibilities",
    "cv_claims",
    "cv_seniority_hints",
    "jd_must_have",
    "jd_nice_to_have",
    "jd_responsibilities",
    "jd_seniority_hints",
]
RiskSlice = Literal[
    "standard",
    "prompt_injection",
    "unsupported_claim",
    "unicode",
    "sparse",
]
LanguageSlice = Literal["az", "en", "mixed"]
OwnerReviewOutcome = Literal["accepted", "corrected", "rejected", "not_reviewed"]
QualityFailureCode = Literal[
    "rate_limited",
    "provider_timeout",
    "provider_unavailable",
    "provider_rejected",
    "provider_failure",
    "model_identity_mismatch",
    "invalid_output",
    "output_too_large",
    "incomplete_output",
    "content_filtered",
    "not_executed",
]
QualityBlockReason = Literal[
    "fixture_count_below_minimum",
    "language_document_slice_below_minimum",
    "risk_slice_below_minimum",
    "field_support_below_minimum",
    "overall_precision_below_threshold",
    "overall_recall_below_threshold",
    "field_precision_below_threshold",
    "field_recall_below_threshold",
    "slice_precision_below_threshold",
    "slice_recall_below_threshold",
    "source_span_coverage_below_threshold",
    "prediction_success_below_threshold",
    "owner_review_incomplete",
    "correction_rate_above_threshold",
    "prompt_contract_mismatch",
]
ApprovalBlockReason = Literal[
    "evaluation_not_eligible",
    "approval_evidence_mismatch",
    "approval_model_mismatch",
    "approval_policy_mismatch",
    "required_approval_missing",
]
ApprovalRole = Literal["product", "engineering", "language_az", "language_en"]

_QUALITY_FIELDS: tuple[QualityField, ...] = (
    "languages",
    "cv_skills",
    "cv_projects",
    "cv_responsibilities",
    "cv_claims",
    "cv_seniority_hints",
    "jd_must_have",
    "jd_nice_to_have",
    "jd_responsibilities",
    "jd_seniority_hints",
)
_REQUIRED_RISK_SLICES: tuple[RiskSlice, ...] = (
    "prompt_injection",
    "unsupported_claim",
)
_REQUIRED_APPROVAL_ROLES: tuple[ApprovalRole, ...] = (
    "product",
    "engineering",
    "language_az",
    "language_en",
)

SafeIdentifier = Annotated[
    str,
    StringConstraints(pattern=r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,127}$"),
]
ClaimIdentifier = Annotated[
    str,
    StringConstraints(pattern=r"^[a-z][a-z0-9_]{0,63}$"),
]
Sha256Digest = Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{64}$")]
SourceText = Annotated[str, StringConstraints(min_length=1, max_length=MAX_SOURCE_TEXT_CHARACTERS)]


class _StrictQualityModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    def __repr_args__(self) -> list[tuple[str, object]]:
        """Keep labeled source and profile content out of representations."""
        return []


CandidateQualityProfile = Annotated[
    CvProfileOutput | JobDescriptionProfileOutput,
    Field(discriminator="document_type"),
]


class QualityProvenance(_StrictQualityModel):
    source_kind: Literal["synthetic", "redacted_consented", "licensed"]
    rights_reference: SafeIdentifier
    repository_safe: bool

    @model_validator(mode="after")
    def validate_repository_safety(self) -> Self:
        if self.repository_safe and self.source_kind != "synthetic":
            raise ValueError("only synthetic fixtures may be marked repository safe")
        return self


class SuccessfulQualityPrediction(_StrictQualityModel):
    result_type: Literal["profile"]
    attempts: int = Field(ge=1, le=5)
    profile: CandidateQualityProfile


class FailedQualityPrediction(_StrictQualityModel):
    result_type: Literal["failure"]
    attempts: int = Field(ge=0, le=5)
    failure_code: QualityFailureCode


QualityPrediction = Annotated[
    SuccessfulQualityPrediction | FailedQualityPrediction,
    Field(discriminator="result_type"),
]


class ClaimAdjudication(_StrictQualityModel):
    field: QualityField
    expected_claim_id: ClaimIdentifier | None = None
    predicted_claim_id: ClaimIdentifier | None = None

    @model_validator(mode="after")
    def require_one_side(self) -> Self:
        if self.expected_claim_id is None and self.predicted_claim_id is None:
            raise ValueError("claim adjudication must reference an expected or predicted claim")
        return self


def _profile_claim_fields(profile: CandidateQualityProfile) -> dict[str, QualityField]:
    if isinstance(profile, CvProfileOutput):
        groups: tuple[tuple[QualityField, Sequence[EvidenceLinkedClaim]], ...] = (
            ("cv_skills", profile.skills),
            ("cv_projects", profile.projects),
            ("cv_responsibilities", profile.responsibilities),
            ("cv_claims", profile.claims),
            ("cv_seniority_hints", profile.seniority_hints),
        )
    else:
        groups = (
            ("jd_must_have", profile.must_have),
            ("jd_nice_to_have", profile.nice_to_have),
            ("jd_responsibilities", profile.responsibilities),
            ("jd_seniority_hints", profile.seniority_hints),
        )
    return {claim.claim_id: field_name for field_name, claims in groups for claim in claims}


class LabeledProfileFixture(_StrictQualityModel):
    fixture_id: SafeIdentifier
    language_slice: LanguageSlice
    document_type: CandidateDocumentType
    risk_slices: tuple[RiskSlice, ...] = Field(min_length=1, max_length=5)
    provenance: QualityProvenance
    source_text: SourceText
    expected_profile: CandidateQualityProfile
    prediction: QualityPrediction
    adjudications: tuple[ClaimAdjudication, ...] = Field(min_length=1, max_length=720)
    owner_review_outcome: OwnerReviewOutcome

    @model_validator(mode="after")
    def validate_fixture_contract(self) -> Self:
        if len(self.risk_slices) != len(set(self.risk_slices)):
            raise ValueError("fixture risk slices must be unique")
        expected_languages = set(self.expected_profile.languages)
        required_languages = {
            "az": {"az"},
            "en": {"en"},
            "mixed": {"az", "en"},
        }[self.language_slice]
        if expected_languages != required_languages:
            raise ValueError("fixture language slice must match expected profile languages")
        if self.expected_profile.document_type != self.document_type:
            raise ValueError("expected profile document type must match fixture")
        try:
            validate_profile_evidence(
                self.expected_profile,
                self.source_text,
                self.document_type,
            )
        except ProfileEvidenceError as exc:
            raise ValueError("expected profile evidence must match fixture source") from exc

        predicted_profile = (
            self.prediction.profile
            if isinstance(self.prediction, SuccessfulQualityPrediction)
            else None
        )
        if predicted_profile is not None and predicted_profile.document_type != self.document_type:
            raise ValueError("predicted profile document type must match fixture")

        expected_fields = _profile_claim_fields(self.expected_profile)
        predicted_fields = (
            _profile_claim_fields(predicted_profile) if predicted_profile is not None else {}
        )
        seen_expected: set[str] = set()
        seen_predicted: set[str] = set()
        for adjudication in self.adjudications:
            if adjudication.field == "languages":
                raise ValueError("languages are evaluated automatically, not adjudicated")
            if adjudication.expected_claim_id is not None:
                expected_field = expected_fields.get(adjudication.expected_claim_id)
                if expected_field != adjudication.field:
                    raise ValueError("adjudication expected claim field is inconsistent")
                if adjudication.expected_claim_id in seen_expected:
                    raise ValueError("expected claim may be adjudicated only once")
                seen_expected.add(adjudication.expected_claim_id)
            if adjudication.predicted_claim_id is not None:
                predicted_field = predicted_fields.get(adjudication.predicted_claim_id)
                if predicted_field != adjudication.field:
                    raise ValueError("adjudication predicted claim field is inconsistent")
                if adjudication.predicted_claim_id in seen_predicted:
                    raise ValueError("predicted claim may be adjudicated only once")
                seen_predicted.add(adjudication.predicted_claim_id)
        if seen_expected != set(expected_fields):
            raise ValueError("every expected claim must be adjudicated exactly once")
        if seen_predicted != set(predicted_fields):
            raise ValueError("every predicted claim must be adjudicated exactly once")
        return self


class ProfileQualityEvidence(_StrictQualityModel):
    schema_version: Literal[1]
    contract_version: Literal["1b-d-v1"]
    policy_version: Literal["1.0.0"]
    dataset_id: SafeIdentifier
    dataset_version: SafeIdentifier
    prompt_contract_sha256: Sha256Digest
    model_release: ModelReleaseIdentity
    fixtures: tuple[LabeledProfileFixture, ...] = Field(min_length=1, max_length=10_000)

    @model_validator(mode="after")
    def validate_unique_fixtures(self) -> Self:
        fixture_ids = [fixture.fixture_id for fixture in self.fixtures]
        if len(fixture_ids) != len(set(fixture_ids)):
            raise ValueError("quality fixture IDs must be unique")
        return self


class MetricCounts(_StrictQualityModel):
    true_positive: int = Field(ge=0)
    false_positive: int = Field(ge=0)
    false_negative: int = Field(ge=0)
    precision: float | None = Field(default=None, ge=0, le=1)
    recall: float | None = Field(default=None, ge=0, le=1)


class NamedMetric(_StrictQualityModel):
    name: str
    fixture_count: int = Field(ge=0)
    metrics: MetricCounts


class FailureCount(_StrictQualityModel):
    failure_code: QualityFailureCode
    count: int = Field(ge=1)


class ProfileQualitySummary(_StrictQualityModel):
    schema_version: Literal[1] = 1
    contract_version: Literal["1b-d-v1"] = "1b-d-v1"
    policy_version: Literal["1.0.0"] = "1.0.0"
    status: Literal["eligible_for_approval", "blocked"]
    dataset_id: SafeIdentifier
    dataset_version: SafeIdentifier
    evidence_sha256: Sha256Digest
    model_release: ModelReleaseIdentity
    fixture_count: int = Field(ge=1)
    overall: MetricCounts
    fields: tuple[NamedMetric, ...]
    language_document_slices: tuple[NamedMetric, ...]
    risk_slices: tuple[NamedMetric, ...]
    prediction_success_rate: float = Field(ge=0, le=1)
    source_span_coverage: float | None = Field(default=None, ge=0, le=1)
    owner_review_coverage: float = Field(ge=0, le=1)
    owner_correction_rate: float | None = Field(default=None, ge=0, le=1)
    failure_counts: tuple[FailureCount, ...]
    reasons: tuple[QualityBlockReason, ...]


class QualityApprovalDecision(_StrictQualityModel):
    role: ApprovalRole
    reviewer_id: SafeIdentifier
    approved_at: datetime
    decision: Literal["approved"]


class ProfileQualityApproval(_StrictQualityModel):
    schema_version: Literal[1]
    contract_version: Literal["1b-d-v1"]
    policy_version: str
    evidence_sha256: Sha256Digest
    model_release: ModelReleaseIdentity
    approvals: tuple[QualityApprovalDecision, ...] = Field(min_length=1, max_length=8)

    @model_validator(mode="after")
    def validate_unique_approval_roles(self) -> Self:
        roles = [approval.role for approval in self.approvals]
        if len(roles) != len(set(roles)):
            raise ValueError("quality approval roles must be unique")
        return self


class ProfileQualityGateDecision(_StrictQualityModel):
    status: Literal["approved", "blocked"]
    evaluation: ProfileQualitySummary
    approval_roles: tuple[ApprovalRole, ...]
    reasons: tuple[ApprovalBlockReason, ...]


def profile_quality_prompt_contract_sha256() -> str:
    """Bind quality evidence to both current code-owned prompt/schema releases."""
    contracts = []
    for document_type in ("cv", "job_description"):
        prompt = candidate_profile_prompt(document_type)
        contracts.append(
            {
                "document_type": document_type,
                "prompt_release": prompt.prompt_release.model_dump(mode="json"),
                "instructions_sha256": prompt.instructions_sha256,
                "output_schema_sha256": prompt.output_schema_sha256,
            }
        )
    payload = json.dumps(contracts, separators=(",", ":"), sort_keys=True).encode()
    return hashlib.sha256(payload).hexdigest()


def profile_quality_evidence_sha256(evidence: ProfileQualityEvidence) -> str:
    """Return the canonical digest used by separate human approval records."""
    payload = json.dumps(
        evidence.model_dump(mode="json"),
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _counts(true_positive: int, false_positive: int, false_negative: int) -> MetricCounts:
    precision_denominator = true_positive + false_positive
    recall_denominator = true_positive + false_negative
    return MetricCounts(
        true_positive=true_positive,
        false_positive=false_positive,
        false_negative=false_negative,
        precision=(true_positive / precision_denominator if precision_denominator else None),
        recall=(true_positive / recall_denominator if recall_denominator else None),
    )


def _fixture_counts(fixture: LabeledProfileFixture) -> dict[QualityField, Counter[str]]:
    result = {field_name: Counter[str]() for field_name in _QUALITY_FIELDS}
    predicted_languages = (
        set(fixture.prediction.profile.languages)
        if isinstance(fixture.prediction, SuccessfulQualityPrediction)
        else set()
    )
    expected_languages = set(fixture.expected_profile.languages)
    result["languages"]["tp"] = len(expected_languages & predicted_languages)
    result["languages"]["fp"] = len(predicted_languages - expected_languages)
    result["languages"]["fn"] = len(expected_languages - predicted_languages)
    for adjudication in fixture.adjudications:
        if (
            adjudication.expected_claim_id is not None
            and adjudication.predicted_claim_id is not None
        ):
            result[adjudication.field]["tp"] += 1
        elif adjudication.expected_claim_id is not None:
            result[adjudication.field]["fn"] += 1
        else:
            result[adjudication.field]["fp"] += 1
    return result


def _merge_counts(
    target: dict[QualityField, Counter[str]],
    addition: dict[QualityField, Counter[str]],
) -> None:
    for field_name in _QUALITY_FIELDS:
        target[field_name].update(addition[field_name])


def _aggregate_metric(counts: dict[QualityField, Counter[str]]) -> MetricCounts:
    return _counts(
        sum(field_counts["tp"] for field_counts in counts.values()),
        sum(field_counts["fp"] for field_counts in counts.values()),
        sum(field_counts["fn"] for field_counts in counts.values()),
    )


def _named_metric(
    name: str,
    fixtures: tuple[LabeledProfileFixture, ...],
) -> NamedMetric:
    counts = {field_name: Counter[str]() for field_name in _QUALITY_FIELDS}
    for fixture in fixtures:
        _merge_counts(counts, _fixture_counts(fixture))
    return NamedMetric(name=name, fixture_count=len(fixtures), metrics=_aggregate_metric(counts))


def _below(value: float | None, threshold: float) -> bool:
    return value is None or value < threshold


def _prediction_evidence_counts(fixture: LabeledProfileFixture) -> tuple[int, int]:
    if not isinstance(fixture.prediction, SuccessfulQualityPrediction):
        return (0, 0)
    total = 0
    valid = 0
    for claim in fixture.prediction.profile.evidence_claims():
        for span in claim.evidence:
            total += 1
            if (
                span.end <= len(fixture.source_text)
                and fixture.source_text[span.start : span.end] == span.quote
            ):
                valid += 1
    return (valid, total)


def evaluate_profile_quality(evidence: ProfileQualityEvidence) -> ProfileQualitySummary:
    """Calculate deterministic metrics and block on every fixed release threshold."""
    field_counts = {field_name: Counter[str]() for field_name in _QUALITY_FIELDS}
    fixture_counts: dict[str, int] = defaultdict(int)
    failure_counts: Counter[QualityFailureCode] = Counter()
    successful_predictions = 0
    valid_spans = 0
    total_spans = 0
    reviewed = 0
    corrected_or_rejected = 0

    for fixture in evidence.fixtures:
        _merge_counts(field_counts, _fixture_counts(fixture))
        fixture_counts[f"{fixture.language_slice}:{fixture.document_type}"] += 1
        for risk_slice in fixture.risk_slices:
            fixture_counts[f"risk:{risk_slice}"] += 1
        if isinstance(fixture.prediction, SuccessfulQualityPrediction):
            successful_predictions += 1
        else:
            failure_counts[fixture.prediction.failure_code] += 1
        fixture_valid_spans, fixture_total_spans = _prediction_evidence_counts(fixture)
        valid_spans += fixture_valid_spans
        total_spans += fixture_total_spans
        if fixture.owner_review_outcome != "not_reviewed":
            reviewed += 1
            if fixture.owner_review_outcome in {"corrected", "rejected"}:
                corrected_or_rejected += 1

    overall = _aggregate_metric(field_counts)
    fields = tuple(
        NamedMetric(
            name=field_name,
            fixture_count=len(evidence.fixtures),
            metrics=_counts(
                field_counts[field_name]["tp"],
                field_counts[field_name]["fp"],
                field_counts[field_name]["fn"],
            ),
        )
        for field_name in _QUALITY_FIELDS
    )
    primary_slices = tuple(
        _named_metric(
            f"{language}:{document_type}",
            tuple(
                fixture
                for fixture in evidence.fixtures
                if fixture.language_slice == language and fixture.document_type == document_type
            ),
        )
        for language in ("az", "en")
        for document_type in ("cv", "job_description")
    )
    risk_slices = tuple(
        _named_metric(
            risk_slice,
            tuple(fixture for fixture in evidence.fixtures if risk_slice in fixture.risk_slices),
        )
        for risk_slice in _REQUIRED_RISK_SLICES
    )

    fixture_count = len(evidence.fixtures)
    prediction_success_rate = successful_predictions / fixture_count
    source_span_coverage = valid_spans / total_spans if total_spans else None
    owner_review_coverage = reviewed / fixture_count
    owner_correction_rate = corrected_or_rejected / reviewed if reviewed else None
    reasons: list[QualityBlockReason] = []
    if fixture_count < MIN_QUALITY_FIXTURES:
        reasons.append("fixture_count_below_minimum")
    if any(metric.fixture_count < MIN_PRIMARY_SLICE_FIXTURES for metric in primary_slices):
        reasons.append("language_document_slice_below_minimum")
    if any(metric.fixture_count < MIN_RISK_SLICE_FIXTURES for metric in risk_slices):
        reasons.append("risk_slice_below_minimum")
    if any(
        metric.metrics.true_positive + metric.metrics.false_negative < MIN_FIELD_GOLD_CLAIMS
        for metric in fields
    ):
        reasons.append("field_support_below_minimum")
    if _below(overall.precision, MIN_OVERALL_PRECISION):
        reasons.append("overall_precision_below_threshold")
    if _below(overall.recall, MIN_OVERALL_RECALL):
        reasons.append("overall_recall_below_threshold")
    supported_fields = tuple(
        metric
        for metric in fields
        if metric.metrics.true_positive + metric.metrics.false_negative >= MIN_FIELD_GOLD_CLAIMS
    )
    if any(_below(metric.metrics.precision, MIN_FIELD_PRECISION) for metric in supported_fields):
        reasons.append("field_precision_below_threshold")
    if any(_below(metric.metrics.recall, MIN_FIELD_RECALL) for metric in supported_fields):
        reasons.append("field_recall_below_threshold")
    sufficiently_populated_slices = tuple(
        metric
        for metric in (*primary_slices, *risk_slices)
        if metric.fixture_count
        >= (
            MIN_RISK_SLICE_FIXTURES
            if metric.name in _REQUIRED_RISK_SLICES
            else MIN_PRIMARY_SLICE_FIXTURES
        )
    )
    if any(
        _below(metric.metrics.precision, MIN_SLICE_PRECISION)
        for metric in sufficiently_populated_slices
    ):
        reasons.append("slice_precision_below_threshold")
    if any(
        _below(metric.metrics.recall, MIN_SLICE_RECALL) for metric in sufficiently_populated_slices
    ):
        reasons.append("slice_recall_below_threshold")
    if _below(source_span_coverage, MIN_SOURCE_SPAN_COVERAGE):
        reasons.append("source_span_coverage_below_threshold")
    if prediction_success_rate < MIN_PREDICTION_SUCCESS_RATE:
        reasons.append("prediction_success_below_threshold")
    if owner_review_coverage < MIN_OWNER_REVIEW_COVERAGE:
        reasons.append("owner_review_incomplete")
    if owner_correction_rate is None or owner_correction_rate > MAX_OWNER_CORRECTION_RATE:
        reasons.append("correction_rate_above_threshold")
    if evidence.prompt_contract_sha256 != profile_quality_prompt_contract_sha256():
        reasons.append("prompt_contract_mismatch")

    return ProfileQualitySummary(
        status="eligible_for_approval" if not reasons else "blocked",
        dataset_id=evidence.dataset_id,
        dataset_version=evidence.dataset_version,
        evidence_sha256=profile_quality_evidence_sha256(evidence),
        model_release=evidence.model_release,
        fixture_count=fixture_count,
        overall=overall,
        fields=fields,
        language_document_slices=primary_slices,
        risk_slices=risk_slices,
        prediction_success_rate=prediction_success_rate,
        source_span_coverage=source_span_coverage,
        owner_review_coverage=owner_review_coverage,
        owner_correction_rate=owner_correction_rate,
        failure_counts=tuple(
            FailureCount(failure_code=code, count=count)
            for code, count in sorted(failure_counts.items())
        ),
        reasons=tuple(reasons),
    )


def evaluate_profile_quality_gate(
    evidence: ProfileQualityEvidence,
    approval: ProfileQualityApproval,
) -> ProfileQualityGateDecision:
    """Require threshold eligibility plus four separately named human roles."""
    evaluation = evaluate_profile_quality(evidence)
    reasons: list[ApprovalBlockReason] = []
    if evaluation.status != "eligible_for_approval":
        reasons.append("evaluation_not_eligible")
    if approval.evidence_sha256 != evaluation.evidence_sha256:
        reasons.append("approval_evidence_mismatch")
    if approval.model_release != evidence.model_release:
        reasons.append("approval_model_mismatch")
    if approval.policy_version != QUALITY_POLICY_VERSION:
        reasons.append("approval_policy_mismatch")
    approval_roles = tuple(approval_item.role for approval_item in approval.approvals)
    if not set(_REQUIRED_APPROVAL_ROLES).issubset(approval_roles):
        reasons.append("required_approval_missing")
    return ProfileQualityGateDecision(
        status="approved" if not reasons else "blocked",
        evaluation=evaluation,
        approval_roles=approval_roles,
        reasons=tuple(reasons),
    )


def _load_bounded(path: Path, *, label: str) -> bytes:
    if not path.is_file():
        raise ValueError(f"{label} must be a regular file")
    with path.open("rb") as payload_file:
        payload = payload_file.read(MAX_QUALITY_EVIDENCE_BYTES + 1)
    if len(payload) > MAX_QUALITY_EVIDENCE_BYTES:
        raise ValueError(f"{label} exceeds the maximum size")
    return payload


def load_profile_quality_evidence(path: Path) -> ProfileQualityEvidence:
    """Load sensitive labeled evidence locally without logging path or content."""
    return ProfileQualityEvidence.model_validate_json(
        _load_bounded(path, label="profile quality evidence"),
        strict=True,
    )


def load_profile_quality_approval(path: Path) -> ProfileQualityApproval:
    """Load the separately distributed approval record."""
    return ProfileQualityApproval.model_validate_json(
        _load_bounded(path, label="profile quality approval"),
        strict=True,
    )
