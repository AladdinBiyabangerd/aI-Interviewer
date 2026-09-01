from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from sqlalchemy import func, select

from ai_interviewer.identity.models import Account
from ai_interviewer.persistence.database import Database
from ai_interviewer.persistence.models import AuditEvent, OutboxEvent
from ai_interviewer.persistence.repositories import NewAuditEvent, record_audit_event
from ai_interviewer.privacy.consent import (
    AdultAttestationRequiredError,
    ConsentNotFoundError,
    ConsentUnavailableError,
    ProfileInput,
)
from ai_interviewer.privacy.lifecycle import (
    PrivacyLifecycleService,
    PrivacyRequestConflictError,
    PrivacyRequestNotFoundError,
)
from ai_interviewer.privacy.models import (
    BackupDeletionMarker,
    ConsentNotice,
    ConsentRecord,
    PrivacyPolicyVersion,
    PrivacyProfile,
    PrivacyRequest,
    ProcessingRule,
    Processor,
    ProcessorActivity,
    ProcessorDeletionTask,
    ProcessorUsage,
    RetentionRule,
)
from ai_interviewer.privacy.policy import build_default_jurisdiction_registry
from ai_interviewer.privacy.retention import apply_due_privacy_retention
from ai_interviewer.privacy.rules import (
    ConsentRequiredError,
    PrivacyPolicyUnavailableError,
    ProcessingDeniedError,
    resolve_retention_for_context,
)

pytestmark = pytest.mark.integration


@dataclass(frozen=True, slots=True)
class PrivacyContext:
    service: PrivacyLifecycleService
    account_id: UUID
    issuer: str
    subject: str
    policy_id: UUID
    notice_id: UUID


async def _create_privacy_context(database: Database) -> PrivacyContext:
    now = datetime.now(UTC)
    unique = uuid4()
    issuer = "https://identity.example.com/"
    subject = f"privacy-subject-{unique}"
    async with database.transaction() as session:
        account = Account(issuer=issuer, subject=subject)
        policy = PrivacyPolicyVersion(
            policy_key=f"az-policy-{unique}",
            policy_version="legal-approved-1",
            jurisdiction_code="AZERBAIJAN",
            status="active",
            legal_review_status="approved",
            minimum_age=18,
            request_deadline_days=30,
            notice_uri="https://legal.example.com/privacy/az/1",
            content_sha256="a" * 64,
            effective_at=now - timedelta(days=1),
        )
        session.add_all([account, policy])
        await session.flush()
        notice = ConsentNotice(
            privacy_policy_version_id=policy.id,
            notice_key="product-analytics",
            notice_version="1",
            status="active",
            purpose="product_analytics",
            data_category="usage_analytics",
            document_uri="https://legal.example.com/consent/product-analytics/1",
            content_sha256="b" * 64,
            effective_at=now - timedelta(days=1),
        )
        session.add(notice)
        await session.flush()
        retention_contexts = (
            ("audit_evidence", "privacy_administration", 365, "delete"),
            ("consent_evidence", "product_analytics", 365, "delete"),
            ("privacy_request", "privacy_administration", 365, "anonymize"),
            ("deletion_tombstone", "privacy_administration", 90, "delete"),
            ("processor_deletion_evidence", "privacy_administration", 365, "anonymize"),
            ("usage_analytics", "product_analytics", 30, "delete"),
            ("interview_response", "interview_simulation", 90, "delete"),
        )
        session.add_all(
            [
                RetentionRule(
                    privacy_policy_version_id=policy.id,
                    jurisdiction_code="AZERBAIJAN",
                    data_category=category,
                    purpose=purpose,
                    retention_days=days,
                    action=action,
                )
                for category, purpose, days, action in retention_contexts
            ]
        )
        session.add(
            ProcessingRule(
                privacy_policy_version_id=policy.id,
                jurisdiction_code="AZERBAIJAN",
                data_category="usage_analytics",
                purpose="product_analytics",
                allowed=True,
                legal_basis="consent",
                consent_notice_id=notice.id,
            )
        )
        account_id = account.id
        policy_id = policy.id
        notice_id = notice.id

    service = PrivacyLifecycleService(
        database=database,
        registry=build_default_jurisdiction_registry(),
        subject_hmac_key=b"integration-privacy-hmac-key-value" * 2,
        max_processor_deletion_attempts=3,
        processor_retry_base_seconds=10,
    )
    await service.configure_profile(
        account_id,
        ProfileInput(
            residence_country_code="AZ",
            residence_subdivision_code=None,
            storage_region="az-primary",
            adult_attested=True,
            privacy_policy_version_id=policy_id,
        ),
        "profile-setup",
    )
    return PrivacyContext(
        service=service,
        account_id=account_id,
        issuer=issuer,
        subject=subject,
        policy_id=policy_id,
        notice_id=notice_id,
    )


