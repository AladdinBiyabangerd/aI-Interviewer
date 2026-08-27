import base64
import hashlib
import json
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from pydantic import SecretStr
from sqlalchemy import func, select
from tests.integration.test_privacy import PrivacyContext, _create_privacy_context

from ai_interviewer.core.crypto import ApplicationKeyring
from ai_interviewer.file_security.lifecycle import FileSecurityService, FileStateConflictError
from ai_interviewer.file_security.models import (
    FileAsset,
    FileDeletionTask,
    ParserReleasePolicy,
)
from ai_interviewer.file_security.object_store import ObjectStoreError, StoredObject
from ai_interviewer.file_security.scanner import MalwareScannerError, ScannerVersion, ScanResult
from ai_interviewer.file_security.validation import PDF_MEDIA_TYPE
from ai_interviewer.identity.models import Account
from ai_interviewer.persistence.database import Database
from ai_interviewer.privacy.lifecycle import PrivacyLifecycleService
from ai_interviewer.privacy.models import (
    ProcessingRule,
    Processor,
    ProcessorActivity,
    ProcessorDeletionTask,
    RetentionRule,
)
from ai_interviewer.privacy.policy import build_default_jurisdiction_registry

pytestmark = pytest.mark.integration


class MemoryObjectStore:
    def __init__(self) -> None:
        self.objects: dict[str, list[tuple[str, bytes]]] = {}
        self.delete_failures = 0
        self.put_failures = 0
        self.read_failures = 0
        self._version = 0

    async def is_ready(self) -> bool:
        return True

    def _next_version(self) -> str:
        self._version += 1
        return f"version-{self._version}"

    async def put_quarantined(
        self,
        *,
        key: str,
        content: bytes,
        content_type: str,
        content_sha256: str,
    ) -> StoredObject:
        del content_type
        if self.put_failures:
            self.put_failures -= 1
            raise ObjectStoreError("synthetic upload failure")
        assert hashlib.sha256(content).hexdigest() == content_sha256
        version = self._next_version()
        self.objects.setdefault(key, []).append((version, content))
        return StoredObject(key, version, content_sha256, len(content))

    async def read_verified(
        self,
        *,
        key: str,
        version_id: str,
        expected_sha256: str,
        maximum_bytes: int,
    ) -> bytes:
        if self.read_failures:
            self.read_failures -= 1
            raise ObjectStoreError("synthetic read failure")
        for stored_version, content in self.objects.get(key, []):
            if stored_version == version_id:
                if (
                    len(content) > maximum_bytes
                    or hashlib.sha256(content).hexdigest() != expected_sha256
                ):
                    raise ObjectStoreError("verification failed")
                return content
        raise ObjectStoreError("object version missing")

    async def promote_clean(
        self,
        *,
        source_key: str,
        source_version_id: str,
        destination_key: str,
        content_type: str,
        content_sha256: str,
    ) -> StoredObject:
        content = await self.read_verified(
            key=source_key,
            version_id=source_version_id,
            expected_sha256=content_sha256,
            maximum_bytes=25 * 1024 * 1024,
        )
        return await self.put_quarantined(
            key=destination_key,
            content=content,
            content_type=content_type,
            content_sha256=content_sha256,
        )

    async def delete_all_versions(self, *, key: str) -> int:
        if self.delete_failures:
            self.delete_failures -= 1
            raise ObjectStoreError("synthetic deletion failure")
        return len(self.objects.pop(key, []))


class StaticScanner:
    def __init__(self, verdict: str = "clean") -> None:
        self.verdict = verdict

    async def is_ready(self, *, now: datetime | None = None) -> bool:
        del now
        return True

    async def scan(self, content: bytes, *, now: datetime | None = None) -> ScanResult:
        assert content
        evaluated_at = now or datetime.now(UTC)
        version = ScannerVersion("test-engine", "test-signatures", evaluated_at)
        if self.verdict == "infected":
            return ScanResult("infected", version, "a" * 64)
        return ScanResult("clean", version)


