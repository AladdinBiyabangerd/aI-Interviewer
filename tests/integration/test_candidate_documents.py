from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from sqlalchemy import select, update
from sqlalchemy.exc import DBAPIError
from tests.integration.test_candidate_inputs import (
    _allow_candidate_context,
    _input,
)
from tests.integration.test_file_security import (
    MemoryObjectStore,
    StaticScanner,
    _configure_file_policy,
)
from tests.integration.test_privacy import _create_privacy_context

from ai_interviewer.candidate_inputs.document_models import (
    CandidateDocument,
    CandidateDocumentVersion,
)
from ai_interviewer.candidate_inputs.documents import (
    CandidateDocumentConflictError,
    CandidateDocumentNotFoundError,
    CandidateDocumentService,
)
from ai_interviewer.candidate_inputs.service import CandidateInputService
from ai_interviewer.file_security.lifecycle import FileSecurityService
from ai_interviewer.file_security.models import FileAsset
from ai_interviewer.file_security.validation import PDF_MEDIA_TYPE
from ai_interviewer.persistence.database import Database
from ai_interviewer.persistence.models import AuditEvent, OutboxEvent
from ai_interviewer.privacy.lifecycle import PrivacyLifecycleService
from ai_interviewer.privacy.policy import build_default_jurisdiction_registry

pytestmark = pytest.mark.integration


def _file_service(
    database: Database,
    store: MemoryObjectStore,
    documents: CandidateDocumentService,
) -> FileSecurityService:
    return FileSecurityService(
        database=database,
        object_store=store,
        scanner=StaticScanner(),
        bucket="private-files",
        kms_key_id="alias/private-files",
        maximum_upload_bytes=1_000_000,
        maximum_archive_entries=100,
        maximum_archive_uncompressed_bytes=2_000_000,
        maximum_deletion_attempts=3,
        deletion_retry_base_seconds=1,
        reference_lifecycle=documents,
    )


async def _preparation(database: Database, account_id: UUID, suffix: str) -> UUID:
    result = await CandidateInputService(database).create_preparation(
        account_id,
        _input(company_name=f"Synthetic Company {suffix}"),
        f"candidate-document-preparation-{suffix}",
        f"candidate-document-preparation-{suffix}",
    )
    return result.preparation.id


async def _released_asset(
    files: FileSecurityService,
    *,
    account_id: UUID,
    marker: str,
) -> FileAsset:
    staged = await files.stage_upload(
        account_id=account_id,
        data_category="candidate_document",
        purpose="interview_preparation",
        declared_media_type=PDF_MEDIA_TYPE,
        content=f"%PDF-1.7\nsynthetic {marker}\n%%EOF".encode(),
    )
    released = await files.scan_and_release(
        account_id=account_id,
        file_asset_id=staged.id,
    )
    worker_id = f"candidate-document-cleanup-{marker}"
    claimed = await files.claim_deletion_tasks(worker_id=worker_id, limit=100)
    cleanup = next(
        task
        for task in claimed
        if task.file_asset_id == released.id and task.task_kind == "quarantine_cleanup"
    )
    completed = await files.execute_deletion_task(
        task_id=cleanup.id,
        worker_id=worker_id,
    )
    assert completed.status == "completed"
    return released


async def _domain(
    database: Database,
    suffix: str,
) -> tuple[UUID, UUID, CandidateDocumentService, FileSecurityService, MemoryObjectStore]:
    context = await _create_privacy_context(database)
    await _allow_candidate_context(database, context)
    await _configure_file_policy(database, context)
    preparation_id = await _preparation(database, context.account_id, suffix)
    documents = CandidateDocumentService(database)
    store = MemoryObjectStore()
    files = _file_service(database, store, documents)
    return context.account_id, preparation_id, documents, files, store


async def _delete_test_assets(
    database: Database,
    files: FileSecurityService,
    asset_ids: set[UUID],
    *,
    worker_id: str,
) -> None:
    due_at = datetime.now(UTC)
    created_at = due_at - timedelta(days=31)
    async with database.transaction() as session:
        await session.execute(
            update(FileAsset)
            .where(FileAsset.id.in_(asset_ids))
            .values(
                created_at=created_at,
                updated_at=created_at,
                retain_until=due_at - timedelta(seconds=1),
            )
        )
    await files.schedule_due_retention(now=due_at)
    claimed = await files.claim_deletion_tasks(
        worker_id=worker_id,
        limit=100,
        now=due_at,
    )
    deletions = [
        task
        for task in claimed
        if task.file_asset_id in asset_ids and task.task_kind == "asset_deletion"
    ]
    assert {task.file_asset_id for task in deletions} == asset_ids
    for task in deletions:
        completed = await files.execute_deletion_task(
            task_id=task.id,
            worker_id=worker_id,
            now=due_at,
        )
        assert completed.status == "completed"


