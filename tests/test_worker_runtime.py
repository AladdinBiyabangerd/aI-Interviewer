import asyncio
import logging
from dataclasses import dataclass, field

import pytest
from uuid6 import uuid7

from ai_interviewer.candidate_inputs import (
    DisabledCandidateExtractionWorker,
    WorkerOutcome,
)
from ai_interviewer.profiling import (
    DisabledCandidateProfilingWorker,
    ProfilingWorkerOutcome,
)
from ai_interviewer.worker_runtime import (
    WorkerBatchSummary,
    WorkerSupervisor,
    WorkerSupervisorUnavailableError,
)


@dataclass
class FakeExtractionWorker:
    enabled: bool = True
    outcomes: tuple[WorkerOutcome, ...] = ()
    error: BaseException | None = None
    calls: list[int] = field(default_factory=list)
    stop_event: asyncio.Event | None = None
    stop_after_calls: int | None = None

    async def run_once(self, limit: int = 1) -> tuple[WorkerOutcome, ...]:
        self.calls.append(limit)
        if self.stop_event is not None and self.stop_after_calls == len(self.calls):
            self.stop_event.set()
        if self.error is not None:
            raise self.error
        return self.outcomes


@dataclass
class FakeProfilingWorker:
    enabled: bool = True
    outcomes: tuple[ProfilingWorkerOutcome, ...] = ()
    error: BaseException | None = None
    calls: list[int] = field(default_factory=list)

    async def run_once(self, limit: int = 1) -> tuple[ProfilingWorkerOutcome, ...]:
        self.calls.append(limit)
        if self.error is not None:
            raise self.error
        return self.outcomes


def _supervisor(
    extraction: FakeExtractionWorker | DisabledCandidateExtractionWorker,
    profiling: FakeProfilingWorker | DisabledCandidateProfilingWorker,
    **overrides: object,
) -> WorkerSupervisor:
    values = {
        "batch_size": 10,
        "poll_interval_seconds": 0.1,
        "error_backoff_seconds": 1.0,
        **overrides,
    }
    return WorkerSupervisor(extraction, profiling, **values)  # type: ignore[arg-type]


@pytest.mark.asyncio
async def test_supervisor_summarizes_both_worker_batches() -> None:
    extraction = FakeExtractionWorker(
        outcomes=(
            WorkerOutcome(uuid7(), "succeeded", None),
            WorkerOutcome(uuid7(), "retry", "source_unavailable"),
            WorkerOutcome(uuid7(), "fenced", "lease_expired"),
        )
    )
    profiling = FakeProfilingWorker(
        outcomes=(
            ProfilingWorkerOutcome(uuid7(), "succeeded", None),
            ProfilingWorkerOutcome(uuid7(), "failed", "invalid_output"),
        )
    )

    summary = await _supervisor(extraction, profiling, batch_size=7).run_once()

    assert extraction.calls == [7]
    assert profiling.calls == [7]
    assert summary.claimed == 5
    assert summary.extraction == WorkerBatchSummary(
        claimed=3,
        succeeded=1,
        retry=1,
        failed=0,
        fenced=1,
    )
    assert summary.profiling.failed == 1
    assert summary.runtime_errors == ()


def test_busy_summary_is_logged_without_identifiers(caplog: pytest.LogCaptureFixture) -> None:
    summary = WorkerBatchSummary.from_statuses(["succeeded"])

    with caplog.at_level(logging.INFO, logger="ai_interviewer.workers"):
        WorkerSupervisor.log_summary(
            type(
                "Summary",
                (),
                {
                    "extraction": summary,
                    "profiling": WorkerBatchSummary(),
                    "runtime_errors": (),
                    "claimed": 1,
                },
            )()
        )

    assert "Worker sweep completed" in caplog.text


@pytest.mark.asyncio
async def test_runtime_failure_is_payload_blind_and_does_not_starve_other_worker(
    caplog: pytest.LogCaptureFixture,
) -> None:
    extraction = FakeExtractionWorker(error=RuntimeError("candidate secret payload"))
    profiling = FakeProfilingWorker(outcomes=(ProfilingWorkerOutcome(uuid7(), "succeeded", None),))
    supervisor = _supervisor(extraction, profiling)

    with caplog.at_level(logging.ERROR, logger="ai_interviewer.workers"):
        summary = await supervisor.run_once()
        supervisor.log_summary(summary)

    assert summary.runtime_errors == ("extraction:RuntimeError",)
    assert summary.profiling.succeeded == 1
    assert profiling.calls == [10]
    assert "candidate secret payload" not in caplog.text
    assert supervisor._delay_after(summary) == 1.0


@pytest.mark.asyncio
async def test_supervisor_propagates_cancellation() -> None:
    supervisor = _supervisor(
        FakeExtractionWorker(error=asyncio.CancelledError()),
        DisabledCandidateProfilingWorker(),
    )

    with pytest.raises(asyncio.CancelledError):
        await supervisor.run_once()

    profiling_supervisor = _supervisor(
        DisabledCandidateExtractionWorker(),
        FakeProfilingWorker(error=asyncio.CancelledError()),
    )
    with pytest.raises(asyncio.CancelledError):
        await profiling_supervisor.run_once()


@pytest.mark.asyncio
async def test_profiling_runtime_failure_is_recorded() -> None:
    supervisor = _supervisor(
        DisabledCandidateExtractionWorker(),
        FakeProfilingWorker(error=RuntimeError("sensitive provider detail")),
    )

    summary = await supervisor.run_once()

    assert summary.runtime_errors == ("profiling:RuntimeError",)


@pytest.mark.asyncio
async def test_continuous_supervisor_drains_work_then_stops() -> None:
    stop_event = asyncio.Event()
    extraction = FakeExtractionWorker(
        stop_event=stop_event,
        stop_after_calls=1,
    )
    supervisor = _supervisor(extraction, DisabledCandidateProfilingWorker())

    await supervisor.run_until_stopped(stop_event)

    assert extraction.calls == [10]


@pytest.mark.asyncio
async def test_idle_wait_times_out_and_returns() -> None:
    await WorkerSupervisor._wait_or_stop(asyncio.Event(), 0.001)


def test_supervisor_rejects_disabled_workers_unknown_outcomes_and_invalid_bounds() -> None:
    with pytest.raises(WorkerSupervisorUnavailableError, match="no candidate worker"):
        _supervisor(
            DisabledCandidateExtractionWorker(),
            DisabledCandidateProfilingWorker(),
        )

    with pytest.raises(ValueError, match="unsupported outcome"):
        WorkerBatchSummary.from_statuses(["unknown"])

    extraction = FakeExtractionWorker()
    profiling = DisabledCandidateProfilingWorker()
    with pytest.raises(ValueError, match="batch_size"):
        _supervisor(extraction, profiling, batch_size=0)
    with pytest.raises(ValueError, match="poll_interval"):
        _supervisor(extraction, profiling, poll_interval_seconds=0)
    with pytest.raises(ValueError, match="error_backoff"):
        _supervisor(extraction, profiling, error_backoff_seconds=0)


def test_supervisor_selects_idle_and_busy_delays() -> None:
    supervisor = _supervisor(FakeExtractionWorker(), DisabledCandidateProfilingWorker())

    assert (
        supervisor._delay_after(type("Summary", (), {"runtime_errors": (), "claimed": 0})()) == 0.1
    )
    assert supervisor._delay_after(type("Summary", (), {"runtime_errors": (), "claimed": 1})()) == 0