@pytest.mark.asyncio
async def test_versioned_consent_withdrawal_and_purpose_processing(database: Database) -> None:
    context = await _create_privacy_context(database)

    grant = await context.service.grant(context.account_id, context.notice_id, "consent-grant")
    repeated = await context.service.grant(
        context.account_id, context.notice_id, "consent-grant-repeated"
    )
    decision = await context.service.authorize(
        context.account_id,
        data_category="usage_analytics",
        purpose="product_analytics",
    )

    assert grant.id == repeated.id
    assert decision.allowed is True
    assert decision.legal_basis == "consent"
    assert decision.consent_notice_id == context.notice_id

    withdrawn = await context.service.withdraw(context.account_id, grant.id, "consent-withdrawal")
    assert withdrawn.withdrawn_at is not None
    with pytest.raises(ConsentRequiredError):
        await context.service.authorize(
            context.account_id,
            data_category="usage_analytics",
            purpose="product_analytics",
        )

    replacement = await context.service.grant(
        context.account_id, context.notice_id, "consent-regrant"
    )
    assert replacement.id != grant.id
    assert len(await context.service.list_consents(context.account_id)) == 2
    async with database.transaction() as session:
        grants = await session.scalar(
            select(func.count())
            .select_from(AuditEvent)
            .where(
                AuditEvent.owner_id == context.account_id,
                AuditEvent.action == "consent.granted",
            )
        )
        withdrawals = await session.scalar(
            select(func.count())
            .select_from(AuditEvent)
            .where(
                AuditEvent.owner_id == context.account_id,
                AuditEvent.action == "consent.withdrawn",
            )
        )
    assert grants == 2
    assert withdrawals == 1


@pytest.mark.asyncio
async def test_access_export_is_machine_readable_and_idempotent(database: Database) -> None:
    context = await _create_privacy_context(database)
    await context.service.grant(context.account_id, context.notice_id, "export-consent")

    first = await context.service.create_request(
        context.account_id, "export", "stable-export-key", "export-request"
    )
    repeated = await context.service.create_request(
        context.account_id, "export", "stable-export-key", "export-request-repeated"
    )

    assert first.request_id == repeated.request_id
    assert first.status == "completed"
    assert first.data is not None
    assert first.data["schema_version"] == "phase-1b-c2"
    assert first.data["candidate_document_intakes"] == []
    assert first.data["stored_files"] == []
    assert first.data["candidate_documents"] == []
    assert first.data["candidate_preparations"] == []
    assert first.data["candidate_source_texts"] == []
    assert first.data["candidate_extraction_jobs"] == []
    assert first.data["candidate_profiles"] == []
    assert first.data["candidate_profiling_jobs"] == []
    assert first.data["account"]["identity_subject"] == context.subject
    assert first.data["privacy_profile"]["jurisdiction_codes"] == [
        "AZERBAIJAN",
        "GLOBAL_BASELINE",
    ]
    assert "idempotency_key_hash" not in str(first.data)
    async with database.transaction() as session:
        request_count = await session.scalar(
            select(func.count())
            .select_from(PrivacyRequest)
            .where(PrivacyRequest.account_id == context.account_id)
        )
    assert request_count == 1


