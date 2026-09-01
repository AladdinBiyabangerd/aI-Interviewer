import base64
import json
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import cast
from uuid import uuid4

import pytest
from pydantic import SecretStr
from sqlalchemy.ext.asyncio import AsyncSession

from ai_interviewer.candidate_inputs.source_text_models import MAX_SOURCE_TEXT_CHARACTERS
from ai_interviewer.candidate_inputs.source_texts import (
    CandidateSourceTextConflictError,
    CandidateSourceTextService,
    CandidateSourceTextUnavailableError,
    FailClosedCandidateSourceTextService,
    ParserExecutionIdentity,
    build_candidate_source_texts,
)
from ai_interviewer.core.config import Settings
from ai_interviewer.core.crypto import ApplicationKeyring, KeyringError
from ai_interviewer.persistence.database import DatabaseRuntime
from tests.fakes import ReadyDatabase


def _keyring_document() -> str:
    def entry(key_id: str, purpose: str, marker: bytes) -> dict[str, str]:
        return {
            "id": key_id,
            "purpose": purpose,
            "material": base64.b64encode(marker * 32).decode(),
        }

    return json.dumps(
        {
            "version": 1,
            "active": {
                "field_encryption": "field-v1",
                "manifest_hmac": "manifest-v1",
                "subject_hmac": "subject-v1",
            },
            "keys": [
                entry("field-v1", "field_encryption", b"f"),
                entry("manifest-v1", "manifest_hmac", b"m"),
                entry("subject-v1", "subject_hmac", b"s"),
            ],
        }
    )


def _service() -> CandidateSourceTextService:
    return CandidateSourceTextService(
        cast(DatabaseRuntime, ReadyDatabase()),
        ApplicationKeyring.from_secret(SecretStr(_keyring_document())),
    )


class _FixedKeyring:
    def __init__(self, *, content: str | None = None, fail_decryption: bool = False) -> None:
        self._content = content
        self._fail_decryption = fail_decryption

    def decrypt_field(self, _encrypted: object, *, aad: bytes) -> str:
        del aad
        if self._fail_decryption:
            raise KeyringError("synthetic decryption failure")
        assert self._content is not None
        return self._content

    def verify_hmac(
        self,
        _purpose: str,
        *,
        key_id: str,
        data: bytes,
        digest: str,
    ) -> bool:
        del key_id, data, digest
        return False


def _stored_version(
    content: str = "expected content",
) -> tuple[
    SimpleNamespace,
    SimpleNamespace,
    SimpleNamespace,
]:
    source_text_id = uuid4()
    owner_id = uuid4()
    document_version_id = uuid4()
    source_text = SimpleNamespace(id=source_text_id, owner_id=owner_id)
    document_version = SimpleNamespace(id=document_version_id, owner_id=owner_id)
    version = SimpleNamespace(
        id=uuid4(),
        source_text_id=source_text_id,
        owner_id=owner_id,
        version_number=1,
        origin="user_correction",
        previous_version_id=None,
        parser_release_policy_id=None,
        parser_adapter=None,
        parser_version=None,
        isolation_profile=None,
        character_count=len(content),
        utf8_byte_count=len(content.encode()),
        line_count=1,
        content_digest="a" * 64,
        content_digest_key_id="subject-v1",
        content_encryption_key_id="field-v1",
        content_nonce=b"n" * 12,
        content_ciphertext=b"ciphertext",
        created_at=datetime.now(UTC),
    )
    return source_text, document_version, version


@pytest.mark.parametrize(
    ("keyring", "message"),
    [
        (_FixedKeyring(fail_decryption=True), "decryption"),
        (_FixedKeyring(content="unexpected content"), "integrity"),
    ],
)
def test_source_text_version_record_fails_closed_on_crypto_or_integrity_error(
    keyring: _FixedKeyring,
    message: str,
) -> None:
    source_text, document_version, version = _stored_version()
    service = CandidateSourceTextService(
        cast(DatabaseRuntime, ReadyDatabase()),
        cast(ApplicationKeyring, keyring),
    )

    with pytest.raises(CandidateSourceTextUnavailableError, match=message):
        service._version_record(source_text, document_version, version)


