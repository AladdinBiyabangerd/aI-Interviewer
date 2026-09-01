import asyncio
from collections.abc import AsyncIterator, Coroutine
from contextlib import asynccontextmanager
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi import FastAPI

from ai_interviewer import worker_runner
from ai_interviewer.candidate_inputs import DisabledCandidateExtractionWorker
from ai_interviewer.profiling import DisabledCandidateProfilingWorker


class EnabledWorker:
    enabled = True

    def __init__(self, *, error: Exception | None = None) -> None:
        self.error = error
        self.calls: list[int] = []

    async def run_once(self, limit: int = 1) -> tuple[()]:
        self.calls.append(limit)
        if self.error is not None:
            raise self.error
        return ()


def _app(
    extraction_worker: object,
    profiling_worker: object,
    lifecycle: list[str] | None = None,
) -> FastAPI:
    events = lifecycle if lifecycle is not None else []

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        events.append("started")
        try:
            yield
        finally:
            events.append("stopped")

    application = FastAPI(lifespan=lifespan)
    application.state.settings = SimpleNamespace(
        worker_batch_size=10,
        worker_poll_interval_seconds=0.1,
        worker_error_backoff_seconds=1.0,
    )
    application.state.candidate_extraction_worker = extraction_worker
    application.state.candidate_profiling_worker = profiling_worker
    return application


@pytest.mark.asyncio
async def test_worker_application_once_is_gated_and_uses_normal_lifecycle() -> None:
    lifecycle: list[str] = []
    disabled_app = _app(
        DisabledCandidateExtractionWorker(),
        DisabledCandidateProfilingWorker(),
        lifecycle,
    )

    disabled_code = await worker_runner.run_worker_application(disabled_app, once=True)

    enabled = EnabledWorker()
    enabled_code = await worker_runner.run_worker_application(
        _app(enabled, DisabledCandidateProfilingWorker()),
        once=True,
    )

    assert disabled_code == 2
    assert lifecycle == ["started", "stopped"]
    assert enabled_code == 0
    assert enabled.calls == [10]


@pytest.mark.asyncio
async def test_worker_application_once_returns_failure_without_exposing_exception() -> None:
    enabled = EnabledWorker(error=RuntimeError("candidate secret payload"))

    exit_code = await worker_runner.run_worker_application(
        _app(enabled, DisabledCandidateProfilingWorker()),
        once=True,
    )

    assert exit_code == 1


@pytest.mark.asyncio
async def test_worker_application_continuous_mode_delegates_to_supervisor(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []

    class RecordingLoop:
        def add_signal_handler(self, *_: object) -> None:
            calls.append("signal-added")

        def remove_signal_handler(self, *_: object) -> None:
            calls.append("signal-removed")

    class RecordingSupervisor:
        def __init__(self, *_: object, **__: object) -> None:
            calls.append("created")

        async def run_until_stopped(self, stop_event: asyncio.Event) -> None:
            assert not stop_event.is_set()
            calls.append("run")

        def log_summary(self, *_: object, **__: object) -> None:
            calls.append("logged")

    monkeypatch.setattr(worker_runner, "WorkerSupervisor", RecordingSupervisor)
    monkeypatch.setattr(worker_runner.asyncio, "get_running_loop", RecordingLoop)

    exit_code = await worker_runner.run_worker_application(
        _app(EnabledWorker(), DisabledCandidateProfilingWorker()),
        once=False,
    )

    assert exit_code == 0
    assert calls == ["created", "signal-added", "run", "signal-removed"]


def test_worker_application_factory_returns_the_asgi_app() -> None:
    assert worker_runner._application().title == "AI Interviewer API"


class RecordingRunner:
    loop_factory: object = "unset"
    exit_code = 0
    interrupt = False

    def __init__(self, *, loop_factory: object) -> None:
        type(self).loop_factory = loop_factory

    def __enter__(self) -> "RecordingRunner":
        return self

    def __exit__(self, *_: object) -> None:
        return None

    def run(self, coroutine: Coroutine[Any, Any, int]) -> int:
        coroutine.close()
        if self.interrupt:
            raise KeyboardInterrupt
        return self.exit_code


@pytest.mark.parametrize(
    ("platform", "expected_factory"),
    [("win32", asyncio.SelectorEventLoop), ("linux", None)],
)
def test_worker_runner_selects_compatible_event_loop(
    monkeypatch: pytest.MonkeyPatch,
    platform: str,
    expected_factory: object,
) -> None:
    RecordingRunner.exit_code = 0
    RecordingRunner.interrupt = False
    monkeypatch.setattr(worker_runner.sys, "platform", platform)
    monkeypatch.setattr(worker_runner.asyncio, "Runner", RecordingRunner)
    monkeypatch.setattr(worker_runner, "_application", lambda: FastAPI())

    worker_runner.main(["--once"])

    assert RecordingRunner.loop_factory is expected_factory


def test_worker_runner_propagates_nonzero_exit_and_handles_interrupt(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(worker_runner.asyncio, "Runner", RecordingRunner)
    monkeypatch.setattr(worker_runner, "_application", lambda: FastAPI())
    RecordingRunner.interrupt = False
    RecordingRunner.exit_code = 2
    with pytest.raises(SystemExit) as exc_info:
        worker_runner.main(["--once"])
    assert exc_info.value.code == 2

    RecordingRunner.interrupt = True
    assert worker_runner.main(["--once"]) is None
