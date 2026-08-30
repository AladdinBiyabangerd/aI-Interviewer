from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from tests.integration.test_candidate_documents import (
    _delete_test_assets,
    _file_service,
    _preparation,
    _released_asset,
)
from tests.integration.test_candidate_inputs import _allow_candidate_context
from tests.integration.test_file_security import (
    MemoryObjectStore,
    _application_keyring,
    _configure_file_policy,
)
from tests.integration.test_privacy import _create_privacy_context

from ai_interviewer.candidate_inputs.documents import CandidateDocumentService
from ai_interviewer.candidate_inputs.extraction_jobs import CandidateExtractionJobService
from ai_interviewer.candidate_inputs.extraction_worker import CandidateExtractionWorker
from ai_interviewer.candidate_inputs.source_texts import CandidateSourceTextService
from ai_interviewer.file_security.lifecycle import FileSecurityService
from ai_interviewer.file_security.models import FileAsset, ParserReleasePolicy
from ai_interviewer.file_security.validation import TEXT_MEDIA_TYPE
from ai_interviewer.persistence.database import Database

pytestmark = pytest.mark.integration


async def _text_capable_domain(
    database: Database,
    suffix: str,
) -> tuple[UUID, UUID, CandidateDocumentService, FileSecurityService, MemoryObjectStore]:
    context = await _create_privacy_context(database)
    await _allow_candidate_context(database, context)
    await _configure_file_policy(database, context)
    async with database.transaction() as session:
        session.add(
            ParserReleasePolicy(
                policy_key=f"candidate-text-{uuid4()}",
                policy_version="1",
                status="active",
                privacy_policy_version_id=context.policy_id,
                data_category="candidate_document",
                purpose="interview_preparation",
                media_type=TEXT_MEDIA_TYPE,
                maximum_bytes=1_000_000,
                malware_scan_required=True,
                parser_adapter="isolated-text-parser",
                parser_version="1",
                isolation_profile="no-network-readonly-v1",
                approved_at=datetime.now(UTC) - timedelta(minutes=1),
            )
        )
    preparation_id = await _preparation(database, context.account_id, suffix)
    documents = CandidateDocumentService(database)
    store = MemoryObjectStore()
    files = _file_service(database, store, documents)
    return context.account_id, preparation_id, documents, files, store


async def _released_text_asset(
    files: FileSecurityService,
    *,
    account_id: UUID,
    marker: str,
    content: bytes,
) -> FileAsset:
    staged = await files.stage_upload(
        account_id=account_id,
        data_category="candidate_document",
        purpose="interview_preparation",
        declared_media_type=TEXT_MEDIA_TYPE,
        content=content,
    )
    released = await files.scan_and_release(account_id=account_id, file_asset_id=staged.id)
    worker_id = f"candidate-document-text-cleanup-{marker}"
    claimed = await files.claim_deletion_tasks(worker_id=worker_id, limit=100)
    cleanup = next(
        task
        for task in claimed
        if task.file_asset_id == released.id and task.task_kind == "quarantine_cleanup"
    )
    completed = await files.execute_deletion_task(task_id=cleanup.id, worker_id=worker_id)
    assert completed.status == "completed"
    return released


@pytest.mark.asyncio
async def test_extraction_worker_succeeds_end_to_end_for_text_document(
    database: Database,
) -> None:
    account_id, preparation_id, documents, files, _ = await _text_capable_domain(
        database,
        "extraction-worker-success",
    )
    content = b"Experienced backend engineer with a distributed systems background."
    asset = await _released_text_asset(
        files,
        account_id=account_id,
        marker="worker-success",
        content=content,
    )
    attached = await documents.attach_released_asset(
        account_id,
        preparation_id,
        "cv",
        asset.id,
        "upload",
        "extraction-worker-attach",
    )
    document_version_id = attached.attached_version.version_id

    jobs = CandidateExtractionJobService(database)
    source_texts = CandidateSourceTextService(database, _application_keyring())
    worker = CandidateExtractionWorker(jobs, files, source_texts, worker_id="extraction-worker-1")

    scheduled = await jobs.schedule_extraction(
        account_id,
        document_version_id,
        "extraction-worker-schedule",
    )
    assert scheduled.job.status == "pending"

    outcomes = await worker.run_once(limit=1)

    assert len(outcomes) == 1
    assert outcomes[0].status == "succeeded"
    assert outcomes[0].error_code is None

    stored = await source_texts.get_source_text(account_id, document_version_id)
    assert stored.versions[-1].content == content.decode()
    assert stored.versions[-1].origin == "parser_extraction"
    assert stored.versions[-1].parser_adapter == "isolated-text-parser"

    await _delete_test_assets(
        database,
        files,
        {asset.id},
        worker_id="extraction-worker-success-cleanup",
    )


@pytest.mark.asyncio
async def test_extraction_worker_terminates_a_job_on_corrupt_pdf_input(
    database: Database,
) -> None:
    account_id, preparation_id, documents, files, _ = await _text_capable_domain(
        database,
        "extraction-worker-corrupt",
    )
    asset = await _released_asset(files, account_id=account_id, marker="worker-corrupt")
    attached = await documents.attach_released_asset(
        account_id,
        preparation_id,
        "cv",
        asset.id,
        "upload",
        "extraction-worker-corrupt-attach",
    )
    document_version_id = attached.attached_version.version_id

    jobs = CandidateExtractionJobService(database)
    source_texts = CandidateSourceTextService(database, _application_keyring())
    worker = CandidateExtractionWorker(jobs, files, source_texts, worker_id="extraction-worker-2")

    await jobs.schedule_extraction(
        account_id,
        document_version_id,
        "extraction-worker-corrupt-schedule",
    )
    outcomes = await worker.run_once(limit=1)

    assert len(outcomes) == 1
    assert outcomes[0].status == "failed"
    assert outcomes[0].error_code == "input_corrupt"

    await _delete_test_assets(
        database,
        files,
        {asset.id},
        worker_id="extraction-worker-corrupt-cleanup",
    )