@pytest.mark.asyncio
async def test_profile_consent_and_request_fail_closed_edges(database: Database) -> None:
    context = await _create_privacy_context(database)
    with pytest.raises(AdultAttestationRequiredError):
        await context.service.configure_profile(
            context.account_id,
            ProfileInput("AZ", None, "az-primary", False, context.policy_id),
            "underage-profile",
        )
    with pytest.raises(ValueError, match="storage_region"):
        await context.service.configure_profile(
            context.account_id,
            ProfileInput("AZ", None, "", True, context.policy_id),
            "invalid-storage",
        )
    with pytest.raises(ConsentUnavailableError):
        await context.service.grant(context.account_id, uuid4(), "missing-notice")
    with pytest.raises(ConsentNotFoundError):
        await context.service.withdraw(context.account_id, uuid4(), "missing-consent")
    with pytest.raises(ValueError, match="idempotency key"):
        await context.service.create_request(
            context.account_id, "access", "short", "invalid-idempotency"
        )
    with pytest.raises(PrivacyRequestNotFoundError):
        await context.service.get_request(context.account_id, uuid4())
    with pytest.raises(ValueError, match="processor subject reference"):
        await context.service.register_processor_use(
            context.account_id,
            processor_activity_id=uuid4(),
            processor_subject_reference="",
        )
    with pytest.raises(PrivacyPolicyUnavailableError, match="no jurisdiction"):
        async with database.transaction() as session:
            await resolve_retention_for_context(
                session,
                privacy_policy_version_id=context.policy_id,
                jurisdiction_codes=[],
                data_category="privacy_request",
                purpose="privacy_administration",
            )
    with pytest.raises(PrivacyPolicyUnavailableError, match="no processing rule"):
        await context.service.authorize(
            context.account_id,
            data_category="unknown_category",
            purpose="unknown_purpose",
        )

    async with database.transaction() as session:
        session.add(
            ProcessingRule(
                privacy_policy_version_id=context.policy_id,
                jurisdiction_code="AZERBAIJAN",
                data_category="blocked_category",
                purpose="blocked_purpose",
                allowed=False,
                legal_basis="prohibited",
            )
        )
    with pytest.raises(ProcessingDeniedError):
        await context.service.authorize(
            context.account_id,
            data_category="blocked_category",
            purpose="blocked_purpose",
        )

    updated = await context.service.configure_profile(
        context.account_id,
        ProfileInput("AZ", None, "az-secondary", True, context.policy_id),
        "profile-update",
    )
    assert updated.storage_region == "az-secondary"
    assert updated.version == 2

    first = await context.service.create_request(
        context.account_id, "access", "shared-idempotency", "access-request"
    )
    assert (
        await context.service.get_request(context.account_id, first.request_id)
    ).request_id == first.request_id
    with pytest.raises(PrivacyRequestConflictError, match="another request type"):
        await context.service.create_request(
            context.account_id, "export", "shared-idempotency", "conflicting-request"
        )


@pytest.mark.asyncio
async def test_deletion_erases_local_identity_and_emits_backup_outbox(database: Database) -> None:
    context = await _create_privacy_context(database)
    await context.service.grant(context.account_id, context.notice_id, "delete-consent")

    result = await context.service.create_request(
        context.account_id, "deletion", "delete-local-account", "delete-request"
    )

    assert result.status == "completed"
    async with database.transaction() as session:
        account = await session.get(Account, context.account_id)
        profile = await session.get(PrivacyProfile, context.account_id)
        consent_count = await session.scalar(
            select(func.count())
            .select_from(ConsentRecord)
            .where(ConsentRecord.account_id == context.account_id)
        )
        request = await session.get(PrivacyRequest, result.request_id)
        marker = await session.scalar(
            select(BackupDeletionMarker).where(
                BackupDeletionMarker.privacy_request_id == result.request_id
            )
        )
        assert marker is not None
        events = set(
            (
                await session.scalars(
                    select(OutboxEvent.event_type).where(
                        OutboxEvent.aggregate_id.in_((result.request_id, marker.id))
                    )
                )
            ).all()
        )
        audit_details = list(
            (
                await session.scalars(
                    select(AuditEvent.details).where(AuditEvent.owner_id == context.account_id)
                )
            ).all()
        )
    assert account is None
    assert profile is None
    assert consent_count == 0
    assert request is not None and request.account_id is None
    assert marker.subject_fingerprint not in {context.subject, context.issuer}
    assert events == {"privacy.backup_deletion.manifested", "privacy.deletion.completed"}
    assert context.subject not in str(audit_details)
    assert context.issuer not in str(audit_details)


