from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import select, update
from sqlalchemy.exc import DBAPIError
from tests.integration.test_candidate_documents import _delete_test_assets
from tests.integration.test_candidate_source_texts import _attached_document_version
from tests.integration.test_file_security import _application_keyring
from tests.integration.test_privacy import _create_privacy_context

from ai_interviewer.candidate_inputs.extraction_jobs import (
    CandidateExtractionJobConflictError,
    CandidateExtractionJobNotFoundError,
    CandidateExtractionJobService,
)
from ai_interviewer.candidate_inputs.extraction_models import (
    EXTRACTION_LEASE_SECONDS,
    MAX_EXTRACTION_ATTEMPTS,
    CandidateExtractionJob,
)
from ai_interviewer.candidate_inputs.source_texts import CandidateSourceTextService
from ai_interviewer.persistence.database import Database

pytestmark = pytest.mark.integration


@pytest.mark.asyncio
async def test_extraction_job_schedule_claim_retry_fencing_and_success(
    database: Database,
) -> None:
    account_id, _, _, files, asset, attached, parser = await _attached_document_version(
        database,
        "extraction-job-lifecycle",
    )
    document_version_id = attached.attached_version.version_id
    jobs = CandidateExtractionJobService(database)
    source_texts = CandidateSourceTextService(database, _application_keyring())
    now = datetime.now(UTC)

    first = await jobs.schedule_extraction(
        account_id,
        document_version_id,
        "job-schedule",
        now=now,
    )
    repeated = await jobs.schedule_extraction(
        account_id,
        document_version_id,
        "job-schedule-retry",
        now=now + timedelta(seconds=1),
    )
    assert first.created is True
    assert repeated.created is False
    assert repeated.job == first.job
    assert first.job.status == "pending"
    assert first.job.attempts == 0
    assert first.job.parser_release_policy_id == parser.parser_release_policy_id
    assert first.job.file_asset_id == asset.id

    claim = (await jobs.claim_jobs("parser-worker-a", 1, now=now + timedelta(seconds=2)))[0]
    assert claim.job_id == first.job.job_id
    assert claim.status == "processing"
    assert claim.attempts == 1
    assert claim.lease_token is not None

    retry = await jobs.mark_failed(
        claim.job_id,
        "parser-worker-a",
        claim.lease_token,
        "parser_timeout",
        now=now + timedelta(seconds=3),
    )
    assert retry.status == "retry"
    assert retry.error_code == "parser_timeout"
    assert retry.completed_at is None
    assert retry.available_at == now + timedelta(seconds=63)

    assert await jobs.claim_jobs("parser-worker-b", 1, now=now + timedelta(seconds=62)) == ()
    reclaimed = (await jobs.claim_jobs("parser-worker-b", 1, now=retry.available_at))[0]
    assert reclaimed.attempts == 2
    assert reclaimed.lease_token is not None
    assert reclaimed.lease_token != claim.lease_token

    with pytest.raises(CandidateExtractionJobConflictError, match="not claimed"):
        await jobs.mark_failed(
            reclaimed.job_id,
            "parser-worker-a",
            claim.lease_token,
            "internal_failure",
            now=now + timedelta(seconds=64),
        )

    with pytest.raises(CandidateExtractionJobConflictError, match="requires the matching"):
        await jobs.mark_succeeded(
            reclaimed.job_id,
            "parser-worker-b",
            reclaimed.lease_token,
            uuid4(),
            now=now + timedelta(seconds=65),
        )

    stored = await source_texts.store_parser_extraction(
        account_id,
        document_version_id,
        "CV source text for the isolated parser boundary",
        parser,
        "job-result",
        now=now + timedelta(seconds=66),
    )
    succeeded = await jobs.mark_succeeded(
        reclaimed.job_id,
        "parser-worker-b",
        reclaimed.lease_token,
        stored.source_text.source_text_id,
        now=now + timedelta(seconds=67),
    )
    assert succeeded.status == "succeeded"
    assert succeeded.source_text_id == stored.source_text.source_text_id
    assert succeeded.completed_at == now + timedelta(seconds=67)
    assert succeeded.lease_token is None

    async with database.transaction() as session:
        persisted = await session.scalar(
            select(CandidateExtractionJob).where(CandidateExtractionJob.id == first.job.job_id)
        )
    assert persisted is not None
    with pytest.raises(DBAPIError, match="identity is immutable"):
        async with database.transaction() as session:
            await session.execute(
                update(CandidateExtractionJob)
                .where(CandidateExtractionJob.id == first.job.job_id)
                .values(parser_version="tampered")
            )

    await _delete_test_assets(
        database,
        files,
        {asset.id},
        worker_id="extraction-job-cleanup",
    )
    async with database.transaction() as session:
        assert await session.get(CandidateExtractionJob, first.job.job_id) is None


