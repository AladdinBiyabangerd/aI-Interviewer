from __future__ import annotations

import asyncio
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest

from ai_interviewer.candidate_inputs.source_texts import (
    CandidateSourceTextConflictError,
    CandidateSourceTextNotFoundError,
    CandidateSourceTextRecord,
    CandidateSourceTextVersionRecord,
)
from ai_interviewer.core.config import Settings
from ai_interviewer.model_gateway import (
    DisabledModelGateway,
    ModelGatewayError,
    ModelGatewayResult,
    ModelReleaseIdentity,
)
from ai_interviewer.privacy.processors import ProcessorPolicyError
from ai_interviewer.profiling import (
    CandidateProfileConflictError,
    CandidateProfileRecord,
    CandidateProfileUnavailableError,
    CandidateProfilingJobConflictError,
    CandidateProfilingJobRecord,
    CandidateProfilingWorker,
    CandidateProfilingWorkerUnavailableError,
    CvProfileOutput,
    CvSkillClaim,
    DisabledCandidateProfilingWorker,
    JobDescriptionProfileOutput,
    SourceSpan,
    StoreModelProfileResult,
    build_candidate_profiling_worker,
    candidate_profile_prompt,
)
from ai_interviewer.profiling.job_models import RETRYABLE_PROFILING_FAILURES

_NOW = datetime(2026, 9, 1, tzinfo=UTC)
_MODEL_RELEASE = ModelReleaseIdentity(
    provider="test-provider",
    model_id="structured-profile-model",
    model_version="2026-09-01",
)


def _profile(*, quote: str = "Python") -> CvProfileOutput:
    return CvProfileOutput(
        document_type="cv",
        languages=("en",),
        skills=(
            CvSkillClaim(
                claim_id="skill_python",
                statement="Python experience",
                assertion_kind="explicit",
                evidence=(SourceSpan(start=0, end=6, quote=quote),),
                name="Python",
                category="programming_language",
            ),
        ),
    )


def _result(*, quote: str = "Python") -> ModelGatewayResult[CvProfileOutput]:
    prompt = candidate_profile_prompt("cv")
    return ModelGatewayResult(
        output=_profile(quote=quote),
        model_release=_MODEL_RELEASE,
        prompt_release=prompt.prompt_release,
        instructions_sha256=prompt.instructions_sha256,
        output_schema_sha256=prompt.output_schema_sha256,
        attempts=1,
    )


def _job(**overrides: object) -> CandidateProfilingJobRecord:
    prompt = candidate_profile_prompt("cv")
    values: dict[str, object] = {
        "job_id": uuid4(),
        "owner_id": uuid4(),
        "preparation_id": uuid4(),
        "document_version_id": uuid4(),
        "source_text_id": uuid4(),
        "source_text_version_id": uuid4(),
        "processor_activity_id": uuid4(),
        "document_type": "cv",
        "privacy_policy_version_id": uuid4(),
        "retention_rule_id": uuid4(),
        "jurisdiction_code": "AZERBAIJAN",
        "legal_basis": "contract",
        "retain_until": _NOW + timedelta(days=30),
        "retention_action": "delete",
        "model_provider": _MODEL_RELEASE.provider,
        "model_id": _MODEL_RELEASE.model_id,
        "model_version": _MODEL_RELEASE.model_version,
        "prompt_id": prompt.prompt_release.prompt_id,
        "prompt_version": prompt.prompt_release.prompt_version,
        "schema_id": prompt.prompt_release.schema_id,
        "schema_version": prompt.prompt_release.schema_version,
        "instructions_sha256": prompt.instructions_sha256,
        "output_schema_sha256": prompt.output_schema_sha256,
        "max_output_tokens": prompt.max_output_tokens,
        "status": "processing",
        "attempts": 1,
        "available_at": _NOW,
        "locked_at": _NOW,
        "locked_by": "profiling-worker",
        "lease_token": uuid4(),
        "error_code": None,
        "profile_id": None,
        "completed_at": None,
        "created_at": _NOW,
        "updated_at": _NOW,
    }
    values.update(overrides)
    return CandidateProfilingJobRecord(**values)  # type: ignore[arg-type]


