from datetime import UTC, datetime, timedelta
from typing import cast
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession

from ai_interviewer.candidate_inputs.documents import (
    CandidateDocumentNotFoundError,
    CandidateDocumentRecord,
    CandidateDocumentRuntime,
    CandidateDocumentService,
    CandidateDocumentUnavailableError,
    CandidateDocumentVersionRecord,
    FailClosedCandidateDocumentService,
    build_candidate_documents,
)
from ai_interviewer.core.config import Settings
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


def _document() -> CandidateDocumentRecord:
    now = datetime.now(UTC)
    return CandidateDocumentRecord(
        document_id=uuid4(),
        preparation_id=uuid4(),
        document_type="cv",
        latest_version_number=2,
        aggregate_version=2,
        created_at=now - timedelta(minutes=2),
        updated_at=now,
        versions=(
            CandidateDocumentVersionRecord(
                version_id=uuid4(),
                file_asset_id=uuid4(),
                version_number=1,
                source_kind="upload",
                media_type="application/pdf",
                content_length=42,
                content_sha256="a" * 64,
                created_at=now - timedelta(minutes=2),
                retain_until=now + timedelta(days=30),
            ),
            CandidateDocumentVersionRecord(
                version_id=uuid4(),
                file_asset_id=uuid4(),
                version_number=2,
                source_kind="paste",
                media_type="text/plain",
                content_length=21,
                content_sha256="b" * 64,
                created_at=now,
                retain_until=now + timedelta(days=30),
            ),
        ),
    )


class ControlledCandidateDocuments:
    def __init__(self, account_id: UUID, error: Exception | None = None) -> None:
        self.account_id = account_id
        self.error = error
        self.item = _document()

    def _raise(self) -> None:
        if self.error is not None:
            raise self.error

    async def attach_released_asset(self, *args: object, **kwargs: object) -> object:
        del args, kwargs
        self._raise()
        raise AssertionError("the read-only API must not attach document versions")

    async def list_documents(
        self,
        account_id: UUID,
        preparation_id: UUID,
    ) -> tuple[CandidateDocumentRecord, ...]:
        assert account_id == self.account_id
        assert preparation_id == self.item.preparation_id
        self._raise()
        return (self.item,)

    async def get_document(
        self,
        account_id: UUID,
        preparation_id: UUID,
        document_id: UUID,
    ) -> CandidateDocumentRecord:
        assert account_id == self.account_id
        assert preparation_id == self.item.preparation_id
        assert document_id == self.item.document_id
        self._raise()
        return self.item

    async def export_account_document_metadata(
        self,
        session: object,
        *,
        account_id: UUID,
    ) -> list[dict[str, object]]:
        del session, account_id
        return []

    async def erase_account_document_metadata(
        self,
        session: object,
        *,
        account_id: UUID,
    ) -> int:
        del session, account_id
        return 0

    async def release_file_asset_reference(
        self,
        session: object,
        *,
        file_asset_id: UUID,
    ) -> int:
        del session, file_asset_id
        return 0


def _client(
    scopes: frozenset[str],
    service: ControlledCandidateDocuments | FailClosedCandidateDocumentService,
) -> TestClient:
    account_id = (
        service.account_id if isinstance(service, ControlledCandidateDocuments) else uuid4()
    )
    return TestClient(
        create_app(
            Settings(environment="test", allowed_hosts=("testserver",)),
            database=cast(DatabaseRuntime, ReadyDatabase()),
            authentication=ControlledAuthentication(Principal(account_id, scopes)),
            candidate_documents=cast(CandidateDocumentRuntime, service),
        )
    )


def test_list_and_detail_expose_only_owned_version_metadata() -> None:
    service = ControlledCandidateDocuments(uuid4())
    headers = {"authorization": "Bearer valid"}
    with _client(frozenset({"preparation:read"}), service) as client:
        listed = client.get(
            f"/api/v1/preparations/{service.item.preparation_id}/documents",
            headers=headers,
        )
        detail = client.get(
            f"/api/v1/preparations/{service.item.preparation_id}/documents/"
            f"{service.item.document_id}",
            headers=headers,
        )

    assert listed.status_code == 200
    assert listed.json()["items"][0]["latest_version_number"] == 2
    assert [item["version_number"] for item in detail.json()["versions"]] == [1, 2]
    assert detail.headers["etag"] == '"2"'
    serialized = detail.text
    assert "object_key" not in serialized
    assert "privacy_policy_version_id" not in serialized
    assert "legal_basis" not in serialized


def test_document_reads_require_scope_and_map_failures_without_leaking_details() -> None:
    service = ControlledCandidateDocuments(uuid4())
    path = (
        f"/api/v1/preparations/{service.item.preparation_id}/documents/{service.item.document_id}"
    )
    with _client(frozenset(), service) as client:
        forbidden = client.get(path, headers={"authorization": "Bearer valid"})
    assert forbidden.status_code == 403

    cases = (
        (CandidateDocumentNotFoundError("private database detail"), 404),
        (CandidateDocumentUnavailableError("private dependency detail"), 503),
    )
    for error, expected_status in cases:
        failing = ControlledCandidateDocuments(service.account_id, error)
        failing.item = service.item
        with _client(frozenset({"preparation:read"}), failing) as client:
            response = client.get(path, headers={"authorization": "Bearer valid"})
        assert response.status_code == expected_status
        assert "private" not in response.text


@pytest.mark.asyncio
async def test_fail_closed_boundary_rejects_commands_but_keeps_lifecycle_noops_safe() -> None:
    service = FailClosedCandidateDocumentService()
    account_id = uuid4()
    preparation_id = uuid4()
    document_id = uuid4()
    file_asset_id = uuid4()
    commands = (
        service.attach_released_asset(
            account_id,
            preparation_id,
            "cv",
            file_asset_id,
            "upload",
            None,
        ),
        service.list_documents(account_id, preparation_id),
        service.get_document(account_id, preparation_id, document_id),
    )
    for command in commands:
        with pytest.raises(CandidateDocumentUnavailableError):
            await command

    assert (
        await service.export_account_document_metadata(
            cast(AsyncSession, object()), account_id=account_id
        )
        == []
    )
    assert (
        await service.erase_account_document_metadata(
            cast(AsyncSession, object()), account_id=account_id
        )
        == 0
    )
    assert (
        await service.release_file_asset_reference(
            cast(AsyncSession, object()), file_asset_id=file_asset_id
        )
        == 0
    )


@pytest.mark.asyncio
async def test_builder_and_command_codes_fail_closed_before_database_access() -> None:
    disabled = build_candidate_documents(
        Settings(environment="test", privacy_enabled=False),
        cast(DatabaseRuntime, ReadyDatabase()),
    )
    assert isinstance(disabled, FailClosedCandidateDocumentService)

    service = CandidateDocumentService(cast(DatabaseRuntime, ReadyDatabase()))
    with pytest.raises(ValueError, match="document_type"):
        await service.attach_released_asset(
            uuid4(),
            uuid4(),
            "portfolio",  # type: ignore[arg-type]
            uuid4(),
            "upload",
            None,
        )
    with pytest.raises(ValueError, match="source_kind"):
        await service.attach_released_asset(
            uuid4(),
            uuid4(),
            "cv",
            uuid4(),
            "remote_url",  # type: ignore[arg-type]
            None,
        )