@pytest.mark.asyncio
async def test_attach_is_idempotent_versioned_owner_scoped_and_database_immutable(
    database: Database,
) -> None:
    account_id, preparation_id, documents, files, _ = await _domain(database, "lineage")
    first_asset = await _released_asset(files, account_id=account_id, marker="cv-v1")
    second_asset = await _released_asset(files, account_id=account_id, marker="cv-v2")

    first = await documents.attach_released_asset(
        account_id,
        preparation_id,
        "cv",
        first_asset.id,
        "upload",
        "candidate-document-v1",
    )
    repeated = await documents.attach_released_asset(
        account_id,
        preparation_id,
        "cv",
        first_asset.id,
        "upload",
        "candidate-document-v1-retry",
    )
    second = await documents.attach_released_asset(
        account_id,
        preparation_id,
        "cv",
        second_asset.id,
        "upload",
        "candidate-document-v2",
    )

    assert first.created is True
    assert repeated.created is False
    assert repeated.attached_version.version_id == first.attached_version.version_id
    assert second.document.document_id == first.document.document_id
    assert second.document.document_id.version == 7
    assert second.attached_version.version_id.version == 7
    assert second.document.latest_version_number == 2
    assert second.document.aggregate_version == 2
    assert [version.version_number for version in second.document.versions] == [1, 2]
    assert second.document.versions[0].content_sha256 == first_asset.content_sha256
    assert second.document.versions[1].content_sha256 == second_asset.content_sha256

    listed = await documents.list_documents(account_id, preparation_id)
    fetched = await documents.get_document(
        account_id,
        preparation_id,
        first.document.document_id,
    )
    assert listed == (fetched,)
    with pytest.raises(CandidateDocumentNotFoundError):
        await documents.list_documents(uuid4(), preparation_id)

    async with database.transaction() as session:
        audit = await session.scalar(
            select(AuditEvent).where(
                AuditEvent.resource_id == second.attached_version.version_id,
                AuditEvent.action == "candidate_document.version_attached",
            )
        )
        event = await session.scalar(
            select(OutboxEvent).where(
                OutboxEvent.aggregate_id == second.document.document_id,
                OutboxEvent.event_type == "candidate_document.version_attached",
                OutboxEvent.payload["version_number"].as_integer() == 2,
            )
        )
    assert audit is not None and event is not None
    operational_metadata = f"{audit.details} {event.payload}"
    assert second_asset.content_sha256 not in operational_metadata
    assert "Synthetic Company" not in operational_metadata

    with pytest.raises(DBAPIError, match="immutable"):
        async with database.transaction() as session:
            await session.execute(
                update(CandidateDocumentVersion)
                .where(CandidateDocumentVersion.id == first.attached_version.version_id)
                .values(content_sha256="f" * 64)
            )
    after_rejected_update = await documents.get_document(
        account_id,
        preparation_id,
        first.document.document_id,
    )
    assert after_rejected_update.versions[0].content_sha256 == first_asset.content_sha256
    await _delete_test_assets(
        database,
        files,
        {first_asset.id, second_asset.id},
        worker_id="candidate-document-lineage-cleanup",
    )


@pytest.mark.asyncio
async def test_attach_rejects_unreleased_assets_and_archived_preparations(
    database: Database,
) -> None:
    account_id, preparation_id, documents, files, _ = await _domain(database, "conflicts")
    staged = await files.stage_upload(
        account_id=account_id,
        data_category="candidate_document",
        purpose="interview_preparation",
        declared_media_type=PDF_MEDIA_TYPE,
        content=b"%PDF-1.7\nunreleased synthetic fixture\n%%EOF",
    )
    with pytest.raises(CandidateDocumentConflictError, match="not released"):
        await documents.attach_released_asset(
            account_id,
            preparation_id,
            "cv",
            staged.id,
            "upload",
            "candidate-document-unreleased",
        )

    preparation = await CandidateInputService(database).get_preparation(
        account_id,
        preparation_id,
    )
    await CandidateInputService(database).archive_preparation(
        account_id,
        preparation_id,
        expected_version=preparation.version,
        request_id="candidate-document-archive",
    )
    with pytest.raises(CandidateDocumentConflictError, match="archived"):
        await documents.attach_released_asset(
            account_id,
            preparation_id,
            "job_description",
            staged.id,
            "upload",
            "candidate-document-archived",
        )
    await _delete_test_assets(
        database,
        files,
        {staged.id},
        worker_id="candidate-document-conflict-cleanup",
    )


