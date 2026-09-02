import asyncio
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory
from fastapi.testclient import TestClient
from sqlalchemy import String, func, inspect, select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy.orm.exc import StaleDataError

from ai_interviewer.core.config import Settings
from ai_interviewer.identity.models import Account
from ai_interviewer.identity.service import (
    AccountAccessDeniedError,
    AuthenticationService,
)
from ai_interviewer.identity.tokens import VerifiedAccessToken
from ai_interviewer.main import create_app
from ai_interviewer.persistence.base import (
    OwnedRecordMixin,
    TimestampMixin,
    UUIDPrimaryKeyMixin,
    VersionedRecordMixin,
)
from ai_interviewer.persistence.database import Database
from ai_interviewer.persistence.models import AuditEvent, OutboxEvent
from ai_interviewer.persistence.repositories import (
    NewAuditEvent,
    NewOutboxEvent,
    claim_outbox_batch,
    enqueue_outbox,
    mark_outbox_failed,
    mark_outbox_published,
    record_audit_event,
)
from ai_interviewer.persistence.schema import EXPECTED_SCHEMA_REVISION

pytestmark = pytest.mark.integration


class SubjectTokenVerifier:
    async def verify(self, token: str) -> VerifiedAccessToken:
        return VerifiedAccessToken(
            issuer="https://identity.example.com/",
            subject=token,
            scopes=frozenset({"profile:read"}),
        )


class IntegrationModelBase(DeclarativeBase):
    """Isolated metadata for validating reusable persistence conventions."""


class VersionedOwnedRecord(
    UUIDPrimaryKeyMixin,
    TimestampMixin,
    OwnedRecordMixin,
    VersionedRecordMixin,
    IntegrationModelBase,
):
    __tablename__ = "test_versioned_owned_records"

    name: Mapped[str] = mapped_column(String(100), nullable=False)


def test_migration_roundtrip_and_model_parity(migrated_database: str) -> None:
    del migrated_database
    config = Config("alembic.ini")

    command.downgrade(config, "base")
    command.upgrade(config, "head")
    command.upgrade(config, "head")
    command.check(config)
    assert ScriptDirectory.from_config(config).get_heads() == [EXPECTED_SCHEMA_REVISION]


@pytest.mark.asyncio
async def test_database_readiness_and_transaction_rollback(database: Database) -> None:
    assert await database.is_ready() is True
    aggregate_id = uuid4()

    with pytest.raises(RuntimeError, match="force rollback"):
        async with database.transaction() as session:
            await enqueue_outbox(
                session,
                NewOutboxEvent(
                    aggregate_type="test",
                    aggregate_id=aggregate_id,
                    event_type="test.created",
                    payload={"sequence": 1},
                ),
            )
            raise RuntimeError("force rollback")

    async with database.transaction() as session:
        count = await session.scalar(
            select(func.count())
            .select_from(OutboxEvent)
            .where(OutboxEvent.aggregate_id == aggregate_id)
        )
    assert count == 0


@pytest.mark.asyncio
async def test_database_readiness_rejects_an_incompatible_schema(database: Database) -> None:
    async with database.engine.begin() as connection:
        await connection.execute(text("UPDATE alembic_version SET version_num = 'unexpected'"))
    try:
        assert await database.is_ready() is False
    finally:
        async with database.engine.begin() as connection:
            await connection.execute(
                text("UPDATE alembic_version SET version_num = :revision"),
                {"revision": EXPECTED_SCHEMA_REVISION},
            )

    assert await database.is_ready() is True


