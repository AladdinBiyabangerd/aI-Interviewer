import asyncio
import base64
import hashlib
import io
import json
import stat
import struct
import zipfile
from datetime import UTC, datetime, timedelta
from email.utils import format_datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from ai_interviewer.core import secrets as secret_delivery
from ai_interviewer.core.config import Settings
from ai_interviewer.core.crypto import ApplicationKeyring, EncryptedValue, KeyringError
from ai_interviewer.core.secrets import SecretFileError, read_secret_file
from ai_interviewer.file_security import validation as upload_validation
from ai_interviewer.file_security.lifecycle import (
    DisabledFileSecurity,
    FileAssetNotFoundError,
    FileSecurityService,
    FileSecurityUnavailableError,
    FileStateConflictError,
    build_file_security,
)
from ai_interviewer.file_security.object_store import (
    ObjectStoreConfigurationError,
    ObjectStoreError,
    S3EncryptedObjectStore,
)
from ai_interviewer.file_security.scanner import (
    ClamAVScanner,
    MalwareScannerError,
    ScannerVersion,
)
from ai_interviewer.file_security.validation import (
    DOCX_MEDIA_TYPE,
    PDF_MEDIA_TYPE,
    TEXT_MEDIA_TYPE,
    UploadValidationError,
    validate_upload,
)
from tests.fakes import ReadyDatabase


def _keyring_document(*, include_old_field_key: bool = False) -> str:
    def key(identifier: str, purpose: str, byte: bytes) -> dict[str, str]:
        return {
            "id": identifier,
            "purpose": purpose,
            "material": base64.b64encode(byte * 32).decode(),
        }

    keys = [
        key("subject-v1", "subject_hmac", b"s"),
        key("field-v1", "field_encryption", b"f"),
        key("manifest-v1", "manifest_hmac", b"m"),
    ]
    if include_old_field_key:
        keys.append(key("field-old", "field_encryption", b"o"))
    return json.dumps(
        {
            "version": 1,
            "active": {
                "subject_hmac": "subject-v1",
                "field_encryption": "field-v1",
                "manifest_hmac": "manifest-v1",
            },
            "keys": keys,
        }
    )


def _keyring() -> ApplicationKeyring:
    from pydantic import SecretStr

    return ApplicationKeyring.from_secret(SecretStr(_keyring_document()))


@pytest.mark.asyncio
async def test_disabled_file_security_is_ready_but_content_fails_closed() -> None:
    disabled = DisabledFileSecurity()
    assert await disabled.is_ready()
    with pytest.raises(FileSecurityUnavailableError):
        await disabled.stage_upload(
            account_id=uuid4(),
            data_category="candidate_document",
            purpose="interview_preparation",
            declared_media_type=PDF_MEDIA_TYPE,
            content=b"%PDF-1.7\nsynthetic\n%%EOF",
        )
    with pytest.raises(FileSecurityUnavailableError):
        await disabled.scan_and_release(
            account_id=uuid4(),
            file_asset_id=uuid4(),
        )
    with pytest.raises(FileSecurityUnavailableError):
        await disabled.read_for_parser(
            account_id=uuid4(),
            file_asset_id=uuid4(),
            parser_adapter="isolated-text-parser",
            parser_version="1",
            isolation_profile="no-network-readonly-v1",
        )
    assert (
        await disabled.schedule_account_deletion(
            None,  # type: ignore[arg-type]
            account_id=uuid4(),
            privacy_request_id=uuid4(),
            retain_until=datetime.now(UTC),
            retention_action="delete",
            now=datetime.now(UTC),
        )
        == 0
    )
    assert not await disabled.has_pending_account_deletion(
        None,  # type: ignore[arg-type]
        privacy_request_id=uuid4(),
    )
    assert (
        await disabled.export_account_metadata(
            None,  # type: ignore[arg-type]
            account_id=uuid4(),
        )
        == []
    )


def test_secret_file_is_bounded_and_trims_one_mount_newline(tmp_path: Path) -> None:
    secret_file = tmp_path / "database-url"
    secret_file.write_text("postgresql://example\n", encoding="utf-8")
    secret_file.chmod(0o600)

    assert read_secret_file(secret_file, hosted=True) == "postgresql://example"

    secret_file.write_bytes(b"x" * 65_537)
    with pytest.raises(SecretFileError, match="65536-byte"):
        read_secret_file(secret_file, hosted=False)


@pytest.mark.parametrize("payload", [b"", b" leading", b"trailing ", b"nul\x00value", b"\xff"])
def test_secret_file_rejects_malformed_values(tmp_path: Path, payload: bytes) -> None:
    secret_file = tmp_path / "secret"
    secret_file.write_bytes(payload)
    secret_file.chmod(0o600)

    with pytest.raises(SecretFileError):
        read_secret_file(secret_file, hosted=False)


def test_secret_file_rejects_relative_production_paths_and_non_files(tmp_path: Path) -> None:
    with pytest.raises(SecretFileError, match="must be absolute"):
        read_secret_file(Path("relative-secret"), hosted=True)
    with pytest.raises(SecretFileError, match=r"unavailable|regular file"):
        read_secret_file(tmp_path, hosted=False)

    repeated_newline = tmp_path / "repeated-newline"
    repeated_newline.write_text("secret\n\n", encoding="utf-8")
    repeated_newline.chmod(0o600)
    with pytest.raises(SecretFileError, match="malformed"):
        read_secret_file(repeated_newline, hosted=False)


