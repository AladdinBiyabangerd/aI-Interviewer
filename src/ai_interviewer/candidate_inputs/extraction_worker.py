"""Isolated extraction worker: claim, read, isolate, persist, and transition.

This is the D2.2 boundary described by ADR 0014: it fetches bytes only through the
existing `read_for_parser` release boundary, runs the exact adapter in an isolated
child process, and persists success through the D1 source-text service before
completing the D2.1 job with the current lease token. It never queries object storage
or writes source text directly.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime
from typing import Literal, NoReturn, Protocol, cast
from uuid import UUID

from ai_interviewer.candidate_inputs.extraction_jobs import (
    CandidateExtractionJobConflictError,
    CandidateExtractionJobRecord,
    CandidateExtractionJobRuntime,
)
from ai_interviewer.candidate_inputs.extraction_models import ExtractionFailureCode
from ai_interviewer.candidate_inputs.source_texts import (
    CandidateSourceTextConflictError,
    CandidateSourceTextRuntime,
    ParserExecutionIdentity,
)
from ai_interviewer.core.config import Settings
from ai_interviewer.extraction_runtime.isolation import (
    DEFAULT_ISOLATION_LIMITS,
    IsolationExecutionError,
    IsolationLimits,
    run_isolated_extraction,
)
from ai_interviewer.file_security.lifecycle import (
    FileSecurityUnavailableError,
    FileStateConflictError,
)
from ai_interviewer.file_security.object_store import ObjectStoreError

_SOURCE_FAILURE_CODE: ExtractionFailureCode = "source_unavailable"
_POLICY_FAILURE_CODE: ExtractionFailureCode = "policy_unavailable"

WorkerOutcomeStatus = Literal["succeeded", "retry", "failed", "fenced"]


class CandidateExtractionWorkerUnavailableError(RuntimeError):
    """Extraction execution is disabled or lacks its secure file boundary."""


@dataclass(frozen=True, slots=True)
class WorkerOutcome:
    job_id: UUID
    status: WorkerOutcomeStatus
    error_code: str | None


class CandidateExtractionWorkerRuntime(Protocol):
    enabled: bool

    async def run_once(self, limit: int = 1) -> tuple[WorkerOutcome, ...]: ...


class DisabledCandidateExtractionWorker:
    """Never claims parser work while extraction execution is disabled."""

    enabled = False

    @staticmethod
    def _unavailable() -> NoReturn:
        raise CandidateExtractionWorkerUnavailableError(
            "candidate extraction execution is not configured"
        )

    async def run_once(self, limit: int = 1) -> tuple[WorkerOutcome, ...]:
        del limit
        self._unavailable()


class FileParserSource(Protocol):
    """The exact release boundary the worker is allowed to read through."""

    async def read_for_parser(
        self,
        *,
        account_id: UUID,
        file_asset_id: UUID,
        parser_adapter: str,
        parser_version: str,
        isolation_profile: str,
        now: datetime | None = None,
    ) -> bytes: ...


class CandidateExtractionWorker:
    """Drive one exact claimed job from released bytes to a terminal transition."""

    enabled = True

    def __init__(
        self,
        extraction_jobs: CandidateExtractionJobRuntime,
        file_source: FileParserSource,
        source_texts: CandidateSourceTextRuntime,
        *,
        worker_id: str,
        limits: IsolationLimits = DEFAULT_ISOLATION_LIMITS,
    ) -> None:
        normalized_worker = worker_id.strip()
        if not normalized_worker or len(normalized_worker) > 128:
            raise ValueError("worker_id must contain 1-128 characters")
        self._jobs = extraction_jobs
        self._files = file_source
        self._source_texts = source_texts
        self._worker_id = normalized_worker
        self._limits = limits

    async def run_once(
        self,
        limit: int = 1,
        *,
        now: datetime | None = None,
    ) -> tuple[WorkerOutcome, ...]:
        """Claim up to `limit` jobs and drive each one to a terminal transition."""
        claimed = await self._jobs.claim_jobs(self._worker_id, limit, now=now)
        outcomes = [await self._process(job) for job in claimed]
        return tuple(outcomes)

    async def _process(self, job: CandidateExtractionJobRecord) -> WorkerOutcome:
        if job.lease_token is None:
            raise RuntimeError("a claimed extraction job must carry a lease token")

        try:
            content = await self._files.read_for_parser(
                account_id=job.owner_id,
                file_asset_id=job.file_asset_id,
                parser_adapter=job.parser_adapter,
                parser_version=job.parser_version,
                isolation_profile=job.isolation_profile,
            )
        except (FileStateConflictError, FileSecurityUnavailableError, ObjectStoreError):
            return await self._fail(job, _SOURCE_FAILURE_CODE)

        try:
            text = await asyncio.to_thread(
                run_isolated_extraction,
                job.parser_adapter,
                job.parser_version,
                content,
                limits=self._limits,
            )
        except IsolationExecutionError as exc:
            return await self._fail(job, exc.code)

        try:
            stored = await self._source_texts.store_parser_extraction(
                job.owner_id,
                job.document_version_id,
                text,
                ParserExecutionIdentity(
                    parser_release_policy_id=job.parser_release_policy_id,
                    parser_adapter=job.parser_adapter,
                    parser_version=job.parser_version,
                    isolation_profile=job.isolation_profile,
                ),
                request_id=None,
            )
        except CandidateSourceTextConflictError:
            return await self._fail(job, _POLICY_FAILURE_CODE)

        try:
            succeeded = await self._jobs.mark_succeeded(
                job.job_id,
                self._worker_id,
                job.lease_token,
                stored.source_text.source_text_id,
            )
        except CandidateExtractionJobConflictError:
            return WorkerOutcome(job.job_id, "fenced", "lease_expired")
        return WorkerOutcome(job_id=succeeded.job_id, status="succeeded", error_code=None)

    async def _fail(
        self,
        job: CandidateExtractionJobRecord,
        code: ExtractionFailureCode,
    ) -> WorkerOutcome:
        lease_token = cast(UUID, job.lease_token)
        try:
            updated = await self._jobs.mark_failed(
                job.job_id,
                self._worker_id,
                lease_token,
                code,
            )
        except CandidateExtractionJobConflictError:
            return WorkerOutcome(job.job_id, "fenced", "lease_expired")
        status: WorkerOutcomeStatus = "retry" if updated.status == "retry" else "failed"
        return WorkerOutcome(job_id=updated.job_id, status=status, error_code=updated.error_code)


def build_candidate_extraction_worker(
    settings: Settings,
    extraction_jobs: CandidateExtractionJobRuntime,
    file_source: FileParserSource,
    source_texts: CandidateSourceTextRuntime,
) -> CandidateExtractionWorkerRuntime:
    if not settings.extraction_worker_enabled:
        return DisabledCandidateExtractionWorker()
    return CandidateExtractionWorker(
        extraction_jobs,
        file_source,
        source_texts,
        worker_id=settings.extraction_worker_id,
    )
