"""Authenticated read contract for immutable candidate document lineage."""

from typing import Annotated, cast
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from pydantic import BaseModel, ConfigDict

from ai_interviewer.candidate_inputs.document_models import (
    CandidateDocumentSource,
    CandidateDocumentType,
)
from ai_interviewer.candidate_inputs.documents import (
    CandidateDocumentNotFoundError,
    CandidateDocumentRecord,
    CandidateDocumentRuntime,
    CandidateDocumentUnavailableError,
    CandidateDocumentVersionRecord,
)
from ai_interviewer.identity.authorization import require_scopes
from ai_interviewer.identity.service import Principal

router = APIRouter(
    prefix="/preparations/{preparation_id}/documents",
    tags=["candidate-inputs"],
)


class CandidateDocumentVersionResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version_id: UUID
    file_asset_id: UUID
    version_number: int
    source_kind: CandidateDocumentSource
    media_type: str
    content_length: int
    content_sha256: str
    created_at: str
    retain_until: str


class CandidateDocumentResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    document_id: UUID
    preparation_id: UUID
    document_type: CandidateDocumentType
    latest_version_number: int
    aggregate_version: int
    created_at: str
    updated_at: str
    versions: list[CandidateDocumentVersionResponse]


class CandidateDocumentListResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: list[CandidateDocumentResponse]


def _runtime(request: Request) -> CandidateDocumentRuntime:
    return cast(CandidateDocumentRuntime, request.app.state.candidate_documents)


def _version_response(item: CandidateDocumentVersionRecord) -> CandidateDocumentVersionResponse:
    return CandidateDocumentVersionResponse(
        version_id=item.version_id,
        file_asset_id=item.file_asset_id,
        version_number=item.version_number,
        source_kind=item.source_kind,
        media_type=item.media_type,
        content_length=item.content_length,
        content_sha256=item.content_sha256,
        created_at=item.created_at.isoformat(),
        retain_until=item.retain_until.isoformat(),
    )


def _response(item: CandidateDocumentRecord) -> CandidateDocumentResponse:
    return CandidateDocumentResponse(
        document_id=item.document_id,
        preparation_id=item.preparation_id,
        document_type=item.document_type,
        latest_version_number=item.latest_version_number,
        aggregate_version=item.aggregate_version,
        created_at=item.created_at.isoformat(),
        updated_at=item.updated_at.isoformat(),
        versions=[_version_response(version) for version in item.versions],
    )


def _raise_http(exc: Exception) -> None:
    if isinstance(exc, CandidateDocumentUnavailableError):
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Candidate documents are temporarily unavailable.",
        ) from exc
    if isinstance(exc, CandidateDocumentNotFoundError):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="The requested candidate document was not found.",
        ) from exc
    raise exc


@router.get("", response_model=CandidateDocumentListResponse, summary="List document lineage")
async def list_candidate_documents(
    preparation_id: UUID,
    request: Request,
    principal: Annotated[Principal, Depends(require_scopes("preparation:read"))],
) -> CandidateDocumentListResponse:
    try:
        documents = await _runtime(request).list_documents(
            principal.account_id,
            preparation_id,
        )
    except Exception as exc:
        _raise_http(exc)
        raise AssertionError("unreachable") from exc
    return CandidateDocumentListResponse(items=[_response(item) for item in documents])


@router.get(
    "/{document_id}",
    response_model=CandidateDocumentResponse,
    summary="Get immutable document lineage",
)
async def get_candidate_document(
    preparation_id: UUID,
    document_id: UUID,
    request: Request,
    response: Response,
    principal: Annotated[Principal, Depends(require_scopes("preparation:read"))],
) -> CandidateDocumentResponse:
    try:
        document = await _runtime(request).get_document(
            principal.account_id,
            preparation_id,
            document_id,
        )
    except Exception as exc:
        _raise_http(exc)
        raise AssertionError("unreachable") from exc
    response.headers["ETag"] = f'"{document.aggregate_version}"'
    return _response(document)
