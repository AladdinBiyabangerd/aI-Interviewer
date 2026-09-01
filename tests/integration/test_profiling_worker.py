from datetime import UTC, datetime

import pytest
from sqlalchemy import select, update
from tests.integration.test_candidate_documents import _delete_test_assets
from tests.integration.test_file_security import _application_keyring
from tests.integration.test_profiling_jobs import _schedule
from tests.test_candidate_profiles import _result

from ai_interviewer.candidate_inputs.source_texts import CandidateSourceTextService
from ai_interviewer.model_gateway import (
    ModelGatewayPolicy,
    ModelProviderRequest,
    ModelProviderResponse,
    StructuredModelGateway,
)
from ai_interviewer.persistence.database import Database
from ai_interviewer.persistence.models import AuditEvent, OutboxEvent
from ai_interviewer.privacy.lifecycle import PrivacyLifecycleService
from ai_interviewer.privacy.models import ProcessorActivity, ProcessorUsage
from ai_interviewer.privacy.policy import build_default_jurisdiction_registry
from ai_interviewer.profiling import (
    CandidateProfileService,
    CandidateProfilingWorker,
    candidate_profile_prompt,
)
from ai_interviewer.profiling.job_models import CandidateProfilingJob
from ai_interviewer.profiling.models import CandidateProfileVersion

pytestmark = pytest.mark.integration


class RecordingProfileProvider:
    def __init__(self) -> None:
        self.requests: list[ModelProviderRequest] = []

    async def generate(self, request: ModelProviderRequest) -> ModelProviderResponse:
        self.requests.append(request)
        return ModelProviderResponse(
            output_json=_result().output.model_dump_json(),
            model_release=request.model_release,
            finish_reason="stop",
        )


def _gateway(provider: RecordingProfileProvider) -> StructuredModelGateway:
    return StructuredModelGateway(
        provider,
        _result().model_release,
        ModelGatewayPolicy(max_attempts=1, retry_base_seconds=0),
    )


def _privacy(database: Database) -> PrivacyLifecycleService:
    return PrivacyLifecycleService(
        database=database,
        registry=build_default_jurisdiction_registry(),
        application_keyring=_application_keyring(),
    )


@pytest.mark.asyncio
async def test_real_profiling_worker_authorizes_calls_persists_and_completes(
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
    ) = await _schedule(database, "profiling-worker-success")
    provider = RecordingProfileProvider()
    gateway = _gateway(provider)
    prompt = candidate_profile_prompt("cv")
    scheduled = await jobs.schedule_profiling(
        account_id,
        preparation_id,
        document_version_id,
        source_version_id,
        prompt.release_snapshot(gateway.model_release, processor_activity_id),
        "profiling-worker-schedule",
    )
    profiles = CandidateProfileService(database, _application_keyring())
    worker = CandidateProfilingWorker(
        jobs,
        CandidateSourceTextService(database, _application_keyring()),
        profiles,
        _privacy(database),
        gateway,
        worker_id="profiling-worker-integration",
    )

    outcome = (await worker.run_once())[0]

    assert outcome.status == "succeeded"
    assert len(provider.requests) == 1
    assert provider.requests[0].request_id == scheduled.job.job_id
    assert provider.requests[0].input_text == "Python backend engineer"
    assert provider.requests[0].prompt_release == prompt.prompt_release

    async with database.transaction() as session:
        job = await session.get(CandidateProfilingJob, scheduled.job.job_id)
        usage = await session.scalar(
            select(ProcessorUsage).where(
                ProcessorUsage.account_id == account_id,
                ProcessorUsage.processor_activity_id == processor_activity_id,
            )
        )
        profile_version = await session.scalar(
            select(CandidateProfileVersion).where(
                CandidateProfileVersion.profile_id == job.profile_id  # type: ignore[union-attr]
            )
        )
        audit_details = list(
            (
                await session.scalars(
                    select(AuditEvent.details).where(AuditEvent.owner_id == account_id)
                )
            ).all()
        )
        outbox_payloads = list(
            (
                await session.scalars(
                    select(OutboxEvent.payload).where(OutboxEvent.owner_id == account_id)
                )
            ).all()
        )
    assert job is not None and job.status == "succeeded" and job.profile_id is not None
    assert usage is not None
    assert usage.processor_subject_reference is None
    assert usage.processor_subject_ciphertext is not None
    assert profile_version is not None
    assert b"Python" not in profile_version.profile_ciphertext
    assert "Python backend engineer" not in f"{audit_details} {outbox_payloads}"

    await _delete_test_assets(
        database,
        files,
        {asset.id},
        worker_id="profiling-worker-success-cleanup",
    )


@pytest.mark.asyncio
async def test_processor_revocation_dead_letters_before_external_call(database: Database) -> None:
    (
        account_id,
        preparation_id,
        files,
        asset,
        document_version_id,
        source_version_id,
        processor_activity_id,
        jobs,
    ) = await _schedule(database, "profiling-worker-revoked")
    provider = RecordingProfileProvider()
    gateway = _gateway(provider)
    scheduled = await jobs.schedule_profiling(
        account_id,
        preparation_id,
        document_version_id,
        source_version_id,
        candidate_profile_prompt("cv").release_snapshot(
            gateway.model_release,
            processor_activity_id,
        ),
        "profiling-worker-revoked-schedule",
        now=datetime.now(UTC),
    )
    async with database.transaction() as session:
        await session.execute(
            update(ProcessorActivity)
            .where(ProcessorActivity.id == processor_activity_id)
            .values(status="suspended")
        )
    worker = CandidateProfilingWorker(
        jobs,
        CandidateSourceTextService(database, _application_keyring()),
        CandidateProfileService(database, _application_keyring()),
        _privacy(database),
        gateway,
        worker_id="profiling-worker-revoked",
    )

    outcome = (await worker.run_once())[0]

    assert outcome.status == "failed"
    assert outcome.error_code == "policy_unavailable"
    assert provider.requests == []
    async with database.transaction() as session:
        job = await session.get(CandidateProfilingJob, scheduled.job.job_id)
        usage = await session.scalar(
            select(ProcessorUsage).where(
                ProcessorUsage.account_id == account_id,
                ProcessorUsage.processor_activity_id == processor_activity_id,
            )
        )
    assert job is not None and job.status == "dead_letter"
    assert job.error_code == "policy_unavailable"
    assert usage is None

    await _delete_test_assets(
        database,
        files,
        {asset.id},
        worker_id="profiling-worker-revoked-cleanup",
    )
