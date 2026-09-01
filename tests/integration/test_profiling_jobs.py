from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from sqlalchemy import select, update
from sqlalchemy.exc import DBAPIError
from tests.integration.test_candidate_documents import _delete_test_assets
from tests.integration.test_candidate_profiles import _source_revision
from tests.integration.test_file_security import _application_keyring
from tests.test_candidate_profiles import _result

from ai_interviewer.persistence.database import Database
from ai_interviewer.persistence.models import AuditEvent, OutboxEvent
from ai_interviewer.privacy.lifecycle import PrivacyLifecycleService
from ai_interviewer.privacy.models import PrivacyProfile, Processor, ProcessorActivity
from ai_interviewer.privacy.policy import build_default_jurisdiction_registry
from ai_interviewer.profiling import (
    MAX_PROFILING_ATTEMPTS,
    CandidateProfileService,
    CandidateProfilingJobConflictError,
    CandidateProfilingJobNotFoundError,
    CandidateProfilingJobService,
    CandidateProfilingReleaseSnapshot,
)
from ai_interviewer.profiling.job_models import CandidateProfilingJob

pytestmark = pytest.mark.integration


def _release(processor_activity_id: UUID) -> CandidateProfilingReleaseSnapshot:
    result = _result()
    return CandidateProfilingReleaseSnapshot(
        model_release=result.model_release,
        prompt_release=result.prompt_release,
        processor_activity_id=processor_activity_id,
        instructions_sha256=result.instructions_sha256,
        output_schema_sha256=result.output_schema_sha256,
        max_output_tokens=4_096,
    )


async def _schedule(
    database: Database,
    suffix: str,
) -> tuple[
    UUID,
    UUID,
    object,
    object,
    UUID,
    UUID,
    UUID,
    CandidateProfilingJobService,
]:
    account_id, preparation_id, files, asset, _, stored_source = await _source_revision(
        database,
        suffix,
    )
    document_version_id = stored_source.source_text.document_version_id
    source_version_id = stored_source.source_text.versions[0].text_version_id
    async with database.transaction() as session:
        privacy_profile = await session.get(PrivacyProfile, account_id)
        assert privacy_profile is not None
        processor = Processor(
            processor_key="test-provider",
            inventory_version=f"1-{suffix}",
            legal_name="Test Structured Model Processor",
            status="active",
            privacy_uri="https://processor.example.test/privacy",
            contract_reference="dpa-reviewed-test",
            operating_countries=["AZ"],
            subprocessors=[],
        )
        session.add(processor)
        await session.flush()
        activity = ProcessorActivity(
            processor_id=processor.id,
            privacy_policy_version_id=privacy_profile.privacy_policy_version_id,
            status="active",
            data_category="candidate_document",
            purpose="interview_preparation",
            origin_region=privacy_profile.storage_region,
            processing_region=privacy_profile.storage_region,
            storage_region=privacy_profile.storage_region,
            cross_border=False,
            transfer_mechanism=None,
            deletion_mechanism="provider-request-id",
            deletion_sla_days=30,
            approved_at=datetime.now(UTC),
        )
        session.add(activity)
        await session.flush()
        processor_activity_id = activity.id
    jobs = CandidateProfilingJobService(database)
    return (
        account_id,
        preparation_id,
        files,
        asset,
        document_version_id,
        source_version_id,
        processor_activity_id,
        jobs,
    )


