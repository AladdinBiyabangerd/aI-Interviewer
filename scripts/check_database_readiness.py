"""Exit successfully only when the configured PostgreSQL dependency is ready."""

import asyncio
import sys

from ai_interviewer.core.config import Settings
from ai_interviewer.persistence.database import Database


async def check() -> int:
    database = Database(Settings())
    try:
        ready = await database.is_ready()
    finally:
        await database.close()
    print("database=up" if ready else "database=down")
    return 0 if ready else 1


def main() -> None:
    loop_factory = asyncio.SelectorEventLoop if sys.platform == "win32" else None
    with asyncio.Runner(loop_factory=loop_factory) as runner:
        raise SystemExit(runner.run(check()))


if __name__ == "__main__":
    main()
