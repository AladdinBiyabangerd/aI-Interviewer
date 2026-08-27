"""Processor inventory enforcement and retryable deletion propagation work."""

import hashlib
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import or_, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession
from uuid6 import uuid7

from ai_interviewer.core.crypto import ApplicationKeyring, EncryptedValue
from ai_interviewer.persistence.repositories import NewOutboxEvent, enqueue_outbox
from ai_interviewer.privacy.models import (
    PrivacyProfile,
    Processor,
    ProcessorActivity,
    ProcessorDeletionTask,
    ProcessorUsage,
)
from ai_interviewer.privacy.rules import ProcessingDecision, authorize_processing


class ProcessorPolicyError(Exception):
    """A vendor activity is missing, suspended, or outside the approved policy context."""


@dataclass(frozen=True, slots=True)
class DeletionTaskFailure:
    task: ProcessorDeletionTask
    escalated: bool


async def register_processor_usage(
    session: AsyncSession,
    *,
    account_id: UUID,
    processor_activity_id: UUID,
    processor_subject_reference: str,
    application_keyring: ApplicationKeyring | None = None,
    now: datetime | None = None,
) -> tuple[ProcessorUsage, ProcessingDecision]:
    evaluated_at = now or datetime.now(UTC)
    locator = processor_subject_reference.strip()
    if not locator or len(locator) > 255:
        raise ValueError("processor subject reference must contain 1-255 characters")
    activity = await session.get(ProcessorActivity, processor_activity_id)
    if activity is None:
        raise ProcessorPolicyError("the processor activity is unavailable")
    processor = await session.get(Processor, activity.processor_id)
    profile = await session.get(PrivacyProfile, account_id)
    if (
        processor is None
        or profile is None
        or processor.status != "active"
        or activity.status != "active"
        or activity.privacy_policy_version_id != profile.privacy_policy_version_id
        or activity.origin_region != profile.storage_region
    ):
        raise ProcessorPolicyError("the processor activity is not approved for this profile")
    decision = await authorize_processing(
        session,
        account_id=account_id,
        data_category=activity.data_category,
        purpose=activity.purpose,
        now=evaluated_at,
    )
    usage_id = uuid7()
    digest_material = (
        f"processor-locator\x00{account_id}\x00{activity.processor_id}\x00{locator}".encode()
    )
    locator_digest = (
        application_keyring.hmac_digest("subject_hmac", digest_material)
        if application_keyring is not None
        else hashlib.sha256(digest_material).hexdigest()
    )
    encrypted = (
        application_keyring.encrypt_field(
            locator,
            aad=processor_locator_aad(account_id, activity.processor_id),
        )
        if application_keyring is not None
        else None
    )
    statement = (
        insert(ProcessorUsage)
        .values(
            id=usage_id,
            account_id=account_id,
            processor_activity_id=activity.id,
            processor_subject_reference=locator if encrypted is None else None,
            processor_subject_ciphertext=(encrypted.ciphertext if encrypted is not None else None),
            processor_subject_nonce=encrypted.nonce if encrypted is not None else None,
            processor_subject_key_id=encrypted.key_id if encrypted is not None else None,
            processor_subject_digest=locator_digest,
            registered_at=evaluated_at,
        )
        .on_conflict_do_nothing(
            index_elements=[
                ProcessorUsage.account_id,
                ProcessorUsage.processor_activity_id,
                ProcessorUsage.processor_subject_digest,
            ]
        )
        .returning(ProcessorUsage)
    )
    usage = (await session.scalars(statement)).one_or_none()
    if usage is None:
        usage = await session.scalar(
            select(ProcessorUsage).where(
                ProcessorUsage.account_id == account_id,
                ProcessorUsage.processor_activity_id == activity.id,
                ProcessorUsage.processor_subject_digest == locator_digest,
            )
        )
        if usage is None:
            raise RuntimeError("processor usage conflict resolved without a visible row")
    return usage, decision


async def claim_processor_deletion_tasks(
    session: AsyncSession,
    *,
    worker_id: str,
    limit: int,
    now: datetime | None = None,
    lock_timeout: timedelta = timedelta(minutes=5),
) -> list[ProcessorDeletionTask]:
    if not worker_id or len(worker_id) > 128:
        raise ValueError("worker_id must contain 1-128 characters")
    if limit < 1 or limit > 100:
        raise ValueError("limit must be between 1 and 100")
    claimed_at = now or datetime.now(UTC)
    stale_before = claimed_at - lock_timeout
    statement = (
        select(ProcessorDeletionTask)
        .where(
            ProcessorDeletionTask.status.in_(("pending", "retry", "processing")),
            ProcessorDeletionTask.available_at <= claimed_at,
            or_(
                ProcessorDeletionTask.locked_at.is_(None),
                ProcessorDeletionTask.locked_at < stale_before,
            ),
        )
        .order_by(ProcessorDeletionTask.available_at, ProcessorDeletionTask.id)
        .limit(limit)
        .with_for_update(skip_locked=True)
    )
    tasks = list((await session.scalars(statement)).all())
    for task in tasks:
        task.status = "processing"
        task.locked_at = claimed_at
        task.locked_by = worker_id
    await session.flush()
    return tasks


