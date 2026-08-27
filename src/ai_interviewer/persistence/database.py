"""Async PostgreSQL lifecycle and transaction boundary."""

import asyncio
import logging
from collections.abc import AsyncIterator
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from typing import Protocol, cast

from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from ai_interviewer.core.config import Settings
from ai_interviewer.core.telemetry import (
    DatabasePoolSnapshot,
    DisabledTelemetry,
    TelemetryRuntime,
)
from ai_interviewer.persistence.schema import EXPECTED_SCHEMA_REVISION

logger = logging.getLogger("ai_interviewer.database")


class DatabaseRuntime(Protocol):
    """Minimal lifecycle used by the HTTP application."""

    async def is_ready(self) -> bool: ...

    def transaction(self) -> AbstractAsyncContextManager[AsyncSession]: ...

    async def close(self) -> None: ...


def database_connect_args(settings: Settings) -> dict[str, object]:
    """Build psycopg connection options without mutating or logging the DSN."""
    return {
        "sslmode": settings.database_tls_mode,
        "options": f"-c statement_timeout={settings.database_statement_timeout_ms}",
        "connect_timeout": settings.database_connect_timeout_seconds,
    }


class Database:
    """Own one async engine and expose explicit transactional sessions."""

    def __init__(
        self,
        settings: Settings,
        telemetry: TelemetryRuntime | None = None,
    ) -> None:
        self._healthcheck_timeout_seconds = settings.database_healthcheck_timeout_seconds
        self._pool_base_limit = settings.database_pool_size
        self._pool_overflow_limit = settings.database_max_overflow
        self._telemetry = telemetry or DisabledTelemetry()
        self.engine: AsyncEngine = create_async_engine(
            settings.database_url.get_secret_value(),
            pool_pre_ping=True,
            pool_size=settings.database_pool_size,
            max_overflow=settings.database_max_overflow,
            pool_timeout=settings.database_pool_timeout_seconds,
            pool_recycle=settings.database_pool_recycle_seconds,
            connect_args=database_connect_args(settings),
        )
        self.session_factory = async_sessionmaker(
            bind=self.engine,
            class_=AsyncSession,
            expire_on_commit=False,
            autoflush=False,
        )
        self._telemetry.register_database_pool(self._pool_snapshot)

    def _pool_snapshot(self) -> DatabasePoolSnapshot:
        class ObservablePool(Protocol):
            def checkedin(self) -> int: ...

            def checkedout(self) -> int: ...

        pool = cast(ObservablePool, self.engine.pool)
        return DatabasePoolSnapshot(
            idle=pool.checkedin(),
            used=pool.checkedout(),
            base_limit=self._pool_base_limit,
            overflow_limit=self._pool_overflow_limit,
        )

    @asynccontextmanager
    async def transaction(self) -> AsyncIterator[AsyncSession]:
        """Commit atomically on success and roll back on any exception."""
        async with self.session_factory() as session, session.begin():
            yield session

    async def is_ready(self) -> bool:
        """Check the required database dependency within a strict time budget."""
        try:
            async with asyncio.timeout(self._healthcheck_timeout_seconds):
                async with self.engine.connect() as connection:
                    await connection.execute(text("SELECT 1"))
                    revision = await connection.scalar(
                        text("SELECT version_num FROM alembic_version")
                    )
                    if revision != EXPECTED_SCHEMA_REVISION:
                        logger.warning(
                            "Database schema revision is not compatible with this release"
                        )
                        return False
            return True
        except (TimeoutError, SQLAlchemyError):
            logger.warning("Database readiness check failed", exc_info=True)
            return False

    async def close(self) -> None:
        """Release all pooled connections during application shutdown."""
        await self.engine.dispose()