@pytest.mark.asyncio
async def test_extraction_job_schedule_is_owner_scoped_and_snapshot_bound(
    database: Database,
) -> None:
    account_id, _, _, files, asset, attached, _ = await _attached_document_version(
        database,
        "extraction-job-owner",
    )
    jobs = CandidateExtractionJobService(database)
    with pytest.raises(CandidateExtractionJobConflictError, match="account cannot process"):
        await jobs.schedule_extraction(uuid4(), attached.attached_version.version_id, None)
    with pytest.raises(CandidateExtractionJobNotFoundError):
        other_owner = (await _create_privacy_context(database)).account_id
        await jobs.schedule_extraction(other_owner, attached.attached_version.version_id, None)
    with pytest.raises(CandidateExtractionJobNotFoundError):
        await jobs.schedule_extraction(account_id, uuid4(), None)

    scheduled = await jobs.schedule_extraction(
        account_id,
        attached.attached_version.version_id,
        "job-owner",
    )
    assert scheduled.job.content_length == attached.attached_version.content_length
    assert scheduled.job.content_sha256 == attached.attached_version.content_sha256
    assert scheduled.job.retention_action == "delete"

    await _delete_test_assets(
        database,
        files,
        {asset.id},
        worker_id="extraction-job-owner-cleanup",
    )


@pytest.mark.asyncio
async def test_expired_final_lease_becomes_a_terminal_failure(database: Database) -> None:
    account_id, _, _, files, asset, attached, _ = await _attached_document_version(
        database,
        "extraction-job-expired-lease",
    )
    jobs = CandidateExtractionJobService(database)
    now = datetime.now(UTC)
    scheduled = await jobs.schedule_extraction(
        account_id,
        attached.attached_version.version_id,
        "expired-lease-schedule",
        now=now,
    )
    claim = (await jobs.claim_jobs("expired-lease-worker", 1, now=now))[0]
    assert claim.lease_token is not None

    current = claim
    for attempt in range(1, MAX_EXTRACTION_ATTEMPTS):
        failed = await jobs.mark_failed(
            current.job_id,
            "expired-lease-worker",
            current.lease_token,
            "parser_timeout",
            now=now + timedelta(seconds=attempt * 1_000),
        )
        assert failed.status == "retry"
        current = (
            await jobs.claim_jobs(
                "expired-lease-worker",
                1,
                now=failed.available_at,
            )
        )[0]

    assert current.attempts == MAX_EXTRACTION_ATTEMPTS
    assert current.lease_token is not None
    assert current.locked_at is not None
    exhausted_at = now + timedelta(seconds=MAX_EXTRACTION_ATTEMPTS * 2_000)
    assert exhausted_at - current.locked_at > timedelta(seconds=EXTRACTION_LEASE_SECONDS)
    assert await jobs.claim_jobs("expired-lease-recovery", 1, now=exhausted_at) == ()

    async with database.transaction() as session:
        expired = await session.get(CandidateExtractionJob, scheduled.job.job_id)
    assert expired is not None
    assert expired.status == "failed"
    assert expired.error_code == "lease_expired"
    assert expired.completed_at == exhausted_at
    assert expired.lease_token is None

    await _delete_test_assets(
        database,
        files,
        {asset.id},
        worker_id="extraction-job-expired-lease-cleanup",
    )