def test_secret_file_handles_crlf_and_opaque_read_failures(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    secret_file = tmp_path / "secret"
    secret_file.write_bytes(b"secret\r\n")
    secret_file.chmod(0o600)
    assert read_secret_file(secret_file, hosted=False) == "secret"

    monkeypatch.setattr(secret_delivery.os, "read", lambda *_: (_ for _ in ()).throw(OSError()))
    with pytest.raises(SecretFileError, match="could not be read"):
        read_secret_file(secret_file, hosted=False)


def test_secret_file_defends_against_changed_metadata_and_oversized_reads(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    secret_file = tmp_path / "secret"
    secret_file.write_bytes(b"secret")

    monkeypatch.setattr(
        secret_delivery.os,
        "fstat",
        lambda _: SimpleNamespace(st_mode=stat.S_IFDIR, st_size=1),
    )
    with pytest.raises(SecretFileError, match="regular file"):
        read_secret_file(secret_file, hosted=False)

    monkeypatch.setattr(
        secret_delivery.os,
        "fstat",
        lambda _: SimpleNamespace(st_mode=stat.S_IFREG, st_size=1),
    )
    monkeypatch.setattr(secret_delivery.os, "read", lambda *_: b"x" * 65_537)
    with pytest.raises(SecretFileError, match="65536-byte"):
        read_secret_file(secret_file, hosted=False)


def test_keyring_encrypts_with_aad_and_supports_versioned_hmac() -> None:
    keyring = _keyring()
    encrypted = keyring.encrypt_field("vendor-subject", aad=b"account-and-processor")

    assert encrypted.key_id == "field-v1"
    assert keyring.decrypt_field(encrypted, aad=b"account-and-processor") == "vendor-subject"
    with pytest.raises(KeyringError, match="authentication failed"):
        keyring.decrypt_field(encrypted, aad=b"another-account")

    digest = keyring.hmac_digest("manifest_hmac", b"manifest")
    assert keyring.verify_hmac(
        "manifest_hmac",
        key_id="manifest-v1",
        data=b"manifest",
        digest=digest,
    )
    assert not keyring.verify_hmac(
        "manifest_hmac",
        key_id="missing",
        data=b"manifest",
        digest=digest,
    )


def test_keyring_rejects_wrong_key_sizes_and_unknown_ciphertext() -> None:
    from pydantic import SecretStr

    malformed = json.loads(_keyring_document())
    malformed["keys"][0]["material"] = base64.b64encode(b"short").decode()
    with pytest.raises(KeyringError, match="exactly 32"):
        ApplicationKeyring.from_secret(SecretStr(json.dumps(malformed)))

    with pytest.raises(KeyringError, match="unavailable"):
        _keyring().decrypt_field(
            EncryptedValue(key_id="retired", nonce=b"0" * 12, ciphertext=b"invalid"),
            aad=b"context",
        )

    with pytest.raises(ValueError, match="must not be empty"):
        _keyring().encrypt_field("", aad=b"context")


@pytest.mark.parametrize("document", ["not-json", "[]", "null"])
def test_keyring_rejects_non_object_documents(document: str) -> None:
    from pydantic import SecretStr

    with pytest.raises(KeyringError, match="JSON object"):
        ApplicationKeyring.from_secret(SecretStr(document))


def test_keyring_rejects_missing_active_material_and_wrong_purpose() -> None:
    from pydantic import SecretStr

    missing = json.loads(_keyring_document())
    missing["keys"] = missing["keys"][1:]
    with pytest.raises(KeyringError, match="active privacy key is missing"):
        ApplicationKeyring.from_secret(SecretStr(json.dumps(missing)))

    wrong_purpose = json.loads(_keyring_document())
    wrong_purpose["keys"][0]["purpose"] = "field_encryption"
    with pytest.raises(KeyringError, match="active subject_hmac"):
        ApplicationKeyring.from_secret(SecretStr(json.dumps(wrong_purpose)))


@pytest.mark.parametrize(
    "mutator, error",
    [
        (lambda value: value.update(version=2), "version must be 1"),
        (lambda value: value.pop("active"), "active and keys"),
        (
            lambda value: value["active"].update(subject_hmac="invalid key id"),
            "invalid active key id",
        ),
        (lambda value: value["keys"].append("not-an-object"), "must be objects"),
        (
            lambda value: value["keys"][0].update(id="field-v1"),
            "invalid or duplicated",
        ),
        (
            lambda value: value["keys"][0].update(material="not-base64!"),
            "canonical base64",
        ),
    ],
)
def test_keyring_schema_is_fail_closed(mutator: Any, error: str) -> None:
    from pydantic import SecretStr

    document = json.loads(_keyring_document())
    mutator(document)
    with pytest.raises(KeyringError, match=error):
        ApplicationKeyring.from_secret(SecretStr(json.dumps(document)))


def _validate(content: bytes, media_type: str) -> str:
    return validate_upload(
        content,
        declared_media_type=media_type,
        maximum_bytes=1_000_000,
        maximum_archive_entries=100,
        maximum_archive_uncompressed_bytes=2_000_000,
    ).media_type


def test_upload_validation_checks_bytes_and_safe_docx_containers() -> None:
    assert _validate(b"%PDF-1.7\n%%EOF", PDF_MEDIA_TYPE) == PDF_MEDIA_TYPE
    assert _validate(b"Salam interview", TEXT_MEDIA_TYPE) == TEXT_MEDIA_TYPE

    document = io.BytesIO()
    with zipfile.ZipFile(document, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("[Content_Types].xml", "<Types />")
        archive.writestr("word/document.xml", "<document />")
    assert _validate(document.getvalue(), DOCX_MEDIA_TYPE) == DOCX_MEDIA_TYPE

    with pytest.raises(UploadValidationError, match="media_type_mismatch"):
        _validate(b"%PDF-1.7\n%%EOF", TEXT_MEDIA_TYPE)


def test_upload_validation_rejects_unsafe_archives_and_binary_text() -> None:
    traversal = io.BytesIO()
    with zipfile.ZipFile(traversal, "w") as archive:
        archive.writestr("[Content_Types].xml", "<Types />")
        archive.writestr("word/document.xml", "<document />")
        archive.writestr("../escape", "unsafe")
    with pytest.raises(UploadValidationError, match="unsafe_archive_path"):
        _validate(traversal.getvalue(), DOCX_MEDIA_TYPE)
    with pytest.raises(UploadValidationError, match="binary_content"):
        _validate(b"binary\x00payload", TEXT_MEDIA_TYPE)


def _docx_bytes(
    *extra_entries: tuple[str, bytes],
    compression: int = zipfile.ZIP_DEFLATED,
) -> bytes:
    document = io.BytesIO()
    with zipfile.ZipFile(document, "w", compression=compression) as archive:
        archive.writestr("[Content_Types].xml", b"<Types />")
        archive.writestr("word/document.xml", b"<document />")
        for name, payload in extra_entries:
            archive.writestr(name, payload)
    return document.getvalue()


@pytest.mark.parametrize(
    "content, maximum_entries, maximum_uncompressed, code",
    [
        (b"PK\x03\x04broken", 100, 2_000_000, "invalid_archive"),
        (io.BytesIO().getvalue(), 100, 2_000_000, "invalid_archive"),
        (_docx_bytes(("word/extra.xml", b"x")), 2, 2_000_000, "archive_entry_limit"),
        (_docx_bytes(), 100, 1, "archive_uncompressed_limit"),
        (
            _docx_bytes(("word/script.js", b"safe-looking")),
            100,
            2_000_000,
            "active_archive_content",
        ),
    ],
)
def test_docx_validation_enforces_archive_bounds(
    content: bytes,
    maximum_entries: int,
    maximum_uncompressed: int,
    code: str,
) -> None:
    with pytest.raises(UploadValidationError, match=code):
        upload_validation._validate_docx_archive(
            content,
            maximum_entries=maximum_entries,
            maximum_uncompressed_bytes=maximum_uncompressed,
        )


def test_docx_validation_rejects_duplicates_missing_parts_and_zip_bombs() -> None:
    duplicate = io.BytesIO()
    with zipfile.ZipFile(duplicate, "w") as archive:
        archive.writestr("[Content_Types].xml", b"one")
        with pytest.warns(UserWarning, match="Duplicate name"):
            archive.writestr("[Content_Types].xml", b"two")
        archive.writestr("word/document.xml", b"document")
    with pytest.raises(UploadValidationError, match="unsafe_archive_path"):
        _validate(duplicate.getvalue(), DOCX_MEDIA_TYPE)

    missing_part = io.BytesIO()
    with zipfile.ZipFile(missing_part, "w") as archive:
        archive.writestr("[Content_Types].xml", b"types")
    with pytest.raises(UploadValidationError, match="not_a_docx_container"):
        _validate(missing_part.getvalue(), DOCX_MEDIA_TYPE)

    compressed = _docx_bytes(("word/large.xml", b"0" * 1_100_000))
    with pytest.raises(UploadValidationError, match="archive_compression_ratio"):
        _validate(compressed, DOCX_MEDIA_TYPE)


def test_docx_validation_rejects_encrypted_flags_and_bad_crc() -> None:
    encrypted = bytearray(_docx_bytes(compression=zipfile.ZIP_STORED))
    local_header = encrypted.index(b"PK\x03\x04")
    central_header = encrypted.index(b"PK\x01\x02")
    encrypted[local_header + 6] |= 0x01
    encrypted[central_header + 8] |= 0x01
    with pytest.raises(UploadValidationError, match="encrypted_archive_entry"):
        _validate(bytes(encrypted), DOCX_MEDIA_TYPE)

    valid = _docx_bytes(compression=zipfile.ZIP_STORED)
    with zipfile.ZipFile(io.BytesIO(valid)) as archive:
        info = archive.getinfo("word/document.xml")
        data_offset = info.header_offset + 30 + len(info.filename.encode()) + len(info.extra)
    corrupted = bytearray(valid)
    corrupted[data_offset] ^= 0x01
    with pytest.raises(UploadValidationError, match="archive_crc_failure"):
        _validate(bytes(corrupted), DOCX_MEDIA_TYPE)


@pytest.mark.parametrize(
    "content, media_type, code",
    [
        (b"", TEXT_MEDIA_TYPE, "empty_file"),
        (b"plain", "application/octet-stream", "media_type_not_allowed"),
        (b"%PDF-1.7 without eof", PDF_MEDIA_TYPE, "invalid_pdf_signature"),
        (b"\xff\xfe", TEXT_MEDIA_TYPE, "text_must_be_utf8"),
        (b"control\x01", TEXT_MEDIA_TYPE, "text_contains_control"),
    ],
)
def test_upload_validation_rejects_additional_failure_paths(
    content: bytes,
    media_type: str,
    code: str,
) -> None:
    with pytest.raises(UploadValidationError, match=code):
        _validate(content, media_type)

    if content and media_type in {PDF_MEDIA_TYPE, DOCX_MEDIA_TYPE, TEXT_MEDIA_TYPE}:
        with pytest.raises(UploadValidationError, match="file_too_large"):
            validate_upload(
                content,
                declared_media_type=media_type,
                maximum_bytes=max(1, len(content) - 1),
                maximum_archive_entries=100,
                maximum_archive_uncompressed_bytes=2_000_000,
            )


class _Body:
    def __init__(self, content: bytes) -> None:
        self._content = content

    def read(self, amount: int | None = None) -> bytes:
        return self._content if amount is None else self._content[:amount]


class _S3Fake:
    def __init__(self, content: bytes) -> None:
        self.content = content
        self.put_parameters: dict[str, Any] = {}
        self.deleted: list[dict[str, str]] = []

    def get_bucket_versioning(self, **_: Any) -> dict[str, Any]:
        return {"Status": "Enabled"}

    def get_public_access_block(self, **_: Any) -> dict[str, Any]:
        return {
            "PublicAccessBlockConfiguration": {
                "BlockPublicAcls": True,
                "IgnorePublicAcls": True,
                "BlockPublicPolicy": True,
                "RestrictPublicBuckets": True,
            }
        }

    def get_bucket_encryption(self, **_: Any) -> dict[str, Any]:
        return {
            "ServerSideEncryptionConfiguration": {
                "Rules": [{"ApplyServerSideEncryptionByDefault": {"SSEAlgorithm": "aws:kms"}}]
            }
        }

    def put_object(self, **kwargs: Any) -> dict[str, Any]:
        self.put_parameters = kwargs
        return {"VersionId": "q-version-1"}

    def get_object(self, **_: Any) -> dict[str, Any]:
        return {
            "VersionId": "q-version-1",
            "ContentLength": len(self.content),
            "ServerSideEncryption": "aws:kms",
            "Body": _Body(self.content),
        }

    def copy_object(self, **_: Any) -> dict[str, Any]:
        return {"VersionId": "released-version-1"}

    def list_object_versions(self, **_: Any) -> dict[str, Any]:
        return {
            "IsTruncated": False,
            "Versions": [{"Key": "quarantine/key", "VersionId": "v1"}],
            "DeleteMarkers": [{"Key": "quarantine/key", "VersionId": "d1"}],
        }

    def delete_objects(self, **kwargs: Any) -> dict[str, Any]:
        self.deleted.extend(kwargs["Delete"]["Objects"])
        return {"Deleted": kwargs["Delete"]["Objects"]}


class _ReadyScanner:
    async def is_ready(self, *, now: datetime | None = None) -> bool:
        del now
        return True

    async def scan(self, content: bytes, *, now: datetime | None = None) -> Any:
        del content, now
        raise AssertionError("scan is not expected in this construction test")


@pytest.mark.asyncio
async def test_file_security_builder_selects_disabled_or_configured_runtime() -> None:
    assert isinstance(
        build_file_security(Settings(_env_file=None), ReadyDatabase()),
        DisabledFileSecurity,
    )
    content = b"content"
    store = S3EncryptedObjectStore(
        bucket="private-files",
        region="eu-central-1",
        kms_key_id="alias/files",
        client=_S3Fake(content),
    )
    settings = Settings(
        _env_file=None,
        privacy_enabled=True,
        privacy_keyring=_keyring_document(),
        file_security_enabled=True,
        object_storage_bucket="private-files",
        object_storage_region="eu-central-1",
        object_storage_kms_key_id="alias/files",
        malware_scanner_tcp_host="127.0.0.1",
    )
    runtime = build_file_security(
        settings,
        ReadyDatabase(),
        object_store=store,
        scanner=_ReadyScanner(),
    )
    assert isinstance(runtime, FileSecurityService)
    assert await runtime.is_ready()

    incomplete = settings.model_copy(
        update={
            "object_storage_bucket": None,
            "object_storage_region": None,
            "object_storage_kms_key_id": None,
        }
    )
    with pytest.raises(RuntimeError, match="complete object storage"):
        build_file_security(incomplete, ReadyDatabase())


class _ScalarCollection:
    def __init__(self, values: list[Any]) -> None:
        self._values = values

    def all(self) -> list[Any]:
        return self._values


class _SessionStub:
    def __init__(self, *, scalar_values: list[Any] | None = None, rows: list[Any] | None = None):
        self.scalar_values = list(scalar_values or [])
        self.rows = list(rows or [])

    async def scalar(self, _: Any) -> Any:
        return self.scalar_values.pop(0) if self.scalar_values else None

    async def scalars(self, _: Any) -> _ScalarCollection:
        return _ScalarCollection(self.rows)


@pytest.mark.asyncio
async def test_file_security_internal_lookups_fail_closed() -> None:
    account_id = uuid4()
    asset_id = uuid4()
    task_id = uuid4()
    session = _SessionStub()

    with pytest.raises(FileAssetNotFoundError, match="asset"):
        await FileSecurityService._owned_asset(session, account_id, asset_id)  # type: ignore[arg-type]
    with pytest.raises(FileAssetNotFoundError, match="asset"):
        await FileSecurityService._owned_locked_asset(  # type: ignore[arg-type]
            session,
            account_id,
            asset_id,
        )
    with pytest.raises(FileAssetNotFoundError, match="asset"):
        await FileSecurityService._locked_asset(session, asset_id)  # type: ignore[arg-type]
    with pytest.raises(FileAssetNotFoundError, match="task"):
        await FileSecurityService._locked_task(session, task_id)  # type: ignore[arg-type]

    with pytest.raises(FileStateConflictError, match="exactly one"):
        await FileSecurityService._resolve_parser_policy(  # type: ignore[arg-type]
            session,
            privacy_policy_version_id=uuid4(),
            data_category="candidate_document",
            purpose="interview_preparation",
            media_type=PDF_MEDIA_TYPE,
            now=datetime.now(UTC),
        )
    assert await FileSecurityService._next_scan_attempt(session, asset_id) == 1  # type: ignore[arg-type]
    assert (
        await FileSecurityService._next_scan_attempt(
            _SessionStub(scalar_values=[3]),  # type: ignore[arg-type]
            asset_id,
        )
        == 4
    )


@pytest.mark.asyncio
async def test_file_security_refuses_to_promote_non_clean_assets() -> None:
    service = FileSecurityService(
        database=ReadyDatabase(),  # type: ignore[arg-type]
        object_store=_S3Fake(b"content"),  # type: ignore[arg-type]
        scanner=_ReadyScanner(),
        bucket="private-files",
        kms_key_id="alias/files",
        maximum_upload_bytes=100,
        maximum_archive_entries=10,
        maximum_archive_uncompressed_bytes=1_000,
        maximum_deletion_attempts=3,
        deletion_retry_base_seconds=1,
    )
    with pytest.raises(FileStateConflictError, match="only a clean"):
        await service._promote_clean(  # type: ignore[arg-type]
            SimpleNamespace(status="quarantined", quarantine_version_id=None),
            datetime.now(UTC),
        )


@pytest.mark.asyncio
async def test_s3_adapter_enforces_kms_checksum_and_deletes_every_version() -> None:
    content = b"verified content"
    digest = hashlib.sha256(content).hexdigest()
    client = _S3Fake(content)
    store = S3EncryptedObjectStore(
        bucket="private-files",
        region="eu-central-1",
        kms_key_id="alias/files",
        client=client,
    )

    assert await store.is_ready()
    stored = await store.put_quarantined(
        key="quarantine/key",
        content=content,
        content_type=TEXT_MEDIA_TYPE,
        content_sha256=digest,
    )
    assert stored.version_id == "q-version-1"
    assert client.put_parameters["ServerSideEncryption"] == "aws:kms"
    assert client.put_parameters["SSEKMSKeyId"] == "alias/files"
    assert (
        client.put_parameters["ChecksumSHA256"] == base64.b64encode(bytes.fromhex(digest)).decode()
    )
    assert (
        await store.read_verified(
            key="quarantine/key",
            version_id=stored.version_id,
            expected_sha256=digest,
            maximum_bytes=100,
        )
        == content
    )
    assert await store.delete_all_versions(key="quarantine/key") == 2
    assert {entry["VersionId"] for entry in client.deleted} == {"v1", "d1"}

    with pytest.raises(ObjectStoreError, match="SHA-256"):
        await store.read_verified(
            key="quarantine/key",
            version_id=stored.version_id,
            expected_sha256="0" * 64,
            maximum_bytes=100,
        )


class _InsecureS3Fake(_S3Fake):
    def get_bucket_versioning(self, **_: Any) -> dict[str, Any]:
        return {"Status": "Suspended"}


class _MissingVersionS3Fake(_S3Fake):
    def put_object(self, **kwargs: Any) -> dict[str, Any]:
        self.put_parameters = kwargs
        return {}

    def copy_object(self, **_: Any) -> dict[str, Any]:
        return {}


class _PaginationS3Fake(_S3Fake):
    def __init__(self, content: bytes) -> None:
        super().__init__(content)
        self.pages = 0

    def list_object_versions(self, **_: Any) -> dict[str, Any]:
        self.pages += 1
        if self.pages == 1:
            return {
                "IsTruncated": True,
                "NextKeyMarker": "quarantine/key",
                "NextVersionIdMarker": "v1",
                "Versions": [{"Key": "quarantine/key", "VersionId": "v1"}],
            }
        return {
            "IsTruncated": False,
            "DeleteMarkers": [{"Key": "quarantine/key", "VersionId": "d1"}],
        }


@pytest.mark.asyncio
async def test_s3_bucket_control_verification_fails_closed() -> None:
    store = S3EncryptedObjectStore(
        bucket="private-files",
        region="eu-central-1",
        kms_key_id="alias/files",
        client=_InsecureS3Fake(b"content"),
    )
    assert not await store.is_ready()
    with pytest.raises(ObjectStoreConfigurationError, match="versioning"):
        store._verify_bucket_controls()


@pytest.mark.asyncio
async def test_s3_adapter_promotion_pagination_and_provider_failures() -> None:
    content = b"content"
    digest = hashlib.sha256(content).hexdigest()
    paged = _PaginationS3Fake(content)
    store = S3EncryptedObjectStore(
        bucket="private-files",
        region="eu-central-1",
        kms_key_id="alias/files",
        client=paged,
    )
    promoted = await store.promote_clean(
        source_key="quarantine/key",
        source_version_id="v1",
        destination_key="released/key",
        content_type=TEXT_MEDIA_TYPE,
        content_sha256=digest,
    )
    assert promoted.version_id == "released-version-1"
    assert await store.delete_all_versions(key="quarantine/key") == 2
    assert paged.pages == 2

    missing = S3EncryptedObjectStore(
        bucket="private-files",
        region="eu-central-1",
        kms_key_id="alias/files",
        client=_MissingVersionS3Fake(content),
    )
    with pytest.raises(ObjectStoreConfigurationError, match="versioned"):
        await missing.put_quarantined(
            key="quarantine/key",
            content=content,
            content_type=TEXT_MEDIA_TYPE,
            content_sha256=digest,
        )
    with pytest.raises(ObjectStoreConfigurationError, match="versioned"):
        await missing.promote_clean(
            source_key="quarantine/key",
            source_version_id="v1",
            destination_key="released/key",
            content_type=TEXT_MEDIA_TYPE,
            content_sha256=digest,
        )


@pytest.mark.asyncio
async def test_s3_read_rejects_length_and_encryption_mismatch() -> None:
    content = b"content"
    digest = hashlib.sha256(content).hexdigest()
    client = _S3Fake(content)
    store = S3EncryptedObjectStore(
        bucket="private-files",
        region="eu-central-1",
        kms_key_id="alias/files",
        client=client,
    )
    with pytest.raises(ObjectStoreError, match="length"):
        await store.read_verified(
            key="key",
            version_id="v1",
            expected_sha256=digest,
            maximum_bytes=1,
        )

    original_get = client.get_object

    def unencrypted(**kwargs: Any) -> dict[str, Any]:
        response = original_get(**kwargs)
        response["ServerSideEncryption"] = "AES256"
        return response

    client.get_object = unencrypted  # type: ignore[method-assign]
    with pytest.raises(ObjectStoreError, match="SSE-KMS"):
        await store.read_verified(
            key="key",
            version_id="v1",
            expected_sha256=digest,
            maximum_bytes=100,
        )


def test_s3_bucket_controls_require_public_block_and_kms_rules() -> None:
    client = _S3Fake(b"content")
    store = S3EncryptedObjectStore(
        bucket="private-files",
        region="eu-central-1",
        kms_key_id="alias/files",
        client=client,
    )

    client.get_public_access_block = lambda **_: {  # type: ignore[method-assign]
        "PublicAccessBlockConfiguration": {"BlockPublicAcls": True}
    }
    with pytest.raises(ObjectStoreConfigurationError, match="public-access"):
        store._verify_bucket_controls()

    client.get_public_access_block = _S3Fake(b"").get_public_access_block  # type: ignore[method-assign]
    client.get_bucket_encryption = lambda **_: {  # type: ignore[method-assign]
        "ServerSideEncryptionConfiguration": {"Rules": [None, {"wrong": "shape"}]}
    }
    with pytest.raises(ObjectStoreConfigurationError, match="SSE-KMS"):
        store._verify_bucket_controls()

    client.get_bucket_encryption = lambda **_: {}  # type: ignore[method-assign]
    with pytest.raises(ObjectStoreConfigurationError, match="SSE-KMS"):
        store._verify_bucket_controls()


@pytest.mark.asyncio
async def test_s3_adapter_wraps_provider_errors_and_rejects_bad_body() -> None:
    content = b"content"
    digest = hashlib.sha256(content).hexdigest()
    client = _S3Fake(content)
    store = S3EncryptedObjectStore(
        bucket="private-files",
        region="eu-central-1",
        kms_key_id="alias/files",
        client=client,
    )

    client.get_object = lambda **_: {  # type: ignore[method-assign]
        "ContentLength": len(content) + 1,
        "ServerSideEncryption": "aws:kms",
        "Body": _Body(content),
    }
    with pytest.raises(ObjectStoreError, match="length verification"):
        await store.read_verified(
            key="key",
            version_id="v1",
            expected_sha256=digest,
            maximum_bytes=100,
        )

    def explode(**_: Any) -> dict[str, Any]:
        raise RuntimeError("provider details must not escape")

    client.put_object = explode  # type: ignore[method-assign]
    with pytest.raises(ObjectStoreError, match="upload failed"):
        await store.put_quarantined(
            key="key",
            content=content,
            content_type=TEXT_MEDIA_TYPE,
            content_sha256=digest,
        )

    client.get_object = explode  # type: ignore[method-assign]
    with pytest.raises(ObjectStoreError, match="download failed"):
        await store.read_verified(
            key="key",
            version_id="v1",
            expected_sha256=digest,
            maximum_bytes=100,
        )

    client.copy_object = explode  # type: ignore[method-assign]
    with pytest.raises(ObjectStoreError, match="promotion failed"):
        await store.promote_clean(
            source_key="quarantine/key",
            source_version_id="v1",
            destination_key="released/key",
            content_type=TEXT_MEDIA_TYPE,
            content_sha256=digest,
        )

    client.list_object_versions = explode  # type: ignore[method-assign]
    with pytest.raises(ObjectStoreError, match="deletion failed"):
        await store.delete_all_versions(key="key")

    with pytest.raises(ObjectStoreError, match="SHA-256"):
        await store.put_quarantined(
            key="key",
            content=content,
            content_type=TEXT_MEDIA_TYPE,
            content_sha256="too-short",
        )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "page, error",
    [
        ({"Versions": "wrong"}, "listing is malformed"),
        (
            {
                "Versions": [{"Key": "key", "VersionId": "v1"}],
                "IsTruncated": True,
            },
            "pagination markers",
        ),
    ],
)
async def test_s3_deletion_rejects_malformed_listings(
    page: dict[str, Any],
    error: str,
) -> None:
    client = _S3Fake(b"")
    client.list_object_versions = lambda **_: page  # type: ignore[method-assign]
    store = S3EncryptedObjectStore(
        bucket="private-files",
        region="eu-central-1",
        kms_key_id="alias/files",
        client=client,
    )
    with pytest.raises(ObjectStoreError, match=error):
        await store.delete_all_versions(key="key")


@pytest.mark.asyncio
async def test_s3_deletion_filters_prefixes_and_fails_on_partial_delete() -> None:
    client = _S3Fake(b"")
    client.list_object_versions = lambda **_: {  # type: ignore[method-assign]
        "IsTruncated": False,
        "Versions": [
            "malformed",
            {"Key": "key-suffix", "VersionId": "wrong"},
            {"Key": "key", "VersionId": ""},
            {"Key": "key", "VersionId": "v1"},
        ],
    }
    client.delete_objects = lambda **_: {"Errors": [{"Code": "Denied"}]}  # type: ignore[method-assign]
    store = S3EncryptedObjectStore(
        bucket="private-files",
        region="eu-central-1",
        kms_key_id="alias/files",
        client=client,
    )
    with pytest.raises(ObjectStoreError, match="could not be deleted"):
        await store.delete_all_versions(key="key")


@pytest.mark.asyncio
async def test_clamav_instream_clean_and_infected_contract() -> None:
    now = datetime.now(UTC).replace(microsecond=0)

    async def handle(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        command = await reader.readuntil(b"\0")
        if command == b"zPING\0":
            writer.write(b"PONG\0")
        elif command == b"zVERSION\0":
            version = f"ClamAV 1.4.3/30001/{format_datetime(now)}\0"
            writer.write(version.encode())
        elif command == b"zINSTREAM\0":
            payload = bytearray()
            while True:
                size = struct.unpack("!I", await reader.readexactly(4))[0]
                if size == 0:
                    break
                payload.extend(await reader.readexactly(size))
            response = (
                b"stream: Eicar-Test-Signature FOUND\0" if b"EICAR" in payload else b"stream: OK\0"
            )
            writer.write(response)
        await writer.drain()
        writer.close()

    server = await asyncio.start_server(handle, "127.0.0.1", 0)
    port = server.sockets[0].getsockname()[1]
    scanner = ClamAVScanner(
        maximum_stream_bytes=1_000_000,
        maximum_signature_age=timedelta(hours=1),
        timeout_seconds=2,
        tcp_host="127.0.0.1",
        tcp_port=port,
    )
    try:
        assert await scanner.is_ready(now=now)
        assert (await scanner.scan(b"safe", now=now)).verdict == "clean"
        infected = await scanner.scan(b"EICAR", now=now)
        assert infected.verdict == "infected"
        assert infected.malware_signature_sha256 is not None
        assert "Eicar" not in infected.malware_signature_sha256
    finally:
        server.close()
        await server.wait_closed()


@pytest.mark.asyncio
async def test_clamav_rejects_stale_empty_and_unknown_responses() -> None:
    now = datetime.now(UTC).replace(microsecond=0)

    async def handle(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        command = await reader.readuntil(b"\0")
        if command == b"zPING\0":
            writer.write(b"PONG\0")
        elif command == b"zVERSION\0":
            stale = now - timedelta(days=10)
            writer.write(f"ClamAV 1.4.3/1/{format_datetime(stale)}\0".encode())
        await writer.drain()
        writer.close()

    server = await asyncio.start_server(handle, "127.0.0.1", 0)
    port = server.sockets[0].getsockname()[1]
    scanner = ClamAVScanner(
        maximum_stream_bytes=4,
        maximum_signature_age=timedelta(hours=1),
        timeout_seconds=1,
        tcp_host="127.0.0.1",
        tcp_port=port,
    )
    try:
        assert not await scanner.is_ready(now=now)
        with pytest.raises(MalwareScannerError, match="empty or exceeds"):
            await scanner.scan(b"", now=now)
        with pytest.raises(MalwareScannerError, match="stale"):
            await scanner.scan(b"safe", now=now)
    finally:
        server.close()
        await server.wait_closed()


def test_clamav_requires_exactly_one_transport() -> None:
    parameters = {
        "maximum_stream_bytes": 10,
        "maximum_signature_age": timedelta(hours=1),
        "timeout_seconds": 1,
    }
    with pytest.raises(ValueError, match="exactly one"):
        ClamAVScanner(**parameters)
    with pytest.raises(ValueError, match="exactly one"):
        ClamAVScanner(
            **parameters,
            unix_socket=Path("/run/clamav/clamd.sock"),
            tcp_host="127.0.0.1",
        )


@pytest.mark.asyncio
async def test_clamav_rejects_malformed_version_and_verdicts() -> None:
    now = datetime.now(UTC).replace(microsecond=0)
    scanner = ClamAVScanner(
        maximum_stream_bytes=4,
        maximum_signature_age=timedelta(hours=1),
        timeout_seconds=1,
        tcp_host="127.0.0.1",
    )
    scanner._command = AsyncMock(return_value="malformed")  # type: ignore[method-assign]
    with pytest.raises(MalwareScannerError, match="version response"):
        await scanner._version()
    assert not await scanner.is_ready(now=now)

    scanner._command = AsyncMock(return_value="ClamAV 1.4/1/not-a-date")  # type: ignore[method-assign]
    with pytest.raises(MalwareScannerError, match="timestamp"):
        await scanner._version()

    naive = now.replace(tzinfo=None).strftime("%a, %d %b %Y %H:%M:%S")
    scanner._command = AsyncMock(return_value=f"ClamAV 1.4/1/{naive}")  # type: ignore[method-assign]
    assert (await scanner._version()).signature_date.tzinfo is UTC

    with pytest.raises(MalwareScannerError, match="empty or exceeds"):
        await scanner.scan(b"12345", now=now)


@pytest.mark.asyncio
async def test_clamav_rejects_unknown_and_invalid_infected_responses() -> None:
    now = datetime.now(UTC).replace(microsecond=0)
    responses = iter(
        [
            b"stream: scanner ERROR\0",
            b"stream:  FOUND\0",
            b"stream: " + (b"x" * 513) + b" FOUND\0",
        ]
    )

    async def handle(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        command = await reader.readuntil(b"\0")
        if command == b"zVERSION\0":
            writer.write(f"ClamAV 1.4.3/30001/{format_datetime(now)}\0".encode())
        elif command == b"zINSTREAM\0":
            while True:
                size = struct.unpack("!I", await reader.readexactly(4))[0]
                if size == 0:
                    break
                await reader.readexactly(size)
            writer.write(next(responses))
        await writer.drain()
        writer.close()

    server = await asyncio.start_server(handle, "127.0.0.1", 0)
    port = server.sockets[0].getsockname()[1]
    scanner = ClamAVScanner(
        maximum_stream_bytes=1_000,
        maximum_signature_age=timedelta(hours=1),
        timeout_seconds=1,
        tcp_host="127.0.0.1",
        tcp_port=port,
    )
    try:
        with pytest.raises(MalwareScannerError, match="unknown verdict"):
            await scanner.scan(b"safe", now=now)
        with pytest.raises(MalwareScannerError, match="invalid signature"):
            await scanner.scan(b"safe", now=now)
        with pytest.raises(MalwareScannerError, match="invalid signature"):
            await scanner.scan(b"safe", now=now)
    finally:
        server.close()
        await server.wait_closed()


@pytest.mark.asyncio
async def test_clamav_bounds_and_decodes_responses() -> None:
    scanner = ClamAVScanner(
        maximum_stream_bytes=10,
        maximum_signature_age=timedelta(hours=1),
        timeout_seconds=1,
        tcp_host="127.0.0.1",
    )

    oversized = asyncio.StreamReader(limit=8_192)
    oversized.feed_data(b"x" * 4_096 + b"\0")
    with pytest.raises(MalwareScannerError, match="exceeded"):
        await scanner._read_response(oversized)

    limited = asyncio.StreamReader(limit=4)
    limited.feed_data(b"12345\0")
    with pytest.raises(MalwareScannerError, match="exceeded"):
        await scanner._read_response(limited)

    invalid_utf8 = asyncio.StreamReader()
    invalid_utf8.feed_data(b"\xff\0")
    with pytest.raises(MalwareScannerError, match="not UTF-8"):
        await scanner._read_response(invalid_utf8)


@pytest.mark.asyncio
async def test_clamav_unavailable_transport_fails_closed() -> None:
    temporary = await asyncio.start_server(lambda _r, _w: None, "127.0.0.1", 0)
    port = temporary.sockets[0].getsockname()[1]
    temporary.close()
    await temporary.wait_closed()
    scanner = ClamAVScanner(
        maximum_stream_bytes=10,
        maximum_signature_age=timedelta(hours=1),
        timeout_seconds=0.1,
        tcp_host="127.0.0.1",
        tcp_port=port,
    )
    assert not await scanner.is_ready()
    with pytest.raises(MalwareScannerError, match="unavailable"):
        await scanner._connect()


class _WriterStub:
    def write(self, _: bytes) -> None:
        return None

    async def drain(self) -> None:
        return None

    def close(self) -> None:
        return None

    async def wait_closed(self) -> None:
        return None


@pytest.mark.asyncio
async def test_clamav_wraps_incomplete_command_and_scan_responses() -> None:
    now = datetime.now(UTC)
    scanner = ClamAVScanner(
        maximum_stream_bytes=10,
        maximum_signature_age=timedelta(hours=1),
        timeout_seconds=1,
        tcp_host="127.0.0.1",
    )
    incomplete = asyncio.StreamReader()
    incomplete.feed_eof()
    scanner._connect = AsyncMock(return_value=(incomplete, _WriterStub()))  # type: ignore[method-assign]
    with pytest.raises(MalwareScannerError, match="command failed"):
        await scanner._command(b"zPING\0")

    scan_response = asyncio.StreamReader()
    scan_response.feed_eof()
    scanner._version = AsyncMock(  # type: ignore[method-assign]
        return_value=ScannerVersion("engine", "signatures", now)
    )
    scanner._connect = AsyncMock(return_value=(scan_response, _WriterStub()))  # type: ignore[method-assign]
    with pytest.raises(MalwareScannerError, match="transport failed"):
        await scanner.scan(b"safe", now=now)


@pytest.mark.asyncio
async def test_clamav_unix_connector_is_bounded_and_wrapped(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scanner = ClamAVScanner(
        maximum_stream_bytes=10,
        maximum_signature_age=timedelta(hours=1),
        timeout_seconds=1,
        unix_socket=Path("/run/clamav/clamd.sock"),
    )
    reader = asyncio.StreamReader()
    writer = _WriterStub()
    connector = AsyncMock(return_value=(reader, writer))
    monkeypatch.setattr(asyncio, "open_unix_connection", connector, raising=False)
    connected_reader, connected_writer = await scanner._connect()
    assert connected_reader is reader
    assert connected_writer is writer
    connector.assert_awaited_once_with(path=Path("/run/clamav/clamd.sock"))

    monkeypatch.setattr(
        asyncio,
        "open_unix_connection",
        AsyncMock(side_effect=OSError("socket missing")),
        raising=False,
    )
    with pytest.raises(MalwareScannerError, match="unavailable"):
        await scanner._connect()
