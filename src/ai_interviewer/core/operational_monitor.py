"""Periodic, bounded snapshots of durable operational work."""

import asyncio
import logging
from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ai_interviewer.core.telemetry import (
    DeletionQueueSnapshot,
    DeletionTaskState,
    DeletionTaskType,
    TelemetryRuntime,
)
from ai_interviewer.file_security.models import FileDeletionTask
from ai_interviewer.persistence.database import Database
from ai_interviewer.privacy.models import ProcessorDeletionTask

logger = logging.getLogger("ai_interviewer.operational_monitor")

_ACTIVE_STATES: tuple[DeletionTaskState, ...] = (
    "pending",
    "processing",
    "retry",
    "escalated",
)


class OperationalMonitor:
    """Observe durable queues without exposing task, owner, or object identifiers."""

    def __init__(
        self,
        *,
        database: Database,
        telemetry: TelemetryRuntime,
        interval_seconds: int,
    ) -> None:
        self._database = database
        self._telemetry = telemetry
        self._interval_seconds = interval_seconds
        self._stop = asyncio.Event()
        self._task: asyncio.Task[None] | None = None

    def start(self) -> None:
        if self._task is not None:
            raise RuntimeError("operational monitor is already started")
        self._task = asyncio.create_task(self._run(), name="operational-telemetry-monitor")

    async def stop(self) -> None:
        if self._task is None:
            return
        self._stop.set()
        await self._task
        self._task = None

    async def _run(self) -> None:
        while not self._stop.is_set():
            try:
                await self.collect_once()
            except Exception:
                logger.exception("Operational telemetry snapshot failed")
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=self._interval_seconds)
            except TimeoutError:
                continue

    async def collect_once(self) -> None:
        try:
            with self._telemetry.dependency_operation(
                dependency="database", operation="operational_snapshot"
            ):
                async with self._database.transaction() as session:
                    database_now = await session.scalar(select(func.now()))
                    if database_now is None:
                        raise RuntimeError("database clock is unavailable")
                    snapshots = []
                    snapshots.extend(
                        await self._queue_snapshots(
                            session,
                            FileDeletionTask,
                            "file",
                            database_now,
                        )
                    )
                    snapshots.extend(
                        await self._queue_snapshots(
                            session,
                            ProcessorDeletionTask,
                            "processor",
                            database_now,
                        )
                    )
            self._telemetry.record_deletion_snapshot(snapshots)
        except Exception:
            self._telemetry.record_operational_snapshot("error")
            raise
        self._telemetry.record_operational_snapshot("success")

    @staticmethod
    async def _queue_snapshots(
        session: AsyncSession,
        model: type[FileDeletionTask] | type[ProcessorDeletionTask],
        task_type: DeletionTaskType,
        database_now: datetime,
    ) -> list[DeletionQueueSnapshot]:
        rows = (
            await session.execute(
                select(
                    model.status,
                    func.count(),
                    func.min(model.available_at),
                )
                .where(model.status.in_(_ACTIVE_STATES))
                .group_by(model.status)
            )
        ).all()
        current: dict[str, tuple[int, datetime | None]] = {
            str(state): (int(count), oldest) for state, count, oldest in rows
        }
        snapshots: list[DeletionQueueSnapshot] = []
        for state in _ACTIVE_STATES:
            count, oldest = current.get(state, (0, None))
            age = (
                max((database_now.astimezone(UTC) - oldest.astimezone(UTC)).total_seconds(), 0)
                if oldest is not None
                else 0
            )
            snapshots.append(
                DeletionQueueSnapshot(
                    task_type=task_type,
                    state=state,
                    count=count,
                    oldest_age_seconds=age,
                )
            )
        return snapshots