def _source(job: CandidateProfilingJobRecord, *, content: str = "Python backend engineer"):
    return CandidateSourceTextRecord(
        source_text_id=job.source_text_id,
        document_version_id=job.document_version_id,
        latest_version_number=1,
        aggregate_version=1,
        created_at=_NOW,
        updated_at=_NOW,
        versions=(
            CandidateSourceTextVersionRecord(
                text_version_id=job.source_text_version_id,
                version_number=1,
                origin="user_correction",
                previous_version_id=uuid4(),
                parser_release_policy_id=None,
                parser_adapter=None,
                parser_version=None,
                isolation_profile=None,
                character_count=len(content),
                utf8_byte_count=len(content.encode()),
                line_count=1,
                created_at=_NOW,
                content=content,
            ),
        ),
    )


def _profile_record(job: CandidateProfilingJobRecord) -> CandidateProfileRecord:
    return CandidateProfileRecord(
        profile_id=uuid4(),
        source_text_id=job.source_text_id,
        source_text_version_id=job.source_text_version_id,
        document_version_id=job.document_version_id,
        document_type=job.document_type,
        latest_version_number=1,
        aggregate_version=1,
        privacy_policy_version_id=job.privacy_policy_version_id,
        retention_rule_id=job.retention_rule_id,
        jurisdiction_code=job.jurisdiction_code,
        legal_basis=job.legal_basis,
        retain_until=job.retain_until,
        retention_action="delete",
        created_at=_NOW,
        updated_at=_NOW,
        versions=(),
    )


class FakeJobs:
    def __init__(
        self,
        job: CandidateProfilingJobRecord,
        *,
        fence_success: bool = False,
        fence_failure: bool = False,
    ) -> None:
        self.job = job
        self.fence_success = fence_success
        self.fence_failure = fence_failure
        self.failed_codes: list[str] = []
        self.succeeded_profile_id: UUID | None = None

    async def claim_jobs(self, worker_id: str, limit: int, **_: object):
        assert worker_id == "profiling-worker"
        return (self.job,) if limit else ()

    async def mark_failed(
        self,
        job_id: UUID,
        worker_id: str,
        lease_token: UUID,
        error_code: str,
        **_: object,
    ):
        assert (job_id, worker_id, lease_token) == (
            self.job.job_id,
            "profiling-worker",
            self.job.lease_token,
        )
        if self.fence_failure:
            raise CandidateProfilingJobConflictError("job is not claimed")
        self.failed_codes.append(error_code)
        status = "retry" if error_code in RETRYABLE_PROFILING_FAILURES else "dead_letter"
        return replace(self.job, status=status, error_code=error_code)

    async def mark_succeeded(
        self,
        job_id: UUID,
        worker_id: str,
        lease_token: UUID,
        profile_id: UUID,
        **_: object,
    ):
        if self.fence_success:
            raise CandidateProfilingJobConflictError("job is not claimed")
        assert (job_id, worker_id, lease_token) == (
            self.job.job_id,
            "profiling-worker",
            self.job.lease_token,
        )
        self.succeeded_profile_id = profile_id
        return replace(self.job, status="succeeded", profile_id=profile_id)


class FakeSourceTexts:
    def __init__(
        self,
        source: CandidateSourceTextRecord,
        *,
        error: BaseException | None = None,
    ) -> None:
        self.source = source
        self.error = error
        self.calls = 0

    async def get_source_text(self, *_: object) -> CandidateSourceTextRecord:
        self.calls += 1
        if self.error is not None:
            raise self.error
        return self.source


class FakeProfiles:
    def __init__(
        self,
        record: CandidateProfileRecord,
        *,
        error: BaseException | None = None,
    ) -> None:
        self.record = record
        self.error = error
        self.calls = 0

    async def store_model_profile(self, *_: object, **__: object) -> StoreModelProfileResult:
        self.calls += 1
        if self.error is not None:
            raise self.error
        return StoreModelProfileResult(candidate_profile=self.record, created=True)


class FakeProcessorUsage:
    def __init__(
        self,
        events: list[str],
        *,
        error: BaseException | None = None,
    ) -> None:
        self.events = events
        self.error = error
        self.references: list[str] = []

    async def register_processor_use(
        self,
        account_id: UUID,
        *,
        processor_activity_id: UUID,
        processor_subject_reference: str,
    ) -> object:
        del account_id, processor_activity_id
        self.events.append("processor")
        self.references.append(processor_subject_reference)
        if self.error is not None:
            raise self.error
        return object()


