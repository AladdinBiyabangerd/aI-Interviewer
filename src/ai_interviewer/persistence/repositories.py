"""Transactional outbox and immutable audit write operations."""

import re
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any, Literal
from uuid import UUID

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from ai_interviewer.persistence.models import AuditEvent, OutboxEvent

ActorType = Literal["system", "user", "service"]
_MAX_ERROR_LENGTH = 4_000
_SENSITIVE_METADATA_KEYS = {
    "answer",
    "answer_content",
    "answer_text",
    "access_token",
    "api_key",
    "authorization",
    "cv",
    "cv_content",
    "cv_text",
    "password",
    "raw_answer",
    "raw_cv",
    "raw_resume",
    "raw_transcript",
    "refresh_token",
    "id_token",
    "resume",
    "resume_content",
    "resume_text",
    "secret",
    "token",
    "transcript",
    "transcript_content",
    "transcript_text",
}


@dataclass(frozen=True, slots=True)
class NewOutboxEvent:
    aggregate_type: str
    aggregate_id: UUID
    event_type: str
    payload: dict[str, Any]
    owner_id: UUID | None = None
    available_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class NewAuditEvent:
    actor_type: ActorType
    action: str
    resource_type: str
    actor_id: UUID | None = None
    resource_id: UUID | None = None
    owner_id: UUID | None = None
    request_id: str | None = None
    details: dict[str, Any] = field(default_factory=dict)
    evidence_category: str | None = None
    retain_until: datetime | None = None


def _ensure_metadata_is_non_sensitive(value: object, path: str) -> None:
    if isinstance(value, dict):
        for key, nested in value.items():
            normalized_key = re.sub(r"(?<!^)(?=[A-Z])", "_", str(key).strip())
            normalized_key = re.sub(r"[^a-zA-Z0-9]+", "_", normalized_key).strip("_").lower()
            credential_key = normalized_key.startswith(("password_", "secret_")) or (
                normalized_key.endswith(("_password", "_secret"))
            )
            if normalized_key in _SENSITIVE_METADATA_KEYS or credential_key:
                raise ValueError(f"sensitive metadata key is forbidden: {path}.{key}")
            _ensure_metadata_is_non_sensitive(nested, f"{path}.{key}")
    elif isinstance(value, list):
        for index, nested in enumerate(value):
            _ensure_metadata_is_non_sensitive(nested, f"{path}[{index}]")


async def enqueue_outbox(session: AsyncSession, event: NewOutboxEvent) -> OutboxEvent:
    """Stage an outbox event inside the caller's transaction."""
    _ensure_metadata_is_non_sensitive(event.payload, "payload")
    record = OutboxEvent(
        aggregate_type=event.aggregate_type,
        aggregate_id=event.aggregate_id,
        event_type=event.event_type,
        payload=event.payload,
        owner_id=event.owner_id,
    )
    if event.available_at is not None:
        record.available_at = event.available_at
    session.add(record)
    await session.flush()
    return record


async def claim_outbox_batch(
    session: AsyncSession,
    *,
    worker_id: str,
    limit: int,
    lock_timeout: timedelta = timedelta(minutes=5),
    now: datetime | None = None,
) -> list[OutboxEvent]:
    """Claim available events with `SKIP LOCKED` for safe competing workers."""
    if not worker_id or len(worker_id) > 128:
        raise ValueError("worker_id must contain 1-128 characters")
    if limit < 1 or limit > 100:
        raise ValueError("limit must be between 1 and 100")
    claimed_at = now or datetime.now(UTC)
    stale_before = claimed_at - lock_timeout
    statement = (
        select(OutboxEvent)
        .where(
            OutboxEvent.published_at.is_(None),
            OutboxEvent.available_at <= claimed_at,
            or_(OutboxEvent.locked_at.is_(None), OutboxEvent.locked_at < stale_before),
        )
        .order_by(OutboxEvent.occurred_at, OutboxEvent.id)
        .limit(limit)
        .with_for_update(skip_locked=True)
    )
    records = list((await session.scalars(statement)).all())
    for record in records:
        record.locked_at = claimed_at
        record.locked_by = worker_id
    await session.flush()
    return records


async def mark_outbox_published(
    session: AsyncSession,
    record: OutboxEvent,
    *,
    worker_id: str,
    published_at: datetime | None = None,
) -> None:
    """Complete a claim only when it is still owned by the same worker."""
    if record.published_at is not None:
        raise ValueError("outbox event is already published")
    if record.locked_by != worker_id:
        raise ValueError("outbox event is not claimed by this worker")
    record.published_at = published_at or datetime.now(UTC)
    record.locked_at = None
    record.locked_by = None
    record.last_error = None
    await session.flush()


async def mark_outbox_failed(
    session: AsyncSession,
    record: OutboxEvent,
    *,
    worker_id: str,
    error: str,
    retry_at: datetime,
) -> None:
    """Release a failed claim and schedule a bounded retry."""
    if record.published_at is not None:
        raise ValueError("published outbox events cannot fail")
    if record.locked_by != worker_id:
        raise ValueError("outbox event is not claimed by this worker")
    record.attempts += 1
    record.last_error = error[:_MAX_ERROR_LENGTH]
    record.available_at = retry_at
    record.locked_at = None
    record.locked_by = None
    await session.flush()


async def record_audit_event(session: AsyncSession, event: NewAuditEvent) -> AuditEvent:
    """Append non-sensitive audit metadata; mutation is blocked by the database."""
    _ensure_metadata_is_non_sensitive(event.details, "details")
    if (event.evidence_category is None) != (event.retain_until is None):
        raise ValueError("audit evidence category and retention must be supplied together")
    record = AuditEvent(
        actor_type=event.actor_type,
        actor_id=event.actor_id,
        action=event.action,
        resource_type=event.resource_type,
        resource_id=event.resource_id,
        owner_id=event.owner_id,
        request_id=event.request_id,
        details=event.details,
        evidence_category=event.evidence_category,
        retain_until=event.retain_until,
    )
    session.add(record)
    await session.flush()
    return record
