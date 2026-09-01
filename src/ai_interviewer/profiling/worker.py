"""Policy-gated profiling execution over durable fenced jobs."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Literal, NoReturn, Protocol, cast
from uuid import UUID

from ai_interviewer.candidate_inputs.document_models import CandidateDocumentType
from ai_interviewer.candidate_inputs.source_texts import (
    CandidateSourceTextConflictError,
    CandidateSourceTextNotFoundError,
    CandidateSourceTextRuntime,
    CandidateSourceTextUnavailableError,
)
from ai_interviewer.core.config import Settings
from ai_interviewer.model_gateway import (
    ModelGatewayError,
    ModelGatewayResult,
    ModelGatewayRuntime,
    ModelReleaseIdentity,
    StrictModelOutput,
)
from ai_interviewer.privacy.lifecycle import PrivacyUnavailableError
from ai_interviewer.privacy.processors import ProcessorPolicyError
from ai_interviewer.profiling.contracts import CandidateProfileOutput
from ai_interviewer.profiling.evidence import ProfileEvidenceError, validate_profile_evidence
from ai_interviewer.profiling.job_models import ProfilingFailureCode
from ai_interviewer.profiling.jobs import (
    CandidateProfilingJobConflictError,
    CandidateProfilingJobRecord,
    CandidateProfilingJobRuntime,
)
from ai_interviewer.profiling.profiles import (
    CandidateProfileConflictError,
    CandidateProfileRuntime,
    CandidateProfileUnavailableError,
)
from ai_interviewer.profiling.prompts import CandidateProfilePrompt, candidate_profile_prompt

ProfilingWorkerOutcomeStatus = Literal["succeeded", "retry", "failed", "fenced"]


class CandidateProfilingWorkerUnavailableError(RuntimeError):
    """Profiling execution is disabled or lacks a reviewed provider boundary."""


class ProcessorUsageRuntime(Protocol):
    """Narrow privacy port required immediately before an external processor call."""

    async def register_processor_use(
        self,
        account_id: UUID,
        *,
        processor_activity_id: UUID,
        processor_subject_reference: str,
    ) -> object: ...


@dataclass(frozen=True, slots=True)
class ProfilingWorkerOutcome:
    job_id: UUID
    status: ProfilingWorkerOutcomeStatus
    error_code: str | None


class CandidateProfilingWorkerRuntime(Protocol):
    enabled: bool

    async def run_once(self, limit: int = 1) -> tuple[ProfilingWorkerOutcome, ...]: ...


class DisabledCandidateProfilingWorker:
    """Never claims work while external model processing is disabled."""

    enabled = False

    @staticmethod
    def _unavailable() -> NoReturn:
        raise CandidateProfilingWorkerUnavailableError(
            "candidate profiling execution is not configured"
        )

    async def run_once(self, limit: int = 1) -> tuple[ProfilingWorkerOutcome, ...]:
        del limit
        self._unavailable()


class CandidateProfilingWorker:
    """Claim exact-source jobs, authorize the processor, validate, persist, and fence."""

    enabled = True

    def __init__(
        self,
        jobs: CandidateProfilingJobRuntime,
        source_texts: CandidateSourceTextRuntime,
        profiles: CandidateProfileRuntime,
        processor_usage: ProcessorUsageRuntime,
        gateway: ModelGatewayRuntime,
        *,
        worker_id: str,
    ) -> None:
        normalized_worker = worker_id.strip()
        if not normalized_worker or len(normalized_worker) > 128:
            raise ValueError("worker_id must contain 1-128 characters")
        if not gateway.enabled or gateway.model_release is None:
            raise CandidateProfilingWorkerUnavailableError(
                "candidate profiling requires an enabled model gateway"
            )
        self._jobs = jobs
        self._source_texts = source_texts
        self._profiles = profiles
        self._processor_usage = processor_usage
        self._gateway = gateway
        self._worker_id = normalized_worker

    async def run_once(self, limit: int = 1) -> tuple[ProfilingWorkerOutcome, ...]:
        claimed = await self._jobs.claim_jobs(self._worker_id, limit)
        outcomes = [await self._process(job) for job in claimed]
        return tuple(outcomes)

    async def _process(self, job: CandidateProfilingJobRecord) -> ProfilingWorkerOutcome:
        if job.lease_token is None:
            raise RuntimeError("a claimed profiling job must carry a lease token")
        prompt = self._prompt_for_job(job)
        if prompt is None:
            return await self._fail(job, "policy_unavailable")
        if not self._model_matches_job(job, self._gateway.model_release):
            return await self._fail(job, "model_identity_mismatch")

        try:
            source = await self._source_texts.get_source_text(
                job.owner_id,
                job.preparation_id,
                job.document_version_id,
            )
        except (CandidateSourceTextNotFoundError, CandidateSourceTextUnavailableError):
            return await self._fail(job, "source_unavailable")
        except CandidateSourceTextConflictError:
            return await self._fail(job, "persistence_conflict")

        if source.source_text_id != job.source_text_id or not source.versions:
            return await self._fail(job, "persistence_conflict")
        source_version = source.versions[-1]
        if (
            source.latest_version_number != source_version.version_number
            or source_version.text_version_id != job.source_text_version_id
        ):
            return await self._fail(job, "persistence_conflict")

        try:
            await self._processor_usage.register_processor_use(
                job.owner_id,
                processor_activity_id=job.processor_activity_id,
                processor_subject_reference=str(job.job_id),
            )
        except (ProcessorPolicyError, PrivacyUnavailableError):
            return await self._fail(job, "policy_unavailable")
        except asyncio.CancelledError:
            raise
        except Exception:
            return await self._fail(job, "internal_failure")

        try:
            raw_result = await self._gateway.generate(
                prompt.request(source_version.content, request_id=job.job_id),
                prompt.output_type,
            )
        except ModelGatewayError as exc:
            return await self._fail(job, cast(ProfilingFailureCode, exc.code))
        except asyncio.CancelledError:
            raise
        except Exception:
            return await self._fail(job, "internal_failure")

        if not self._result_matches_job(job, raw_result):
            return await self._fail(job, "model_identity_mismatch")
        result = cast(ModelGatewayResult[CandidateProfileOutput], raw_result)
        try:
            validate_profile_evidence(
                result.output,
                source_version.content,
                cast(CandidateDocumentType, job.document_type),
            )
        except ProfileEvidenceError:
            return await self._fail(job, "invalid_output")

        try:
            stored = await self._profiles.store_model_profile(
                job.owner_id,
                job.preparation_id,
                job.document_version_id,
                job.source_text_version_id,
                result,
                None,
            )
        except CandidateProfileUnavailableError:
            return await self._fail(job, "source_unavailable")
        except CandidateProfileConflictError:
            return await self._fail(job, "persistence_conflict")
        except asyncio.CancelledError:
            raise
        except Exception:
            return await self._fail(job, "internal_failure")

        try:
            completed = await self._jobs.mark_succeeded(
                job.job_id,
                self._worker_id,
                job.lease_token,
                stored.candidate_profile.profile_id,
            )
        except CandidateProfilingJobConflictError:
            return ProfilingWorkerOutcome(job.job_id, "fenced", "lease_expired")
        return ProfilingWorkerOutcome(completed.job_id, "succeeded", None)

    def _prompt_for_job(self, job: CandidateProfilingJobRecord) -> CandidateProfilePrompt | None:
        if job.document_type not in {"cv", "job_description"}:
            return None
        prompt = candidate_profile_prompt(cast(CandidateDocumentType, job.document_type))
        if (
            prompt.prompt_release.prompt_id != job.prompt_id
            or prompt.prompt_release.prompt_version != job.prompt_version
            or prompt.prompt_release.schema_id != job.schema_id
            or prompt.prompt_release.schema_version != job.schema_version
            or prompt.instructions_sha256 != job.instructions_sha256
            or prompt.output_schema_sha256 != job.output_schema_sha256
            or prompt.max_output_tokens != job.max_output_tokens
        ):
            return None
        return prompt

    @staticmethod
    def _model_matches_job(
        job: CandidateProfilingJobRecord,
        model_release: ModelReleaseIdentity | None,
    ) -> bool:
        return model_release == ModelReleaseIdentity(
            provider=job.model_provider,
            model_id=job.model_id,
            model_version=job.model_version,
        )

    @staticmethod
    def _result_matches_job(
        job: CandidateProfilingJobRecord,
        result: ModelGatewayResult[StrictModelOutput],
    ) -> bool:
        return (
            result.model_release.provider == job.model_provider
            and result.model_release.model_id == job.model_id
            and result.model_release.model_version == job.model_version
            and result.prompt_release.prompt_id == job.prompt_id
            and result.prompt_release.prompt_version == job.prompt_version
            and result.prompt_release.schema_id == job.schema_id
            and result.prompt_release.schema_version == job.schema_version
            and result.instructions_sha256 == job.instructions_sha256
            and result.output_schema_sha256 == job.output_schema_sha256
        )

    async def _fail(
        self,
        job: CandidateProfilingJobRecord,
        code: ProfilingFailureCode,
    ) -> ProfilingWorkerOutcome:
        if job.lease_token is None:
            raise RuntimeError("a claimed profiling job must carry a lease token")
        try:
            updated = await self._jobs.mark_failed(
                job.job_id,
                self._worker_id,
                job.lease_token,
                code,
            )
        except CandidateProfilingJobConflictError:
            return ProfilingWorkerOutcome(job.job_id, "fenced", "lease_expired")
        status: ProfilingWorkerOutcomeStatus = "retry" if updated.status == "retry" else "failed"
        return ProfilingWorkerOutcome(updated.job_id, status, updated.error_code)


def build_candidate_profiling_worker(
    settings: Settings,
    jobs: CandidateProfilingJobRuntime,
    source_texts: CandidateSourceTextRuntime,
    profiles: CandidateProfileRuntime,
    processor_usage: ProcessorUsageRuntime,
    gateway: ModelGatewayRuntime,
) -> CandidateProfilingWorkerRuntime:
    if not settings.profiling_worker_enabled:
        return DisabledCandidateProfilingWorker()
    return CandidateProfilingWorker(
        jobs,
        source_texts,
        profiles,
        processor_usage,
        gateway,
        worker_id=settings.profiling_worker_id,
    )