async def _add_processor_usage(database: Database, context: PrivacyContext) -> UUID:
    now = datetime.now(UTC)
    async with database.transaction() as session:
        processor = Processor(
            processor_key=f"speech-vendor-{uuid4()}",
            inventory_version="1",
            legal_name="Example Speech Processor",
            status="active",
            privacy_uri="https://processor.example.com/privacy",
            contract_reference="dpa-reviewed-1",
            operating_countries=["AZ"],
            subprocessors=[],
        )
        session.add(processor)
        await session.flush()
        activity = ProcessorActivity(
            processor_id=processor.id,
            privacy_policy_version_id=context.policy_id,
            status="active",
            data_category="interview_response",
            purpose="interview_simulation",
            origin_region="az-primary",
            processing_region="az-primary",
            storage_region="az-primary",
            cross_border=False,
            transfer_mechanism=None,
            deletion_mechanism="vendor-api",
            deletion_sla_days=30,
            approved_at=now,
        )
        session.add(activity)
        session.add(
            ProcessingRule(
                privacy_policy_version_id=context.policy_id,
                jurisdiction_code="AZERBAIJAN",
                data_category="interview_response",
                purpose="interview_simulation",
                allowed=True,
                legal_basis="contract",
                consent_notice_id=None,
            )
        )
        await session.flush()
        activity_id = activity.id
    usage = await context.service.register_processor_use(
        context.account_id,
        processor_activity_id=activity_id,
        processor_subject_reference=f"processor-subject-{uuid4()}",
    )
    return usage.id


@pytest.mark.asyncio
async def test_processor_deletion_retries_then_completes_and_anonymizes(database: Database) -> None:
    context = await _create_privacy_context(database)
    usage_id = await _add_processor_usage(database, context)
    result = await context.service.create_request(
        context.account_id, "deletion", "delete-with-processor", "processor-delete"
    )

    assert result.status == "processing"
    async with database.transaction() as session:
        assert await session.get(ProcessorUsage, usage_id) is None
        task = await session.scalar(
            select(ProcessorDeletionTask).where(
                ProcessorDeletionTask.privacy_request_id == result.request_id
            )
        )
        account = await session.get(Account, context.account_id)
    assert task is not None
    assert account is not None and account.status == "deletion_pending"

    claim_time = datetime.now(UTC) + timedelta(seconds=1)
    claimed = await context.service.claim_processor_tasks(
        worker_id="privacy-worker", limit=10, now=claim_time
    )
    assert [item.id for item in claimed] == [task.id]
    retry_result = await context.service.reject_processor_task(
        task_id=task.id,
        worker_id="privacy-worker",
        error_code="vendor_timeout",
        now=claim_time,
    )
    assert retry_result.status == "processing"
    assert (
        await context.service.claim_processor_tasks(
            worker_id="privacy-worker", limit=10, now=claim_time + timedelta(seconds=9)
        )
        == []
    )

    claimed_retry = await context.service.claim_processor_tasks(
        worker_id="privacy-worker", limit=10, now=claim_time + timedelta(seconds=10)
    )
    assert [item.id for item in claimed_retry] == [task.id]
    completed = await context.service.acknowledge_processor_task(
        task_id=task.id,
        worker_id="privacy-worker",
        now=claim_time + timedelta(seconds=10),
    )
    assert completed.status == "completed"

    async with database.transaction() as session:
        persisted_task = await session.get(ProcessorDeletionTask, task.id)
        persisted_account = await session.get(Account, context.account_id)
        retry_events = await session.scalar(
            select(func.count())
            .select_from(OutboxEvent)
            .where(
                OutboxEvent.aggregate_id == task.id,
                OutboxEvent.event_type == "privacy.processor_deletion.retry_scheduled",
            )
        )
    assert persisted_account is None
    assert persisted_task is not None
    assert persisted_task.status == "completed"
    assert persisted_task.account_id is None
    assert persisted_task.processor_subject_reference is None
    assert persisted_task.attempts == 1
    assert retry_events == 1


