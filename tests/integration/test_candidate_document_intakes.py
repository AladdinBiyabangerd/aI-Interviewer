import asyncio
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from sqlalchemy import func, select, update
from tests.integration.test_candidate_documents import _delete_test_assets, _preparation
from tests.integration.test_candidate_inputs import _allow_candidate_context
from tests.integration.test_file_security import (
    MemoryObjectStore,
    StaticScanner,
    _configure_file_policy,
)
from tests.integration.test_privacy import _create_privacy_context

from ai_interviewer.candidate_inputs.asset_references import (
    CandidateFileAssetReferenceLifecycle,
)
from ai_interviewer.candidate_inputs.document_models import (
    CandidateDocument,
    CandidateDocumentVersion,
)
from ai_interviewer.candidate_inputs.documents import CandidateDocumentService
from ai_interviewer.candidate_inputs.intake_models import CandidateDocumentIntake
from ai_interviewer.candidate_inputs.intakes import (
    CandidateDocumentIntakeConflictError,
    CandidateDocumentIntakeNotFoundError,
    CandidateDocumentIntakeService,
    CandidateDocumentIntakeUnavailableError,
    apply_due_candidate_document_intake_retention,
)
from ai_interviewer.candidate_inputs.service import CandidateInputService
from ai_interviewer.file_security.lifecycle import FileSecurityService
from ai_interviewer.file_security.models import FileAsset, ParserReleasePolicy
from ai_interviewer.file_security.validation import PDF_MEDIA_TYPE, TEXT_MEDIA_TYPE
from ai_interviewer.persistence.database import Database
from ai_interviewer.persistence.models import AuditEvent, OutboxEvent
from ai_interviewer.privacy.lifecycle import PrivacyLifecycleService
from ai_interviewer.privacy.policy import build_default_jurisdiction_registry

pytestmark = pytest.mark.integration


def _files(
    database: Database,
    store: MemoryObjectStore,
    scanner: StaticScanner | None = None,
) -> FileSecurityService:
    return FileSecurityService(
        database=database,
        object_store=store,
        scanner=scanner or StaticScanner(),
        bucket="private-files",
        kms_key_id="alias/private-files",
        maximum_upload_bytes=1_000_000,
        maximum_archive_entries=100,
        maximum_archive_uncompressed_bytes=2_000_000,
        maximum_deletion_attempts=3,
        deletion_retry_base_seconds=1,
        reference_lifecycle=CandidateFileAssetReferenceLifecycle(),
    )


async def _configure_text_policy(database: Database, policy_id: UUID) -> None:
    now = datetime.now(UTC)
    async with database.transaction() as session:
        session.add(
            ParserReleasePolicy(
                policy_key=f"candidate-text-{uuid4()}",
                policy_version="1",
                status="active",
                privacy_policy_version_id=policy_id,
                data_category="candidate_document",
                purpose="interview_preparation",
                media_type=TEXT_MEDIA_TYPE,
                maximum_bytes=1_000_000,
                malware_scan_required=True,
                parser_adapter="isolated-text-parser",
                parser_version="1",
                isolation_profile="no-network-readonly-v1",
                approved_at=now - timedelta(minutes=1),
            )
        )


async def _domain(
    database: Database,
    suffix: str,
    *,
    store: MemoryObjectStore | None = None,
    scanner: StaticScanner | None = None,
) -> tuple[
    UUID,
    UUID,
    CandidateInputService,
    CandidateDocumentService,
    FileSecurityService,
    CandidateDocumentIntakeService,
    MemoryObjectStore,
]:
    context = await _create_privacy_context(database)
    await _allow_candidate_context(database, context)
    await _configure_file_policy(database, context)
    await _configure_text_policy(database, context.policy_id)
    preparation_id = await _preparation(database, context.account_id, suffix)
    inputs = CandidateInputService(database)
    documents = CandidateDocumentService(database)
    resolved_store = store or MemoryObjectStore()
    files = _files(database, resolved_store, scanner)
    intakes = CandidateDocumentIntakeService(database, files, documents)
    return (
        context.account_id,
        preparation_id,
        inputs,
        documents,
        files,
        intakes,
        resolved_store,
    )