class FailingScanner(StaticScanner):
    async def scan(self, content: bytes, *, now: datetime | None = None) -> ScanResult:
        del content, now
        raise MalwareScannerError("synthetic scanner failure")


async def _configure_file_policy(database: Database, context: PrivacyContext) -> None:
    now = datetime.now(UTC)
    async with database.transaction() as session:
        session.add_all(
            [
                ProcessingRule(
                    privacy_policy_version_id=context.policy_id,
                    jurisdiction_code="AZERBAIJAN",
                    data_category="candidate_document",
                    purpose="interview_preparation",
                    allowed=True,
                    legal_basis="contract",
                ),
                RetentionRule(
                    privacy_policy_version_id=context.policy_id,
                    jurisdiction_code="AZERBAIJAN",
                    data_category="candidate_document",
                    purpose="interview_preparation",
                    retention_days=30,
                    action="delete",
                ),
                RetentionRule(
                    privacy_policy_version_id=context.policy_id,
                    jurisdiction_code="AZERBAIJAN",
                    data_category="file_deletion_evidence",
                    purpose="privacy_administration",
                    retention_days=365,
                    action="anonymize",
                ),
                ParserReleasePolicy(
                    policy_key=f"candidate-pdf-{uuid4()}",
                    policy_version="1",
                    status="active",
                    privacy_policy_version_id=context.policy_id,
                    data_category="candidate_document",
                    purpose="interview_preparation",
                    media_type=PDF_MEDIA_TYPE,
                    maximum_bytes=1_000_000,
                    malware_scan_required=True,
                    parser_adapter="isolated-pdf-parser",
                    parser_version="1",
                    isolation_profile="no-network-readonly-v1",
                    approved_at=now - timedelta(minutes=1),
                ),
            ]
        )


def _file_service(
    database: Database,
    store: MemoryObjectStore,
    scanner: StaticScanner,
    *,
    maximum_deletion_attempts: int = 3,
) -> FileSecurityService:
    return FileSecurityService(
        database=database,
        object_store=store,
        scanner=scanner,
        bucket="private-files",
        kms_key_id="alias/private-files",
        maximum_upload_bytes=1_000_000,
        maximum_archive_entries=100,
        maximum_archive_uncompressed_bytes=2_000_000,
        maximum_deletion_attempts=maximum_deletion_attempts,
        deletion_retry_base_seconds=1,
    )


def _application_keyring() -> ApplicationKeyring:
    def entry(identifier: str, purpose: str, byte: bytes) -> dict[str, str]:
        return {
            "id": identifier,
            "purpose": purpose,
            "material": base64.b64encode(byte * 32).decode(),
        }

    document = {
        "version": 1,
        "active": {
            "subject_hmac": "subject-v1",
            "field_encryption": "field-v1",
            "manifest_hmac": "manifest-v1",
        },
        "keys": [
            entry("subject-v1", "subject_hmac", b"s"),
            entry("field-v1", "field_encryption", b"f"),
            entry("manifest-v1", "manifest_hmac", b"m"),
        ],
    }
    return ApplicationKeyring.from_secret(SecretStr(json.dumps(document)))


