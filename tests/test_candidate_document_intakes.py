from dataclasses import replace
from datetime import UTC, datetime, timedelta
from typing import cast
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.requests import Request

from ai_interviewer.api.routes.document_intakes import (
    IntakePayloadTooLargeError,
    _bounded_body,
)
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
    CandidateDocumentIntakeService,
    CandidateDocumentIntakeUnavailableError,
    FailClosedCandidateDocumentIntakeService,
    SubmitCandidateDocumentIntakeResult,
    build_candidate_document_intakes,
)
from ai_interviewer.core.config import Settings
from ai_interviewer.file_security.validation import UploadValidationError
from ai_interviewer.identity.service import Principal
from ai_interviewer.main import create_app
from ai_interviewer.persistence.database import DatabaseRuntime
from tests.fakes import ReadyDatabase


class ControlledAuthentication:
    def __init__(self, principal: Principal) -> None:
        self.principal = principal

    async def authenticate(self, access_token: str, request_id: str | None) -> Principal:
        del access_token, request_id
        return self.principal


def _intake(status: str = "completed") -> CandidateDocumentIntakeRecord:
    now = datetime.now(UTC)
    completed = status == "completed"
    failed = status in {"scan_failed", "rejected"}
    return CandidateDocumentIntakeRecord(
        intake_id=uuid4(),
        preparation_id=uuid4(),
        document_type="cv",
        source_kind="upload",
        status=cast(CandidateDocumentIntakeStatus, status),
        declared_media_type="application/pdf",
        content_length=27,
        attempts=1,
        last_error_code="scan_unavailable" if failed else None,
        file_asset_id=uuid4() if completed else None,
        document_id=uuid4() if completed else None,
        document_version_id=uuid4() if completed else None,
        aggregate_version=2,
        created_at=now - timedelta(seconds=1),
        updated_at=now,
        completed_at=now if completed else None,
        retain_until=now + timedelta(days=30),
    )


class ControlledIntakes:
    def __init__(
        self,
        account_id: UUID,
        *,
        status: str = "completed",
        created: bool = True,
        error: Exception | None = None,
    ) -> None:
        self.account_id = account_id
        self.item = _intake(status)
        self.created = created
        self.error = error
        self.submissions: list[tuple[object, ...]] = []

    def _raise(self) -> None:
        if self.error is not None:
            raise self.error

    async def submit(
        self,
        account_id: UUID,
        preparation_id: UUID,
        document_type: str,
        source_kind: str,
        declared_media_type: str,
        content: bytes,
        idempotency_key: str,
        request_id: str | None,
        *,
        now: datetime | None = None,
    ) -> SubmitCandidateDocumentIntakeResult:
        del now
        assert account_id == self.account_id
        self._raise()
        self.submissions.append(
            (
                preparation_id,
                document_type,
                source_kind,
                declared_media_type,
                content,
                idempotency_key,
                request_id,
            )
        )
        self.item = replace(
            self.item,
            preparation_id=preparation_id,
            document_type=cast(CandidateDocumentType, document_type),
            source_kind=cast(CandidateDocumentSource, source_kind),
            declared_media_type=declared_media_type,
            content_length=len(content),
        )
        return SubmitCandidateDocumentIntakeResult(self.item, self.created)

    async def get_intake(
        self,
        account_id: UUID,
        preparation_id: UUID,
        intake_id: UUID,
    ) -> CandidateDocumentIntakeRecord:
        assert account_id == self.account_id
        assert preparation_id == self.item.preparation_id
        assert intake_id == self.item.intake_id
        self._raise()
        return self.item

    async def export_account_intake_metadata(
        self,
        session: AsyncSession,
        *,
        account_id: UUID,
    ) -> list[dict[str, object]]:
        del session, account_id
        return []

    async def erase_account_intake_metadata(
        self,
        session: AsyncSession,
        *,
        account_id: UUID,
    ) -> int:
        del session, account_id
        return 0