def _pdf(marker: str) -> bytes:
    return f"%PDF-1.7\nsynthetic {marker}\n%%EOF".encode()


@pytest.mark.asyncio
async def test_intake_is_idempotent_versioned_owner_scoped_and_audited(
    database: Database,
) -> None:
    account_id, preparation_id, _, documents, files, intakes, _ = await _domain(
        database,
        "intake-lineage",
    )
    pdf = _pdf("intake-v1")
    first = await intakes.submit(
        account_id,
        preparation_id,
        "cv",
        "upload",
        PDF_MEDIA_TYPE,
        pdf,
        "intake-lineage-upload-001",
        "intake-lineage-request-001",
    )
    replay = await intakes.submit(
        account_id,
        preparation_id,
        "cv",
        "upload",
        PDF_MEDIA_TYPE,
        pdf,
        "intake-lineage-upload-001",
        "intake-lineage-request-002",
    )
    pasted = await intakes.submit(
        account_id,
        preparation_id,
        "cv",
        "paste",
        TEXT_MEDIA_TYPE,
        b"Synthetic CV version two",
        "intake-lineage-paste-001",
        "intake-lineage-request-003",
    )

    assert first.created and first.intake.status == "completed"
    assert not replay.created and replay.intake.intake_id == first.intake.intake_id
    assert replay.intake.document_version_id == first.intake.document_version_id
    assert pasted.intake.status == "completed"
    assert pasted.intake.document_id == first.intake.document_id
    assert pasted.intake.document_version_id != first.intake.document_version_id
    assert first.intake.document_id is not None
    document = await documents.get_document(
        account_id,
        preparation_id,
        first.intake.document_id,
    )
    assert document.latest_version_number == 2

    with pytest.raises(CandidateDocumentIntakeConflictError):
        await intakes.submit(
            account_id,
            preparation_id,
            "cv",
            "upload",
            PDF_MEDIA_TYPE,
            _pdf("different-content"),
            "intake-lineage-upload-001",
            None,
        )
    with pytest.raises(CandidateDocumentIntakeNotFoundError):
        await intakes.get_intake(uuid4(), preparation_id, first.intake.intake_id)

    async with database.transaction() as session:
        intake_count = await session.scalar(
            select(func.count(CandidateDocumentIntake.id)).where(
                CandidateDocumentIntake.owner_id == account_id
            )
        )
        version_count = await session.scalar(
            select(func.count(CandidateDocumentVersion.id)).where(
                CandidateDocumentVersion.owner_id == account_id
            )
        )
        audit_actions = set(
            (
                await session.scalars(
                    select(AuditEvent.action).where(
                        AuditEvent.owner_id == account_id,
                        AuditEvent.resource_type == "candidate_document_intake",
                    )
                )
            ).all()
        )
        event_payloads = list(
            (
                await session.scalars(
                    select(OutboxEvent.payload).where(
                        OutboxEvent.owner_id == account_id,
                        OutboxEvent.aggregate_type == "candidate_document_intake",
                    )
                )
            ).all()
        )
    assert intake_count == 2
    assert version_count == 2
    assert audit_actions == {
        "candidate_document.intake_started",
        "candidate_document.intake_completed",
    }
    serialized_events = str(event_payloads)
    assert "Synthetic" not in serialized_events
    assert "intake-lineage-upload-001" not in serialized_events

    await _delete_test_assets(
        database,
        files,
        {first.intake.file_asset_id, pasted.intake.file_asset_id},  # type: ignore[arg-type]
        worker_id="intake-lineage-cleanup",
    )


