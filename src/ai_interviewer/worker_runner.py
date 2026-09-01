"""Cross-platform process entrypoint for explicitly enabled background workers."""

from __future__ import annotations

import argparse
import asyncio
import signal
import sys
from collections.abc import Sequence

from fastapi import FastAPI

from ai_interviewer.worker_runtime import (
    WorkerSupervisor,
    WorkerSupervisorUnavailableError,
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run enabled AI Interviewer workers")
    parser.add_argument(
        "--once",
        action="store_true",
        help="run one bounded sweep and exit",
    )
    return parser


def _application() -> FastAPI:
    from ai_interviewer.main import app

    return app


async def run_worker_application(application: FastAPI, *, once: bool) -> int:
    """Run workers inside the application's normal resource lifecycle."""
    async with application.router.lifespan_context(application):
        settings = application.state.settings
        try:
            supervisor = WorkerSupervisor(
                application.state.candidate_extraction_worker,
                application.state.candidate_profiling_worker,
                batch_size=settings.worker_batch_size,
                poll_interval_seconds=settings.worker_poll_interval_seconds,
                error_backoff_seconds=settings.worker_error_backoff_seconds,
            )
        except WorkerSupervisorUnavailableError:
            return 2

        if once:
            summary = await supervisor.run_once()
            supervisor.log_summary(summary, include_idle=True)
            return 1 if summary.runtime_errors else 0

        stop_event = asyncio.Event()
        loop = asyncio.get_running_loop()
        signal_installed = False
        try:
            loop.add_signal_handler(signal.SIGTERM, stop_event.set)
            signal_installed = True
        except (NotImplementedError, RuntimeError):
            pass
        try:
            await supervisor.run_until_stopped(stop_event)
        finally:
            if signal_installed:
                loop.remove_signal_handler(signal.SIGTERM)
        return 0


def main(argv: Sequence[str] | None = None) -> None:
    args = _parser().parse_args(argv)

    loop_factory = asyncio.SelectorEventLoop if sys.platform == "win32" else None
    try:
        with asyncio.Runner(loop_factory=loop_factory) as runner:
            exit_code = runner.run(run_worker_application(_application(), once=args.once))
    except KeyboardInterrupt:
        return
    if exit_code:
        raise SystemExit(exit_code)


if __name__ == "__main__":
    main()
