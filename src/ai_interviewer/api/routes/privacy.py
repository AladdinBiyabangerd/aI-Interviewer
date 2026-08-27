"""Authenticated privacy self-service API."""

from datetime import datetime
from typing import Annotated, Literal, cast
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, Request, status
from pydantic import BaseModel, ConfigDict, Field

from ai_interviewer.api.errors import request_id_from
from ai_interviewer.identity.authorization import current_principal, require_scopes
from ai_interviewer.identity.service import Principal
from ai_interviewer.privacy.consent import (
    AdultAttestationRequiredError,
    ConsentNotFoundError,
    ConsentUnavailableError,
    ProfileInput,
)
from ai_interviewer.privacy.lifecycle import (
    PrivacyRequestConflictError,
    PrivacyRequestNotFoundError,
    PrivacyRequestResult,
    PrivacyRuntime,
    PrivacyUnavailableError,
)
from ai_interviewer.privacy.models import ConsentRecord, PrivacyProfile, PrivacyRequestType
from ai_interviewer.privacy.policy import JurisdictionResolutionError
from ai_interviewer.privacy.rules import PrivacyPolicyError

router = APIRouter(prefix="/privacy", tags=["privacy"])


class PrivacyProfileRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    residence_country_code: str = Field(min_length=2, max_length=2)
    residence_subdivision_code: str | None = Field(default=None, min_length=4, max_length=16)
    storage_region: str = Field(min_length=1, max_length=64)
    adult_attested: Literal[True]
    privacy_policy_version_id: UUID


class PrivacyProfileResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    account_id: UUID
    residence_country_code: str
    residence_subdivision_code: str | None
    jurisdiction_codes: list[str]
    jurisdiction_versions: dict[str, str]
    storage_region: str
    adult_attested_at: datetime
    privacy_policy_version_id: UUID


class ConsentResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    consent_record_id: UUID
    consent_notice_id: UUID
    granted_at: datetime
    withdrawn_at: datetime | None


class PrivacyRequestBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    request_type: PrivacyRequestType


class PrivacyRequestResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    request_id: UUID
    request_type: PrivacyRequestType
    status: str
    requested_at: datetime
    due_at: datetime
    completed_at: datetime | None
    data: dict[str, object] | None


def _privacy_runtime(request: Request) -> PrivacyRuntime:
    return cast(PrivacyRuntime, request.app.state.privacy)


def _profile_response(profile: PrivacyProfile) -> PrivacyProfileResponse:
    return PrivacyProfileResponse(
        account_id=profile.account_id,
        residence_country_code=profile.residence_country_code,
        residence_subdivision_code=profile.residence_subdivision_code,
        jurisdiction_codes=profile.jurisdiction_codes,
        jurisdiction_versions=profile.jurisdiction_versions,
        storage_region=profile.storage_region,
        adult_attested_at=profile.adult_attested_at,
        privacy_policy_version_id=profile.privacy_policy_version_id,
    )


def _consent_response(record: ConsentRecord) -> ConsentResponse:
    return ConsentResponse(
        consent_record_id=record.id,
        consent_notice_id=record.consent_notice_id,
        granted_at=record.granted_at,
        withdrawn_at=record.withdrawn_at,
    )


def _request_response(result: PrivacyRequestResult) -> PrivacyRequestResponse:
    return PrivacyRequestResponse(
        request_id=result.request_id,
        request_type=result.request_type,
        status=result.status,
        requested_at=result.requested_at,
        due_at=result.due_at,
        completed_at=result.completed_at,
        data=cast(dict[str, object] | None, result.data),
    )


def _raise_http_for_privacy_error(exc: Exception) -> None:
    if isinstance(exc, PrivacyUnavailableError):
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Privacy self-service is temporarily unavailable.",
        ) from exc
    if isinstance(exc, (ConsentNotFoundError, PrivacyRequestNotFoundError)):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="The requested privacy resource was not found.",
        ) from exc
    if isinstance(exc, AdultAttestationRequiredError):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="This product is available only to users aged 18 or older.",
        ) from exc
    if isinstance(
        exc,
        (
            ConsentUnavailableError,
            JurisdictionResolutionError,
            PrivacyPolicyError,
            PrivacyRequestConflictError,
        ),
    ):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="No approved privacy policy permits this operation.",
        ) from exc
    raise exc


