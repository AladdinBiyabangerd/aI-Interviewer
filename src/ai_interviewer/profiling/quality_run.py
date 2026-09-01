"""Explicitly authorized offline prediction artifacts for the Phase 1B-D2 quality run."""

from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime
from pathlib import Path
from typing import Literal, Self, cast
from uuid import NAMESPACE_URL, UUID, uuid5

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator

from ai_interviewer.candidate_inputs.document_models import CandidateDocumentType
from ai_interviewer.model_gateway import (
    ModelGatewayError,
    ModelGatewayRuntime,
    ModelReleaseIdentity,
)
from ai_interviewer.profiling.contracts import CvProfileOutput, JobDescriptionProfileOutput
from ai_interviewer.profiling.evidence import ProfileEvidenceError, validate_profile_evidence
from ai_interviewer.profiling.prompts import candidate_profile_prompt
from ai_interviewer.profiling.quality import (
    CandidateQualityProfile,
    ClaimAdjudication,
    FailedQualityPrediction,
    LabeledProfileFixture,
    LanguageSlice,
    OwnerReviewOutcome,
    ProfileQualityEvidence,
    QualityFailureCode,
    QualityPrediction,
    QualityProvenance,
    RiskSlice,
    SafeIdentifier,
    Sha256Digest,
    SourceText,
    SuccessfulQualityPrediction,
    _load_bounded,
    profile_quality_prompt_contract_sha256,
)

MAX_QUALITY_PREDICTION_FIXTURES = 200
QualityRunStatus = Literal["completed"]


class _StrictQualityRunModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    def __repr_args__(self) -> list[tuple[str, object]]:
        """Keep source, gold labels, and predictions out of representations."""
        return []


class ProfileQualityCorpusFixture(_StrictQualityRunModel):
    fixture_id: SafeIdentifier
    language_slice: LanguageSlice
    document_type: CandidateDocumentType
    risk_slices: tuple[RiskSlice, ...] = Field(min_length=1, max_length=5)
    provenance: QualityProvenance
    source_text: SourceText
    expected_profile: CandidateQualityProfile

    @model_validator(mode="after")
    def validate_fixture_contract(self) -> Self:
        if len(self.risk_slices) != len(set(self.risk_slices)):
            raise ValueError("corpus fixture risk slices must be unique")
        expected_languages = set(self.expected_profile.languages)
        required_languages = {
            "az": {"az"},
            "en": {"en"},
            "mixed": {"az", "en"},
        }[self.language_slice]
        if expected_languages != required_languages:
            raise ValueError("corpus language slice must match expected profile languages")
        if self.expected_profile.document_type != self.document_type:
            raise ValueError("corpus expected profile document type must match fixture")
        try:
            validate_profile_evidence(
                self.expected_profile,
                self.source_text,
                self.document_type,
            )
        except ProfileEvidenceError as exc:
            raise ValueError("corpus expected evidence must match fixture source") from exc
        return self


class ProfileQualityCorpus(_StrictQualityRunModel):
    schema_version: Literal[1]
    contract_version: Literal["1b-d-v1"]
    policy_version: Literal["1.0.0"]
    dataset_id: SafeIdentifier
    dataset_version: SafeIdentifier
    prompt_contract_sha256: Sha256Digest
    fixtures: tuple[ProfileQualityCorpusFixture, ...] = Field(
        min_length=1,
        max_length=MAX_QUALITY_PREDICTION_FIXTURES,
    )

    @model_validator(mode="after")
    def validate_unique_fixtures(self) -> Self:
        fixture_ids = [fixture.fixture_id for fixture in self.fixtures]
        if len(fixture_ids) != len(set(fixture_ids)):
            raise ValueError("quality corpus fixture IDs must be unique")
        return self