@pytest.mark.asyncio
async def test_profiling_job_is_idempotent_fenced_and_requires_matching_profile(
    database: Database,
) -> None:
    (
        account_id,
        preparation_id,
        files,
        asset,
        document_version_id,
        source_version_id,
        processor_activity_id,
        jobs,
    ) = await _schedule(database, "profiling-job-lifecycle")
    now = datetime.now(UTC)
    release = _release(processor_activity_id)

    first = await jobs.schedule_profiling(
        account_id,
        preparation_id,
        document_version_id,
        source_version_id,
        release,
        "profiling-schedule",
        now=now,
    )
    repeated = await jobs.schedule_profiling(
        account_id,
        preparation_id,
        document_version_id,
        source_version_id,
        release,
        "profiling-schedule-retry",
        now=now + timedelta(seconds=1),
    )
    assert first.created is True
    assert repeated.created is False
    assert repeated.job == first.job
    assert first.job.status == "pending"
    assert first.job.attempts == 0
    assert first.job.schema_id == "cv-profile"
    assert first.job.source_text_version_id == source_version_id
    assert (
        await jobs.get_profiling_job(
            account_id,
            preparation_id,
            document_version_id,
            source_version_id,
        )
        == first.job
    )
    with pytest.raises(CandidateProfilingJobNotFoundError):
        await jobs.get_profiling_job(
            uuid4(),
            preparation_id,
            document_version_id,
            source_version_id,
        )

    changed_release = CandidateProfilingReleaseSnapshot(
        model_release=release.model_release,
        prompt_release=release.prompt_release,
        processor_activity_id=release.processor_activity_id,
        instructions_sha256="c" * 64,
        output_schema_sha256=release.output_schema_sha256,
    )
    with pytest.raises(CandidateProfilingJobConflictError, match="different profiling release"):
        await jobs.schedule_profiling(
            account_id,
            preparation_id,
            document_version_id,
            source_version_id,
            changed_release,
            None,
            now=now + timedelta(seconds=1),
        )

    unapproved_processor_release = CandidateProfilingReleaseSnapshot(
        model_release=release.model_release,
        prompt_release=release.prompt_release,
        processor_activity_id=uuid4(),
        instructions_sha256=release.instructions_sha256,
        output_schema_sha256=release.output_schema_sha256,
    )
    with pytest.raises(CandidateProfilingJobConflictError, match="processor activity"):
        await jobs.schedule_profiling(
            account_id,
            preparation_id,
            document_version_id,
            source_version_id,
            unapproved_processor_release,
            None,
            now=now + timedelta(seconds=1),
        )

    claim = (await jobs.claim_jobs("profiling-worker-a", 1, now=now + timedelta(seconds=2)))[0]
    assert claim.status == "processing"
    assert claim.attempts == 1
    assert claim.lease_token is not None
    retry = await jobs.mark_failed(
        claim.job_id,
        "profiling-worker-a",
        claim.lease_token,
        "provider_timeout",
        now=now + timedelta(seconds=3),
    )
    assert retry.status == "retry"
    assert retry.error_code == "provider_timeout"
    assert retry.available_at == now + timedelta(seconds=63)
    assert await jobs.claim_jobs("profiling-worker-b", 1, now=now + timedelta(seconds=62)) == ()

    reclaimed = (await jobs.claim_jobs("profiling-worker-b", 1, now=retry.available_at))[0]
    assert reclaimed.attempts == 2
    assert reclaimed.lease_token is not None
    assert reclaimed.lease_token != claim.lease_token
    with pytest.raises(CandidateProfilingJobConflictError, match="not claimed"):
        await jobs.mark_failed(
            reclaimed.job_id,
            "profiling-worker-a",
            claim.lease_token,
            "internal_failure",
        )
    with pytest.raises(CandidateProfilingJobConflictError, match="matching encrypted profile"):
        await jobs.mark_succeeded(
            reclaimed.job_id,
            "profiling-worker-b",
            reclaimed.lease_token,
            uuid4(),
        )

    profiles = CandidateProfileService(database, _application_keyring())
    stored_profile = await profiles.store_model_profile(
        account_id,
        preparation_id,
        document_version_id,
        source_version_id,
        _result(),
        "profiling-job-result",
        now=now + timedelta(seconds=64),
    )
    succeeded = await jobs.mark_succeeded(
        reclaimed.job_id,
        "profiling-worker-b",
        reclaimed.lease_token,
        stored_profile.candidate_profile.profile_id,
        now=now + timedelta(seconds=65),
    )
    assert succeeded.status == "succeeded"
    assert succeeded.profile_id == stored_profile.candidate_profile.profile_id
    assert succeeded.completed_at == now + timedelta(seconds=65)
    assert succeeded.lease_token is None

    async with database.transaction() as session:
        audit = await session.scalar(
            select(AuditEvent).where(
                AuditEvent.resource_id == first.job.job_id,
                AuditEvent.action == "candidate_profiling_job.succeeded",
            )
        )
        event = await session.scalar(
            select(OutboxEvent).where(
                OutboxEvent.aggregate_id == first.job.job_id,
                OutboxEvent.event_type == "candidate_profiling_job.succeeded",
            )
        )
    assert audit is not None and event is not None
    assert "Python backend engineer" not in f"{audit.details} {event.payload}"
    assert release.instructions_sha256 not in f"{audit.details} {event.payload}"

    with pytest.raises(DBAPIError, match="snapshot is immutable"):
        async with database.transaction() as session:
            await session.execute(
                update(CandidateProfilingJob)
                .where(CandidateProfilingJob.id == first.job.job_id)
                .values(processor_activity_id=uuid4())
            )
    with pytest.raises(DBAPIError, match="terminal candidate profiling job"):
        async with database.transaction() as session:
            await session.execute(
                update(CandidateProfilingJob)
                .where(CandidateProfilingJob.id == first.job.job_id)
                .values(
                    status="retry",
                    profile_id=None,
                    completed_at=None,
                    error_code="internal_failure",
                )
            )

    privacy = PrivacyLifecycleService(
        database=database,
        registry=build_default_jurisdiction_registry(),
        subject_hmac_key=b"candidate-profiling-job-export-key" * 2,
        candidate_profile_lifecycle=profiles,
        candidate_profiling_job_lifecycle=jobs,
    )
    exported = await privacy.create_request(
        account_id,
        "export",
        "profiling-job-export-key",
        "profiling-job-export",
    )
    assert exported.data is not None
    assert exported.data["schema_version"] == "phase-1b-c2"
    exported_jobs = exported.data["candidate_profiling_jobs"]
    assert len(exported_jobs) == 1
    assert exported_jobs[0]["job_id"] == str(first.job.job_id)
    assert exported_jobs[0]["processor_activity_id"] == str(processor_activity_id)
    assert exported_jobs[0]["status"] == "succeeded"
    assert exported_jobs[0]["profile_id"] == str(succeeded.profile_id)

    await _delete_test_assets(
        database,
        files,
        {asset.id},
        worker_id="profiling-job-cleanup",
    )
    async with database.transaction() as session:
        assert await session.get(CandidateProfilingJob, first.job.job_id) is None