class _Rows:
    def __init__(self, values: list[object]) -> None:
        self._values = values

    def all(self) -> list[object]:
        return self._values


class _RecordSession:
    def __init__(self, document_version: object | None, versions: list[object]) -> None:
        self._document_version = document_version
        self._versions = versions

    async def get(self, _model: object, _identifier: object) -> object | None:
        return self._document_version

    async def scalars(self, _statement: object) -> _Rows:
        return _Rows(self._versions)


@pytest.mark.asyncio
async def test_source_text_record_rejects_missing_or_incomplete_lineage() -> None:
    source_text, document_version, _ = _stored_version()
    source_text.document_version_id = document_version.id
    source_text.latest_version_number = 1
    source_text.version = 1
    source_text.created_at = datetime.now(UTC)
    source_text.updated_at = source_text.created_at

    service = _service()
    with pytest.raises(CandidateSourceTextUnavailableError, match="lineage is unavailable"):
        await service._record(cast(AsyncSession, _RecordSession(None, [])), source_text)
    with pytest.raises(CandidateSourceTextUnavailableError, match="lineage is incomplete"):
        await service._record(
            cast(AsyncSession, _RecordSession(document_version, [])),
            source_text,
        )


def _correctable_snapshot() -> tuple[
    SimpleNamespace,
    SimpleNamespace,
    SimpleNamespace,
    SimpleNamespace,
]:
    now = datetime.now(UTC)
    privacy_policy_id = uuid4()
    parser_policy_id = uuid4()
    document_version = SimpleNamespace(
        version_number=1,
        retain_until=now + timedelta(days=1),
        parser_release_policy_id=parser_policy_id,
        privacy_policy_version_id=privacy_policy_id,
        jurisdiction_code="AZERBAIJAN",
        media_type="text/plain",
        content_length=10,
        content_sha256="a" * 64,
    )
    preparation = SimpleNamespace(
        status="draft",
        retain_until=now + timedelta(days=1),
        retention_action="delete",
        privacy_policy_version_id=privacy_policy_id,
        jurisdiction_code="AZERBAIJAN",
    )
    document = SimpleNamespace(latest_version_number=1)
    asset = SimpleNamespace(
        status="released",
        released_object_key="released/test",
        released_version_id="version-1",
        released_at=now,
        parser_release_policy_id=parser_policy_id,
        privacy_policy_version_id=privacy_policy_id,
        jurisdiction_code="AZERBAIJAN",
        data_category="candidate_document",
        purpose="interview_preparation",
        content_sha256="a" * 64,
        content_length=10,
        media_type="text/plain",
        retain_until=document_version.retain_until,
        retention_action="delete",
    )
    return preparation, document, document_version, asset


@pytest.mark.parametrize(
    ("target", "attribute", "value", "message"),
    [
        ("preparation", "status", "archived", "archived"),
        ("preparation", "retain_until", datetime.min.replace(tzinfo=UTC), "privacy snapshot"),
        ("document", "latest_version_number", 2, "latest document version"),
        (
            "document_version",
            "retain_until",
            datetime.min.replace(tzinfo=UTC),
            "retention deadline",
        ),
    ],
)
def test_correctable_snapshot_rejects_each_unsafe_lineage(
    target: str,
    attribute: str,
    value: object,
    message: str,
) -> None:
    preparation, document, document_version, _ = _correctable_snapshot()
    objects = {
        "preparation": preparation,
        "document": document,
        "document_version": document_version,
    }
    setattr(objects[target], attribute, value)

    with pytest.raises(CandidateSourceTextConflictError, match=message):
        CandidateSourceTextService._require_correctable_document(
            preparation,
            document,
            document_version,
            datetime.now(UTC),
        )