class FakeGateway:
    enabled = True
    model_release = _MODEL_RELEASE

    def __init__(
        self,
        events: list[str],
        *,
        result: ModelGatewayResult[CvProfileOutput] | None = None,
        error: BaseException | None = None,
    ) -> None:
        self.events = events
        self.result = result or _result()
        self.error = error
        self.requests = []

    async def generate(self, request, output_type):
        self.events.append("gateway")
        self.requests.append((request, output_type))
        if self.error is not None:
            raise self.error
        return self.result


def _worker(
    job: CandidateProfilingJobRecord,
    *,
    jobs: FakeJobs | None = None,
    source: CandidateSourceTextRecord | None = None,
    profiles: FakeProfiles | None = None,
    processor: FakeProcessorUsage | None = None,
    gateway: FakeGateway | None = None,
):
    events: list[str] = []
    resolved_jobs = jobs or FakeJobs(job)
    resolved_source = FakeSourceTexts(source or _source(job))
    resolved_profiles = profiles or FakeProfiles(_profile_record(job))
    resolved_processor = processor or FakeProcessorUsage(events)
    resolved_gateway = gateway or FakeGateway(events)
    worker = CandidateProfilingWorker(
        resolved_jobs,  # type: ignore[arg-type]
        resolved_source,  # type: ignore[arg-type]
        resolved_profiles,  # type: ignore[arg-type]
        resolved_processor,
        resolved_gateway,
        worker_id="profiling-worker",
    )
    return (
        worker,
        resolved_jobs,
        resolved_source,
        resolved_profiles,
        resolved_processor,
        resolved_gateway,
    )


@pytest.mark.asyncio
async def test_worker_authorizes_processor_then_persists_and_fences_success() -> None:
    job = _job()
    worker, jobs, _, profiles, processor, gateway = _worker(job)

    outcome = (await worker.run_once())[0]

    assert outcome.status == "succeeded"
    assert jobs.succeeded_profile_id == profiles.record.profile_id
    assert processor.references == [str(job.job_id)]
    assert gateway.events == ["processor", "gateway"]
    request, output_type = gateway.requests[0]
    assert request.request_id == job.job_id
    assert request.input_text == "Python backend engineer"
    assert output_type is CvProfileOutput
    assert "untrusted" in request.instructions
    assert "Python backend engineer" not in repr(request)


@pytest.mark.asyncio
async def test_gateway_safe_failure_is_mapped_to_retry() -> None:
    job = _job()
    events: list[str] = []
    gateway = FakeGateway(events, error=ModelGatewayError("provider_timeout", 3))
    worker, jobs, *_ = _worker(job, gateway=gateway, processor=FakeProcessorUsage(events))

    outcome = (await worker.run_once())[0]

    assert outcome.status == "retry"
    assert outcome.error_code == "provider_timeout"
    assert jobs.failed_codes == ["provider_timeout"]


@pytest.mark.asyncio
async def test_invalid_exact_evidence_is_dead_lettered() -> None:
    job = _job()
    events: list[str] = []
    gateway = FakeGateway(events, result=_result(quote="Kotlin"))
    worker, jobs, *_ = _worker(job, gateway=gateway, processor=FakeProcessorUsage(events))

    outcome = (await worker.run_once())[0]

    assert outcome.status == "failed"
    assert outcome.error_code == "invalid_output"
    assert jobs.failed_codes == ["invalid_output"]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("job", "expected"),
    [
        (_job(prompt_version="unsupported"), "policy_unavailable"),
        (_job(model_version="different"), "model_identity_mismatch"),
    ],
)
async def test_release_mismatch_never_reaches_source_or_provider(
    job: CandidateProfilingJobRecord,
    expected: str,
) -> None:
    worker, jobs, source, _, _, gateway = _worker(job)

    outcome = (await worker.run_once())[0]

    assert outcome.error_code == expected
    assert jobs.failed_codes == [expected]
    assert source.calls == 0
    assert gateway.requests == []