@pytest.mark.asyncio
async def test_processor_deletion_escalation_can_be_manually_requeued(database: Database) -> None:
    context = await _create_privacy_context(database)
    await _add_processor_usage(database, context)
    result = await context.service.create_request(
        context.account_id, "deletion", "delete-escalation", "escalation-delete"
    )
    async with database.transaction() as session:
        task = await session.scalar(
            select(ProcessorDeletionTask).where(
                ProcessorDeletionTask.privacy_request_id == result.request_id
            )
        )
    assert task is not None

    with pytest.raises(ValueError, match="worker_id"):
        await context.service.claim_processor_tasks(worker_id="", limit=1)
    with pytest.raises(ValueError, match="limit"):
        await context.service.claim_processor_tasks(worker_id="worker", limit=0)

    base = datetime.now(UTC) + timedelta(seconds=1)
    retry_times = (base, base + timedelta(seconds=10), base + timedelta(seconds=30))
    for index, claim_at in enumerate(retry_times, start=1):
        claimed = await context.service.claim_processor_tasks(
            worker_id="escalation-worker", limit=1, now=claim_at
        )
        assert [item.id for item in claimed] == [task.id]
        failed = await context.service.reject_processor_task(
            task_id=task.id,
            worker_id="escalation-worker",
            error_code="vendor_unavailable",
            now=claim_at,
        )
        assert failed.status == ("failed" if index == 3 else "processing")

    async with database.transaction() as session:
        escalated = await session.get(ProcessorDeletionTask, task.id)
        assert escalated is not None
        assert escalated.status == "escalated"
        assert escalated.processor_subject_reference is not None

    requeue_at = base + timedelta(seconds=31)
    await context.service.requeue_escalated_task(task_id=task.id, now=requeue_at)
    requeued = await context.service.claim_processor_tasks(
        worker_id="escalation-worker", limit=1, now=requeue_at
    )
    assert [item.id for item in requeued] == [task.id]
    completed = await context.service.acknowledge_processor_task(
        task_id=task.id,
        worker_id="escalation-worker",
        now=requeue_at,
    )
    assert completed.status == "completed"

    async with database.transaction() as session:
        event_types = set(
            (
                await session.scalars(
                    select(OutboxEvent.event_type).where(OutboxEvent.aggregate_id == task.id)
                )
            ).all()
        )
    assert "privacy.processor_deletion.escalated" in event_types
    assert "privacy.processor_deletion.manually_requeued" in event_types


@pytest.mark.asyncio
async def test_backup_manifest_erases_restored_data_but_not_newer_account(
    database: Database,
) -> None:
    context = await _create_privacy_context(database)
    await context.service.create_request(
        context.account_id, "deletion", "delete-before-restore", "restore-delete"
    )
    manifest = await context.service.export_deletion_manifest()
    entry = next(item for item in manifest if item.account_id == context.account_id)

    async with database.transaction() as session:
        session.add(
            Account(
                id=context.account_id,
                issuer=context.issuer,
                subject=context.subject,
                created_at=entry.cutoff_at - timedelta(days=1),
            )
        )
    replay = await context.service.apply_deletion_manifest([entry])
    assert replay.restored_accounts_erased == 1
    async with database.transaction() as session:
        assert await session.get(Account, context.account_id) is None

    async with database.transaction() as session:
        session.add(
            Account(
                id=context.account_id,
                issuer=context.issuer,
                subject=context.subject,
                created_at=entry.cutoff_at + timedelta(seconds=1),
            )
        )
    safe_replay = await context.service.apply_deletion_manifest([entry])
    assert safe_replay.markers_recorded == 0
    assert safe_replay.restored_accounts_erased == 0
    async with database.transaction() as session:
        newer = await session.get(Account, context.account_id)
        assert newer is not None
        await session.delete(newer)