@pytest.mark.asyncio
async def test_outbox_claim_publish_retry_and_competing_workers(database: Database) -> None:
    owner_id = uuid4()
    aggregate_id = uuid4()
    future_time = datetime.now(UTC) + timedelta(hours=1)
    async with database.transaction() as session:
        first = await enqueue_outbox(
            session,
            NewOutboxEvent(
                owner_id=owner_id,
                aggregate_type="candidate_input",
                aggregate_id=aggregate_id,
                event_type="candidate_input.created",
                payload={"version": 1},
            ),
        )
        future = await enqueue_outbox(
            session,
            NewOutboxEvent(
                owner_id=owner_id,
                aggregate_type="candidate_input",
                aggregate_id=aggregate_id,
                event_type="candidate_input.retry",
                payload={"version": 2},
                available_at=future_time,
            ),
        )
        first_id, future_id = first.id, future.id

    async with database.session_factory() as first_session, first_session.begin():
        claimed = await claim_outbox_batch(first_session, worker_id="worker-a", limit=10)
        assert [event.id for event in claimed] == [first_id]

        async with database.session_factory() as second_session, second_session.begin():
            competing_claim = await claim_outbox_batch(
                second_session,
                worker_id="worker-b",
                limit=10,
            )
            assert competing_claim == []

        await mark_outbox_failed(
            first_session,
            claimed[0],
            worker_id="worker-a",
            error="temporary" * 1_000,
            retry_at=datetime.now(UTC) - timedelta(seconds=1),
        )

    async with database.transaction() as session:
        retry_claim = await claim_outbox_batch(session, worker_id="worker-b", limit=10)
        assert [event.id for event in retry_claim] == [first_id]
        assert retry_claim[0].attempts == 1
        assert len(retry_claim[0].last_error or "") == 4_000
        await mark_outbox_published(session, retry_claim[0], worker_id="worker-b")

    async with database.transaction() as session:
        persisted_first = await session.get(OutboxEvent, first_id)
        persisted_future = await session.get(OutboxEvent, future_id)
        assert persisted_first is not None and persisted_first.published_at is not None
        assert persisted_first.locked_by is None
        assert persisted_future is not None and persisted_future.published_at is None


@pytest.mark.asyncio
async def test_outbox_rejects_wrong_worker_and_double_publish(database: Database) -> None:
    async with database.transaction() as session:
        event = await enqueue_outbox(
            session,
            NewOutboxEvent(
                aggregate_type="test",
                aggregate_id=uuid4(),
                event_type="test.created",
                payload={},
            ),
        )
        event_id = event.id

    async with database.transaction() as session:
        claimed = await claim_outbox_batch(session, worker_id="owner-worker", limit=1)
        record = next(item for item in claimed if item.id == event_id)
        with pytest.raises(ValueError, match="not claimed"):
            await mark_outbox_published(session, record, worker_id="other-worker")
        await mark_outbox_published(session, record, worker_id="owner-worker")
        with pytest.raises(ValueError, match="already published"):
            await mark_outbox_published(session, record, worker_id="owner-worker")
        with pytest.raises(ValueError, match="cannot fail"):
            await mark_outbox_failed(
                session,
                record,
                worker_id="owner-worker",
                error="late failure",
                retry_at=datetime.now(UTC),
            )


@pytest.mark.asyncio
async def test_audit_events_are_append_only(database: Database) -> None:
    owner_id = uuid4()
    async with database.transaction() as session:
        event = await record_audit_event(
            session,
            NewAuditEvent(
                actor_type="service",
                action="retention.scheduled",
                resource_type="candidate_data",
                resource_id=uuid4(),
                owner_id=owner_id,
                request_id="integration-001",
                details={"retention_class": "candidate-input"},
            ),
        )
        event_id = event.id

    with pytest.raises(DBAPIError, match="append-only"):
        async with database.transaction() as session:
            await session.execute(
                text("UPDATE audit_events SET action = 'tampered' WHERE id = :id"),
                {"id": event_id},
            )

    with pytest.raises(DBAPIError, match="append-only"):
        async with database.transaction() as session:
            await session.execute(text("DELETE FROM audit_events WHERE id = :id"), {"id": event_id})

    with pytest.raises(DBAPIError, match="append-only"):
        async with database.transaction() as session:
            await session.execute(text("TRUNCATE audit_events"))

    async with database.transaction() as session:
        persisted = await session.get(AuditEvent, event_id)
        assert persisted is not None
        assert persisted.action == "retention.scheduled"