@pytest.mark.asyncio
async def test_processor_denial_prevents_external_call() -> None:
    job = _job()
    events: list[str] = []
    processor = FakeProcessorUsage(events, error=ProcessorPolicyError("processor denied"))
    gateway = FakeGateway(events)
    worker, jobs, *_ = _worker(job, processor=processor, gateway=gateway)

    outcome = (await worker.run_once())[0]

    assert outcome.error_code == "policy_unavailable"
    assert jobs.failed_codes == ["policy_unavailable"]
    assert gateway.requests == []


@pytest.mark.asyncio
async def test_stale_source_and_profile_conflict_fail_closed() -> None:
    job = _job()
    stale_source = replace(
        _source(job),
        versions=(replace(_source(job).versions[0], text_version_id=uuid4()),),
    )
    stale_worker, stale_jobs, *_ = _worker(job, source=stale_source)
    stale_outcome = (await stale_worker.run_once())[0]
    assert stale_outcome.error_code == "persistence_conflict"
    assert stale_jobs.failed_codes == ["persistence_conflict"]

    conflicting_profiles = FakeProfiles(
        _profile_record(job),
        error=CandidateProfileConflictError("stale profile"),
    )
    conflict_worker, conflict_jobs, *_ = _worker(job, profiles=conflicting_profiles)
    conflict_outcome = (await conflict_worker.run_once())[0]
    assert conflict_outcome.error_code == "persistence_conflict"
    assert conflict_jobs.failed_codes == ["persistence_conflict"]


@pytest.mark.asyncio
async def test_lost_lease_after_profile_write_returns_fenced_without_failure_mutation() -> None:
    job = _job()
    jobs = FakeJobs(job, fence_success=True)
    worker, _, _, profiles, *_ = _worker(job, jobs=jobs)

    outcome = (await worker.run_once())[0]

    assert profiles.calls == 1
    assert outcome.status == "fenced"
    assert outcome.error_code == "lease_expired"
    assert jobs.failed_codes == []


@pytest.mark.asyncio
async def test_disabled_worker_never_claims_and_enabled_worker_requires_gateway() -> None:
    disabled = build_candidate_profiling_worker(
        Settings(_env_file=None),
        object(),  # type: ignore[arg-type]
        object(),  # type: ignore[arg-type]
        object(),  # type: ignore[arg-type]
        object(),  # type: ignore[arg-type]
        DisabledModelGateway(),
    )
    assert isinstance(disabled, DisabledCandidateProfilingWorker)
    with pytest.raises(CandidateProfilingWorkerUnavailableError):
        await disabled.run_once()

    with pytest.raises(CandidateProfilingWorkerUnavailableError):
        CandidateProfilingWorker(
            object(),  # type: ignore[arg-type]
            object(),  # type: ignore[arg-type]
            object(),  # type: ignore[arg-type]
            object(),  # type: ignore[arg-type]
            DisabledModelGateway(),
            worker_id="worker",
        )


def test_prompt_registry_covers_jd_and_rejects_unknown_document_types() -> None:
    prompt = candidate_profile_prompt("job_description")
    assert prompt.operation == "profile_job_description"
    assert prompt.prompt_release.schema_id == "job-description-profile"
    assert prompt.output_type is JobDescriptionProfileOutput
    assert "Do not infer company facts" in prompt.instructions
    with pytest.raises(ValueError, match="document type"):
        candidate_profile_prompt("unknown")  # type: ignore[arg-type]


@pytest.mark.asyncio
async def test_worker_rejects_invalid_worker_and_unleased_claim() -> None:
    job = _job()
    with pytest.raises(ValueError, match="worker_id"):
        CandidateProfilingWorker(
            FakeJobs(job),  # type: ignore[arg-type]
            FakeSourceTexts(_source(job)),  # type: ignore[arg-type]
            FakeProfiles(_profile_record(job)),  # type: ignore[arg-type]
            FakeProcessorUsage([]),
            FakeGateway([]),
            worker_id=" ",
        )
    worker, *_ = _worker(replace(job, lease_token=None))
    with pytest.raises(RuntimeError, match="lease token"):
        await worker.run_once()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("error", "expected"),
    [
        (CandidateSourceTextNotFoundError("missing"), "source_unavailable"),
        (CandidateSourceTextConflictError("stale"), "persistence_conflict"),
    ],
)
async def test_source_failures_are_normalized(error: BaseException, expected: str) -> None:
    job = _job()
    source = FakeSourceTexts(_source(job), error=error)
    worker, jobs, *_ = _worker(job)
    worker._source_texts = source  # type: ignore[assignment]

    outcome = (await worker.run_once())[0]

    assert outcome.error_code == expected
    assert jobs.failed_codes == [expected]


