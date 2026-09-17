import asyncio
from collections.abc import Coroutine
from typing import Any

import pytest

from ai_interviewer import runner as application_runner


class RecordingRunner:
    loop_factory: object = "unset"
    interrupt = False

    def __init__(self, *, loop_factory: object) -> None:
        type(self).loop_factory = loop_factory

    def __enter__(self) -> "RecordingRunner":
        return self

    def __exit__(self, *_: object) -> None:
        return None

    def run(self, coroutine: Coroutine[Any, Any, object]) -> None:
        coroutine.close()
        if self.interrupt:
            raise KeyboardInterrupt


class StubServer:
    def __init__(self, _: object) -> None:
        return None

    async def serve(self) -> None:
        return None


@pytest.mark.parametrize(
    ("platform", "expected_factory"),
    [("win32", asyncio.SelectorEventLoop), ("linux", None)],
)
def test_runner_selects_compatible_event_loop(
    monkeypatch: pytest.MonkeyPatch,
    platform: str,
    expected_factory: object,
) -> None:
    RecordingRunner.interrupt = False
    monkeypatch.setattr(application_runner.sys, "platform", platform)
    monkeypatch.setattr(application_runner.asyncio, "Runner", RecordingRunner)
    monkeypatch.setattr(application_runner.uvicorn, "Config", lambda *args, **kwargs: object())
    monkeypatch.setattr(application_runner.uvicorn, "Server", StubServer)

    application_runner.main()

    assert RecordingRunner.loop_factory is expected_factory


def test_runner_handles_operator_interrupt(monkeypatch: pytest.MonkeyPatch) -> None:
    RecordingRunner.interrupt = True
    monkeypatch.setattr(application_runner.asyncio, "Runner", RecordingRunner)
    monkeypatch.setattr(application_runner.uvicorn, "Config", lambda *args, **kwargs: object())
    monkeypatch.setattr(application_runner.uvicorn, "Server", StubServer)

    assert application_runner.main() is None


def test_listen_port_defaults_and_reads_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("PORT", raising=False)
    assert application_runner.listen_port() == 8000
    monkeypatch.setenv("PORT", "8080")
    assert application_runner.listen_port() == 8080
    assert application_runner.listen_port("3000") == 3000
    assert application_runner.listen_port("") == 8000


@pytest.mark.parametrize("raw", ["0", "65536", "abc"])
def test_listen_port_rejects_invalid(raw: str) -> None:
    with pytest.raises(SystemExit):
        application_runner.listen_port(raw)
