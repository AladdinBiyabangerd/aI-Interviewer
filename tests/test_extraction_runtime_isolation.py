import os
import signal
import socket as socket_module
import sys
import time
from multiprocessing import Queue

import pytest

from ai_interviewer.extraction_runtime import isolation as isolation_module
from ai_interviewer.extraction_runtime.adapters import (
    TEXT_ADAPTER,
    TEXT_ADAPTER_VERSION,
)
from ai_interviewer.extraction_runtime.isolation import (
    IsolationExecutionError,
    IsolationLimits,
    _ChildPayload,
    _disable_network,
    _refuse_root,
    run_isolated_extraction,
)


def _hang_forever(
    result_queue: "Queue[_ChildPayload]",
    adapter: str,
    version: str,
    content: bytes,
    limits: IsolationLimits,
) -> None:
    del result_queue, adapter, version, content, limits
    time.sleep(60)


def _crash_immediately(
    result_queue: "Queue[_ChildPayload]",
    adapter: str,
    version: str,
    content: bytes,
    limits: IsolationLimits,
) -> None:
    del result_queue, adapter, version, content, limits
    os._exit(1)


def _die_by_signal(
    result_queue: "Queue[_ChildPayload]",
    adapter: str,
    version: str,
    content: bytes,
    limits: IsolationLimits,
) -> None:
    del result_queue, adapter, version, content, limits
    os.kill(os.getpid(), signal.SIGKILL)


# A generous, test-only wall clock: under a full-suite/coverage run, spawning a fresh
# interpreter and importing pypdf/python-docx can occasionally exceed the 25s
# production default on a loaded machine. This does not change the production limit.
_GENEROUS_TEST_LIMITS = IsolationLimits(wall_clock_seconds=90.0)


def test_run_isolated_extraction_returns_sanitized_text() -> None:
    text = run_isolated_extraction(
        TEXT_ADAPTER,
        TEXT_ADAPTER_VERSION,
        b"hello\r\nworld",
        limits=_GENEROUS_TEST_LIMITS,
    )
    assert text == "hello\nworld"


@pytest.mark.parametrize(
    ("adapter", "version", "content", "code"),
    [
        (TEXT_ADAPTER, TEXT_ADAPTER_VERSION, b"", "input_empty"),
        (TEXT_ADAPTER, TEXT_ADAPTER_VERSION, b"\xff\xfe", "input_corrupt"),
        ("unknown-parser", "1", b"content", "input_unsupported"),
    ],
    ids=("empty", "corrupt", "unsupported"),
)
def test_run_isolated_extraction_maps_adapter_failures(
    adapter: str,
    version: str,
    content: bytes,
    code: str,
) -> None:
    with pytest.raises(IsolationExecutionError) as exc_info:
        run_isolated_extraction(adapter, version, content, limits=_GENEROUS_TEST_LIMITS)
    assert exc_info.value.code == code


def test_run_isolated_extraction_times_out_when_child_hangs() -> None:
    limits = IsolationLimits(wall_clock_seconds=0.2)
    with pytest.raises(IsolationExecutionError) as exc_info:
        run_isolated_extraction(
            TEXT_ADAPTER,
            TEXT_ADAPTER_VERSION,
            b"content",
            limits=limits,
            _entrypoint=_hang_forever,
        )
    assert exc_info.value.code == "parser_timeout"


def test_run_isolated_extraction_reports_crash_without_payload() -> None:
    with pytest.raises(IsolationExecutionError) as exc_info:
        run_isolated_extraction(
            TEXT_ADAPTER,
            TEXT_ADAPTER_VERSION,
            b"content",
            _entrypoint=_crash_immediately,
        )
    assert exc_info.value.code == "parser_crashed"


@pytest.mark.skipif(sys.platform == "win32", reason="signal-based exit codes are POSIX-only")
def test_run_isolated_extraction_reports_resource_exceeded_when_signal_killed() -> None:
    with pytest.raises(IsolationExecutionError) as exc_info:
        run_isolated_extraction(
            TEXT_ADAPTER,
            TEXT_ADAPTER_VERSION,
            b"content",
            _entrypoint=_die_by_signal,
        )
    assert exc_info.value.code == "resource_exceeded"


def test_disable_network_blocks_socket_creation_and_connection() -> None:
    original_socket = socket_module.socket
    original_create_connection = socket_module.create_connection
    original_getaddrinfo = socket_module.getaddrinfo
    try:
        _disable_network()
        with pytest.raises(OSError):
            socket_module.socket()
        with pytest.raises(OSError):
            socket_module.create_connection(("127.0.0.1", 80))
        with pytest.raises(OSError):
            socket_module.getaddrinfo("127.0.0.1", 80)
    finally:
        socket_module.socket = original_socket  # type: ignore[misc]
        socket_module.create_connection = original_create_connection
        socket_module.getaddrinfo = original_getaddrinfo


def test_refuse_root_raises_when_uid_is_zero(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(isolation_module.os, "getuid", lambda: 0, raising=False)
    with pytest.raises(RuntimeError, match="must not run as root"):
        _refuse_root()


def test_refuse_root_allows_non_root(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(isolation_module.os, "getuid", lambda: 1000, raising=False)
    _refuse_root()