@pytest.mark.asyncio
async def test_empty_source_and_result_release_mismatch_fail_closed() -> None:
    job = _job()
    empty = replace(_source(job), versions=())
    empty_worker, empty_jobs, *_ = _worker(job, source=empty)
    empty_outcome = (await empty_worker.run_once())[0]
    assert empty_outcome.error_code == "persistence_conflict"
    assert empty_jobs.failed_codes == ["persistence_conflict"]

    mismatched = replace(_result(), instructions_sha256="f" * 64)
    events: list[str] = []
    mismatch_worker, mismatch_jobs, *_ = _worker(
        job,
        processor=FakeProcessorUsage(events),
        gateway=FakeGateway(events, result=mismatched),
    )
    mismatch_outcome = (await mismatch_worker.run_once())[0]
    assert mismatch_outcome.error_code == "model_identity_mismatch"
    assert mismatch_jobs.failed_codes == ["model_identity_mismatch"]


@pytest.mark.asyncio
@pytest.mark.parametrize("boundary", ["processor", "gateway", "profile"])
async def test_unexpected_boundary_failures_are_payload_blind_internal_errors(
    boundary: str,
) -> None:
    job = _job()
    events: list[str] = []
    processor = FakeProcessorUsage(
        events,
        error=RuntimeError("candidate-secret") if boundary == "processor" else None,
    )
    gateway = FakeGateway(
        events,
        error=RuntimeError("candidate-secret") if boundary == "gateway" else None,
    )
    profiles = FakeProfiles(
        _profile_record(job),
        error=RuntimeError("candidate-secret") if boundary == "profile" else None,
    )
    worker, jobs, *_ = _worker(
        job,
        processor=processor,
        gateway=gateway,
        profiles=profiles,
    )

    outcome = (await worker.run_once())[0]

    assert outcome.error_code == "internal_failure"
    assert "candidate-secret" not in repr(outcome)
    assert jobs.failed_codes == ["internal_failure"]


@pytest.mark.asyncio
@pytest.mark.parametrize("boundary", ["processor", "gateway", "profile"])
async def test_worker_propagates_cancellation_without_committing_failure(boundary: str) -> None:
    job = _job()
    events: list[str] = []
    processor = FakeProcessorUsage(
        events,
        error=asyncio.CancelledError() if boundary == "processor" else None,
    )
    gateway = FakeGateway(
        events,
        error=asyncio.CancelledError() if boundary == "gateway" else None,
    )
    profiles = FakeProfiles(
        _profile_record(job),
        error=asyncio.CancelledError() if boundary == "profile" else None,
    )
    worker, jobs, *_ = _worker(
        job,
        processor=processor,
        gateway=gateway,
        profiles=profiles,
    )

    with pytest.raises(asyncio.CancelledError):
        await worker.run_once()
    assert jobs.failed_codes == []


@pytest.mark.asyncio
async def test_profile_unavailable_and_failure_fencing_are_safe() -> None:
    job = _job()
    unavailable = FakeProfiles(
        _profile_record(job),
        error=CandidateProfileUnavailableError("ciphertext unavailable"),
    )
    worker, jobs, *_ = _worker(job, profiles=unavailable)
    outcome = (await worker.run_once())[0]
    assert outcome.status == "retry"
    assert outcome.error_code == "source_unavailable"
    assert jobs.failed_codes == ["source_unavailable"]

    fenced_job = replace(job, prompt_version="unsupported")
    fenced_jobs = FakeJobs(fenced_job, fence_failure=True)
    fenced_worker, *_ = _worker(fenced_job, jobs=fenced_jobs)
    fenced = (await fenced_worker.run_once())[0]
    assert fenced.status == "fenced"
    assert fenced.error_code == "lease_expired"
