"""Authenticated owner profile status, inspection, and correction contract."""

import json
import re
from typing import Annotated, cast
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, Request, Response, status
from pydantic import BaseModel, ConfigDict, Field

from ai_interviewer.api.errors import request_id_from
from ai_interviewer.identity.authorization import require_scopes
from ai_interviewer.identity.service import Principal
from ai_interviewer.profiling.contracts import (
    CandidateProfileOutput,
    profile_output_type,
)
from ai_interviewer.profiling.job_models import ProfilingFailureCode, ProfilingJobStatus
from ai_interviewer.profiling.jobs import (
    CandidateProfilingJobConflictError,
    CandidateProfilingJobNotFoundError,
    CandidateProfilingJobRecord,
    CandidateProfilingJobRuntime,
    CandidateProfilingJobUnavailableError,
)
from ai_interviewer.profiling.profiles import (
    CandidateProfileConflictError,
    CandidateProfileNotFoundError,
    CandidateProfilePreconditionError,
    CandidateProfileRecord,
    CandidateProfileRuntime,
    CandidateProfileUnavailableError,
    CandidateProfileVersionRecord,
)

router = APIRouter(
    prefix=(
        "/preparations/{preparation_id}/document-versions/{document_version_id}"
        "/profiles/{source_text_version_id}"
    ),
    tags=["profiling"],
)
_ETAG = re.compile(r'^"([1-9][0-9]*)"$')


class CandidateProfileVersionResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    profile_version_id: UUID
    version_number: int
    origin: str
    previous_version_id: UUID | None
    schema_id: str
    schema_version: str
    model_provider: str | None
    model_id: str | None
    model_version: str | None
    prompt_id: str | None
    prompt_version: str | None
    claim_count: int
    evidence_span_count: int
    evidence_character_count: int
    created_at: str
    profile: CandidateProfileOutput


class CandidateProfileResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    profile_id: UUID
    source_text_id: UUID
    source_text_version_id: UUID
    document_version_id: UUID
    document_type: str
    latest_version_number: int
    aggregate_version: int
    created_at: str
    updated_at: str
    versions: list[CandidateProfileVersionResponse]


class CandidateProfilingStatusResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    job_id: UUID
    source_text_version_id: UUID
    document_type: str
    status: ProfilingJobStatus
    attempts: int
    retryable: bool
    error_code: ProfilingFailureCode | None
    available_at: str
    completed_at: str | None
    profile: CandidateProfileResponse | None


class CandidateProfileCorrectionPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    profile: dict[str, object] = Field(min_length=1)


def _profile_runtime(request: Request) -> CandidateProfileRuntime:
    return cast(CandidateProfileRuntime, request.app.state.candidate_profiles)


def _job_runtime(request: Request) -> CandidateProfilingJobRuntime:
    return cast(CandidateProfilingJobRuntime, request.app.state.candidate_profiling_jobs)


def _etag(version: int) -> str:
    return f'"{version}"'


def _expected_version(if_match: str | None) -> int:
    if if_match is None:
        raise HTTPException(
            status_code=status.HTTP_428_PRECONDITION_REQUIRED,
            detail="An If-Match version is required.",
        )
    match = _ETAG.fullmatch(if_match.strip())
    if match is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="If-Match must contain one quoted positive version.",
        )
    return int(match.group(1))


def _corrected_profile(payload: dict[str, object]) -> CandidateProfileOutput:
    document_type = payload.get("document_type")
    if document_type == "cv":
        output_type = profile_output_type("cv")
    elif document_type == "job_description":
        output_type = profile_output_type("job_description")
    else:
        raise ValueError("profile document type is not supported")
    return output_type.model_validate_json(
        json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
        strict=True,
    )


def _version_response(item: CandidateProfileVersionRecord) -> CandidateProfileVersionResponse:
    return CandidateProfileVersionResponse(
        profile_version_id=item.profile_version_id,
        version_number=item.version_number,
        origin=item.origin,
        previous_version_id=item.previous_version_id,
        schema_id=item.schema_id,
        schema_version=item.schema_version,
        model_provider=item.model_provider,
        model_id=item.model_id,
        model_version=item.model_version,
        prompt_id=item.prompt_id,
        prompt_version=item.prompt_version,
        claim_count=item.claim_count,
        evidence_span_count=item.evidence_span_count,
        evidence_character_count=item.evidence_character_count,
        created_at=item.created_at.isoformat(),
        profile=item.profile,
    )


def _profile_response(item: CandidateProfileRecord) -> CandidateProfileResponse:
    return CandidateProfileResponse(
        profile_id=item.profile_id,
        source_text_id=item.source_text_id,
        source_text_version_id=item.source_text_version_id,
        document_version_id=item.document_version_id,
        document_type=item.document_type,
        latest_version_number=item.latest_version_number,
        aggregate_version=item.aggregate_version,
        created_at=item.created_at.isoformat(),
        updated_at=item.updated_at.isoformat(),
        versions=[_version_response(version) for version in item.versions],
    )