@pytest.mark.asyncio
async def test_scan_failure_retries_same_asset_and_attaches_once(database: Database) -> None:
    store = MemoryObjectStore()
    store.read_failures = 1
    account_id, preparation_id, _, _, files, intakes, _ = await _domain(
        database,
        "intake-scan-retry",
        store=store,
    )
    content = _pdf("scan-retry")
    first = await intakes.submit(
        account_id,
        preparation_id,
        "job_description",
        "upload",
        PDF_MEDIA_TYPE,
        content,
        "intake-scan-retry-001",
        None,
    )
    retried = await intakes.submit(
        account_id,
        preparation_id,
        "job_description",
        "upload",
        PDF_MEDIA_TYPE,
        content,
        "intake-scan-retry-001",
        None,
    )

    assert first.intake.status == "scan_failed"
    assert first.intake.retryable
    assert retried.intake.status == "completed"
    assert retried.intake.attempts == 2
    assert retried.intake.intake_id == first.intake.intake_id
    assert retried.intake.file_asset_id == first.intake.file_asset_id
    async with database.transaction() as session:
        assert (
            await session.scalar(
                select(func.count(CandidateDocumentVersion.id)).where(
                    CandidateDocumentVersion.file_asset_id == retried.intake.file_asset_id
                )
            )
            == 1
        )

    await _delete_test_assets(
        database,
        files,
        {retried.intake.file_asset_id},  # type: ignore[arg-type]
        worker_id="intake-scan-retry-cleanup",
    )


@pytest.mark.asyncio
async def test_storage_failure_rotates_reserved_asset_before_retry(database: Database) -> None:
    store = MemoryObjectStore()
    store.put_failures = 1
    account_id, preparation_id, _, _, files, intakes, _ = await _domain(
        database,
        "intake-storage-retry",
        store=store,
    )
    content = _pdf("storage-retry")
    first = await intakes.submit(
        account_id,
        preparation_id,
        "cv",
        "upload",
        PDF_MEDIA_TYPE,
        content,
        "intake-storage-retry-001",
        None,
    )
    async with database.transaction() as session:
        first_row = await session.get(CandidateDocumentIntake, first.intake.intake_id)
        assert first_row is not None
        failed_asset_id = first_row.reserved_file_asset_id
        failed_asset = await session.get(FileAsset, failed_asset_id)
        assert failed_asset is not None and failed_asset.status == "deletion_pending"

    retried = await intakes.submit(
        account_id,
        preparation_id,
        "cv",
        "upload",
        PDF_MEDIA_TYPE,
        content,
        "intake-storage-retry-001",
        None,
    )

    assert first.intake.status == "scan_failed"
    assert first.intake.last_error_code == "storage_unavailable"
    assert retried.intake.status == "completed"
    assert retried.intake.attempts == 2
    assert retried.intake.file_asset_id != failed_asset_id

    await _delete_test_assets(
        database,
        files,
        {failed_asset_id, retried.intake.file_asset_id},  # type: ignore[arg-type]
        worker_id="intake-storage-retry-cleanup",
    )


class PauseFirstStage:
    def __init__(self, files: FileSecurityService) -> None:
        self.files = files
        self.entered = asyncio.Event()
        self.release = asyncio.Event()
        self.pause = True

    async def stage_upload(self, **kwargs: object) -> FileAsset:
        if self.pause:
            self.entered.set()
            await self.release.wait()
        return await self.files.stage_upload(**kwargs)  # type: ignore[arg-type]

    async def scan_and_release(self, **kwargs: object) -> FileAsset:
        return await self.files.scan_and_release(**kwargs)  # type: ignore[arg-type]


class FailAfterFirstAttachment:
    def __init__(self, documents: CandidateDocumentService) -> None:
        self.documents = documents
        self.fail = True

    async def attach_released_asset(self, *args: object, **kwargs: object) -> object:
        result = await self.documents.attach_released_asset(*args, **kwargs)  # type: ignore[arg-type]
        if self.fail:
            self.fail = False
            raise RuntimeError("synthetic post-attachment failure")
        return result


