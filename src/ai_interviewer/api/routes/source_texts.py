"""Authenticated owner-scoped source-text display and correction contract."""

import re
from typing import Annotated, cast
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, Request, Response, status
from pydantic import BaseModel, ConfigDict, Field

from ai_interviewer.api.errors import request_id_from
from ai_interviewer.candidate_inputs.source_texts import (
    CandidateSourceTextConflictError,
    CandidateSourceTextNotFoundError,
    CandidateSourceTextPreconditionError,
    CandidateSourceTextRecord,
    CandidateSourceTextRuntime,
    CandidateSourceTextUnavailableError,
    CandidateSourceTextVersionRecord,
)
from ai_interviewer.identity.authorization import require_scopes
from ai_interviewer.identity.service import Principal

router = APIRouter(
    prefix="/preparations/{preparation_id}/document-versions/{document_version_id}/source-text",
    tags=["candidate-inputs"],
)
_ETAG = re.compile(r'^"([1-9][0-9]*)"$')


class SourceTextVersionResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    text_version_id: UUID
    version_number: int
    origin: str
    previous_version_id: UUID | None
    parser_adapter: str | None
    parser_version: str | None
    isolation_profile: str | None
    character_count: int
    utf8_byte_count: int
    line_count: int
    created_at: str
    content: str


class SourceTextResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_text_id: UUID
    document_version_id: UUID
    latest_version_number: int
    aggregate_version: int
    created_at: str
    updated_at: str
    versions: list[SourceTextVersionResponse]


class CorrectionPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    content: str = Field(min_length=1, max_length=500_000)


def _runtime(request: Request) -> CandidateSourceTextRuntime:
    return cast(CandidateSourceTextRuntime, request.app.state.candidate_source_texts)


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


def _version_response(item: CandidateSourceTextVersionRecord) -> SourceTextVersionResponse:
    return SourceTextVersionResponse(
        text_version_id=item.text_version_id,
        version_number=item.version_number,
        origin=item.origin,
        previous_version_id=item.previous_version_id,
        parser_adapter=item.parser_adapter,
        parser_version=item.parser_version,
        isolation_profile=item.isolation_profile,
        character_count=item.character_count,
        utf8_byte_count=item.utf8_byte_count,
        line_count=item.line_count,
        created_at=item.created_at.isoformat(),
        content=item.content,
    )


def _response(item: CandidateSourceTextRecord) -> SourceTextResponse:
    return SourceTextResponse(
        source_text_id=item.source_text_id,
        document_version_id=item.document_version_id,
        latest_version_number=item.latest_version_number,
        aggregate_version=item.aggregate_version,
        created_at=item.created_at.isoformat(),
        updated_at=item.updated_at.isoformat(),
        versions=[_version_response(version) for version in item.versions],
    )


def _raise_http(exc: Exception) -> None:
    if isinstance(exc, CandidateSourceTextUnavailableError):
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Candidate source text is temporarily unavailable.",
        ) from exc
    if isinstance(exc, CandidateSourceTextNotFoundError):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="The requested source text was not found.",
        ) from exc
    if isinstance(exc, CandidateSourceTextPreconditionError):
        raise HTTPException(
            status_code=status.HTTP_412_PRECONDITION_FAILED,
            detail="The source text changed; fetch the current version and retry.",
        ) from exc
    if isinstance(exc, CandidateSourceTextConflictError):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="The source text operation is not permitted in its current state.",
        ) from exc
    if isinstance(exc, ValueError):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="The correction content is invalid.",
        ) from exc
    raise exc


@router.get(
    "",
    response_model=SourceTextResponse,
    summary="Read the owner-visible extracted source text and its correction history",
)
async def get_source_text(
    preparation_id: UUID,
    document_version_id: UUID,
    request: Request,
    response: Response,
    principal: Annotated[Principal, Depends(require_scopes("preparation:read"))],
) -> SourceTextResponse:
    try:
        record = await _runtime(request).get_source_text(
            principal.account_id,
            preparation_id,
            document_version_id,
        )
    except Exception as exc:
        _raise_http(exc)
        raise AssertionError("unreachable") from exc
    response.headers["ETag"] = _etag(record.aggregate_version)
    return _response(record)


@router.put(
    "",
    response_model=SourceTextResponse,
    summary="Append an owner correction on top of the current source text",
)
async def correct_source_text(
    preparation_id: UUID,
    document_version_id: UUID,
    body: CorrectionPayload,
    request: Request,
    response: Response,
    principal: Annotated[Principal, Depends(require_scopes("preparation:write"))],
    if_match: Annotated[str | None, Header(alias="If-Match")] = None,
) -> SourceTextResponse:
    expected_version = _expected_version(if_match)
    try:
        record = await _runtime(request).append_correction(
            principal.account_id,
            preparation_id,
            document_version_id,
            body.content,
            expected_version,
            request_id_from(request),
        )
    except Exception as exc:
        _raise_http(exc)
        raise AssertionError("unreachable") from exc
    response.headers["ETag"] = _etag(record.aggregate_version)
    return _response(record)
