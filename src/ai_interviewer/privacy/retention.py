"""Deterministic retention sweep for the privacy records implemented in Phase 0C-B."""

import hashlib
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, cast

from sqlalchemy import delete, exists, select
from sqlalchemy.engine import CursorResult
from sqlalchemy.ext.asyncio import AsyncSession

from ai_interviewer.persistence.models import AuditEvent
from ai_interviewer.privacy.models import (
    BackupDeletionMarker,
    ConsentRecord,
    PrivacyRequest,
    ProcessorDeletionTask,
)


@dataclass(frozen=True, slots=True)
class RetentionSweepResult:
    consent_records_removed: int
    privacy_requests_deleted: int
    privacy_requests_anonymized: int
    processor_tasks_deleted: int
    processor_tasks_anonymized: int
    backup_markers_expired: int
    audit_events_expired: int


async def apply_due_privacy_retention(
    session: AsyncSession,
    *,
    now: datetime | None = None,
) -> RetentionSweepResult:
    """Apply stored rule snapshots; active requests and active consents are never purged."""
    evaluated_at = now or datetime.now(UTC)
    marker_result = cast(
        CursorResult[Any],
        await session.execute(
            delete(BackupDeletionMarker).where(
                BackupDeletionMarker.backups_expire_at <= evaluated_at
            )
        ),
    )
    consent_result = cast(
        CursorResult[Any],
        await session.execute(
            delete(ConsentRecord).where(
                ConsentRecord.withdrawn_at.is_not(None),
                ConsentRecord.retain_until <= evaluated_at,
            )
        ),
    )

    terminal_requests = ("completed", "failed", "cancelled")
    request_candidates = list(
        (
            await session.scalars(
                select(PrivacyRequest)
                .where(
                    PrivacyRequest.status.in_(terminal_requests),
                    PrivacyRequest.retain_until <= evaluated_at,
                    ~exists().where(BackupDeletionMarker.privacy_request_id == PrivacyRequest.id),
                )
                .with_for_update(skip_locked=True)
            )
        ).all()
    )
    requests_deleted = 0
    requests_anonymized = 0
    for request in request_candidates:
        if request.retention_action == "delete":
            await session.delete(request)
            requests_deleted += 1
        elif request.account_id is not None or request.last_error_code is not None:
            request.account_id = None
            request.idempotency_key_hash = hashlib.sha256(str(request.id).encode()).hexdigest()
            request.last_error_code = None
            requests_anonymized += 1

    task_candidates = list(
        (
            await session.scalars(
                select(ProcessorDeletionTask)
                .where(
                    ProcessorDeletionTask.status == "completed",
                    ProcessorDeletionTask.retain_until <= evaluated_at,
                )
                .with_for_update(skip_locked=True)
            )
        ).all()
    )
    tasks_deleted = 0
    tasks_anonymized = 0
    for task in task_candidates:
        if task.retention_action == "delete":
            await session.delete(task)
            tasks_deleted += 1
        elif (
            task.account_id is not None
            or task.processor_subject_reference is not None
            or task.processor_subject_ciphertext is not None
        ):
            task.account_id = None
            task.processor_subject_reference = None
            task.processor_subject_ciphertext = None
            task.processor_subject_nonce = None
            task.processor_subject_key_id = None
            task.processor_usage_id = None
            task.last_error_code = None
            tasks_anonymized += 1

    audit_result = cast(
        CursorResult[Any],
        await session.execute(
            delete(AuditEvent).where(
                AuditEvent.retain_until.is_not(None),
                AuditEvent.retain_until <= evaluated_at,
            )
        ),
    )
    await session.flush()
    return RetentionSweepResult(
        consent_records_removed=consent_result.rowcount,
        privacy_requests_deleted=requests_deleted,
        privacy_requests_anonymized=requests_anonymized,
        processor_tasks_deleted=tasks_deleted,
        processor_tasks_anonymized=tasks_anonymized,
        backup_markers_expired=marker_result.rowcount,
        audit_events_expired=audit_result.rowcount,
    )
