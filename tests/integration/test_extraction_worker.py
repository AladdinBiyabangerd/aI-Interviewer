import io
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from docx import Document
from pypdf import PdfWriter
from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject
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
from ai_interviewer.extraction_runtime.isolation import IsolationLimits
from ai_interviewer.file_security.lifecycle import FileSecurityService
from ai_interviewer.file_security.models import FileAsset, ParserReleasePolicy
from ai_interviewer.file_security.validation import (
    DOCX_MEDIA_TYPE,
    PDF_MEDIA_TYPE,
    TEXT_MEDIA_TYPE,
)
from ai_interviewer.persistence.database import Database

pytestmark = pytest.mark.integration

_TEST_ISOLATION_LIMITS = IsolationLimits(wall_clock_seconds=60.0)


def _pdf_fixture_bytes(text: str) -> bytes:
    """A minimal, genuinely parseable single-page PDF (not just a valid signature)."""
    writer = PdfWriter()
    page = writer.add_blank_page(width=300, height=150)
    stream = DecodedStreamObject()
    stream.set_data(f"BT /Helv 14 Tf 20 100 Td ({text}) Tj ET".encode("latin-1"))
    stream_ref = writer._add_object(stream)
    page[NameObject("/Contents")] = stream_ref
    page[NameObject("/Resources")] = DictionaryObject(
        {
            NameObject("/Font"): DictionaryObject(
                {
                    NameObject("/Helv"): DictionaryObject(
                        {
                            NameObject("/Type"): NameObject("/Font"),
                            NameObject("/Subtype"): NameObject("/Type1"),
                            NameObject("/BaseFont"): NameObject("/Helvetica"),
                        }
                    )
                }
            )
        }
    )
    buffer = io.BytesIO()
    writer.write(buffer)
    return buffer.getvalue()


def _docx_fixture_bytes(text: str) -> bytes:
    document = Document()
    document.add_paragraph(text)
    buffer = io.BytesIO()
    document.save(buffer)
    return buffer.getvalue()


async def _capable_domain(
    database: Database,
    suffix: str,
    *,
    media_type: str,
    parser_adapter: str,
) -> tuple[UUID, UUID, CandidateDocumentService, FileSecurityService, MemoryObjectStore]:
    context = await _create_privacy_context(database)
    await _allow_candidate_context(database, context)
    await _configure_file_policy(database, context)  # always adds an active PDF policy
    if media_type != PDF_MEDIA_TYPE:
        async with database.transaction() as session:
            session.add(
                ParserReleasePolicy(
                    policy_key=f"candidate-{parser_adapter}-{uuid4()}",
                    policy_version="1",
                    status="active",
                    privacy_policy_version_id=context.policy_id,
                    data_category="candidate_document",
                    purpose="interview_preparation",
                    media_type=media_type,
                    maximum_bytes=1_000_000,
                    malware_scan_required=True,
                    parser_adapter=parser_adapter,
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


async def _text_capable_domain(
    database: Database,
    suffix: str,
) -> tuple[UUID, UUID, CandidateDocumentService, FileSecurityService, MemoryObjectStore]:
    return await _capable_domain(
        database,
        suffix,
        media_type=TEXT_MEDIA_TYPE,
        parser_adapter="isolated-text-parser",
    )


async def _released_asset_with_content(
    files: FileSecurityService,
    *,
    account_id: UUID,
    marker: str,
    media_type: str,
    content: bytes,
) -> FileAsset:
    staged = await files.stage_upload(
        account_id=account_id,
        data_category="candidate_document",
        purpose="interview_preparation",
        declared_media_type=media_type,
        content=content,
    )
    released = await files.scan_and_release(account_id=account_id, file_asset_id=staged.id)
    worker_id = f"candidate-document-fixture-cleanup-{marker}"
    claimed = await files.claim_deletion_tasks(worker_id=worker_id, limit=100)
    cleanup = next(
        task
        for task in claimed
        if task.file_asset_id == released.id and task.task_kind == "quarantine_cleanup"
    )
    completed = await files.execute_deletion_task(task_id=cleanup.id, worker_id=worker_id)
    assert completed.status == "completed"
    return released


async def _released_text_asset(
    files: FileSecurityService,
    *,
    account_id: UUID,
    marker: str,
    content: bytes,
) -> FileAsset:
    return await _released_asset_with_content(
        files,
        account_id=account_id,
        marker=marker,
        media_type=TEXT_MEDIA_TYPE,
        content=content,
    )


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
    worker = CandidateExtractionWorker(
        jobs,
        files,
        source_texts,
        worker_id="extraction-worker-1",
        limits=_TEST_ISOLATION_LIMITS,
    )

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

    stored = await source_texts.get_source_text(account_id, preparation_id, document_version_id)
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
    worker = CandidateExtractionWorker(
        jobs,
        files,
        source_texts,
        worker_id="extraction-worker-2",
        limits=_TEST_ISOLATION_LIMITS,
    )

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


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("media_type", "parser_adapter", "content", "expected_text"),
    [
        (
            TEXT_MEDIA_TYPE,
            "isolated-text-parser",
            b"Backend engineer, 6 years, distributed systems background.",
            "Backend engineer, 6 years, distributed systems background.",
        ),
        (
            PDF_MEDIA_TYPE,
            "isolated-pdf-parser",
            _pdf_fixture_bytes("Backend engineer PDF fixture"),
            "Backend engineer PDF fixture",
        ),
        (
            DOCX_MEDIA_TYPE,
            "isolated-docx-parser",
            _docx_fixture_bytes("Backend engineer DOCX fixture"),
            "Backend engineer DOCX fixture",
        ),
    ],
    ids=("text", "pdf", "docx"),
)
async def test_extraction_worker_supports_every_documented_input_format(
    database: Database,
    media_type: str,
    parser_adapter: str,
    content: bytes,
    expected_text: str,
) -> None:
    """Phase 1A-D4 supported-input fixture pass: every 1A-documented format actually
    round-trips through the real isolated worker, not just a synthetic byte signature."""
    account_id, preparation_id, documents, files, _ = await _capable_domain(
        database,
        f"fixture-{parser_adapter}",
        media_type=media_type,
        parser_adapter=parser_adapter,
    )
    asset = await _released_asset_with_content(
        files,
        account_id=account_id,
        marker=parser_adapter,
        media_type=media_type,
        content=content,
    )
    attached = await documents.attach_released_asset(
        account_id,
        preparation_id,
        "cv",
        asset.id,
        "upload",
        f"fixture-attach-{parser_adapter}",
    )
    document_version_id = attached.attached_version.version_id

    jobs = CandidateExtractionJobService(database)
    source_texts = CandidateSourceTextService(database, _application_keyring())
    worker = CandidateExtractionWorker(
        jobs,
        files,
        source_texts,
        worker_id=f"fixture-worker-{parser_adapter}",
        limits=_TEST_ISOLATION_LIMITS,
    )
    await jobs.schedule_extraction(
        account_id,
        document_version_id,
        f"fixture-schedule-{parser_adapter}",
    )

    outcomes = await worker.run_once(limit=1)

    assert len(outcomes) == 1, outcomes
    assert outcomes[0].status == "succeeded", outcomes[0]
    stored = await source_texts.get_source_text(account_id, preparation_id, document_version_id)
    assert stored.versions[-1].content == expected_text
    assert stored.versions[-1].origin == "parser_extraction"
    assert stored.versions[-1].parser_adapter == parser_adapter

    await _delete_test_assets(
        database,
        files,
        {asset.id},
        worker_id=f"fixture-cleanup-{parser_adapter}",
    )