@router.put("/profile", response_model=PrivacyProfileResponse, summary="Set privacy profile")
async def set_privacy_profile(
    body: PrivacyProfileRequest,
    request: Request,
    principal: Annotated[Principal, Depends(require_scopes("privacy:write"))],
) -> PrivacyProfileResponse:
    try:
        profile = await _privacy_runtime(request).configure_profile(
            principal.account_id,
            ProfileInput(
                residence_country_code=body.residence_country_code,
                residence_subdivision_code=body.residence_subdivision_code,
                storage_region=body.storage_region,
                adult_attested=body.adult_attested,
                privacy_policy_version_id=body.privacy_policy_version_id,
            ),
            request_id_from(request),
        )
    except Exception as exc:
        _raise_http_for_privacy_error(exc)
        raise AssertionError("unreachable") from exc
    return _profile_response(profile)


@router.get("/consents", response_model=list[ConsentResponse], summary="List consent history")
async def list_consent_history(
    request: Request,
    principal: Annotated[Principal, Depends(require_scopes("privacy:read"))],
) -> list[ConsentResponse]:
    try:
        records = await _privacy_runtime(request).list_consents(principal.account_id)
    except Exception as exc:
        _raise_http_for_privacy_error(exc)
        raise AssertionError("unreachable") from exc
    return [_consent_response(record) for record in records]


@router.post(
    "/consents/{consent_notice_id}",
    response_model=ConsentResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Grant exact notice consent",
)
async def create_consent(
    consent_notice_id: UUID,
    request: Request,
    principal: Annotated[Principal, Depends(require_scopes("privacy:write"))],
) -> ConsentResponse:
    try:
        record = await _privacy_runtime(request).grant(
            principal.account_id, consent_notice_id, request_id_from(request)
        )
    except Exception as exc:
        _raise_http_for_privacy_error(exc)
        raise AssertionError("unreachable") from exc
    return _consent_response(record)


@router.delete(
    "/consents/{consent_record_id}",
    response_model=ConsentResponse,
    summary="Withdraw consent",
)
async def remove_consent(
    consent_record_id: UUID,
    request: Request,
    principal: Annotated[Principal, Depends(require_scopes("privacy:write"))],
) -> ConsentResponse:
    try:
        record = await _privacy_runtime(request).withdraw(
            principal.account_id, consent_record_id, request_id_from(request)
        )
    except Exception as exc:
        _raise_http_for_privacy_error(exc)
        raise AssertionError("unreachable") from exc
    return _consent_response(record)


@router.post(
    "/requests",
    response_model=PrivacyRequestResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Create an access, export, or deletion request",
)
async def create_privacy_request(
    body: PrivacyRequestBody,
    request: Request,
    principal: Annotated[Principal, Depends(current_principal)],
    idempotency_key: Annotated[
        str,
        Header(alias="Idempotency-Key", min_length=8, max_length=128),
    ],
) -> PrivacyRequestResponse:
    required_scope = {
        "access": "privacy:read",
        "export": "privacy:export",
        "deletion": "privacy:delete",
    }[body.request_type]
    if required_scope not in principal.scopes:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="The token does not grant the required permission.",
            headers={
                "WWW-Authenticate": (f'Bearer error="insufficient_scope", scope="{required_scope}"')
            },
        )
    try:
        result = await _privacy_runtime(request).create_request(
            principal.account_id,
            body.request_type,
            idempotency_key,
            request_id_from(request),
        )
    except Exception as exc:
        _raise_http_for_privacy_error(exc)
        raise AssertionError("unreachable") from exc
    return _request_response(result)


@router.get(
    "/requests/{privacy_request_id}",
    response_model=PrivacyRequestResponse,
    summary="Get an owned privacy request",
)
async def get_privacy_request(
    privacy_request_id: UUID,
    request: Request,
    principal: Annotated[Principal, Depends(require_scopes("privacy:read"))],
) -> PrivacyRequestResponse:
    try:
        result = await _privacy_runtime(request).get_request(
            principal.account_id, privacy_request_id
        )
    except Exception as exc:
        _raise_http_for_privacy_error(exc)
        raise AssertionError("unreachable") from exc
    return _request_response(result)
