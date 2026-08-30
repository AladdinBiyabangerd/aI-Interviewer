"""No-network, resource-bounded child-process execution for extraction adapters.

The isolated child process never receives database, object-store, or cryptography
access; it receives only validated content bytes and returns sanitized text or a
closed, content-free failure code. A crash, timeout, or resource limit in the child
can never take down the calling worker process or leak raw exception text.
"""

from __future__ import annotations

import multiprocessing
import os
import queue as queue_module
import socket as socket_module
import sys
from collections.abc import Callable
from dataclasses import dataclass
from multiprocessing import Queue
from typing import Literal, TypedDict

from ai_interviewer.extraction_runtime.adapters import (
    ExtractionAdapterError,
    resolve_adapter,
)

IsolationFailureCode = Literal[
    "input_unsupported",
    "input_corrupt",
    "input_encrypted",
    "input_empty",
    "parser_timeout",
    "resource_exceeded",
    "parser_crashed",
    "internal_failure",
]

_DEFAULT_CPU_SECONDS = 20
_DEFAULT_MEMORY_BYTES = 512 * 1024 * 1024
_DEFAULT_WALL_CLOCK_SECONDS = 25.0
_JOIN_GRACE_SECONDS = 5.0


@dataclass(frozen=True, slots=True)
class IsolationLimits:
    cpu_seconds: int = _DEFAULT_CPU_SECONDS
    memory_bytes: int = _DEFAULT_MEMORY_BYTES
    wall_clock_seconds: float = _DEFAULT_WALL_CLOCK_SECONDS


DEFAULT_ISOLATION_LIMITS = IsolationLimits()


class IsolationExecutionError(RuntimeError):
    """The isolated child process failed with a closed, content-free code."""

    def __init__(self, code: IsolationFailureCode) -> None:
        super().__init__(code)
        self.code = code


class _SuccessPayload(TypedDict):
    ok: Literal[True]
    text: str


class _FailurePayload(TypedDict):
    ok: Literal[False]
    code: IsolationFailureCode


_ChildPayload = _SuccessPayload | _FailurePayload


_ChildTarget = Callable[["Queue[_ChildPayload]", str, str, bytes, IsolationLimits], None]


def run_isolated_extraction(
    adapter: str,
    version: str,
    content: bytes,
    *,
    limits: IsolationLimits = DEFAULT_ISOLATION_LIMITS,
    _entrypoint: _ChildTarget | None = None,
) -> str:
    """Run one adapter on one document in an isolated child process.

    `_entrypoint` is a test-only seam for injecting a picklable top-level child
    target (to exercise timeout/crash/signal handling); production callers must
    never pass it.
    """
    context = multiprocessing.get_context("spawn")
    result_queue: Queue[_ChildPayload] = context.Queue(maxsize=1)
    process = context.Process(
        target=_entrypoint or _child_entrypoint,
        args=(result_queue, adapter, version, content, limits),
        daemon=True,
    )
    process.start()
    try:
        process.join(timeout=limits.wall_clock_seconds)
        if process.is_alive():
            process.kill()
            process.join(timeout=_JOIN_GRACE_SECONDS)
            raise IsolationExecutionError("parser_timeout")

        try:
            payload = result_queue.get_nowait()
        except queue_module.Empty as exc:
            exit_code = process.exitcode
            if exit_code is not None and exit_code < 0:
                raise IsolationExecutionError("resource_exceeded") from exc
            raise IsolationExecutionError("parser_crashed") from exc

        if not payload["ok"]:
            raise IsolationExecutionError(payload["code"])
        return payload["text"]
    finally:
        if process.is_alive():
            process.kill()
            process.join(timeout=_JOIN_GRACE_SECONDS)
        result_queue.close()


def _child_entrypoint(
    result_queue: Queue[_ChildPayload],
    adapter: str,
    version: str,
    content: bytes,
    limits: IsolationLimits,
) -> None:
    try:
        _apply_resource_limits(limits)
        _disable_network()
        _refuse_root()
        text = resolve_adapter(adapter, version)(content)
        result_queue.put(_SuccessPayload(ok=True, text=text))
    except ExtractionAdapterError as exc:
        result_queue.put(_FailurePayload(ok=False, code=exc.code))  # type: ignore[typeddict-item]
    except Exception:
        result_queue.put(_FailurePayload(ok=False, code="internal_failure"))


def _apply_resource_limits(limits: IsolationLimits) -> None:
    if sys.platform == "win32":
        return
    _apply_posix_resource_limits(limits)


def _apply_posix_resource_limits(limits: IsolationLimits) -> None:  # pragma: no cover
    # Only reachable on the Linux/POSIX production and CI target; `resource` does not
    # exist on Windows, so this cannot run in local Windows development.
    import resource

    for kind, value in (
        (resource.RLIMIT_CPU, limits.cpu_seconds),
        (resource.RLIMIT_AS, limits.memory_bytes),
        (resource.RLIMIT_FSIZE, 0),
    ):
        try:
            resource.setrlimit(kind, (value, value))
        except (OSError, ValueError):
            continue


class _NetworkDisabledSocket:
    def __init__(self, *_args: object, **_kwargs: object) -> None:
        raise OSError("network access is disabled inside the isolated extraction worker")


def _raise_network_disabled(*_args: object, **_kwargs: object) -> None:
    raise OSError("network access is disabled inside the isolated extraction worker")


def _disable_network() -> None:
    socket_module.socket = _NetworkDisabledSocket  # type: ignore[misc,assignment]
    socket_module.create_connection = _raise_network_disabled  # type: ignore[assignment]
    socket_module.getaddrinfo = _raise_network_disabled  # type: ignore[assignment]


def _refuse_root() -> None:
    if hasattr(os, "getuid") and os.getuid() == 0:
        raise RuntimeError("the isolated extraction worker must not run as root")
