from datetime import UTC, datetime
from typing import cast
from uuid import UUID, uuid4

from fastapi.testclient import TestClient

from ai_interviewer.candidate_inputs.source_texts import (
    CandidateSourceTextConflictError,
    CandidateSourceTextNotFoundError,
    CandidateSourceTextPreconditionError,
    CandidateSourceTextRecord,
    CandidateSourceTextRuntime,
    CandidateSourceTextUnavailableError,
    CandidateSourceTextVersionRecord,
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


def _record(
    *, aggregate_version: int = 1, content: str = "parsed cv text"
) -> CandidateSourceTextRecord:
    now = datetime(2026, 8, 30, tzinfo=UTC)
    version = CandidateSourceTextVersionRecord(
        text_version_id=uuid4(),
        version_number=aggregate_version,
        origin="parser_extraction" if aggregate_version == 1 else "user_correction",
        previous_version_id=None if aggregate_version == 1 else uuid4(),
        parser_release_policy_id=uuid4() if aggregate_version == 1 else None,
        parser_adapter="isolated-text-parser" if aggregate_version == 1 else None,
        parser_version="1" if aggregate_version == 1 else None,
        isolation_profile="no-network-readonly-v1" if aggregate_version == 1 else None,
        character_count=len(content),
        utf8_byte_count=len(content.encode()),
        line_count=1,
        created_at=now,
        content=content,
    )
    return CandidateSourceTextRecord(
        source_text_id=uuid4(),
        document_version_id=uuid4(),
        latest_version_number=aggregate_version,
        aggregate_version=aggregate_version,
        created_at=now,
        updated_at=now,
        versions=(version,),
    )


class ControlledSourceTexts:
    def __init__(self, account_id: UUID, error: Exception | None = None) -> None:
        self.account_id = account_id
        self.error = error
        self.item = _record()
        self.correction_calls: list[tuple[UUID, UUID, UUID, str, int]] = []

    def _raise(self) -> None:
        if self.error is not None:
            raise self.error

    async def store_parser_extraction(self, *args: object, **kwargs: object) -> object:
        del args, kwargs
        self._raise()
        raise AssertionError("the display/correction API must not run extraction")

    async def get_source_text(
        self,
        account_id: UUID,
        preparation_id: UUID,
        document_version_id: UUID,
    ) -> CandidateSourceTextRecord:
        assert account_id == self.account_id
        assert document_version_id == self.item.document_version_id
        self._raise()
        return self.item

    async def append_correction(
        self,
        account_id: UUID,
        preparation_id: UUID,
        document_version_id: UUID,
        content: str,
        expected_version: int,
        request_id: str | None,
        *,
        now: datetime | None = None,
    ) -> CandidateSourceTextRecord:
        del now
        assert account_id == self.account_id
        assert document_version_id == self.item.document_version_id
        self.correction_calls.append(
            (account_id, preparation_id, document_version_id, content, expected_version)
        )
        self._raise()
        self.item = _record(aggregate_version=self.item.aggregate_version + 1, content=content)
        return self.item


def _client(scopes: frozenset[str], service: ControlledSourceTexts) -> TestClient:
    return TestClient(
        create_app(
            Settings(environment="test", allowed_hosts=("testserver",)),
            database=cast(DatabaseRuntime, ReadyDatabase()),
            authentication=ControlledAuthentication(Principal(service.account_id, scopes)),
            candidate_source_texts=cast(CandidateSourceTextRuntime, service),
        )
    )


def _path(service: ControlledSourceTexts, preparation_id: UUID | None = None) -> str:
    return (
        f"/api/v1/preparations/{preparation_id or uuid4()}"
        f"/document-versions/{service.item.document_version_id}/source-text"
    )


def test_get_source_text_returns_content_and_etag() -> None:
    service = ControlledSourceTexts(uuid4())
    with _client(frozenset({"preparation:read"}), service) as client:
        response = client.get(_path(service), headers={"authorization": "Bearer valid"})
    assert response.status_code == 200
    assert response.headers["etag"] == '"1"'
    body = response.json()
    assert body["versions"][0]["content"] == "parsed cv text"
    assert body["aggregate_version"] == 1


def test_get_source_text_requires_scope_and_maps_failures() -> None:
    service = ControlledSourceTexts(uuid4())
    with _client(frozenset(), service) as client:
        forbidden = client.get(_path(service), headers={"authorization": "Bearer valid"})
    assert forbidden.status_code == 403

    cases = (
        (CandidateSourceTextNotFoundError("private detail"), 404),
        (CandidateSourceTextUnavailableError("private detail"), 503),
    )
    for error, expected_status in cases:
        failing = ControlledSourceTexts(service.account_id, error)
        with _client(frozenset({"preparation:read"}), failing) as client:
            response = client.get(_path(failing), headers={"authorization": "Bearer valid"})
        assert response.status_code == expected_status
        assert "private" not in response.text


def test_correction_requires_if_match_and_bumps_etag() -> None:
    service = ControlledSourceTexts(uuid4())
    headers = {"authorization": "Bearer valid"}
    with _client(frozenset({"preparation:write"}), service) as client:
        missing = client.put(_path(service), json={"content": "fixed text"}, headers=headers)
        assert missing.status_code == 428

        malformed = client.put(
            _path(service),
            json={"content": "fixed text"},
            headers={**headers, "If-Match": "2"},
        )
        assert malformed.status_code == 400

        applied = client.put(
            _path(service),
            json={"content": "fixed text"},
            headers={**headers, "If-Match": '"1"'},
        )
    assert applied.status_code == 200
    assert applied.headers["etag"] == '"2"'
    assert applied.json()["versions"][0]["content"] == "fixed text"
    assert service.correction_calls[0][3:] == ("fixed text", 1)


def test_correction_maps_precondition_and_conflict_failures() -> None:
    stale = ControlledSourceTexts(uuid4(), CandidateSourceTextPreconditionError("stale"))
    with _client(frozenset({"preparation:write"}), stale) as client:
        response = client.put(
            _path(stale),
            json={"content": "fixed text"},
            headers={"authorization": "Bearer valid", "If-Match": '"1"'},
        )
    assert response.status_code == 412

    conflicted = ControlledSourceTexts(uuid4(), CandidateSourceTextConflictError("archived"))
    with _client(frozenset({"preparation:write"}), conflicted) as client:
        response = client.put(
            _path(conflicted),
            json={"content": "fixed text"},
            headers={"authorization": "Bearer valid", "If-Match": '"1"'},
        )
    assert response.status_code == 409


def test_correction_rejects_invalid_content_body() -> None:
    service = ControlledSourceTexts(uuid4())
    with _client(frozenset({"preparation:write"}), service) as client:
        response = client.put(
            _path(service),
            json={"content": ""},
            headers={"authorization": "Bearer valid", "If-Match": '"1"'},
        )
    assert response.status_code == 422
    assert service.correction_calls == []


def test_correction_requires_scope() -> None:
    service = ControlledSourceTexts(uuid4())
    with _client(frozenset({"preparation:read"}), service) as client:
        response = client.put(
            _path(service),
            json={"content": "fixed text"},
            headers={"authorization": "Bearer valid", "If-Match": '"1"'},
        )
    assert response.status_code == 403