@pytest.mark.asyncio
async def test_retention_deletes_withdrawn_consent_and_expired_audit(database: Database) -> None:
    context = await _create_privacy_context(database)
    now = datetime.now(UTC)
    async with database.transaction() as session:
        record = ConsentRecord(
            account_id=context.account_id,
            consent_notice_id=context.notice_id,
            granted_at=now - timedelta(days=3),
            withdrawn_at=now - timedelta(days=2),
            retain_until=now - timedelta(days=1),
            retention_action="delete",
            request_id="expired-consent",
        )
        session.add(record)
        await session.flush()
        expired_record_id = record.id
        expired_audit = await record_audit_event(
            session,
            NewAuditEvent(
                actor_type="system",
                action="privacy.retention.test",
                resource_type="retention_test",
                evidence_category="privacy_lifecycle",
                retain_until=now - timedelta(days=1),
            ),
        )
        expired_audit_id = expired_audit.id
        processor = Processor(
            processor_key=f"retention-processor-{uuid4()}",
            inventory_version="1",
            legal_name="Retention Test Processor",
            status="retired",
            privacy_uri="https://processor.example.com/privacy",
            contract_reference="retention-test-contract",
            operating_countries=["AZ"],
            subprocessors=[],
        )
        session.add(processor)
        request_values = {
            "account_id": context.account_id,
            "request_type": "access",
            "status": "completed",
            "privacy_policy_version_id": context.policy_id,
            "jurisdiction_code": "AZERBAIJAN",
            "requested_at": now - timedelta(days=10),
            "due_at": now - timedelta(days=5),
            "verified_at": now - timedelta(days=10),
            "processing_started_at": now - timedelta(days=10),
            "completed_at": now - timedelta(days=9),
            "retain_until": now - timedelta(days=1),
        }
        request_to_delete = PrivacyRequest(
            **request_values,
            idempotency_key_hash="c" * 64,
            retention_action="delete",
        )
        request_to_anonymize = PrivacyRequest(
            **request_values,
            idempotency_key_hash="d" * 64,
            retention_action="anonymize",
            last_error_code="old_error",
        )
        task_parent = PrivacyRequest(
            **{
                **request_values,
                "retain_until": now + timedelta(days=30),
            },
            idempotency_key_hash="e" * 64,
            retention_action="anonymize",
        )
        session.add_all([request_to_delete, request_to_anonymize, task_parent])
        await session.flush()
        task_values = {
            "privacy_request_id": task_parent.id,
            "processor_id": processor.id,
            "account_id": context.account_id,
            "status": "completed",
            "attempts": 1,
            "available_at": now - timedelta(days=2),
            "completed_at": now - timedelta(days=2),
            "retain_until": now - timedelta(days=1),
        }
        task_to_delete = ProcessorDeletionTask(
            **task_values,
            processor_subject_reference="expired-delete-locator",
            retention_action="delete",
        )
        task_to_anonymize = ProcessorDeletionTask(
            **task_values,
            processor_subject_reference="expired-anonymize-locator",
            retention_action="anonymize",
            last_error_code="old_error",
        )
        session.add_all([task_to_delete, task_to_anonymize])
        await session.flush()
        request_to_delete_id = request_to_delete.id
        request_to_anonymize_id = request_to_anonymize.id
        task_to_delete_id = task_to_delete.id
        task_to_anonymize_id = task_to_anonymize.id

    async with database.transaction() as session:
        sweep = await apply_due_privacy_retention(session, now=now)

    assert sweep.consent_records_removed >= 1
    assert sweep.privacy_requests_deleted >= 1
    assert sweep.privacy_requests_anonymized >= 1
    assert sweep.processor_tasks_deleted >= 1
    assert sweep.processor_tasks_anonymized >= 1
    assert sweep.audit_events_expired >= 1
    async with database.transaction() as session:
        assert await session.get(ConsentRecord, expired_record_id) is None
        assert await session.get(AuditEvent, expired_audit_id) is None
        assert await session.get(PrivacyRequest, request_to_delete_id) is None
        anonymized_request = await session.get(PrivacyRequest, request_to_anonymize_id)
        assert anonymized_request is not None
        assert anonymized_request.account_id is None
        assert anonymized_request.last_error_code is None
        assert await session.get(ProcessorDeletionTask, task_to_delete_id) is None
        anonymized_task = await session.get(ProcessorDeletionTask, task_to_anonymize_id)
        assert anonymized_task is not None
        assert anonymized_task.account_id is None
        assert anonymized_task.processor_subject_reference is None