@pytest.mark.asyncio
async def test_owned_versioned_convention_detects_stale_writes(database: Database) -> None:
    async with database.engine.begin() as connection:
        await connection.run_sync(VersionedOwnedRecord.__table__.create)

    try:
        owner_id = uuid4()
        async with database.transaction() as session:
            record = VersionedOwnedRecord(owner_id=owner_id, name="initial")
            session.add(record)
            await session.flush()
            record_id = record.id
            assert isinstance(record_id, UUID)
            assert record_id.version == 7
            assert record.version == 1

        async with (
            database.session_factory() as first_session,
            database.session_factory() as second_session,
        ):
            first = await first_session.get(VersionedOwnedRecord, record_id)
            second = await second_session.get(VersionedOwnedRecord, record_id)
            assert first is not None and second is not None
            first.name = "first update"
            await first_session.commit()
            assert first.version == 2

            second.name = "stale update"
            with pytest.raises(StaleDataError):
                await second_session.commit()
            await second_session.rollback()
    finally:
        async with database.engine.begin() as connection:
            await connection.run_sync(VersionedOwnedRecord.__table__.drop)


def test_application_readiness_uses_real_database(migrated_database: str) -> None:
    settings = Settings(
        _env_file=None,
        environment="test",
        allowed_hosts=("testserver",),
        database_url=migrated_database,
        database_tls_mode="disable",
    )
    with TestClient(
        create_app(settings),
        backend_options={"loop_factory": asyncio.SelectorEventLoop},
    ) as client:
        response = client.get("/api/v1/health/ready")

    assert response.status_code == 200
    assert response.json()["checks"]["database"] == "up"


@pytest.mark.asyncio
async def test_migrated_tables_exist(database: Database) -> None:
    async with database.engine.connect() as connection:
        tables = await connection.run_sync(
            lambda sync_connection: inspect(sync_connection).get_table_names()
        )

    assert {
        "accounts",
        "alembic_version",
        "audit_events",
        "backup_deletion_markers",
        "candidate_document_intakes",
        "candidate_document_versions",
        "candidate_documents",
        "candidate_extraction_jobs",
        "candidate_profile_versions",
        "candidate_profiling_jobs",
        "candidate_profiles",
        "candidate_preparations",
        "candidate_source_text_versions",
        "candidate_source_texts",
        "company_fingerprint_evidence",
        "company_interview_fingerprints",
        "consent_notices",
        "consent_records",
        "file_assets",
        "file_deletion_tasks",
        "file_scan_attempts",
        "knowledge_evidence_signals",
        "knowledge_evidence_sources",
        "knowledge_sources",
        "outbox_events",
        "parser_release_policies",
        "privacy_policy_versions",
        "privacy_profiles",
        "privacy_requests",
        "processing_rules",
        "processor_activities",
        "processor_deletion_tasks",
        "processor_usages",
        "processors",
        "question_concept_evidence",
        "question_concepts",
        "retention_rules",
    }.issubset(tables)


@pytest.mark.asyncio
async def test_concurrent_identity_provisioning_is_idempotent_and_audited(
    database: Database,
) -> None:
    subject = f"concurrent-subject-{uuid4()}"
    authentication = AuthenticationService(database, SubjectTokenVerifier())

    first, second = await asyncio.gather(
        authentication.authenticate(subject, "identity-request-1"),
        authentication.authenticate(subject, "identity-request-2"),
    )

    assert first.account_id == second.account_id
    assert first.account_id.version == 7
    async with database.transaction() as session:
        account_count = await session.scalar(
            select(func.count()).select_from(Account).where(Account.subject == subject)
        )
        audit_count = await session.scalar(
            select(func.count())
            .select_from(AuditEvent)
            .where(
                AuditEvent.action == "account.provisioned",
                AuditEvent.resource_id == first.account_id,
            )
        )
    assert account_count == 1
    assert audit_count == 1


@pytest.mark.asyncio
async def test_disabled_identity_fails_closed(database: Database) -> None:
    subject = f"disabled-subject-{uuid4()}"
    authentication = AuthenticationService(database, SubjectTokenVerifier())
    principal = await authentication.authenticate(subject, "identity-disable-setup")

    async with database.transaction() as session:
        account = await session.get(Account, principal.account_id)
        assert account is not None
        account.status = "disabled"

    with pytest.raises(AccountAccessDeniedError):
        await authentication.authenticate(subject, "identity-disabled-attempt")