@pytest.mark.asyncio
async def test_clean_file_release_export_and_privacy_deletion(database: Database) -> None:
    context = await _create_privacy_context(database)
    await _configure_file_policy(database, context)
    store = MemoryObjectStore()
    files = _file_service(database, store, StaticScanner())
    privacy = PrivacyLifecycleService(
        database=database,
        registry=build_default_jurisdiction_registry(),
        subject_hmac_key=b"integration-privacy-hmac-key-value" * 2,
        file_lifecycle=files,
    )

    staged = await files.stage_upload(
        account_id=context.account_id,
        data_category="candidate_document",
        purpose="interview_preparation",
        declared_media_type=PDF_MEDIA_TYPE,
        content=b"%PDF-1.7\nsynthetic fixture\n%%EOF",
    )
    assert staged.status == "quarantined"

    released = await files.scan_and_release(
        account_id=context.account_id,
        file_asset_id=staged.id,
    )
    assert released.status == "released"
    assert (
        await files.read_for_parser(
            account_id=context.account_id,
            file_asset_id=staged.id,
            parser_adapter="isolated-pdf-parser",
            parser_version="1",
            isolation_profile="no-network-readonly-v1",
        )
    ).startswith(b"%PDF-")

    cleanup = await files.claim_deletion_tasks(worker_id="file-worker", limit=10)
    assert [task.task_kind for task in cleanup] == ["quarantine_cleanup"]
    await files.execute_deletion_task(task_id=cleanup[0].id, worker_id="file-worker")
    assert released.released_object_key in store.objects
    assert released.quarantine_object_key not in store.objects

    exported = await privacy.create_request(
        context.account_id,
        "export",
        "file-export-idempotency",
        "file-export",
    )
    assert exported.data is not None
    assert exported.data["stored_files"][0]["id"] == str(staged.id)

    deletion = await privacy.create_request(
        context.account_id,
        "deletion",
        "file-deletion-idempotency",
        "file-deletion",
    )
    assert deletion.status == "processing"
    tasks = await files.claim_deletion_tasks(worker_id="file-worker", limit=10)
    asset_tasks = [task for task in tasks if task.task_kind == "asset_deletion"]
    assert len(asset_tasks) == 1
    await files.execute_deletion_task(task_id=asset_tasks[0].id, worker_id="file-worker")

    completed = await privacy.resume_deletion(deletion.request_id, "file-deletion-resume")
    assert completed.status == "completed"
    async with database.transaction() as session:
        assert await session.get(Account, context.account_id) is None
        assert await session.get(FileAsset, staged.id) is None


@pytest.mark.asyncio
async def test_infected_file_never_releases_and_is_deleted(database: Database) -> None:
    context = await _create_privacy_context(database)
    await _configure_file_policy(database, context)
    store = MemoryObjectStore()
    files = _file_service(database, store, StaticScanner("infected"))

    staged = await files.stage_upload(
        account_id=context.account_id,
        data_category="candidate_document",
        purpose="interview_preparation",
        declared_media_type=PDF_MEDIA_TYPE,
        content=b"%PDF-1.7\nsynthetic infected fixture\n%%EOF",
    )
    infected = await files.scan_and_release(
        account_id=context.account_id,
        file_asset_id=staged.id,
    )
    assert infected.status == "deletion_pending"
    assert infected.released_object_key is None

    tasks = await files.claim_deletion_tasks(worker_id="file-worker", limit=10)
    assert len(tasks) == 1
    await files.execute_deletion_task(task_id=tasks[0].id, worker_id="file-worker")
    async with database.transaction() as session:
        assert await session.get(FileAsset, staged.id) is None


@pytest.mark.asyncio
async def test_file_deletion_retry_escalation_and_manual_requeue(database: Database) -> None:
    context = await _create_privacy_context(database)
    await _configure_file_policy(database, context)
    store = MemoryObjectStore()
    files = _file_service(
        database,
        store,
        StaticScanner("infected"),
        maximum_deletion_attempts=2,
    )
    staged = await files.stage_upload(
        account_id=context.account_id,
        data_category="candidate_document",
        purpose="interview_preparation",
        declared_media_type=PDF_MEDIA_TYPE,
        content=b"%PDF-1.7\nretry fixture\n%%EOF",
    )
    await files.scan_and_release(account_id=context.account_id, file_asset_id=staged.id)
    store.delete_failures = 2

    first_claim = (await files.claim_deletion_tasks(worker_id="worker", limit=1))[0]
    retry = await files.execute_deletion_task(task_id=first_claim.id, worker_id="worker")
    assert retry.status == "retry"
    second_claim = (
        await files.claim_deletion_tasks(
            worker_id="worker",
            limit=1,
            now=retry.available_at,
        )
    )[0]
    escalated = await files.execute_deletion_task(task_id=second_claim.id, worker_id="worker")
    assert escalated.status == "escalated"

    requeued = await files.requeue_escalated_deletion_task(task_id=escalated.id)
    assert requeued.status == "retry"
    final_claim = (
        await files.claim_deletion_tasks(
            worker_id="worker",
            limit=1,
            now=requeued.available_at,
        )
    )[0]
    completed = await files.execute_deletion_task(task_id=final_claim.id, worker_id="worker")
    assert completed.status == "completed"