async def complete_processor_deletion_task(
    session: AsyncSession,
    *,
    task: ProcessorDeletionTask,
    worker_id: str,
    now: datetime | None = None,
) -> None:
    if task.status != "processing" or task.locked_by != worker_id:
        raise ValueError("processor deletion task is not claimed by this worker")
    task.status = "completed"
    task.completed_at = now or datetime.now(UTC)
    task.processor_subject_reference = None
    task.processor_subject_ciphertext = None
    task.processor_subject_nonce = None
    task.processor_subject_key_id = None
    task.locked_at = None
    task.locked_by = None
    task.last_error_code = None
    await session.flush()


async def fail_processor_deletion_task(
    session: AsyncSession,
    *,
    task: ProcessorDeletionTask,
    worker_id: str,
    error_code: str,
    max_attempts: int,
    retry_base_seconds: int,
    now: datetime | None = None,
) -> DeletionTaskFailure:
    if task.status != "processing" or task.locked_by != worker_id:
        raise ValueError("processor deletion task is not claimed by this worker")
    normalized_error = error_code.strip().lower()
    if not normalized_error or len(normalized_error) > 100:
        raise ValueError("error_code must contain 1-100 characters")
    failed_at = now or datetime.now(UTC)
    task.attempts += 1
    task.last_error_code = normalized_error
    task.locked_at = None
    task.locked_by = None
    escalated = task.attempts >= max_attempts
    if escalated:
        task.status = "escalated"
        event_type = "privacy.processor_deletion.escalated"
    else:
        task.status = "retry"
        delay_seconds = min(retry_base_seconds * (2 ** (task.attempts - 1)), 86_400)
        task.available_at = failed_at + timedelta(seconds=delay_seconds)
        event_type = "privacy.processor_deletion.retry_scheduled"
    await enqueue_outbox(
        session,
        NewOutboxEvent(
            aggregate_type="processor_deletion_task",
            aggregate_id=task.id,
            event_type=event_type,
            payload={
                "task_id": str(task.id),
                "privacy_request_id": str(task.privacy_request_id),
                "attempt": task.attempts,
            },
            available_at=None if escalated else task.available_at,
        ),
    )
    await session.flush()
    return DeletionTaskFailure(task=task, escalated=escalated)


async def requeue_escalated_processor_deletion_task(
    session: AsyncSession,
    *,
    task: ProcessorDeletionTask,
    now: datetime | None = None,
) -> None:
    """Allow an authorized operator to resume an escalated task without losing its locator."""
    if task.status != "escalated" or not processor_task_has_locator(task):
        raise ValueError("only an escalated task with a locator can be requeued")
    task.status = "retry"
    task.available_at = now or datetime.now(UTC)
    task.last_error_code = None
    await enqueue_outbox(
        session,
        NewOutboxEvent(
            aggregate_type="processor_deletion_task",
            aggregate_id=task.id,
            event_type="privacy.processor_deletion.manually_requeued",
            payload={
                "task_id": str(task.id),
                "privacy_request_id": str(task.privacy_request_id),
            },
        ),
    )
    await session.flush()


def processor_locator_aad(account_id: UUID, processor_id: UUID) -> bytes:
    return f"processor-locator\x00{account_id}\x00{processor_id}".encode()


def processor_task_has_locator(task: ProcessorDeletionTask) -> bool:
    return (
        task.processor_subject_reference is not None
        or task.processor_subject_ciphertext is not None
    )


def decrypt_processor_task_reference(
    task: ProcessorDeletionTask,
    *,
    application_keyring: ApplicationKeyring | None,
) -> str:
    if task.processor_subject_reference is not None:
        return task.processor_subject_reference
    if (
        application_keyring is None
        or task.account_id is None
        or task.processor_subject_ciphertext is None
        or task.processor_subject_nonce is None
        or task.processor_subject_key_id is None
    ):
        raise ProcessorPolicyError("processor deletion locator is unavailable")
    return application_keyring.decrypt_field(
        EncryptedValue(
            key_id=task.processor_subject_key_id,
            nonce=task.processor_subject_nonce,
            ciphertext=task.processor_subject_ciphertext,
        ),
        aad=processor_locator_aad(task.account_id, task.processor_id),
    )