def _client(
    scopes: frozenset[str],
    service: ControlledIntakes | FailClosedCandidateDocumentIntakeService,
    *,
    maximum_bytes: int = 1_024,
) -> TestClient:
    account_id = service.account_id if isinstance(service, ControlledIntakes) else uuid4()
    settings = Settings(
        environment="test",
        allowed_hosts=("testserver",),
        file_security_max_upload_bytes=maximum_bytes,
    )
    return TestClient(
        create_app(
            settings,
            database=cast(DatabaseRuntime, ReadyDatabase()),
            authentication=ControlledAuthentication(Principal(account_id, scopes)),
            candidate_document_intakes=cast(CandidateDocumentIntakeRuntime, service),
        )
    )


def test_upload_and_paste_contracts_return_owned_status_metadata() -> None:
    account_id = uuid4()
    service = ControlledIntakes(account_id)
    request_id = str(uuid4())
    headers = {
        "authorization": "Bearer valid",
        "idempotency-key": "candidate-upload-001",
        "content-type": "application/pdf",
        "x-request-id": request_id,
    }
    with _client(frozenset({"preparation:write", "preparation:read"}), service) as client:
        uploaded = client.post(
            f"/api/v1/preparations/{service.item.preparation_id}/documents/cv/upload",
            content=b"%PDF-1.7\nsynthetic\n%%EOF",
            headers=headers,
        )
        status_response = client.get(
            f"/api/v1/preparations/{service.item.preparation_id}/document-intakes/"
            f"{service.item.intake_id}",
            headers={"authorization": "Bearer valid"},
        )

        pasted = client.post(
            f"/api/v1/preparations/{service.item.preparation_id}/documents/job_description/paste",
            content=b"Synthetic role description",
            headers={
                "authorization": "Bearer valid",
                "idempotency-key": "candidate-paste-001",
                "content-type": "text/plain; charset=utf-8",
            },
        )

    assert uploaded.status_code == 201
    assert uploaded.headers["location"].endswith(str(service.item.intake_id))
    assert uploaded.headers["etag"] == '"2"'
    assert uploaded.headers["cache-control"] == "no-store"
    assert uploaded.json()["status"] == "completed"
    assert status_response.status_code == 200
    assert status_response.headers["cache-control"] == "no-store"
    assert pasted.status_code == 201
    assert pasted.json()["source_kind"] == "paste"
    assert pasted.json()["declared_media_type"] == "text/plain"
    assert service.submissions[0][4] == b"%PDF-1.7\nsynthetic\n%%EOF"
    assert service.submissions[0][5:] == ("candidate-upload-001", request_id)


@pytest.mark.parametrize(
    ("intake_status", "created", "expected_status", "retry_after"),
    [
        ("completed", False, 200, None),
        ("processing", False, 202, "5"),
        ("scan_failed", True, 202, "5"),
        ("rejected", True, 422, None),
    ],
)
def test_submit_http_status_reflects_durable_intake_state(
    intake_status: str,
    created: bool,
    expected_status: int,
    retry_after: str | None,
) -> None:
    service = ControlledIntakes(uuid4(), status=intake_status, created=created)
    with _client(frozenset({"preparation:write"}), service) as client:
        response = client.post(
            f"/api/v1/preparations/{service.item.preparation_id}/documents/cv/upload",
            content=b"%PDF-1.7\nsynthetic\n%%EOF",
            headers={
                "authorization": "Bearer valid",
                "idempotency-key": "state-contract-001",
                "content-type": "application/pdf",
            },
        )

    assert response.status_code == expected_status
    assert response.headers.get("retry-after") == retry_after
    assert response.json()["retryable"] is (intake_status == "scan_failed")