def _status_response(
    job: CandidateProfilingJobRecord,
    profile: CandidateProfileRecord | None,
) -> CandidateProfilingStatusResponse:
    return CandidateProfilingStatusResponse(
        job_id=job.job_id,
        source_text_version_id=job.source_text_version_id,
        document_type=job.document_type,
        status=cast(ProfilingJobStatus, job.status),
        attempts=job.attempts,
        retryable=job.status in {"pending", "processing", "retry"},
        error_code=cast(ProfilingFailureCode | None, job.error_code),
        available_at=job.available_at.isoformat(),
        completed_at=job.completed_at.isoformat() if job.completed_at is not None else None,
        profile=_profile_response(profile) if profile is not None else None,
    )


def _raise_http(exc: Exception) -> None:
    if isinstance(
        exc,
        (CandidateProfileUnavailableError, CandidateProfilingJobUnavailableError),
    ):
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Candidate profiling is temporarily unavailable.",
        ) from exc
    if isinstance(
        exc,
        (CandidateProfileNotFoundError, CandidateProfilingJobNotFoundError),
    ):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="The requested candidate profile was not found.",
        ) from exc
    if isinstance(exc, CandidateProfilePreconditionError):
        raise HTTPException(
            status_code=status.HTTP_412_PRECONDITION_FAILED,
            detail="The candidate profile changed; fetch the current version and retry.",
        ) from exc
    if isinstance(
        exc,
        (CandidateProfileConflictError, CandidateProfilingJobConflictError),
    ):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="The candidate profile operation is not permitted in its current state.",
        ) from exc
    if isinstance(exc, ValueError):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="The corrected candidate profile is invalid.",
        ) from exc
    raise exc


async def _owned_job(
    request: Request,
    principal: Principal,
    preparation_id: UUID,
    document_version_id: UUID,
    source_text_version_id: UUID,
) -> CandidateProfilingJobRecord:
    return await _job_runtime(request).get_profiling_job(
        principal.account_id,
        preparation_id,
        document_version_id,
        source_text_version_id,
    )


@router.get(
    "",
    response_model=CandidateProfilingStatusResponse,
    summary="Read owner-visible profiling status and immutable profile history",
)
async def get_candidate_profile(
    preparation_id: UUID,
    document_version_id: UUID,
    source_text_version_id: UUID,
    request: Request,
    response: Response,
    principal: Annotated[Principal, Depends(require_scopes("preparation:read"))],
) -> CandidateProfilingStatusResponse:
    try:
        job = await _owned_job(
            request,
            principal,
            preparation_id,
            document_version_id,
            source_text_version_id,
        )
        profile = None
        if job.status == "succeeded":
            profile = await _profile_runtime(request).get_profile(
                principal.account_id,
                preparation_id,
                document_version_id,
                source_text_version_id,
            )
            if job.profile_id != profile.profile_id:
                raise CandidateProfileUnavailableError(
                    "profiling job and profile lineage do not match"
                )
    except Exception as exc:
        _raise_http(exc)
        raise AssertionError("unreachable") from exc

    response.headers["Cache-Control"] = "no-store"
    if profile is not None:
        response.headers["ETag"] = _etag(profile.aggregate_version)
    elif job.status in {"pending", "processing", "retry"}:
        response.headers["Retry-After"] = "5"
    return _status_response(job, profile)


@router.put(
    "",
    response_model=CandidateProfilingStatusResponse,
    summary="Append an owner correction without overwriting generated profile history",
)
async def correct_candidate_profile(
    preparation_id: UUID,
    document_version_id: UUID,
    source_text_version_id: UUID,
    body: CandidateProfileCorrectionPayload,
    request: Request,
    response: Response,
    principal: Annotated[Principal, Depends(require_scopes("preparation:write"))],
    if_match: Annotated[str | None, Header(alias="If-Match")] = None,
) -> CandidateProfilingStatusResponse:
    expected_version = _expected_version(if_match)
    try:
        corrected_profile = _corrected_profile(body.profile)
        job = await _owned_job(
            request,
            principal,
            preparation_id,
            document_version_id,
            source_text_version_id,
        )
        if job.status != "succeeded" or job.profile_id is None:
            raise CandidateProfileConflictError("the generated profile is not complete")
        profile = await _profile_runtime(request).append_correction(
            principal.account_id,
            preparation_id,
            document_version_id,
            source_text_version_id,
            corrected_profile,
            expected_version,
            request_id_from(request),
        )
        if job.profile_id != profile.profile_id:
            raise CandidateProfileUnavailableError("profiling job and profile lineage do not match")
    except Exception as exc:
        _raise_http(exc)
        raise AssertionError("unreachable") from exc

    response.headers["Cache-Control"] = "no-store"
    response.headers["ETag"] = _etag(profile.aggregate_version)
    return _status_response(job, profile)
