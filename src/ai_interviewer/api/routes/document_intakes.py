"""Authenticated bounded raw upload/paste contract for candidate documents."""

from typing import Annotated, cast
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, Request, Response, status
from pydantic import BaseModel, ConfigDict

from ai_interviewer.api.errors import request_id_from
from ai_interviewer.candidate_inputs.document_models import (
    CandidateDocumentSource,
    CandidateDocumentType,
)
from ai_interviewer.candidate_inputs.intake_models import CandidateDocumentIntakeStatus
from ai_interviewer.candidate_inputs.intakes import (
    CandidateDocumentIntakeConflictError,
    CandidateDocumentIntakeNotFoundError,
    CandidateDocumentIntakeRecord,
    CandidateDocumentIntakeRuntime,
    CandidateDocumentIntakeUnavailableError,
)
from ai_interviewer.file_security.validation import ALLOWED_MEDIA_TYPES, TEXT_MEDIA_TYPE
from ai_interviewer.identity.authorization import require_scopes
from ai_interviewer.identity.service import Principal

router = APIRouter(prefix="/preparations", tags=["candidate-inputs"])


class IntakePayloadTooLargeError(ValueError):
    """The HTTP body exceeded the application-owned hard limit."""


class CandidateDocumentIntakeResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    intake_id: UUID
    preparation_id: UUID
    document_type: CandidateDocumentType
    source_kind: CandidateDocumentSource
    status: CandidateDocumentIntakeStatus
    retryable: bool
    declared_media_type: str
    content_length: int
    attempts: int
    last_error_code: str | None
    file_asset_id: UUID | None
    document_id: UUID | None
    document_version_id: UUID | None
    aggregate_version: int
    created_at: str
    updated_at: str
    completed_at: str | None
    retain_until: str


def _runtime(request: Request) -> CandidateDocumentIntakeRuntime:
    return cast(CandidateDocumentIntakeRuntime, request.app.state.candidate_document_intakes)


def _response(item: CandidateDocumentIntakeRecord) -> CandidateDocumentIntakeResponse:
    return CandidateDocumentIntakeResponse(
        intake_id=item.intake_id,
        preparation_id=item.preparation_id,
        document_type=item.document_type,
        source_kind=item.source_kind,
        status=item.status,
        retryable=item.retryable,
        declared_media_type=item.declared_media_type,
        content_length=item.content_length,
        attempts=item.attempts,
        last_error_code=item.last_error_code,
        file_asset_id=item.file_asset_id,
        document_id=item.document_id,
        document_version_id=item.document_version_id,
        aggregate_version=item.aggregate_version,
        created_at=item.created_at.isoformat(),
        updated_at=item.updated_at.isoformat(),
        completed_at=item.completed_at.isoformat() if item.completed_at is not None else None,
        retain_until=item.retain_until.isoformat(),
    )


def _raise_http(exc: Exception) -> None:
    if isinstance(exc, CandidateDocumentIntakeUnavailableError):
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Candidate document intake is temporarily unavailable.",
        ) from exc
    if isinstance(exc, CandidateDocumentIntakeNotFoundError):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="The requested document intake was not found.",
        ) from exc
    if isinstance(exc, CandidateDocumentIntakeConflictError):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="The document intake is not permitted in its current state.",
        ) from exc
    if isinstance(exc, IntakePayloadTooLargeError):
        raise HTTPException(
            status_code=status.HTTP_413_CONTENT_TOO_LARGE,
            detail="The document body exceeds the configured size limit.",
        ) from exc
    if isinstance(exc, ValueError):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="The document input is invalid.",
        ) from exc
    raise exc


async def _bounded_body(request: Request, maximum_bytes: int) -> bytes:
    content_encoding = request.headers.get("content-encoding")
    if content_encoding is not None and content_encoding.strip().lower() != "identity":
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail="Encoded request bodies are not accepted.",
        )
    declared_length = request.headers.get("content-length")
    if declared_length is not None:
        try:
            parsed_length = int(declared_length)
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Content-Length must be a non-negative integer.",
            ) from exc
        if parsed_length < 0:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Content-Length must be a non-negative integer.",
            )
        if parsed_length > maximum_bytes:
            raise IntakePayloadTooLargeError

    body = bytearray()
    async for chunk in request.stream():
        if len(body) + len(chunk) > maximum_bytes:
            raise IntakePayloadTooLargeError
        body.extend(chunk)
    return bytes(body)