@pytest.mark.parametrize(
    ("target", "attribute", "value", "message"),
    [
        ("preparation", "status", "archived", "archived"),
        ("preparation", "retain_until", datetime.min.replace(tzinfo=UTC), "privacy snapshot"),
        ("document", "latest_version_number", 2, "latest document version"),
        (
            "document_version",
            "retain_until",
            datetime.min.replace(tzinfo=UTC),
            "retention deadline",
        ),
        ("asset", "status", "quarantined", "exact released asset"),
    ],
)
def test_processable_snapshot_rejects_each_unsafe_lineage(
    target: str,
    attribute: str,
    value: object,
    message: str,
) -> None:
    preparation, document, document_version, asset = _correctable_snapshot()
    objects = {
        "preparation": preparation,
        "document": document,
        "document_version": document_version,
        "asset": asset,
    }
    setattr(objects[target], attribute, value)

    with pytest.raises(CandidateSourceTextConflictError, match=message):
        CandidateSourceTextService._require_processable_document(
            preparation,
            document,
            document_version,
            asset,
            datetime.now(UTC),
        )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("content", "message"),
    [
        (cast(str, 123), "Unicode text"),
        ("", "empty"),
        (" \n\t", "empty"),
        ("line one\r\nline two", "LF newlines"),
        ("line one\x00line two", "unsafe Unicode"),
        ("line one\u202eline two", "unsafe Unicode"),
        ("x" * (MAX_SOURCE_TEXT_CHARACTERS + 1), "character limit"),
        ("😀" * 500_001, "character limit"),
    ],
    ids=(
        "not-text",
        "empty",
        "whitespace",
        "crlf",
        "nul",
        "bidi-control",
        "character-limit",
        "unicode-limit",
    ),
)
async def test_source_text_validation_fails_before_database_access(
    content: str,
    message: str,
) -> None:
    with pytest.raises(ValueError, match=message):
        await _service().store_parser_extraction(
            uuid4(),
            uuid4(),
            content,
            ParserExecutionIdentity(uuid4(), "parser", "1", "no-network-v1"),
            None,
        )


@pytest.mark.asyncio
async def test_parser_identity_validation_fails_before_database_access() -> None:
    with pytest.raises(ValueError, match="parser_adapter"):
        await _service().store_parser_extraction(
            uuid4(),
            uuid4(),
            "valid text",
            ParserExecutionIdentity(uuid4(), " parser ", "1", "no-network-v1"),
            None,
        )


@pytest.mark.asyncio
async def test_correction_content_validation_fails_before_database_access() -> None:
    with pytest.raises(ValueError, match="empty"):
        await _service().append_correction(uuid4(), uuid4(), uuid4(), "   ", 1, None)
    with pytest.raises(ValueError, match="LF newlines"):
        await _service().append_correction(
            uuid4(),
            uuid4(),
            uuid4(),
            "one\r\ntwo",
            1,
            None,
        )


@pytest.mark.asyncio
async def test_source_text_builder_and_disabled_runtime_fail_closed() -> None:
    disabled = build_candidate_source_texts(
        Settings(_env_file=None, environment="test"),
        cast(DatabaseRuntime, ReadyDatabase()),
    )
    assert isinstance(disabled, FailClosedCandidateSourceTextService)

    with pytest.raises(CandidateSourceTextUnavailableError):
        await disabled.store_parser_extraction(
            uuid4(),
            uuid4(),
            "valid text",
            ParserExecutionIdentity(uuid4(), "parser", "1", "no-network-v1"),
            None,
        )
    with pytest.raises(CandidateSourceTextUnavailableError):
        await disabled.get_source_text(uuid4(), uuid4(), uuid4())
    with pytest.raises(CandidateSourceTextUnavailableError):
        await disabled.append_correction(uuid4(), uuid4(), uuid4(), "valid text", 1, None)
    # Export must degrade gracefully (empty, not raising) so a disabled subsystem
    # never breaks another account's privacy export request.
    assert (
        await disabled.export_account_source_text_metadata(
            cast(AsyncSession, object()),
            account_id=uuid4(),
        )
        == []
    )

    enabled_settings = Settings(_env_file=None, environment="test").model_copy(
        update={
            "privacy_enabled": True,
            "file_security_enabled": True,
            "privacy_keyring": SecretStr(_keyring_document()),
        }
    )
    enabled = build_candidate_source_texts(
        enabled_settings,
        cast(DatabaseRuntime, ReadyDatabase()),
    )
    assert isinstance(enabled, CandidateSourceTextService)
