"""Cross-platform production process entrypoint."""

from __future__ import annotations

import asyncio
import os
import sys

import uvicorn


def listen_port(raw: str | None = None) -> int:
    """Resolve the HTTP listen port (Railway/Render inject ``PORT``)."""
    value = (raw if raw is not None else os.environ.get("PORT", "8000")).strip() or "8000"
    try:
        port = int(value)
    except ValueError as exc:
        raise SystemExit(f"PORT must be an integer, got {value!r}") from exc
    if not 1 <= port <= 65535:
        raise SystemExit(f"PORT must be between 1 and 65535, got {port}")
    return port


def main() -> None:
    """Run Uvicorn on an event loop supported by the PostgreSQL driver."""
    config = uvicorn.Config(
        "ai_interviewer.main:app",
        host="0.0.0.0",
        port=listen_port(),
        access_log=False,
    )
    server = uvicorn.Server(config)
    loop_factory = asyncio.SelectorEventLoop if sys.platform == "win32" else None
    try:
        with asyncio.Runner(loop_factory=loop_factory) as runner:
            runner.run(server.serve())
    except KeyboardInterrupt:
        return


if __name__ == "__main__":
    main()