@pytest.mark.asyncio
async def test_scan_failures_upload_cleanup_and_retention_sweep(database: Database) -> None:
    context = await _create_privacy_context(database)
    await _configure_file_policy(database, context)
    store = MemoryObjectStore()
    files = _file_service(database, store, FailingScanner())

    staged = await files.stage_upload(
        account_id=context.account_id,
        data_category="candidate_document",
        purpose="interview_preparation",
        declared_media_type=PDF_MEDIA_TYPE,
        content=b"%PDF-1.7\nscanner failure\n%%EOF",
    )
    failed = await files.scan_and_release(
        account_id=context.account_id,
        file_asset_id=staged.id,
    )
    assert failed.status == "scan_failed"
    store.read_failures = 1
    failed_again = await files.scan_and_release(
        account_id=context.account_id,
        file_asset_id=staged.id,
    )
    assert failed_again.status == "scan_failed"

    due_at = failed.retain_until + timedelta(seconds=1)
    assert await files.schedule_due_retention(now=due_at) == 1
    tasks = await files.claim_deletion_tasks(
        worker_id="retention-worker",
        limit=10,
        now=due_at,
    )
    asset_task = next(task for task in tasks if task.task_kind == "asset_deletion")
    completed = await files.execute_deletion_task(
        task_id=asset_task.id,
        worker_id="retention-worker",
        now=due_at,
    )
    assert completed.status == "completed"
    assert (
        await files.purge_due_deletion_evidence(now=completed.retain_until + timedelta(seconds=1))
        >= 1
    )

    store.put_failures = 1
    with pytest.raises(ObjectStoreError, match="upload"):
        await files.stage_upload(
            account_id=context.account_id,
            data_category="candidate_document",
            purpose="interview_preparation",
            declared_media_type=PDF_MEDIA_TYPE,
            content=b"%PDF-1.7\nupload failure\n%%EOF",
        )
    async with database.transaction() as session:
        pending_upload_cleanup = await session.scalar(
            select(func.count())
            .select_from(FileDeletionTask)
            .where(
                FileDeletionTask.account_id == context.account_id,
                FileDeletionTask.status == "pending",
            )
        )
    assert pending_upload_cleanup == 1


@pytest.mark.asyncio
async def test_file_service_parameter_and_parser_policy_failures(database: Database) -> None:
    context = await _create_privacy_context(database)
    await _configure_file_policy(database, context)
    store = MemoryObjectStore()
    files = _file_service(database, store, StaticScanner())

    with pytest.raises(ValueError, match="between 1 and 100"):
        await files.claim_deletion_tasks(worker_id="worker", limit=0)
    with pytest.raises(ValueError, match="worker_id"):
        await files.claim_deletion_tasks(worker_id="", limit=1)
    with pytest.raises(ValueError, match="between 1 and 1000"):
        await files.schedule_due_retention(limit=0)
    with pytest.raises(ValueError, match="between 1 and 1000"):
        await files.purge_due_deletion_evidence(limit=0)

    staged = await files.stage_upload(
        account_id=context.account_id,
        data_category="candidate_document",
        purpose="interview_preparation",
        declared_media_type=PDF_MEDIA_TYPE,
        content=b"%PDF-1.7\npolicy fixture\n%%EOF",
    )
    with pytest.raises(FileStateConflictError, match="not released"):
        await files.read_for_parser(
            account_id=context.account_id,
            file_asset_id=staged.id,
            parser_adapter="isolated-pdf-parser",
            parser_version="1",
            isolation_profile="no-network-readonly-v1",
        )
    released = await files.scan_and_release(
        account_id=context.account_id,
        file_asset_id=staged.id,
    )
    with pytest.raises(FileStateConflictError, match="mismatched"):
        await files.read_for_parser(
            account_id=context.account_id,
            file_asset_id=released.id,
            parser_adapter="wrong-parser",
            parser_version="1",
            isolation_profile="no-network-readonly-v1",
        )