def test_upload_boundary_rejects_unsupported_or_oversized_bodies_before_service() -> None:
    service = ControlledIntakes(uuid4())
    path = f"/api/v1/preparations/{service.item.preparation_id}/documents/cv/upload"
    base_headers = {
        "authorization": "Bearer valid",
        "idempotency-key": "boundary-check-001",
    }
    with _client(frozenset({"preparation:write"}), service) as client:
        unsupported = client.post(
            path,
            content=b"content",
            headers={**base_headers, "content-type": "image/png"},
        )
        encoded = client.post(
            path,
            content=b"content",
            headers={
                **base_headers,
                "content-type": "text/plain",
                "content-encoding": "gzip",
            },
        )
        oversized = client.post(
            path,
            content=b"x" * 1_025,
            headers={**base_headers, "content-type": "text/plain"},
        )
        missing_key = client.post(
            path,
            content=b"content",
            headers={"authorization": "Bearer valid", "content-type": "text/plain"},
        )
        wrong_paste_charset = client.post(
            path.replace("/upload", "/paste"),
            content=b"content",
            headers={**base_headers, "content-type": "text/plain; charset=iso-8859-1"},
        )
        missing_media_type = client.post(
            path,
            content=b"content",
            headers={
                "authorization": "Bearer valid",
                "idempotency-key": "missing-media-type-001",
            },
        )
        malformed_length = client.post(
            path,
            content=b"content",
            headers={
                **base_headers,
                "content-type": "text/plain",
                "content-length": "invalid",
            },
        )
        negative_length = client.post(
            path,
            content=b"content",
            headers={
                **base_headers,
                "content-type": "text/plain",
                "content-length": "-1",
            },
        )

    assert unsupported.status_code == 415
    assert encoded.status_code == 415
    assert oversized.status_code == 413
    assert missing_key.status_code == 422
    assert wrong_paste_charset.status_code == 415
    assert missing_media_type.status_code == 415
    assert malformed_length.status_code == 400
    assert negative_length.status_code == 400
    assert service.submissions == []


@pytest.mark.asyncio
async def test_chunked_body_limit_is_enforced_without_content_length() -> None:
    chunks = iter((b"a" * 700, b"b" * 400))

    async def receive() -> dict[str, object]:
        try:
            chunk = next(chunks)
        except StopIteration:
            return {"type": "http.request", "body": b"", "more_body": False}
        return {"type": "http.request", "body": chunk, "more_body": True}

    request = Request(
        {
            "type": "http",
            "method": "POST",
            "path": "/upload",
            "headers": [],
        },
        receive,
    )
    with pytest.raises(IntakePayloadTooLargeError):
        await _bounded_body(request, 1_024)


def test_intake_routes_require_correct_scopes() -> None:
    service = ControlledIntakes(uuid4())
    upload_path = f"/api/v1/preparations/{service.item.preparation_id}/documents/cv/upload"
    status_path = (
        f"/api/v1/preparations/{service.item.preparation_id}/document-intakes/"
        f"{service.item.intake_id}"
    )
    headers = {
        "authorization": "Bearer valid",
        "idempotency-key": "scope-check-001",
        "content-type": "application/pdf",
    }
    with _client(frozenset(), service) as client:
        upload = client.post(upload_path, content=b"%PDF-1.7\nsynthetic\n%%EOF", headers=headers)
        status_response = client.get(
            status_path,
            headers={"authorization": "Bearer valid"},
        )

    assert upload.status_code == 403
    assert status_response.status_code == 403


@pytest.mark.parametrize(
    ("error", "expected_status"),
    [
        (CandidateDocumentIntakeNotFoundError("private missing detail"), 404),
        (CandidateDocumentIntakeConflictError("private conflict detail"), 409),
        (CandidateDocumentIntakeUnavailableError("private dependency detail"), 503),
        (ValueError("private validation detail"), 422),
    ],
)
def test_intake_failures_map_to_safe_problem_responses(
    error: Exception,
    expected_status: int,
) -> None:
    service = ControlledIntakes(uuid4(), error=error)
    with _client(frozenset({"preparation:write"}), service) as client:
        response = client.post(
            f"/api/v1/preparations/{service.item.preparation_id}/documents/cv/upload",
            content=b"%PDF-1.7\nsynthetic\n%%EOF",
            headers={
                "authorization": "Bearer valid",
                "idempotency-key": "failure-map-001",
                "content-type": "application/pdf",
            },
        )

    assert response.status_code == expected_status
    assert "private" not in response.text