def _media_type(request: Request, *, paste: bool) -> str:
    raw = request.headers.get("content-type")
    if raw is None:
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail="A supported Content-Type is required.",
        )
    parts = [part.strip() for part in raw.split(";")]
    media_type = parts[0].lower()
    if media_type not in ALLOWED_MEDIA_TYPES or (paste and media_type != TEXT_MEDIA_TYPE):
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail="The declared document media type is not supported.",
        )
    if paste:
        charset_values = [
            part.split("=", 1)[1].strip().lower()
            for part in parts[1:]
            if part.lower().startswith("charset=")
        ]
        if charset_values and charset_values != ["utf-8"]:
            raise HTTPException(
                status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
                detail="Pasted text must use UTF-8.",
            )
    return media_type


def _apply_result_status(
    response: Response,
    item: CandidateDocumentIntakeRecord,
    created: bool,
) -> None:
    if item.status == "completed":
        response.status_code = status.HTTP_201_CREATED if created else status.HTTP_200_OK
    elif item.status in {"processing", "scan_failed"}:
        response.status_code = status.HTTP_202_ACCEPTED
        response.headers["Retry-After"] = "5"
    else:
        response.status_code = status.HTTP_422_UNPROCESSABLE_CONTENT
    response.headers["ETag"] = f'"{item.aggregate_version}"'
    response.headers["Cache-Control"] = "no-store"


async def _submit(
    *,
    preparation_id: UUID,
    document_type: CandidateDocumentType,
    source_kind: CandidateDocumentSource,
    request: Request,
    response: Response,
    principal: Principal,
    idempotency_key: str,
) -> CandidateDocumentIntakeResponse:
    media_type = _media_type(request, paste=source_kind == "paste")
    maximum_bytes = request.app.state.settings.file_security_max_upload_bytes
    try:
        content = await _bounded_body(request, maximum_bytes)
        result = await _runtime(request).submit(
            principal.account_id,
            preparation_id,
            document_type,
            source_kind,
            media_type,
            content,
            idempotency_key,
            request_id_from(request),
        )
    except Exception as exc:
        _raise_http(exc)
        raise AssertionError("unreachable") from exc
    _apply_result_status(response, result.intake, result.created)
    response.headers["Location"] = (
        f"/api/v1/preparations/{preparation_id}/document-intakes/{result.intake.intake_id}"
    )
    return _response(result.intake)


@router.post(
    "/{preparation_id}/documents/{document_type}/upload",
    response_model=CandidateDocumentIntakeResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Upload a CV or job description without collecting a filename",
)
async def upload_candidate_document(
    preparation_id: UUID,
    document_type: CandidateDocumentType,
    request: Request,
    response: Response,
    principal: Annotated[Principal, Depends(require_scopes("preparation:write"))],
    idempotency_key: Annotated[
        str,
        Header(alias="Idempotency-Key", min_length=8, max_length=128),
    ],
) -> CandidateDocumentIntakeResponse:
    return await _submit(
        preparation_id=preparation_id,
        document_type=document_type,
        source_kind="upload",
        request=request,
        response=response,
        principal=principal,
        idempotency_key=idempotency_key,
    )


@router.post(
    "/{preparation_id}/documents/{document_type}/paste",
    response_model=CandidateDocumentIntakeResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Paste UTF-8 CV or job-description text",
)
async def paste_candidate_document(
    preparation_id: UUID,
    document_type: CandidateDocumentType,
    request: Request,
    response: Response,
    principal: Annotated[Principal, Depends(require_scopes("preparation:write"))],
    idempotency_key: Annotated[
        str,
        Header(alias="Idempotency-Key", min_length=8, max_length=128),
    ],
) -> CandidateDocumentIntakeResponse:
    return await _submit(
        preparation_id=preparation_id,
        document_type=document_type,
        source_kind="paste",
        request=request,
        response=response,
        principal=principal,
        idempotency_key=idempotency_key,
    )


@router.get(
    "/{preparation_id}/document-intakes/{intake_id}",
    response_model=CandidateDocumentIntakeResponse,
    summary="Get an owned document-intake status",
)
async def get_candidate_document_intake(
    preparation_id: UUID,
    intake_id: UUID,
    request: Request,
    response: Response,
    principal: Annotated[Principal, Depends(require_scopes("preparation:read"))],
) -> CandidateDocumentIntakeResponse:
    try:
        intake = await _runtime(request).get_intake(
            principal.account_id,
            preparation_id,
            intake_id,
        )
    except Exception as exc:
        _raise_http(exc)
        raise AssertionError("unreachable") from exc
    response.headers["ETag"] = f'"{intake.aggregate_version}"'
    response.headers["Cache-Control"] = "no-store"
    return _response(intake)