@pytest.mark.asyncio
async def test_processor_locator_encryption_and_signed_manifest(database: Database) -> None:
    context = await _create_privacy_context(database)
    keyring = _application_keyring()
    async with database.transaction() as session:
        session.add(
            ProcessingRule(
                privacy_policy_version_id=context.policy_id,
                jurisdiction_code="AZERBAIJAN",
                data_category="interview_response",
                purpose="interview_simulation",
                allowed=True,
                legal_basis="contract",
            )
        )
        processor = Processor(
            processor_key=f"provider-{uuid4()}",
            inventory_version="1",
            legal_name="Synthetic Processor",
            status="active",
            privacy_uri="https://processor.example/privacy",
            contract_reference="dpa-1",
            operating_countries=["AZ"],
            subprocessors=[],
        )
        session.add(processor)
        await session.flush()
        activity = ProcessorActivity(
            processor_id=processor.id,
            privacy_policy_version_id=context.policy_id,
            status="active",
            data_category="interview_response",
            purpose="interview_simulation",
            origin_region="az-primary",
            processing_region="az-primary",
            storage_region="az-primary",
            cross_border=False,
            transfer_mechanism=None,
            deletion_mechanism="api",
            deletion_sla_days=30,
            approved_at=datetime.now(UTC),
        )
        session.add(activity)
        await session.flush()
        activity_id = activity.id

    privacy = PrivacyLifecycleService(
        database=database,
        registry=build_default_jurisdiction_registry(),
        application_keyring=keyring,
    )
    usage = await privacy.register_processor_use(
        context.account_id,
        processor_activity_id=activity_id,
        processor_subject_reference="vendor-subject-secret",
    )
    assert usage.processor_subject_reference is None
    assert usage.processor_subject_ciphertext is not None
    assert b"vendor-subject-secret" not in usage.processor_subject_ciphertext

    deletion = await privacy.create_request(
        context.account_id,
        "deletion",
        "encrypted-locator-delete",
        "encrypted-locator-delete",
    )
    task = (await privacy.claim_processor_tasks(worker_id="processor-worker", limit=1))[0]
    assert task.processor_subject_reference is None
    assert (
        await privacy.resolve_processor_task_reference(
            task_id=task.id,
            worker_id="processor-worker",
        )
        == "vendor-subject-secret"
    )
    await privacy.acknowledge_processor_task(
        task_id=task.id,
        worker_id="processor-worker",
    )

    manifest = await privacy.export_signed_deletion_manifest()
    assert manifest.key_id == "manifest-v1"
    assert len(manifest.signature) == 64
    with pytest.raises(ValueError, match="signature"):
        await privacy.apply_signed_deletion_manifest(replace(manifest, signature="0" * 64))
    replay = await privacy.apply_signed_deletion_manifest(manifest)
    assert replay.markers_recorded == 0
    assert deletion.request_id == manifest.entries[-1].privacy_request_id

    async with database.transaction() as session:
        encrypted_tasks = await session.scalar(
            select(func.count())
            .select_from(ProcessorDeletionTask)
            .where(ProcessorDeletionTask.processor_subject_ciphertext.is_not(None))
        )
    assert encrypted_tasks == 0
