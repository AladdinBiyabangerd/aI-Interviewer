"""Bounded, payload-blind supervision for candidate background workers."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Iterable
from dataclasses import dataclass

from ai_interviewer.candidate_inputs import CandidateExtractionWorkerRuntime
from ai_interviewer.profiling import CandidateProfilingWorkerRuntime

logger = logging.getLogger("ai_interviewer.workers")

_OUTCOME_STATUSES = ("succeeded", "retry", "failed", "fenced")


class WorkerSupervisorUnavailableError(RuntimeError):
    """No explicitly enabled worker is available to supervise."""


@dataclass(frozen=True, slots=True)
class WorkerBatchSummary:
    claimed: int = 0
    succeeded: int = 0
    retry: int = 0
    failed: int = 0
    fenced: int = 0

    @classmethod
    def from_statuses(cls, statuses: Iterable[str]) -> WorkerBatchSummary:
        counts = {status: 0 for status in _OUTCOME_STATUSES}
        for status in statuses:
            if status not in counts:
                raise ValueError("worker returned an unsupported outcome status")
            counts[status] += 1
        return cls(
            claimed=sum(counts.values()),
            succeeded=counts["succeeded"],
            retry=counts["retry"],
            failed=counts["failed"],
            fenced=counts["fenced"],
        )


@dataclass(frozen=True, slots=True)
class WorkerSweepSummary:
    extraction: WorkerBatchSummary = WorkerBatchSummary()
    profiling: WorkerBatchSummary = WorkerBatchSummary()
    runtime_errors: tuple[str, ...] = ()

    @property
    def claimed(self) -> int:
        return self.extraction.claimed + self.profiling.claimed


class WorkerSupervisor:
    """Run enabled workers in bounded sweeps without logging candidate payloads."""

    def __init__(
        self,
        extraction_worker: CandidateExtractionWorkerRuntime,
        profiling_worker: CandidateProfilingWorkerRuntime,
        *,
        batch_size: int,
        poll_interval_seconds: float,
        error_backoff_seconds: float,
    ) -> None:
        if not extraction_worker.enabled and not profiling_worker.enabled:
            raise WorkerSupervisorUnavailableError("no candidate worker is enabled")
        if not 1 <= batch_size <= 100:
            raise ValueError("batch_size must be between 1 and 100")
        if not 0.1 <= poll_interval_seconds <= 60:
            raise ValueError("poll_interval_seconds must be between 0.1 and 60")
        if not 1 <= error_backoff_seconds <= 300:
            raise ValueError("error_backoff_seconds must be between 1 and 300")
        self._extraction_worker = extraction_worker
        self._profiling_worker = profiling_worker
        self._batch_size = batch_size
        self._poll_interval_seconds = poll_interval_seconds
        self._error_backoff_seconds = error_backoff_seconds

    async def run_once(self) -> WorkerSweepSummary:
        extraction = WorkerBatchSummary()
        profiling = WorkerBatchSummary()
        runtime_errors: list[str] = []

        if self._extraction_worker.enabled:
            try:
                extraction_outcomes = await self._extraction_worker.run_once(self._batch_size)
                extraction = WorkerBatchSummary.from_statuses(
                    outcome.status for outcome in extraction_outcomes
                )
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                runtime_errors.append(f"extraction:{type(exc).__name__}")

        if self._profiling_worker.enabled:
            try:
                profiling_outcomes = await self._profiling_worker.run_once(self._batch_size)
                profiling = WorkerBatchSummary.from_statuses(
                    outcome.status for outcome in profiling_outcomes
                )
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                runtime_errors.append(f"profiling:{type(exc).__name__}")

        return WorkerSweepSummary(
            extraction=extraction,
            profiling=profiling,
            runtime_errors=tuple(runtime_errors),
        )

    async def run_until_stopped(self, stop_event: asyncio.Event) -> None:
        while not stop_event.is_set():
            summary = await self.run_once()
            self.log_summary(summary)
            delay = self._delay_after(summary)
            if delay > 0:
                await self._wait_or_stop(stop_event, delay)

    def _delay_after(self, summary: WorkerSweepSummary) -> float:
        if summary.runtime_errors:
            return self._error_backoff_seconds
        if summary.claimed == 0:
            return self._poll_interval_seconds
        return 0

    @staticmethod
    def log_summary(summary: WorkerSweepSummary, *, include_idle: bool = False) -> None:
        context = {
            "extraction_claimed": summary.extraction.claimed,
            "extraction_succeeded": summary.extraction.succeeded,
            "extraction_retry": summary.extraction.retry,
            "extraction_failed": summary.extraction.failed,
            "extraction_fenced": summary.extraction.fenced,
            "profiling_claimed": summary.profiling.claimed,
            "profiling_succeeded": summary.profiling.succeeded,
            "profiling_retry": summary.profiling.retry,
            "profiling_failed": summary.profiling.failed,
            "profiling_fenced": summary.profiling.fenced,
        }
        if summary.runtime_errors:
            logger.error(
                "Worker sweep encountered runtime failures",
                extra={**context, "runtime_errors": summary.runtime_errors},
            )
        elif summary.claimed or include_idle:
            logger.info("Worker sweep completed", extra=context)

    @staticmethod
    async def _wait_or_stop(stop_event: asyncio.Event, delay: float) -> None:
        try:
            await asyncio.wait_for(stop_event.wait(), timeout=delay)
        except TimeoutError:
            return
