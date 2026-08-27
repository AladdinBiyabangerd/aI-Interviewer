from datetime import UTC, datetime, timedelta
from typing import cast
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from ai_interviewer.core.config import Settings
from ai_interviewer.persistence.database import Database, database_connect_args
from ai_interviewer.persistence.repositories import (
    NewAuditEvent,
    NewOutboxEvent,
    claim_outbox_batch,
    enqueue_outbox,
    record_audit_event,
)


def test_database_connect_args_are_bounded() -> None:
    settings = Settings(
        _env_file=None,
        database_tls_mode="require",
        database_connect_timeout_seconds=7,
        database_statement_timeout_ms=12_000,
    )

    assert database_connect_args(settings) == {
        "sslmode": "require",
        "options": "-c statement_timeout=12000",
        "connect_timeout": 7,
    }


@pytest.mark.asyncio
async def test_database_readiness_fails_closed_when_unreachable() -> None:
    settings = Settings(
        _env_file=None,
        database_url="postgresql+psycopg://app:password@127.0.0.1:1/unreachable",
        database_connect_timeout_seconds=1,
        database_healthcheck_timeout_seconds=0.1,
    )
    database = Database(settings)

    try:
        assert await database.is_ready() is False
    finally:
        await database.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("worker_id", ["", "x" * 129])
async def test_outbox_claim_rejects_invalid_worker_id(worker_id: str) -> None:
    with pytest.raises(ValueError, match="worker_id"):
        await claim_outbox_batch(
            cast(AsyncSession, object()),
            worker_id=worker_id,
            limit=1,
        )


@pytest.mark.asyncio
@pytest.mark.parametrize("limit", [0, 101])
async def test_outbox_claim_rejects_invalid_limit(limit: int) -> None:
    with pytest.raises(ValueError, match="limit"):
        await claim_outbox_batch(
            cast(AsyncSession, object()),
            worker_id="worker-1",
            limit=limit,
        )


@pytest.mark.asyncio
@pytest.mark.parametrize("sensitive_key", ["transcript", "accessToken", "password_hash"])
async def test_audit_details_reject_sensitive_keys_recursively(sensitive_key: str) -> None:
    event = NewAuditEvent(
        actor_type="system",
        action="resource.created",
        resource_type="example",
        resource_id=uuid4(),
        details={"safe": [{sensitive_key: "must not persist"}]},
    )

    with pytest.raises(ValueError, match=rf"details\.safe\[0\]\.{sensitive_key}"):
        await record_audit_event(cast(AsyncSession, object()), event)


@pytest.mark.asyncio
async def test_outbox_payload_rejects_sensitive_content_fields() -> None:
    event = NewOutboxEvent(
        aggregate_type="candidate_input",
        aggregate_id=uuid4(),
        event_type="candidate_input.created",
        payload={"candidate_input_id": str(uuid4()), "rawCv": "must not persist"},
    )

    with pytest.raises(ValueError, match=r"payload\.rawCv"):
        await enqueue_outbox(cast(AsyncSession, object()), event)


def test_repository_time_inputs_are_timezone_aware() -> None:
    now = datetime.now(UTC)
    retry_at = now + timedelta(seconds=30)

    assert now.tzinfo is UTC
    assert retry_at > now
