"""Cross-platform production process entrypoint."""

import asyncio
import sys

import uvicorn


def main() -> None:
    """Run Uvicorn on an event loop supported by the PostgreSQL driver."""
    config = uvicorn.Config(
        "ai_interviewer.main:app",
        host="0.0.0.0",
        port=8000,
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
