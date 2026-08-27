"""Authenticated candidate-preparation target API."""

import re
from datetime import datetime
from typing import Annotated, Protocol, cast
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request, Response, status
from pydantic import BaseModel, ConfigDict, Field

from ai_interviewer.api.errors import request_id_from
from ai_interviewer.candidate_inputs.models import (
    InterviewLanguage,
    InterviewRound,
    PreparationStatus,
    RoleFamily,
    Seniority,
)
from ai_interviewer.candidate_inputs.service import (
    CandidateInputRuntime,
    CandidateInputUnavailableError,
    CandidatePreparationConflictError,
    CandidatePreparationNotFoundError,
    CandidatePreparationPreconditionError,
    PreparationInput,
    normalize_preparation_input,
)
from ai_interviewer.identity.authorization import require_scopes
from ai_interviewer.identity.service import Principal
from ai_interviewer.privacy.rules import PrivacyPolicyError

router = APIRouter(prefix="/preparations", tags=["candidate-inputs"])
_ETAG = re.compile(r'^"([1-9][0-9]*)"$')


class PreparationPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    company_name: str = Field(min_length=1, max_length=200)
    role_family: RoleFamily
    role_family_other: str | None = Field(default=None, min_length=1, max_length=100)
    role_title: str = Field(min_length=1, max_length=200)
    seniority: Seniority
    seniority_other: str | None = Field(default=None, min_length=1, max_length=100)
    target_country_code: str = Field(min_length=2, max_length=2, pattern=r"^[A-Za-z]{2}$")
    target_office: str | None = Field(default=None, min_length=1, max_length=200)
    interview_round: InterviewRound
    interview_round_other: str | None = Field(default=None, min_length=1, max_length=100)
    interview_language: InterviewLanguage

    def to_domain(self) -> PreparationInput:
        return normalize_preparation_input(PreparationInput(**self.model_dump()))


class PreparationResponse(PreparationPayload):
    preparation_id: UUID
    status: PreparationStatus
    version: int
    created_at: str
    updated_at: str
    retain_until: str


class PreparationPageResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: list[PreparationResponse]
    next_after: UUID | None


def _runtime(request: Request) -> CandidateInputRuntime:
    return cast(CandidateInputRuntime, request.app.state.candidate_inputs)


def _response(item: object) -> PreparationResponse:
    preparation = cast("CandidatePreparationLike", item)
    return PreparationResponse(
        preparation_id=preparation.id,
        company_name=preparation.company_name,
        role_family=preparation.role_family,
        role_family_other=preparation.role_family_other,
        role_title=preparation.role_title,
        seniority=preparation.seniority,
        seniority_other=preparation.seniority_other,
        target_country_code=preparation.target_country_code,
        target_office=preparation.target_office,
        interview_round=preparation.interview_round,
        interview_round_other=preparation.interview_round_other,
        interview_language=preparation.interview_language,
        status=preparation.status,
        version=preparation.version,
        created_at=preparation.created_at.isoformat(),
        updated_at=preparation.updated_at.isoformat(),
        retain_until=preparation.retain_until.isoformat(),
    )


class CandidatePreparationLike(Protocol):
    """Structural annotation kept local so the HTTP layer does not own ORM behavior."""

    id: UUID
    company_name: str
    role_family: RoleFamily
    role_family_other: str | None
    role_title: str
    seniority: Seniority
    seniority_other: str | None
    target_country_code: str
    target_office: str | None
    interview_round: InterviewRound
    interview_round_other: str | None
    interview_language: InterviewLanguage
    status: PreparationStatus
    version: int
    created_at: datetime
    updated_at: datetime
    retain_until: datetime


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


def _raise_http(exc: Exception) -> None:
    if isinstance(exc, CandidateInputUnavailableError):
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Candidate onboarding is temporarily unavailable.",
        ) from exc
    if isinstance(exc, CandidatePreparationNotFoundError):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="The requested preparation was not found.",
        ) from exc
    if isinstance(exc, CandidatePreparationPreconditionError):
        raise HTTPException(
            status_code=status.HTTP_412_PRECONDITION_FAILED,
            detail="The preparation changed; fetch the current version and retry.",
        ) from exc
    if isinstance(exc, (CandidatePreparationConflictError, PrivacyPolicyError)):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="The preparation operation is not permitted in its current state.",
        ) from exc
    if isinstance(exc, ValueError):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="The preparation input is invalid.",
        ) from exc
    raise exc