@pytest.mark.asyncio
async def test_file_retention_releases_document_reference_before_asset_deletion(
    database: Database,
) -> None:
    account_id, preparation_id, documents, files, store = await _domain(database, "retention")
    asset = await _released_asset(files, account_id=account_id, marker="retention")
    attached = await documents.attach_released_asset(
        account_id,
        preparation_id,
        "job_description",
        asset.id,
        "upload",
        "candidate-document-retention",
    )
    due_at = datetime.now(UTC)
    created_at = due_at - timedelta(days=31)
    async with database.transaction() as session:
        await session.execute(
            update(FileAsset)
            .where(FileAsset.id == asset.id)
            .values(
                created_at=created_at,
                updated_at=created_at,
                retain_until=due_at - timedelta(seconds=1),
            )
        )

    assert await files.schedule_due_retention(now=due_at) == 1
    claimed = await files.claim_deletion_tasks(
        worker_id="candidate-document-retention-worker",
        limit=100,
        now=due_at,
    )
    deletion = next(
        task
        for task in claimed
        if task.file_asset_id == asset.id and task.task_kind == "asset_deletion"
    )
    completed = await files.execute_deletion_task(
        task_id=deletion.id,
        worker_id="candidate-document-retention-worker",
        now=due_at,
    )
    assert completed.status == "completed"
    assert asset.released_object_key not in store.objects

    async with database.transaction() as session:
        assert await session.get(FileAsset, asset.id) is None
        assert await session.get(CandidateDocument, attached.document.document_id) is None
        assert (
            await session.get(
                CandidateDocumentVersion,
                attached.attached_version.version_id,
            )
            is None
        )


@pytest.mark.asyncio
async def test_privacy_export_and_deletion_cover_document_lineage(
    database: Database,
) -> None:
    context = await _create_privacy_context(database)
    await _allow_candidate_context(database, context)
    await _configure_file_policy(database, context)
    inputs = CandidateInputService(database)
    preparation_id = await _preparation(database, context.account_id, "privacy")
    documents = CandidateDocumentService(database)
    store = MemoryObjectStore()
    files = _file_service(database, store, documents)
    asset = await _released_asset(files, account_id=context.account_id, marker="privacy")
    attached = await documents.attach_released_asset(
        context.account_id,
        preparation_id,
        "cv",
        asset.id,
        "upload",
        "candidate-document-privacy",
    )
    privacy = PrivacyLifecycleService(
        database=database,
        registry=build_default_jurisdiction_registry(),
        subject_hmac_key=b"candidate-document-privacy-hmac-key" * 2,
        file_lifecycle=files,
        candidate_data_lifecycle=inputs,
        candidate_document_lifecycle=documents,
    )

    exported = await privacy.create_request(
        context.account_id,
        "export",
        "candidate-document-export-key",
        "candidate-document-export",
    )
    assert exported.data is not None
    assert exported.data["schema_version"] == "phase-1a-c.1"
    assert exported.data["candidate_document_intakes"] == []
    lineage = exported.data["candidate_documents"][0]
    assert lineage["document_id"] == str(attached.document.document_id)
    assert lineage["versions"][0]["content_sha256"] == asset.content_sha256
    assert "object_key" not in str(lineage)
    assert "privacy_policy_version_id" not in str(lineage)

    deletion = await privacy.create_request(
        context.account_id,
        "deletion",
        "candidate-document-deletion-key",
        "candidate-document-deletion",
    )
    assert deletion.status == "processing"
    async with database.transaction() as session:
        assert await session.get(CandidateDocument, attached.document.document_id) is None
        assert await session.get(FileAsset, asset.id) is not None

    claimed = await files.claim_deletion_tasks(
        worker_id="candidate-document-privacy-worker",
        limit=100,
    )
    asset_deletion = next(
        task
        for task in claimed
        if task.file_asset_id == asset.id and task.task_kind == "asset_deletion"
    )
    completed_task = await files.execute_deletion_task(
        task_id=asset_deletion.id,
        worker_id="candidate-document-privacy-worker",
    )
    assert completed_task.status == "completed"
    completed_request = await privacy.resume_deletion(
        deletion.request_id,
        "candidate-document-deletion-resume",
    )
    assert completed_request.status == "completed"