@pytest.mark.asyncio
async def test_profiling_job_owner_scope_and_final_stale_lease(
    database: Database,
) -> None:
    (
        account_id,
        preparation_id,
        files,
        asset,
        document_version_id,
        source_version_id,
        processor_activity_id,
        jobs,
    ) = await _schedule(database, "profiling-job-dead-letter")
    now = datetime.now(UTC)

    with pytest.raises(CandidateProfilingJobConflictError, match="account cannot profile"):
        await jobs.schedule_profiling(
            uuid4(),
            preparation_id,
            document_version_id,
            source_version_id,
            _release(processor_activity_id),
            None,
        )
    with pytest.raises(CandidateProfilingJobNotFoundError):
        await jobs.schedule_profiling(
            account_id,
            uuid4(),
            document_version_id,
            source_version_id,
            _release(processor_activity_id),
            None,
        )

    scheduled = await jobs.schedule_profiling(
        account_id,
        preparation_id,
        document_version_id,
        source_version_id,
        _release(processor_activity_id),
        "profiling-dead-letter-schedule",
        now=now,
    )
    current = (await jobs.claim_jobs("profiling-dead-letter-worker", 1, now=now))[0]
    assert current.lease_token is not None
    for attempt in range(1, MAX_PROFILING_ATTEMPTS):
        failed = await jobs.mark_failed(
            current.job_id,
            "profiling-dead-letter-worker",
            current.lease_token,
            "provider_timeout",
            now=now + timedelta(seconds=attempt * 1_000),
        )
        assert failed.status == "retry"
        current = (
            await jobs.claim_jobs(
                "profiling-dead-letter-worker",
                1,
                now=failed.available_at,
            )
        )[0]

    assert current.attempts == MAX_PROFILING_ATTEMPTS
    assert current.lease_token is not None
    assert current.locked_at is not None
    exhausted_at = current.locked_at + timedelta(seconds=301)
    assert await jobs.claim_jobs("profiling-recovery-worker", 1, now=exhausted_at) == ()
    async with database.transaction() as session:
        dead_letter = await session.get(CandidateProfilingJob, scheduled.job.job_id)
    assert dead_letter is not None
    assert dead_letter.status == "dead_letter"
    assert dead_letter.error_code == "lease_expired"
    assert dead_letter.completed_at == exhausted_at
    assert dead_letter.lease_token is None

    await _delete_test_assets(
        database,
        files,
        {asset.id},
        worker_id="profiling-job-dead-letter-cleanup",
    )