@pytest.mark.asyncio
async def test_post_attachment_failure_reuses_asset_and_document_version(
    database: Database,
) -> None:
    account_id, preparation_id, _, documents, files, _, _ = await _domain(
        database,
        "intake-attachment-recovery",
    )
    failing_documents = FailAfterFirstAttachment(documents)
    intakes = CandidateDocumentIntakeService(
        database,
        files,
        failing_documents,  # type: ignore[arg-type]
    )
    content = _pdf("attachment-recovery")
    with pytest.raises(CandidateDocumentIntakeUnavailableError):
        await intakes.submit(
            account_id,
            preparation_id,
            "cv",
            "upload",
            PDF_MEDIA_TYPE,
            content,
            "intake-attachment-recovery-001",
            None,
        )
    async with database.transaction() as session:
        failed = await session.scalar(
            select(CandidateDocumentIntake).where(
                CandidateDocumentIntake.owner_id == account_id,
                CandidateDocumentIntake.preparation_id == preparation_id,
            )
        )
        assert failed is not None
        original_asset_id = failed.reserved_file_asset_id
        assert failed.status == "scan_failed"
        assert failed.last_error_code == "internal_dependency_failure"

    recovered = await intakes.submit(
        account_id,
        preparation_id,
        "cv",
        "upload",
        PDF_MEDIA_TYPE,
        content,
        "intake-attachment-recovery-001",
        None,
    )
    assert recovered.intake.status == "completed"
    assert recovered.intake.file_asset_id == original_asset_id
    assert recovered.intake.attempts == 2
    async with database.transaction() as session:
        assert (
            await session.scalar(
                select(func.count(CandidateDocumentVersion.id)).where(
                    CandidateDocumentVersion.owner_id == account_id
                )
            )
            == 1
        )

    await _delete_test_assets(
        database,
        files,
        {original_asset_id},
        worker_id="intake-attachment-recovery-cleanup",
    )


@pytest.mark.asyncio
async def test_expired_processing_lease_recovers_after_worker_cancellation(
    database: Database,
) -> None:
    account_id, preparation_id, _, documents, files, _, _ = await _domain(
        database,
        "intake-lease-recovery",
    )
    paused_files = PauseFirstStage(files)
    intakes = CandidateDocumentIntakeService(database, paused_files, documents)
    content = _pdf("lease-recovery")
    task = asyncio.create_task(
        intakes.submit(
            account_id,
            preparation_id,
            "cv",
            "upload",
            PDF_MEDIA_TYPE,
            content,
            "intake-lease-recovery-001",
            None,
        )
    )
    await paused_files.entered.wait()
    active = await intakes.submit(
        account_id,
        preparation_id,
        "cv",
        "upload",
        PDF_MEDIA_TYPE,
        content,
        "intake-lease-recovery-001",
        None,
    )
    assert active.intake.status == "processing"
    assert not active.created
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    expired_at = datetime.now(UTC) - timedelta(seconds=1)
    async with database.transaction() as session:
        await session.execute(
            update(CandidateDocumentIntake)
            .where(CandidateDocumentIntake.id == active.intake.intake_id)
            .values(processing_lease_until=expired_at)
        )
    paused_files.pause = False
    recovered = await intakes.submit(
        account_id,
        preparation_id,
        "cv",
        "upload",
        PDF_MEDIA_TYPE,
        content,
        "intake-lease-recovery-001",
        None,
    )

    assert recovered.intake.status == "completed"
    assert recovered.intake.attempts == 2
    assert recovered.intake.intake_id == active.intake.intake_id
    await _delete_test_assets(
        database,
        files,
        {recovered.intake.file_asset_id},  # type: ignore[arg-type]
        worker_id="intake-lease-recovery-cleanup",
    )


@pytest.mark.asyncio
async def test_invalid_document_is_durably_rejected_without_file_or_version(
    database: Database,
) -> None:
    account_id, preparation_id, _, _, _, intakes, _ = await _domain(
        database,
        "intake-rejected",
    )
    rejected = await intakes.submit(
        account_id,
        preparation_id,
        "cv",
        "upload",
        PDF_MEDIA_TYPE,
        b"not a PDF",
        "intake-rejected-001",
        None,
    )
    replay = await intakes.submit(
        account_id,
        preparation_id,
        "cv",
        "upload",
        PDF_MEDIA_TYPE,
        b"not a PDF",
        "intake-rejected-001",
        None,
    )

    assert rejected.intake.status == "rejected"
    assert rejected.intake.last_error_code == "media_type_mismatch"
    assert replay.intake.intake_id == rejected.intake.intake_id
    assert replay.intake.attempts == 1
    async with database.transaction() as session:
        assert (
            await session.scalar(
                select(func.count(FileAsset.id)).where(FileAsset.account_id == account_id)
            )
            == 0
        )
        removed = await apply_due_candidate_document_intake_retention(
            session,
            now=datetime.now(UTC) + timedelta(days=31),
        )
        assert removed == 1
        assert await session.get(CandidateDocumentIntake, rejected.intake.intake_id) is None
        assert (
            await session.scalar(
                select(func.count(CandidateDocumentVersion.id)).where(
                    CandidateDocumentVersion.owner_id == account_id
                )
            )
            == 0
        )