def test_status_failure_maps_to_safe_problem_response() -> None:
    service = ControlledIntakes(
        uuid4(),
        error=CandidateDocumentIntakeNotFoundError("private missing detail"),
    )
    with _client(frozenset({"preparation:read"}), service) as client:
        response = client.get(
            f"/api/v1/preparations/{service.item.preparation_id}/document-intakes/"
            f"{service.item.intake_id}",
            headers={"authorization": "Bearer valid"},
        )

    assert response.status_code == 404
    assert "private" not in response.text


@pytest.mark.asyncio
@pytest.mark.parametrize(
    (
        "document_type",
        "source_kind",
        "media_type",
        "content",
        "idempotency_key",
        "error_type",
    ),
    [
        ("portfolio", "upload", "application/pdf", b"content", "valid-key-001", ValueError),
        ("cv", "remote_url", "application/pdf", b"content", "valid-key-001", ValueError),
        ("cv", "upload", "image/png", b"content", "valid-key-001", UploadValidationError),
        (
            "cv",
            "paste",
            "application/pdf",
            b"content",
            "valid-key-001",
            UploadValidationError,
        ),
        ("cv", "paste", "text/plain", b"", "valid-key-001", UploadValidationError),
        ("cv", "paste", "text/plain", b"content", "short", ValueError),
    ],
)
async def test_service_rejects_invalid_contract_before_database_access(
    document_type: str,
    source_kind: str,
    media_type: str,
    content: bytes,
    idempotency_key: str,
    error_type: type[Exception],
) -> None:
    service = CandidateDocumentIntakeService(
        cast(DatabaseRuntime, ReadyDatabase()),
        cast(object, object()),  # type: ignore[arg-type]
        cast(object, object()),  # type: ignore[arg-type]
    )
    with pytest.raises(error_type):
        await service.submit(
            uuid4(),
            uuid4(),
            cast(CandidateDocumentType, document_type),
            cast(CandidateDocumentSource, source_kind),
            media_type,
            content,
            idempotency_key,
            None,
        )


@pytest.mark.asyncio
async def test_fail_closed_intake_boundary_and_builder() -> None:
    service = FailClosedCandidateDocumentIntakeService()
    account_id = uuid4()
    preparation_id = uuid4()
    with pytest.raises(CandidateDocumentIntakeUnavailableError):
        await service.submit(
            account_id,
            preparation_id,
            "cv",
            "paste",
            "text/plain",
            b"Synthetic CV",
            "fail-closed-001",
            None,
        )
    with pytest.raises(CandidateDocumentIntakeUnavailableError):
        await service.get_intake(account_id, preparation_id, uuid4())
    assert (
        await service.export_account_intake_metadata(
            cast(AsyncSession, object()), account_id=account_id
        )
        == []
    )
    assert (
        await service.erase_account_intake_metadata(
            cast(AsyncSession, object()), account_id=account_id
        )
        == 0
    )

    disabled = build_candidate_document_intakes(
        Settings(environment="test", privacy_enabled=False),
        cast(DatabaseRuntime, ReadyDatabase()),
        cast(object, object()),  # type: ignore[arg-type]
        cast(object, object()),  # type: ignore[arg-type]
    )
    assert isinstance(disabled, FailClosedCandidateDocumentIntakeService)
    enabled = build_candidate_document_intakes(
        Settings(environment="test").model_copy(
            update={"privacy_enabled": True, "file_security_enabled": True}
        ),
        cast(DatabaseRuntime, ReadyDatabase()),
        cast(object, object()),  # type: ignore[arg-type]
        cast(object, object()),  # type: ignore[arg-type]
    )
    assert isinstance(enabled, CandidateDocumentIntakeService)