class ProfileQualityRunAuthorization(_StrictQualityRunModel):
    schema_version: Literal[1]
    contract_version: Literal["1b-d-v1"]
    purpose: Literal["profile_quality_evaluation"]
    decision: Literal["approved"]
    dataset_id: SafeIdentifier
    dataset_version: SafeIdentifier
    corpus_sha256: Sha256Digest
    prompt_contract_sha256: Sha256Digest
    model_release: ModelReleaseIdentity
    processor_activity_reference: SafeIdentifier
    data_controls_reference: SafeIdentifier
    approver_id: SafeIdentifier
    approved_at: AwareDatetime
    expires_at: AwareDatetime

    @model_validator(mode="after")
    def validate_authorization(self) -> Self:
        if self.model_release.provider != "openai":
            raise ValueError("quality prediction authorization requires the OpenAI provider")
        if self.expires_at <= self.approved_at:
            raise ValueError("quality prediction authorization must expire after approval")
        return self


class ProfileQualityRunPreflight(_StrictQualityRunModel):
    """Payload-safe proof that the exact corpus authorization is currently active."""

    status: Literal["authorized"] = "authorized"
    dataset_id: SafeIdentifier
    dataset_version: SafeIdentifier
    corpus_sha256: Sha256Digest
    authorization_sha256: Sha256Digest
    prompt_contract_sha256: Sha256Digest
    model_release: ModelReleaseIdentity
    fixture_count: int = Field(ge=1, le=MAX_QUALITY_PREDICTION_FIXTURES)
    approved_at: AwareDatetime
    expires_at: AwareDatetime


class ProfileQualityPredictionRecord(_StrictQualityRunModel):
    fixture_id: SafeIdentifier
    document_type: CandidateDocumentType
    request_id: UUID
    prediction: QualityPrediction


class ProfileQualityPredictionRun(_StrictQualityRunModel):
    schema_version: Literal[1] = 1
    contract_version: Literal["1b-d-v1"] = "1b-d-v1"
    policy_version: Literal["1.0.0"] = "1.0.0"
    status: QualityRunStatus = "completed"
    dataset_id: SafeIdentifier
    dataset_version: SafeIdentifier
    corpus_sha256: Sha256Digest
    authorization_sha256: Sha256Digest
    prompt_contract_sha256: Sha256Digest
    model_release: ModelReleaseIdentity
    fixtures: tuple[ProfileQualityPredictionRecord, ...] = Field(
        min_length=1,
        max_length=MAX_QUALITY_PREDICTION_FIXTURES,
    )

    @model_validator(mode="after")
    def validate_unique_fixtures(self) -> Self:
        fixture_ids = [fixture.fixture_id for fixture in self.fixtures]
        request_ids = [fixture.request_id for fixture in self.fixtures]
        if len(fixture_ids) != len(set(fixture_ids)):
            raise ValueError("prediction run fixture IDs must be unique")
        if len(request_ids) != len(set(request_ids)):
            raise ValueError("prediction run request IDs must be unique")
        return self


class ProfileQualityReviewDraftFixture(_StrictQualityRunModel):
    fixture_id: SafeIdentifier
    language_slice: LanguageSlice
    document_type: CandidateDocumentType
    risk_slices: tuple[RiskSlice, ...] = Field(min_length=1, max_length=5)
    provenance: QualityProvenance
    source_text: SourceText
    expected_profile: CandidateQualityProfile
    prediction: QualityPrediction
    adjudications: tuple[ClaimAdjudication, ...] = Field(default=(), max_length=720)
    owner_review_outcome: OwnerReviewOutcome = "not_reviewed"


class ProfileQualityReviewDraft(_StrictQualityRunModel):
    schema_version: Literal[1] = 1
    contract_version: Literal["1b-d-v1"] = "1b-d-v1"
    policy_version: Literal["1.0.0"] = "1.0.0"
    dataset_id: SafeIdentifier
    dataset_version: SafeIdentifier
    prompt_contract_sha256: Sha256Digest
    model_release: ModelReleaseIdentity
    fixtures: tuple[ProfileQualityReviewDraftFixture, ...] = Field(
        min_length=1,
        max_length=MAX_QUALITY_PREDICTION_FIXTURES,
    )