@pytest.mark.asyncio
async def test_infected_document_is_rejected_without_document_lineage(
    database: Database,
) -> None:
    account_id, preparation_id, _, _, files, intakes, _ = await _domain(
        database,
        "intake-infected",
        scanner=StaticScanner("infected"),
    )
    rejected = await intakes.submit(
        account_id,
        preparation_id,
        "cv",
        "upload",
        PDF_MEDIA_TYPE,
        _pdf("infected"),
        "intake-infected-001",
        None,
    )

    assert rejected.intake.status == "rejected"
    assert rejected.intake.last_error_code == "unsafe_file"
    assert rejected.intake.file_asset_id is not None
    assert rejected.intake.document_version_id is None
    async with database.transaction() as session:
        assert (
            await session.scalar(
                select(func.count(CandidateDocumentVersion.id)).where(
                    CandidateDocumentVersion.owner_id == account_id
                )
            )
            == 0
        )

    await _delete_test_assets(
        database,
        files,
        {rejected.intake.file_asset_id},
        worker_id="intake-infected-cleanup",
    )


@pytest.mark.asyncio
async def test_privacy_export_and_deletion_cover_intake_saga_metadata(
    database: Database,
) -> None:
    account_id, preparation_id, inputs, documents, files, intakes, _ = await _domain(
        database,
        "intake-privacy",
    )
    completed = await intakes.submit(
        account_id,
        preparation_id,
        "cv",
        "paste",
        TEXT_MEDIA_TYPE,
        b"Synthetic privacy lifecycle CV",
        "intake-privacy-paste-001",
        "intake-privacy-request-001",
    )
    privacy = PrivacyLifecycleService(
        database=database,
        registry=build_default_jurisdiction_registry(),
        subject_hmac_key=b"candidate-intake-privacy-hmac-key" * 2,
        file_lifecycle=files,
        candidate_data_lifecycle=inputs,
        candidate_document_lifecycle=documents,
        candidate_document_intake_lifecycle=intakes,
    )

    exported = await privacy.create_request(
        account_id,
        "export",
        "candidate-intake-export-key",
        "candidate-intake-export",
    )
    assert exported.data is not None
    assert exported.data["schema_version"] == "phase-1b-c2"
    intake_export = exported.data["candidate_document_intakes"][0]
    assert intake_export["intake_id"] == str(completed.intake.intake_id)
    assert intake_export["status"] == "completed"
    serialized_export = str(intake_export)
    assert "Synthetic privacy lifecycle CV" not in serialized_export
    assert "intake-privacy-paste-001" not in serialized_export

    deletion = await privacy.create_request(
        account_id,
        "deletion",
        "candidate-intake-deletion-key",
        "candidate-intake-deletion",
    )
    assert deletion.status == "processing"
    async with database.transaction() as session:
        assert await session.get(CandidateDocumentIntake, completed.intake.intake_id) is None
        assert await session.get(CandidateDocument, completed.intake.document_id) is None
        assert await session.get(FileAsset, completed.intake.file_asset_id) is not None

    claimed = await files.claim_deletion_tasks(
        worker_id="candidate-intake-privacy-worker",
        limit=100,
    )
    deletion_task = next(
        item
        for item in claimed
        if item.file_asset_id == completed.intake.file_asset_id
        and item.task_kind == "asset_deletion"
    )
    assert (
        await files.execute_deletion_task(
            task_id=deletion_task.id,
            worker_id="candidate-intake-privacy-worker",
        )
    ).status == "completed"
    assert (
        await privacy.resume_deletion(deletion.request_id, "candidate-intake-delete-resume")
    ).status == "completed"