@router.post(
    "",
    response_model=PreparationResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create an interview preparation target",
)
async def create_preparation(
    body: PreparationPayload,
    request: Request,
    response: Response,
    principal: Annotated[Principal, Depends(require_scopes("preparation:write"))],
    idempotency_key: Annotated[
        str,
        Header(alias="Idempotency-Key", min_length=8, max_length=128),
    ],
) -> PreparationResponse:
    try:
        result = await _runtime(request).create_preparation(
            principal.account_id,
            body.to_domain(),
            idempotency_key,
            request_id_from(request),
        )
    except Exception as exc:
        _raise_http(exc)
        raise AssertionError("unreachable") from exc
    response.status_code = status.HTTP_201_CREATED if result.created else status.HTTP_200_OK
    response.headers["ETag"] = _etag(result.preparation.version)
    return _response(result.preparation)


@router.get("", response_model=PreparationPageResponse, summary="List owned preparations")
async def list_preparations(
    request: Request,
    principal: Annotated[Principal, Depends(require_scopes("preparation:read"))],
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    after: UUID | None = None,
) -> PreparationPageResponse:
    try:
        page = await _runtime(request).list_preparations(
            principal.account_id,
            limit=limit,
            after=after,
        )
    except Exception as exc:
        _raise_http(exc)
        raise AssertionError("unreachable") from exc
    return PreparationPageResponse(
        items=[_response(item) for item in page.items],
        next_after=page.next_after,
    )


@router.get(
    "/{preparation_id}",
    response_model=PreparationResponse,
    summary="Get an owned preparation",
)
async def get_preparation(
    preparation_id: UUID,
    request: Request,
    response: Response,
    principal: Annotated[Principal, Depends(require_scopes("preparation:read"))],
) -> PreparationResponse:
    try:
        preparation = await _runtime(request).get_preparation(principal.account_id, preparation_id)
    except Exception as exc:
        _raise_http(exc)
        raise AssertionError("unreachable") from exc
    response.headers["ETag"] = _etag(preparation.version)
    return _response(preparation)


@router.put(
    "/{preparation_id}",
    response_model=PreparationResponse,
    summary="Replace an owned preparation",
)
async def replace_preparation(
    preparation_id: UUID,
    body: PreparationPayload,
    request: Request,
    response: Response,
    principal: Annotated[Principal, Depends(require_scopes("preparation:write"))],
    if_match: Annotated[str | None, Header(alias="If-Match")] = None,
) -> PreparationResponse:
    expected_version = _expected_version(if_match)
    try:
        preparation = await _runtime(request).replace_preparation(
            principal.account_id,
            preparation_id,
            body.to_domain(),
            expected_version,
            request_id_from(request),
        )
    except Exception as exc:
        _raise_http(exc)
        raise AssertionError("unreachable") from exc
    response.headers["ETag"] = _etag(preparation.version)
    return _response(preparation)


@router.post(
    "/{preparation_id}/archive",
    response_model=PreparationResponse,
    summary="Archive an owned preparation",
)
async def archive_preparation(
    preparation_id: UUID,
    request: Request,
    response: Response,
    principal: Annotated[Principal, Depends(require_scopes("preparation:write"))],
    if_match: Annotated[str | None, Header(alias="If-Match")] = None,
) -> PreparationResponse:
    expected_version = _expected_version(if_match)
    try:
        preparation = await _runtime(request).archive_preparation(
            principal.account_id,
            preparation_id,
            expected_version,
            request_id_from(request),
        )
    except Exception as exc:
        _raise_http(exc)
        raise AssertionError("unreachable") from exc
    response.headers["ETag"] = _etag(preparation.version)
    return _response(preparation)