def _artifact_sha256(artifact: BaseModel) -> str:
    payload = json.dumps(
        artifact.model_dump(mode="json"),
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def profile_quality_corpus_sha256(corpus: ProfileQualityCorpus) -> str:
    """Bind authorization and predictions to the complete labeled corpus."""
    return _artifact_sha256(corpus)


def profile_quality_run_authorization_sha256(
    authorization: ProfileQualityRunAuthorization,
) -> str:
    """Bind prediction output to the exact external-processing approval record."""
    return _artifact_sha256(authorization)


def profile_quality_prediction_run_sha256(run: ProfileQualityPredictionRun) -> str:
    """Return a content digest without exposing the sensitive prediction artifact."""
    return _artifact_sha256(run)


def _request_id(
    corpus: ProfileQualityCorpus,
    authorization: ProfileQualityRunAuthorization,
    fixture: ProfileQualityCorpusFixture,
) -> UUID:
    coordinate = "|".join(
        (
            "ai-interviewer-profile-quality",
            corpus.dataset_id,
            corpus.dataset_version,
            profile_quality_corpus_sha256(corpus),
            fixture.fixture_id,
            authorization.model_release.provider,
            authorization.model_release.model_id,
            authorization.model_release.model_version,
            authorization.prompt_contract_sha256,
        )
    )
    return uuid5(NAMESPACE_URL, coordinate)


def preflight_profile_quality_run(
    corpus: ProfileQualityCorpus,
    authorization: ProfileQualityRunAuthorization,
    *,
    now: datetime,
) -> ProfileQualityRunPreflight:
    """Validate corpus, prompt, digest, and approval window without contacting a provider."""
    current_prompt_digest = profile_quality_prompt_contract_sha256()
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("quality prediction clock must be timezone-aware")
    if corpus.prompt_contract_sha256 != current_prompt_digest:
        raise ValueError("quality corpus prompt contract does not match current code")
    if authorization.prompt_contract_sha256 != corpus.prompt_contract_sha256:
        raise ValueError("quality prediction authorization prompt contract mismatch")
    if (
        authorization.dataset_id != corpus.dataset_id
        or authorization.dataset_version != corpus.dataset_version
        or authorization.corpus_sha256 != profile_quality_corpus_sha256(corpus)
    ):
        raise ValueError("quality prediction authorization corpus mismatch")
    if authorization.approved_at > now or authorization.expires_at <= now:
        raise ValueError("quality prediction authorization is not currently active")
    return ProfileQualityRunPreflight(
        dataset_id=corpus.dataset_id,
        dataset_version=corpus.dataset_version,
        corpus_sha256=profile_quality_corpus_sha256(corpus),
        authorization_sha256=profile_quality_run_authorization_sha256(authorization),
        prompt_contract_sha256=current_prompt_digest,
        model_release=authorization.model_release,
        fixture_count=len(corpus.fixtures),
        approved_at=authorization.approved_at,
        expires_at=authorization.expires_at,
    )


def _validate_run_authorization(
    corpus: ProfileQualityCorpus,
    authorization: ProfileQualityRunAuthorization,
    gateway: ModelGatewayRuntime,
    now: datetime,
) -> None:
    preflight_profile_quality_run(corpus, authorization, now=now)
    if not gateway.enabled or gateway.model_release != authorization.model_release:
        raise ValueError("quality prediction gateway release mismatch")


async def generate_profile_quality_predictions(
    corpus: ProfileQualityCorpus,
    authorization: ProfileQualityRunAuthorization,
    gateway: ModelGatewayRuntime,
    *,
    now: datetime,
) -> ProfileQualityPredictionRun:
    """Run fixtures sequentially and retain only strict profiles or safe failures."""
    _validate_run_authorization(corpus, authorization, gateway, now)
    records: list[ProfileQualityPredictionRecord] = []
    for fixture in corpus.fixtures:
        prompt = candidate_profile_prompt(fixture.document_type)
        request_id = _request_id(corpus, authorization, fixture)
        try:
            result = await gateway.generate(
                prompt.request(fixture.source_text, request_id=request_id),
                prompt.output_type,
            )
        except ModelGatewayError as exc:
            prediction: QualityPrediction = FailedQualityPrediction(
                result_type="failure",
                attempts=exc.attempts,
                failure_code=cast(QualityFailureCode, exc.code),
            )
        else:
            output = result.output
            if not isinstance(output, (CvProfileOutput, JobDescriptionProfileOutput)):
                raise TypeError("quality prediction gateway returned an unsupported profile type")
            if (
                result.model_release != authorization.model_release
                or result.prompt_release != prompt.prompt_release
                or result.instructions_sha256 != prompt.instructions_sha256
                or result.output_schema_sha256 != prompt.output_schema_sha256
            ):
                raise ValueError("quality prediction result release contract mismatch")
            try:
                validate_profile_evidence(output, fixture.source_text, fixture.document_type)
            except ProfileEvidenceError:
                prediction = FailedQualityPrediction(
                    result_type="failure",
                    attempts=result.attempts,
                    failure_code="invalid_output",
                )
            else:
                prediction = SuccessfulQualityPrediction(
                    result_type="profile",
                    attempts=result.attempts,
                    profile=output,
                )
        records.append(
            ProfileQualityPredictionRecord(
                fixture_id=fixture.fixture_id,
                document_type=fixture.document_type,
                request_id=request_id,
                prediction=prediction,
            )
        )
    return ProfileQualityPredictionRun(
        dataset_id=corpus.dataset_id,
        dataset_version=corpus.dataset_version,
        corpus_sha256=profile_quality_corpus_sha256(corpus),
        authorization_sha256=profile_quality_run_authorization_sha256(authorization),
        prompt_contract_sha256=corpus.prompt_contract_sha256,
        model_release=authorization.model_release,
        fixtures=tuple(records),
    )


def prepare_profile_quality_review_draft(
    corpus: ProfileQualityCorpus,
    run: ProfileQualityPredictionRun,
) -> ProfileQualityReviewDraft:
    """Join corpus and predictions without inventing human adjudication or review."""
    if (
        run.dataset_id != corpus.dataset_id
        or run.dataset_version != corpus.dataset_version
        or run.corpus_sha256 != profile_quality_corpus_sha256(corpus)
        or run.prompt_contract_sha256 != corpus.prompt_contract_sha256
    ):
        raise ValueError("quality prediction run does not match corpus")
    corpus_ids = tuple(fixture.fixture_id for fixture in corpus.fixtures)
    run_ids = tuple(fixture.fixture_id for fixture in run.fixtures)
    if run_ids != corpus_ids:
        raise ValueError("quality prediction run fixture order does not match corpus")

    review_fixtures: list[ProfileQualityReviewDraftFixture] = []
    for corpus_fixture, prediction_record in zip(
        corpus.fixtures,
        run.fixtures,
        strict=True,
    ):
        if prediction_record.document_type != corpus_fixture.document_type:
            raise ValueError("quality prediction document type does not match corpus")
        review_fixtures.append(
            ProfileQualityReviewDraftFixture(
                fixture_id=corpus_fixture.fixture_id,
                language_slice=corpus_fixture.language_slice,
                document_type=corpus_fixture.document_type,
                risk_slices=corpus_fixture.risk_slices,
                provenance=corpus_fixture.provenance,
                source_text=corpus_fixture.source_text,
                expected_profile=corpus_fixture.expected_profile,
                prediction=prediction_record.prediction,
            )
        )
    return ProfileQualityReviewDraft(
        dataset_id=corpus.dataset_id,
        dataset_version=corpus.dataset_version,
        prompt_contract_sha256=corpus.prompt_contract_sha256,
        model_release=run.model_release,
        fixtures=tuple(review_fixtures),
    )


def finalize_profile_quality_review(
    corpus: ProfileQualityCorpus,
    run: ProfileQualityPredictionRun,
    review: ProfileQualityReviewDraft,
) -> ProfileQualityEvidence:
    """Create gate evidence only from an exact, exhaustively reviewed draft."""
    expected_review = prepare_profile_quality_review_draft(corpus, run)
    if (
        review.dataset_id != expected_review.dataset_id
        or review.dataset_version != expected_review.dataset_version
        or review.prompt_contract_sha256 != expected_review.prompt_contract_sha256
        or review.model_release != expected_review.model_release
        or len(review.fixtures) != len(expected_review.fixtures)
    ):
        raise ValueError("completed quality review does not match corpus and prediction run")

    labeled_fixtures: list[LabeledProfileFixture] = []
    for expected_fixture, reviewed_fixture in zip(
        expected_review.fixtures,
        review.fixtures,
        strict=True,
    ):
        immutable_review = reviewed_fixture.model_copy(
            update={
                "adjudications": (),
                "owner_review_outcome": "not_reviewed",
            }
        )
        if immutable_review != expected_fixture:
            raise ValueError("completed quality review changed immutable fixture content")
        if reviewed_fixture.owner_review_outcome == "not_reviewed":
            raise ValueError("completed quality review requires every owner outcome")
        labeled_fixtures.append(
            LabeledProfileFixture.model_validate(
                reviewed_fixture.model_dump(mode="python"),
                strict=True,
            )
        )

    return ProfileQualityEvidence(
        schema_version=1,
        contract_version="1b-d-v1",
        policy_version="1.0.0",
        dataset_id=corpus.dataset_id,
        dataset_version=corpus.dataset_version,
        prompt_contract_sha256=corpus.prompt_contract_sha256,
        model_release=run.model_release,
        fixtures=tuple(labeled_fixtures),
    )


def load_profile_quality_corpus(path: Path) -> ProfileQualityCorpus:
    """Load a sensitive labeled corpus without logging path or content."""
    return ProfileQualityCorpus.model_validate_json(
        _load_bounded(path, label="profile quality corpus"),
        strict=True,
    )


def load_profile_quality_run_authorization(path: Path) -> ProfileQualityRunAuthorization:
    """Load the separately reviewed external-processing authorization."""
    return ProfileQualityRunAuthorization.model_validate_json(
        _load_bounded(path, label="profile quality run authorization"),
        strict=True,
    )


def load_profile_quality_prediction_run(path: Path) -> ProfileQualityPredictionRun:
    """Load sensitive predictions without logging path or content."""
    return ProfileQualityPredictionRun.model_validate_json(
        _load_bounded(path, label="profile quality prediction run"),
        strict=True,
    )


def load_profile_quality_review_draft(path: Path) -> ProfileQualityReviewDraft:
    """Load a sensitive human-review artifact without logging path or content."""
    return ProfileQualityReviewDraft.model_validate_json(
        _load_bounded(path, label="profile quality review draft"),
        strict=True,
    )


def write_private_quality_artifact(path: Path, artifact: BaseModel) -> str:
    """Create one private artifact without overwriting an existing path."""
    payload = (
        json.dumps(
            artifact.model_dump(mode="json"),
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )
        + "\n"
    ).encode("utf-8")
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(descriptor, "wb") as artifact_file:
            artifact_file.write(payload)
            artifact_file.flush()
            os.fsync(artifact_file.fileno())
    except BaseException:
        path.unlink(missing_ok=True)
        raise
    return hashlib.sha256(payload.rstrip(b"\n")).hexdigest()


__all__ = [
    "MAX_QUALITY_PREDICTION_FIXTURES",
    "ProfileQualityCorpus",
    "ProfileQualityCorpusFixture",
    "ProfileQualityPredictionRecord",
    "ProfileQualityPredictionRun",
    "ProfileQualityReviewDraft",
    "ProfileQualityReviewDraftFixture",
    "ProfileQualityRunAuthorization",
    "ProfileQualityRunPreflight",
    "finalize_profile_quality_review",
    "generate_profile_quality_predictions",
    "load_profile_quality_corpus",
    "load_profile_quality_prediction_run",
    "load_profile_quality_review_draft",
    "load_profile_quality_run_authorization",
    "preflight_profile_quality_run",
    "prepare_profile_quality_review_draft",
    "profile_quality_corpus_sha256",
    "profile_quality_prediction_run_sha256",
    "profile_quality_run_authorization_sha256",
    "write_private_quality_artifact",
]
