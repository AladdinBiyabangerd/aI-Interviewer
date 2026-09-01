"""Privacy self-service, request orchestration, deletion, export, and restore replay."""

import hashlib
import hmac
import json
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, NoReturn, Protocol
from uuid import UUID

from sqlalchemy import delete, func, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from ai_interviewer.core.config import Settings
from ai_interviewer.core.crypto import ApplicationKeyring
from ai_interviewer.core.telemetry import DisabledTelemetry, TelemetryRuntime
from ai_interviewer.identity.models import Account
from ai_interviewer.persistence.database import DatabaseRuntime
from ai_interviewer.persistence.models import AuditEvent, OutboxEvent
from ai_interviewer.persistence.repositories import NewOutboxEvent, enqueue_outbox
from ai_interviewer.privacy.audit import record_privacy_audit
from ai_interviewer.privacy.consent import (
    ProfileInput,
    configure_privacy_profile,
    grant_consent,
    withdraw_consent,
)
from ai_interviewer.privacy.models import (
    BackupDeletionMarker,
    ConsentNotice,
    ConsentRecord,
    PrivacyProfile,
    PrivacyRequest,
    PrivacyRequestStatus,
    PrivacyRequestType,
    Processor,
    ProcessorActivity,
    ProcessorDeletionTask,
    ProcessorUsage,
    RetentionAction,
)
from ai_interviewer.privacy.policy import JurisdictionPolicyRegistry
from ai_interviewer.privacy.processors import (
    claim_processor_deletion_tasks,
    complete_processor_deletion_task,
    decrypt_processor_task_reference,
    fail_processor_deletion_task,
    register_processor_usage,
    requeue_escalated_processor_deletion_task,
)
from ai_interviewer.privacy.rules import (
    ProcessingDecision,
    authorize_processing,
    require_privacy_profile,
    resolve_retention_for_context,
)


class PrivacyUnavailableError(Exception):
    """Privacy self-service is intentionally unavailable or misconfigured."""


class PrivacyRequestNotFoundError(Exception):
    """The account does not own the requested privacy request."""


class PrivacyRequestConflictError(Exception):
    """The request cannot transition from its current state."""


@dataclass(frozen=True, slots=True)
class PrivacyRequestResult:
    request_id: UUID
    request_type: PrivacyRequestType
    status: PrivacyRequestStatus
    requested_at: datetime
    due_at: datetime
    completed_at: datetime | None
    data: dict[str, Any] | None = None


@dataclass(frozen=True, slots=True)
class DeletionManifestEntry:
    marker_id: UUID
    account_id: UUID
    subject_fingerprint: str
    privacy_request_id: UUID
    privacy_policy_version_id: UUID
    cutoff_at: datetime
    backups_expire_at: datetime
    subject_key_id: str = "legacy-v1"


@dataclass(frozen=True, slots=True)
class RestoreReplayResult:
    markers_recorded: int
    restored_accounts_erased: int
    external_deletions_pending: int = 0


@dataclass(frozen=True, slots=True)
class SignedDeletionManifest:
    schema_version: str
    generated_at: datetime
    key_id: str
    entries: tuple[DeletionManifestEntry, ...]
    signature: str


class FileLifecycleAdapter(Protocol):
    """Narrow cross-context contract used by privacy export and deletion."""

    async def schedule_account_deletion(
        self,
        session: AsyncSession,
        *,
        account_id: UUID,
        privacy_request_id: UUID,
        retain_until: datetime,
        retention_action: RetentionAction,
        now: datetime,
    ) -> int: ...

    async def has_pending_account_deletion(
        self,
        session: AsyncSession,
        *,
        privacy_request_id: UUID,
    ) -> bool: ...

    async def export_account_metadata(
        self,
        session: AsyncSession,
        *,
        account_id: UUID,
    ) -> list[dict[str, Any]]: ...


class CandidateDataLifecycleAdapter(Protocol):
    """Narrow cross-module contract for privacy export and local erasure."""

    async def export_account_metadata(
        self,
        session: AsyncSession,
        *,
        account_id: UUID,
    ) -> list[dict[str, object]]: ...

    async def erase_account_metadata(
        self,
        session: AsyncSession,
        *,
        account_id: UUID,
    ) -> int: ...


class CandidateDocumentLifecycleAdapter(Protocol):
    """Narrow cross-module contract for document-lineage export and local erasure."""

    async def export_account_document_metadata(
        self,
        session: AsyncSession,
        *,
        account_id: UUID,
    ) -> list[dict[str, object]]: ...

    async def erase_account_document_metadata(
        self,
        session: AsyncSession,
        *,
        account_id: UUID,
    ) -> int: ...


class CandidateDocumentIntakeLifecycleAdapter(Protocol):
    """Narrow privacy contract for document-intake status metadata."""

    async def export_account_intake_metadata(
        self,
        session: AsyncSession,
        *,
        account_id: UUID,
    ) -> list[dict[str, object]]: ...

    async def erase_account_intake_metadata(
        self,
        session: AsyncSession,
        *,
        account_id: UUID,
    ) -> int: ...


class CandidateSourceTextLifecycleAdapter(Protocol):
    """Narrow privacy contract for exporting decrypted source-text lineage.

    No erase method exists: `candidate_source_texts` rows are always tied to an
    owner-scoped `candidate_document_versions` row (`ON DELETE CASCADE`, never
    orphaned), so `CandidateDocumentLifecycleAdapter.erase_account_document_metadata`
    already removes them.
    """

    async def export_account_source_text_metadata(
        self,
        session: AsyncSession,
        *,
        account_id: UUID,
    ) -> list[dict[str, object]]: ...


class CandidateExtractionJobLifecycleAdapter(Protocol):
    """Narrow privacy contract for exporting extraction-job operational metadata.

    No erase method exists for the same cascade reason as source-text lineage.
    """

    async def export_account_job_metadata(
        self,
        session: AsyncSession,
        *,
        account_id: UUID,
    ) -> list[dict[str, object]]: ...


class CandidateProfileLifecycleAdapter(Protocol):
    """Narrow privacy contract for exporting decrypted derived profile lineage.

    Profile rows cascade from exact source/document lineage, so document erasure
    remains the one deletion coordinator and cannot leave derived-data orphans.
    """

    async def export_account_profile_metadata(
        self,
        session: AsyncSession,
        *,
        account_id: UUID,
    ) -> list[dict[str, object]]: ...


class CandidateProfilingJobLifecycleAdapter(Protocol):
    """Narrow privacy contract for profiling-job operational metadata.

    Jobs cascade from exact source/document lineage and contain no candidate content.
    """

    async def export_account_profiling_job_metadata(
        self,
        session: AsyncSession,
        *,
        account_id: UUID,
    ) -> list[dict[str, object]]: ...


class _NoFileLifecycle:
    async def schedule_account_deletion(
        self,
        session: AsyncSession,
        *,
        account_id: UUID,
        privacy_request_id: UUID,
        retain_until: datetime,
        retention_action: RetentionAction,
        now: datetime,
    ) -> int:
        del session, account_id, privacy_request_id, retain_until, retention_action, now
        return 0

    async def has_pending_account_deletion(
        self,
        session: AsyncSession,
        *,
        privacy_request_id: UUID,
    ) -> bool:
        del session, privacy_request_id
        return False

    async def export_account_metadata(
        self,
        session: AsyncSession,
        *,
        account_id: UUID,
    ) -> list[dict[str, Any]]:
        del session, account_id
        return []


class _NoCandidateDataLifecycle:
    async def export_account_metadata(
        self,
        session: AsyncSession,
        *,
        account_id: UUID,
    ) -> list[dict[str, object]]:
        del session, account_id
        return []

    async def erase_account_metadata(
        self,
        session: AsyncSession,
        *,
        account_id: UUID,
    ) -> int:
        del session, account_id
        return 0


class _NoCandidateDocumentLifecycle:
    async def export_account_document_metadata(
        self,
        session: AsyncSession,
        *,
        account_id: UUID,
    ) -> list[dict[str, object]]:
        del session, account_id
        return []

    async def erase_account_document_metadata(
        self,
        session: AsyncSession,
        *,
        account_id: UUID,
    ) -> int:
        del session, account_id
        return 0


class _NoCandidateDocumentIntakeLifecycle:
    async def export_account_intake_metadata(
        self,
        session: AsyncSession,
        *,
        account_id: UUID,
    ) -> list[dict[str, object]]:
        del session, account_id
        return []

    async def erase_account_intake_metadata(
        self,
        session: AsyncSession,
        *,
        account_id: UUID,
    ) -> int:
        del session, account_id
        return 0


class _NoCandidateSourceTextLifecycle:
    async def export_account_source_text_metadata(
        self,
        session: AsyncSession,
        *,
        account_id: UUID,
    ) -> list[dict[str, object]]:
        del session, account_id
        return []


class _NoCandidateExtractionJobLifecycle:
    async def export_account_job_metadata(
        self,
        session: AsyncSession,
        *,
        account_id: UUID,
    ) -> list[dict[str, object]]:
        del session, account_id
        return []


class _NoCandidateProfileLifecycle:
    async def export_account_profile_metadata(
        self,
        session: AsyncSession,
        *,
        account_id: UUID,
    ) -> list[dict[str, object]]:
        del session, account_id
        return []


class _NoCandidateProfilingJobLifecycle:
    async def export_account_profiling_job_metadata(
        self,
        session: AsyncSession,
        *,
        account_id: UUID,
    ) -> list[dict[str, object]]:
        del session, account_id
        return []


class PrivacyRuntime(Protocol):
    async def configure_profile(
        self, account_id: UUID, profile_input: ProfileInput, request_id: str | None
    ) -> PrivacyProfile: ...

    async def grant(
        self, account_id: UUID, consent_notice_id: UUID, request_id: str | None
    ) -> ConsentRecord: ...

    async def withdraw(
        self, account_id: UUID, consent_record_id: UUID, request_id: str | None
    ) -> ConsentRecord: ...

    async def list_consents(self, account_id: UUID) -> list[ConsentRecord]: ...

    async def register_processor_use(
        self,
        account_id: UUID,
        *,
        processor_activity_id: UUID,
        processor_subject_reference: str,
    ) -> ProcessorUsage: ...

    async def create_request(
        self,
        account_id: UUID,
        request_type: PrivacyRequestType,
        idempotency_key: str,
        request_id: str | None,
    ) -> PrivacyRequestResult: ...

    async def get_request(self, account_id: UUID, request_id: UUID) -> PrivacyRequestResult: ...

    async def resume_deletion(
        self, request_id: UUID, correlation_id: str | None = None
    ) -> PrivacyRequestResult: ...


class FailClosedPrivacyService:
    """Reject privacy endpoints when the lifecycle is not configured."""

    @staticmethod
    def _unavailable() -> NoReturn:
        raise PrivacyUnavailableError("privacy lifecycle is not configured")

    async def configure_profile(
        self, account_id: UUID, profile_input: ProfileInput, request_id: str | None
    ) -> PrivacyProfile:
        del account_id, profile_input, request_id
        self._unavailable()

    async def grant(
        self, account_id: UUID, consent_notice_id: UUID, request_id: str | None
    ) -> ConsentRecord:
        del account_id, consent_notice_id, request_id
        self._unavailable()

    async def withdraw(
        self, account_id: UUID, consent_record_id: UUID, request_id: str | None
    ) -> ConsentRecord:
        del account_id, consent_record_id, request_id
        self._unavailable()

    async def list_consents(self, account_id: UUID) -> list[ConsentRecord]:
        del account_id
        self._unavailable()

    async def register_processor_use(
        self,
        account_id: UUID,
        *,
        processor_activity_id: UUID,
        processor_subject_reference: str,
    ) -> ProcessorUsage:
        del account_id, processor_activity_id, processor_subject_reference
        self._unavailable()

    async def create_request(
        self,
        account_id: UUID,
        request_type: PrivacyRequestType,
        idempotency_key: str,
        request_id: str | None,
    ) -> PrivacyRequestResult:
        del account_id, request_type, idempotency_key, request_id
        self._unavailable()

    async def get_request(self, account_id: UUID, request_id: UUID) -> PrivacyRequestResult:
        del account_id, request_id
        self._unavailable()

    async def resume_deletion(
        self, request_id: UUID, correlation_id: str | None = None
    ) -> PrivacyRequestResult:
        del request_id, correlation_id
        self._unavailable()


class PrivacyLifecycleService:
    """Own transaction boundaries for the complete Phase 0C-B lifecycle."""

    def __init__(
        self,
        *,
        database: DatabaseRuntime,
        registry: JurisdictionPolicyRegistry,
        subject_hmac_key: bytes | None = None,
        application_keyring: ApplicationKeyring | None = None,
        file_lifecycle: FileLifecycleAdapter | None = None,
        candidate_data_lifecycle: CandidateDataLifecycleAdapter | None = None,
        candidate_document_lifecycle: CandidateDocumentLifecycleAdapter | None = None,
        candidate_document_intake_lifecycle: (
            CandidateDocumentIntakeLifecycleAdapter | None
        ) = None,
        candidate_source_text_lifecycle: CandidateSourceTextLifecycleAdapter | None = None,
        candidate_extraction_job_lifecycle: (CandidateExtractionJobLifecycleAdapter | None) = None,
        candidate_profile_lifecycle: CandidateProfileLifecycleAdapter | None = None,
        candidate_profiling_job_lifecycle: (CandidateProfilingJobLifecycleAdapter | None) = None,
        max_processor_deletion_attempts: int = 10,
        processor_retry_base_seconds: int = 60,
        telemetry: TelemetryRuntime | None = None,
    ) -> None:
        if (subject_hmac_key is None) == (application_keyring is None):
            raise ValueError("exactly one subject cryptography source is required")
        if subject_hmac_key is not None and len(subject_hmac_key) < 32:
            raise ValueError("subject_hmac_key must contain at least 32 bytes")
        self._database = database
        self._registry = registry
        self._file_lifecycle = file_lifecycle or _NoFileLifecycle()
        self._candidate_data_lifecycle = candidate_data_lifecycle or _NoCandidateDataLifecycle()
        self._candidate_document_lifecycle = (
            candidate_document_lifecycle or _NoCandidateDocumentLifecycle()
        )
        self._candidate_document_intake_lifecycle = (
            candidate_document_intake_lifecycle or _NoCandidateDocumentIntakeLifecycle()
        )
        self._candidate_source_text_lifecycle = (
            candidate_source_text_lifecycle or _NoCandidateSourceTextLifecycle()
        )
        self._candidate_extraction_job_lifecycle = (
            candidate_extraction_job_lifecycle or _NoCandidateExtractionJobLifecycle()
        )
        self._candidate_profile_lifecycle = (
            candidate_profile_lifecycle or _NoCandidateProfileLifecycle()
        )
        self._candidate_profiling_job_lifecycle = (
            candidate_profiling_job_lifecycle or _NoCandidateProfilingJobLifecycle()
        )
        self._subject_hmac_key = subject_hmac_key
        self._application_keyring = application_keyring
        self._max_processor_deletion_attempts = max_processor_deletion_attempts
        self._processor_retry_base_seconds = processor_retry_base_seconds
        self._telemetry = telemetry or DisabledTelemetry()

    def _fingerprint(self, issuer: str, subject: str) -> tuple[str, str]:
        material = f"{issuer}\x00{subject}".encode()
        if self._application_keyring is not None:
            return (
                self._application_keyring.active_key_id("subject_hmac"),
                self._application_keyring.hmac_digest("subject_hmac", material),
            )
        if self._subject_hmac_key is None:
            raise RuntimeError("subject cryptography is unavailable")
        return (
            "legacy-v1",
            hmac.new(self._subject_hmac_key, material, hashlib.sha256).hexdigest(),
        )

    def _matches_fingerprint(
        self,
        issuer: str,
        subject: str,
        *,
        key_id: str,
        digest: str,
    ) -> bool:
        material = f"{issuer}\x00{subject}".encode()
        if self._application_keyring is not None:
            return self._application_keyring.verify_hmac(
                "subject_hmac",
                key_id=key_id,
                data=material,
                digest=digest,
            )
        generated_key_id, generated_digest = self._fingerprint(issuer, subject)
        return key_id == generated_key_id and hmac.compare_digest(generated_digest, digest)

    async def configure_profile(
        self,
        account_id: UUID,
        profile_input: ProfileInput,
        request_id: str | None,
    ) -> PrivacyProfile:
        async with self._database.transaction() as session:
            return await configure_privacy_profile(
                session,
                registry=self._registry,
                account_id=account_id,
                profile_input=profile_input,
                request_id=request_id,
            )

    async def grant(
        self,
        account_id: UUID,
        consent_notice_id: UUID,
        request_id: str | None,
    ) -> ConsentRecord:
        async with self._database.transaction() as session:
            return await grant_consent(
                session,
                account_id=account_id,
                consent_notice_id=consent_notice_id,
                request_id=request_id,
            )

    async def withdraw(
        self,
        account_id: UUID,
        consent_record_id: UUID,
        request_id: str | None,
    ) -> ConsentRecord:
        async with self._database.transaction() as session:
            return await withdraw_consent(
                session,
                account_id=account_id,
                consent_record_id=consent_record_id,
                request_id=request_id,
            )

    async def list_consents(self, account_id: UUID) -> list[ConsentRecord]:
        async with self._database.transaction() as session:
            await require_privacy_profile(session, account_id)
            return list(
                (
                    await session.scalars(
                        select(ConsentRecord)
                        .where(ConsentRecord.account_id == account_id)
                        .order_by(ConsentRecord.granted_at, ConsentRecord.id)
                    )
                ).all()
            )

    async def authorize(
        self,
        account_id: UUID,
        *,
        data_category: str,
        purpose: str,
    ) -> ProcessingDecision:
        async with self._database.transaction() as session:
            return await authorize_processing(
                session,
                account_id=account_id,
                data_category=data_category,
                purpose=purpose,
            )

    async def register_processor_use(
        self,
        account_id: UUID,
        *,
        processor_activity_id: UUID,
        processor_subject_reference: str,
    ) -> ProcessorUsage:
        async with self._database.transaction() as session:
            usage, _ = await register_processor_usage(
                session,
                account_id=account_id,
                processor_activity_id=processor_activity_id,
                processor_subject_reference=processor_subject_reference,
                application_keyring=self._application_keyring,
            )
            return usage

    async def create_request(
        self,
        account_id: UUID,
        request_type: PrivacyRequestType,
        idempotency_key: str,
        request_id: str | None,
    ) -> PrivacyRequestResult:
        if request_type not in {"access", "export", "deletion"}:
            raise ValueError("unsupported privacy request type")
        normalized_key = idempotency_key.strip()
        if len(normalized_key) < 8 or len(normalized_key) > 128:
            raise ValueError("idempotency key must contain 8-128 characters")
        key_hash = hashlib.sha256(normalized_key.encode()).hexdigest()
        now = datetime.now(UTC)
        async with self._database.transaction() as session:
            account = await session.scalar(
                select(Account).where(Account.id == account_id).with_for_update()
            )
            if account is None or account.status != "active":
                raise PrivacyRequestConflictError("the account cannot create privacy requests")
            profile, policy = await require_privacy_profile(session, account_id, now=now)
            existing = await session.scalar(
                select(PrivacyRequest).where(
                    PrivacyRequest.account_id == account_id,
                    PrivacyRequest.idempotency_key_hash == key_hash,
                )
            )
            if existing is not None:
                if existing.request_type != request_type:
                    raise PrivacyRequestConflictError(
                        "the idempotency key was used for another request type"
                    )
                data = (
                    await self._build_export(session, account_id, now)
                    if request_type in {"access", "export"}
                    else None
                )
                return self._result(existing, data)

            request_retention = await resolve_retention_for_context(
                session,
                privacy_policy_version_id=policy.id,
                jurisdiction_codes=profile.jurisdiction_codes,
                data_category="privacy_request",
                purpose="privacy_administration",
            )
            privacy_request = PrivacyRequest(
                account_id=account_id,
                request_type=request_type,
                status="received",
                privacy_policy_version_id=policy.id,
                jurisdiction_code=policy.jurisdiction_code,
                idempotency_key_hash=key_hash,
                requested_at=now,
                due_at=now + timedelta(days=policy.request_deadline_days),
                retain_until=now + timedelta(days=request_retention.retention_days),
                retention_action=request_retention.action,
            )
            session.add(privacy_request)
            await session.flush()
            await self._audit_request(
                session,
                profile,
                privacy_request,
                account_id,
                request_id,
                "privacy.request.received",
                now,
            )
            privacy_request.status = "verified"
            privacy_request.verified_at = now
            await self._audit_request(
                session,
                profile,
                privacy_request,
                account_id,
                request_id,
                "privacy.request.verified",
                now,
            )
            privacy_request.status = "processing"
            privacy_request.processing_started_at = now
            await self._audit_request(
                session,
                profile,
                privacy_request,
                account_id,
                request_id,
                "privacy.request.processing",
                now,
            )

            if request_type in {"access", "export"}:
                data = await self._build_export(session, account_id, now)
                privacy_request.status = "completed"
                privacy_request.completed_at = now
                await self._audit_request(
                    session,
                    profile,
                    privacy_request,
                    account_id,
                    request_id,
                    "privacy.request.completed",
                    now,
                )
                await session.flush()
                return self._result(privacy_request, data)

            await self._initiate_deletion(
                session,
                account=account,
                profile=profile,
                privacy_request=privacy_request,
                request_id=request_id,
                now=now,
            )
            await session.flush()
            return self._result(privacy_request, None)

    async def get_request(self, account_id: UUID, request_id: UUID) -> PrivacyRequestResult:
        async with self._database.transaction() as session:
            privacy_request = await session.scalar(
                select(PrivacyRequest).where(
                    PrivacyRequest.id == request_id,
                    PrivacyRequest.account_id == account_id,
                )
            )
            if privacy_request is None:
                raise PrivacyRequestNotFoundError("privacy request was not found")
            return self._result(privacy_request, None)

    async def resume_deletion(
        self,
        request_id: UUID,
        correlation_id: str | None = None,
    ) -> PrivacyRequestResult:
        """Resume an internal deletion after durable processor or file acknowledgements."""
        completed_at = datetime.now(UTC)
        async with self._database.transaction() as session:
            privacy_request = await session.scalar(
                select(PrivacyRequest).where(PrivacyRequest.id == request_id).with_for_update()
            )
            if privacy_request is None or privacy_request.request_type != "deletion":
                raise PrivacyRequestNotFoundError("deletion request was not found")
            if privacy_request.status == "completed":
                return self._result(privacy_request, None)
            if privacy_request.status != "processing" or privacy_request.account_id is None:
                raise PrivacyRequestConflictError("deletion request cannot be resumed")
            account_id = privacy_request.account_id
            account = await session.scalar(
                select(Account).where(Account.id == account_id).with_for_update()
            )
            if account is None or account.status != "deletion_pending":
                raise PrivacyRequestConflictError("deletion account is unavailable")
            profile, _ = await require_privacy_profile(session, account_id, now=completed_at)
            processor_pending = await session.scalar(
                select(func.count())
                .select_from(ProcessorDeletionTask)
                .where(
                    ProcessorDeletionTask.privacy_request_id == privacy_request.id,
                    ProcessorDeletionTask.status != "completed",
                )
            )
            file_pending = await self._file_lifecycle.has_pending_account_deletion(
                session,
                privacy_request_id=privacy_request.id,
            )
            if processor_pending or file_pending:
                return self._result(privacy_request, None)
            await self._finalize_deletion(
                session,
                account=account,
                profile=profile,
                privacy_request=privacy_request,
                request_id=correlation_id,
                now=completed_at,
            )
            return self._result(privacy_request, None)

    async def claim_processor_tasks(
        self,
        *,
        worker_id: str,
        limit: int,
        now: datetime | None = None,
    ) -> list[ProcessorDeletionTask]:
        async with self._database.transaction() as session:
            tasks = await claim_processor_deletion_tasks(
                session, worker_id=worker_id, limit=limit, now=now
            )
        if tasks:
            self._telemetry.record_deletion_transition("processor", "processing", len(tasks))
        return tasks

    async def resolve_processor_task_reference(
        self,
        *,
        task_id: UUID,
        worker_id: str,
    ) -> str:
        """Decrypt a claimed vendor locator only at the connector boundary."""
        async with self._database.transaction() as session:
            task = await session.get(ProcessorDeletionTask, task_id)
            if task is None or task.status != "processing" or task.locked_by != worker_id:
                raise PrivacyRequestConflictError("processor deletion task is not claimed")
            return decrypt_processor_task_reference(
                task,
                application_keyring=self._application_keyring,
            )

    async def acknowledge_processor_task(
        self,
        *,
        task_id: UUID,
        worker_id: str,
        request_id: str | None = None,
        now: datetime | None = None,
    ) -> PrivacyRequestResult:
        completed_at = now or datetime.now(UTC)
        async with self._database.transaction() as session:
            task = await session.scalar(
                select(ProcessorDeletionTask)
                .where(ProcessorDeletionTask.id == task_id)
                .with_for_update()
            )
            if task is None:
                raise PrivacyRequestNotFoundError("processor deletion task was not found")
            privacy_request = await session.scalar(
                select(PrivacyRequest)
                .where(PrivacyRequest.id == task.privacy_request_id)
                .with_for_update()
            )
            if privacy_request is None or privacy_request.account_id is None:
                raise PrivacyRequestConflictError("the deletion request cannot be completed")
            profile, _ = await require_privacy_profile(
                session, privacy_request.account_id, now=completed_at
            )
            account_id = privacy_request.account_id
            await complete_processor_deletion_task(
                session, task=task, worker_id=worker_id, now=completed_at
            )
            await record_privacy_audit(
                session,
                profile=profile,
                occurred_at=completed_at,
                actor_id=None,
                action="processor.deletion.acknowledged",
                resource_type="processor_deletion_task",
                resource_id=task.id,
                owner_id=account_id,
                request_id=request_id,
                details={"attempts": task.attempts, "processor_id": str(task.processor_id)},
            )
            incomplete = await session.scalar(
                select(func.count())
                .select_from(ProcessorDeletionTask)
                .where(
                    ProcessorDeletionTask.privacy_request_id == privacy_request.id,
                    ProcessorDeletionTask.status != "completed",
                )
            )
            if incomplete == 0:
                account = await session.get(Account, account_id)
                if account is None:
                    raise PrivacyRequestConflictError("the deletion account is missing")
                await self._finalize_deletion(
                    session,
                    account=account,
                    profile=profile,
                    privacy_request=privacy_request,
                    request_id=request_id,
                    now=completed_at,
                )
            result = self._result(privacy_request, None)
        self._telemetry.record_deletion_transition("processor", "completed")
        return result

    async def reject_processor_task(
        self,
        *,
        task_id: UUID,
        worker_id: str,
        error_code: str,
        request_id: str | None = None,
        now: datetime | None = None,
    ) -> PrivacyRequestResult:
        failed_at = now or datetime.now(UTC)
        async with self._database.transaction() as session:
            task = await session.scalar(
                select(ProcessorDeletionTask)
                .where(ProcessorDeletionTask.id == task_id)
                .with_for_update()
            )
            if task is None or task.account_id is None:
                raise PrivacyRequestNotFoundError("processor deletion task was not found")
            privacy_request = await session.get(PrivacyRequest, task.privacy_request_id)
            if privacy_request is None:
                raise PrivacyRequestConflictError("the deletion request is missing")
            profile, _ = await require_privacy_profile(session, task.account_id, now=failed_at)
            failure = await fail_processor_deletion_task(
                session,
                task=task,
                worker_id=worker_id,
                error_code=error_code,
                max_attempts=self._max_processor_deletion_attempts,
                retry_base_seconds=self._processor_retry_base_seconds,
                now=failed_at,
            )
            privacy_request.attempts += 1
            privacy_request.last_error_code = error_code.strip().lower()
            action = (
                "processor.deletion.escalated" if failure.escalated else "processor.deletion.retry"
            )
            if failure.escalated:
                privacy_request.status = "failed"
            await record_privacy_audit(
                session,
                profile=profile,
                occurred_at=failed_at,
                actor_id=None,
                action=action,
                resource_type="processor_deletion_task",
                resource_id=task.id,
                owner_id=task.account_id,
                request_id=request_id,
                details={"attempts": task.attempts, "error_code": task.last_error_code},
            )
            result = self._result(privacy_request, None)
        self._telemetry.record_deletion_transition(
            "processor", "escalated" if failure.escalated else "retry"
        )
        return result

    async def requeue_escalated_task(
        self,
        *,
        task_id: UUID,
        now: datetime | None = None,
    ) -> None:
        async with self._database.transaction() as session:
            task = await session.scalar(
                select(ProcessorDeletionTask)
                .where(ProcessorDeletionTask.id == task_id)
                .with_for_update()
            )
            if task is None:
                raise PrivacyRequestNotFoundError("processor deletion task was not found")
            request = await session.get(PrivacyRequest, task.privacy_request_id)
            if request is None:
                raise PrivacyRequestConflictError("the deletion request is missing")
            await requeue_escalated_processor_deletion_task(session, task=task, now=now)
            request.status = "processing"
            request.last_error_code = None
        self._telemetry.record_deletion_transition("processor", "retry")

    async def export_deletion_manifest(self) -> list[DeletionManifestEntry]:
        async with self._database.transaction() as session:
            markers = list(
                (
                    await session.scalars(
                        select(BackupDeletionMarker).order_by(
                            BackupDeletionMarker.cutoff_at, BackupDeletionMarker.id
                        )
                    )
                ).all()
            )
            return [self._manifest_entry(marker) for marker in markers]

    async def export_signed_deletion_manifest(
        self,
        *,
        generated_at: datetime | None = None,
    ) -> SignedDeletionManifest:
        if self._application_keyring is None:
            raise PrivacyUnavailableError("signed deletion manifests require a privacy keyring")
        entries = tuple(await self.export_deletion_manifest())
        created_at = generated_at or datetime.now(UTC)
        key_id = self._application_keyring.active_key_id("manifest_hmac")
        payload = self._canonical_manifest_payload(
            schema_version="phase-0c-c.deletion-manifest.v1",
            generated_at=created_at,
            key_id=key_id,
            entries=entries,
        )
        signature = self._application_keyring.hmac_digest("manifest_hmac", payload)
        return SignedDeletionManifest(
            schema_version="phase-0c-c.deletion-manifest.v1",
            generated_at=created_at,
            key_id=key_id,
            entries=entries,
            signature=signature,
        )

    async def apply_signed_deletion_manifest(
        self,
        manifest: SignedDeletionManifest,
        *,
        now: datetime | None = None,
    ) -> RestoreReplayResult:
        if self._application_keyring is None:
            raise PrivacyUnavailableError("signed deletion manifests require a privacy keyring")
        if manifest.schema_version != "phase-0c-c.deletion-manifest.v1":
            raise ValueError("deletion manifest schema is unsupported")
        payload = self._canonical_manifest_payload(
            schema_version=manifest.schema_version,
            generated_at=manifest.generated_at,
            key_id=manifest.key_id,
            entries=manifest.entries,
        )
        if not self._application_keyring.verify_hmac(
            "manifest_hmac",
            key_id=manifest.key_id,
            data=payload,
            digest=manifest.signature,
        ):
            raise ValueError("deletion manifest signature is invalid")
        return await self.apply_deletion_manifest(list(manifest.entries), now=now)

    async def apply_deletion_manifest(
        self,
        entries: list[DeletionManifestEntry],
        *,
        now: datetime | None = None,
    ) -> RestoreReplayResult:
        evaluated_at = now or datetime.now(UTC)
        recorded = 0
        erased = 0
        pending = 0
        async with self._database.transaction() as session:
            for entry in entries:
                if entry.backups_expire_at <= entry.cutoff_at:
                    raise ValueError("manifest backup expiry must follow its cutoff")
                statement = (
                    insert(BackupDeletionMarker)
                    .values(
                        id=entry.marker_id,
                        account_id=entry.account_id,
                        subject_key_id=entry.subject_key_id,
                        subject_fingerprint=entry.subject_fingerprint,
                        privacy_request_id=entry.privacy_request_id,
                        privacy_policy_version_id=entry.privacy_policy_version_id,
                        cutoff_at=entry.cutoff_at,
                        backups_expire_at=entry.backups_expire_at,
                    )
                    .on_conflict_do_nothing(index_elements=[BackupDeletionMarker.id])
                    .returning(BackupDeletionMarker.id)
                )
                if (await session.scalar(statement)) is not None:
                    recorded += 1
                account = await session.get(Account, entry.account_id)
                if (
                    account is not None
                    and account.created_at <= entry.cutoff_at
                    and self._matches_fingerprint(
                        account.issuer,
                        account.subject,
                        key_id=entry.subject_key_id,
                        digest=entry.subject_fingerprint,
                    )
                ):
                    completed = await self._erase_restored_account(
                        session,
                        account,
                        entry=entry,
                        now=evaluated_at,
                    )
                    if completed:
                        erased += 1
                    else:
                        pending += 1
        return RestoreReplayResult(
            markers_recorded=recorded,
            restored_accounts_erased=erased,
            external_deletions_pending=pending,
        )

    async def _initiate_deletion(
        self,
        session: AsyncSession,
        *,
        account: Account,
        profile: PrivacyProfile,
        privacy_request: PrivacyRequest,
        request_id: str | None,
        now: datetime,
    ) -> None:
        marker_retention = await resolve_retention_for_context(
            session,
            privacy_policy_version_id=profile.privacy_policy_version_id,
            jurisdiction_codes=profile.jurisdiction_codes,
            data_category="deletion_tombstone",
            purpose="privacy_administration",
        )
        task_retention = await resolve_retention_for_context(
            session,
            privacy_policy_version_id=profile.privacy_policy_version_id,
            jurisdiction_codes=profile.jurisdiction_codes,
            data_category="processor_deletion_evidence",
            purpose="privacy_administration",
        )
        subject_key_id, subject_fingerprint = self._fingerprint(account.issuer, account.subject)
        marker = BackupDeletionMarker(
            account_id=account.id,
            subject_key_id=subject_key_id,
            subject_fingerprint=subject_fingerprint,
            privacy_request_id=privacy_request.id,
            privacy_policy_version_id=profile.privacy_policy_version_id,
            cutoff_at=now,
            backups_expire_at=now + timedelta(days=marker_retention.retention_days),
        )
        session.add(marker)
        await session.flush()
        await enqueue_outbox(
            session,
            NewOutboxEvent(
                aggregate_type="backup_deletion_marker",
                aggregate_id=marker.id,
                event_type="privacy.backup_deletion.manifested",
                payload={"marker_id": str(marker.id), "cutoff_at": now.isoformat()},
            ),
        )

        usage_rows = (
            await session.execute(
                select(ProcessorUsage, ProcessorActivity)
                .join(
                    ProcessorActivity,
                    ProcessorActivity.id == ProcessorUsage.processor_activity_id,
                )
                .where(ProcessorUsage.account_id == account.id)
                .with_for_update()
            )
        ).all()
        tasks: list[ProcessorDeletionTask] = []
        for usage, activity in usage_rows:
            task = ProcessorDeletionTask(
                privacy_request_id=privacy_request.id,
                processor_id=activity.processor_id,
                processor_usage_id=usage.id,
                account_id=account.id,
                processor_subject_reference=usage.processor_subject_reference,
                processor_subject_ciphertext=usage.processor_subject_ciphertext,
                processor_subject_nonce=usage.processor_subject_nonce,
                processor_subject_key_id=usage.processor_subject_key_id,
                status="pending",
                available_at=now,
                retain_until=now + timedelta(days=task_retention.retention_days),
                retention_action=task_retention.action,
            )
            session.add(task)
            await session.flush()
            await enqueue_outbox(
                session,
                NewOutboxEvent(
                    aggregate_type="processor_deletion_task",
                    aggregate_id=task.id,
                    event_type="privacy.processor_deletion.requested",
                    payload={
                        "task_id": str(task.id),
                        "privacy_request_id": str(privacy_request.id),
                    },
                ),
            )
            tasks.append(task)
            await session.delete(usage)

        file_task_count = await self._file_lifecycle.schedule_account_deletion(
            session,
            account_id=account.id,
            privacy_request_id=privacy_request.id,
            retain_until=now + timedelta(days=task_retention.retention_days),
            retention_action=task_retention.action,
            now=now,
        )
        candidate_intake_count = (
            await self._candidate_document_intake_lifecycle.erase_account_intake_metadata(
                session,
                account_id=account.id,
            )
        )
        candidate_document_count = (
            await self._candidate_document_lifecycle.erase_account_document_metadata(
                session,
                account_id=account.id,
            )
        )
        candidate_record_count = await self._candidate_data_lifecycle.erase_account_metadata(
            session,
            account_id=account.id,
        )

        account.status = "deletion_pending"
        await record_privacy_audit(
            session,
            profile=profile,
            occurred_at=now,
            actor_id=account.id,
            action="privacy.deletion.initiated",
            resource_type="privacy_request",
            resource_id=privacy_request.id,
            owner_id=account.id,
            request_id=request_id,
            details={
                "processor_task_count": len(tasks),
                "file_task_count": file_task_count,
                "candidate_record_count": candidate_record_count,
                "candidate_document_count": candidate_document_count,
                "candidate_intake_count": candidate_intake_count,
            },
        )
        await session.execute(delete(ConsentRecord).where(ConsentRecord.account_id == account.id))
        if not tasks and file_task_count == 0:
            await self._finalize_deletion(
                session,
                account=account,
                profile=profile,
                privacy_request=privacy_request,
                request_id=request_id,
                now=now,
            )

    async def _finalize_deletion(
        self,
        session: AsyncSession,
        *,
        account: Account,
        profile: PrivacyProfile,
        privacy_request: PrivacyRequest,
        request_id: str | None,
        now: datetime,
    ) -> None:
        if await self._file_lifecycle.has_pending_account_deletion(
            session,
            privacy_request_id=privacy_request.id,
        ):
            return
        await record_privacy_audit(
            session,
            profile=profile,
            occurred_at=now,
            actor_id=None,
            action="privacy.deletion.completed",
            resource_type="privacy_request",
            resource_id=privacy_request.id,
            owner_id=account.id,
            request_id=request_id,
            details={"result": "erased_and_anonymized"},
        )
        privacy_request.status = "completed"
        privacy_request.completed_at = now
        privacy_request.account_id = None
        privacy_request.last_error_code = None
        await session.execute(
            update(ProcessorDeletionTask)
            .where(ProcessorDeletionTask.privacy_request_id == privacy_request.id)
            .values(
                account_id=None,
                processor_subject_reference=None,
                processor_subject_ciphertext=None,
                processor_subject_nonce=None,
                processor_subject_key_id=None,
            )
        )
        await session.execute(
            update(OutboxEvent).where(OutboxEvent.owner_id == account.id).values(owner_id=None)
        )
        await enqueue_outbox(
            session,
            NewOutboxEvent(
                aggregate_type="privacy_request",
                aggregate_id=privacy_request.id,
                event_type="privacy.deletion.completed",
                payload={"privacy_request_id": str(privacy_request.id)},
            ),
        )
        await session.delete(account)
        await session.flush()

    async def _erase_restored_account(
        self,
        session: AsyncSession,
        account: Account,
        *,
        entry: DeletionManifestEntry,
        now: datetime,
    ) -> bool:
        await session.execute(
            update(ProcessorDeletionTask)
            .where(ProcessorDeletionTask.account_id == account.id)
            .values(
                account_id=None,
                processor_subject_reference=None,
                processor_subject_ciphertext=None,
                processor_subject_nonce=None,
                processor_subject_key_id=None,
                status="completed",
                completed_at=now,
                locked_at=None,
                locked_by=None,
                last_error_code=None,
            )
        )
        await session.execute(
            update(OutboxEvent).where(OutboxEvent.owner_id == account.id).values(owner_id=None)
        )
        file_task_count = await self._file_lifecycle.schedule_account_deletion(
            session,
            account_id=account.id,
            privacy_request_id=entry.privacy_request_id,
            retain_until=entry.backups_expire_at,
            retention_action="delete",
            now=now,
        )
        await self._candidate_document_intake_lifecycle.erase_account_intake_metadata(
            session,
            account_id=account.id,
        )
        await self._candidate_document_lifecycle.erase_account_document_metadata(
            session,
            account_id=account.id,
        )
        await self._candidate_data_lifecycle.erase_account_metadata(
            session,
            account_id=account.id,
        )
        if file_task_count:
            account.status = "deletion_pending"
            await session.flush()
            return False
        await session.delete(account)
        await session.flush()
        return True

    async def _audit_request(
        self,
        session: AsyncSession,
        profile: PrivacyProfile,
        privacy_request: PrivacyRequest,
        account_id: UUID,
        request_id: str | None,
        action: str,
        now: datetime,
    ) -> None:
        await record_privacy_audit(
            session,
            profile=profile,
            occurred_at=now,
            actor_id=account_id,
            action=action,
            resource_type="privacy_request",
            resource_id=privacy_request.id,
            owner_id=account_id,
            request_id=request_id,
            details={"request_type": privacy_request.request_type},
        )

    async def _build_export(
        self, session: AsyncSession, account_id: UUID, generated_at: datetime
    ) -> dict[str, Any]:
        account = await session.get(Account, account_id)
        profile = await session.get(PrivacyProfile, account_id)
        if account is None or profile is None:
            raise PrivacyRequestConflictError("the account export is unavailable")
        consent_rows = (
            await session.execute(
                select(ConsentRecord, ConsentNotice)
                .join(ConsentNotice, ConsentNotice.id == ConsentRecord.consent_notice_id)
                .where(ConsentRecord.account_id == account_id)
                .order_by(ConsentRecord.granted_at, ConsentRecord.id)
            )
        ).all()
        requests = list(
            (
                await session.scalars(
                    select(PrivacyRequest)
                    .where(PrivacyRequest.account_id == account_id)
                    .order_by(PrivacyRequest.requested_at, PrivacyRequest.id)
                )
            ).all()
        )
        processor_rows = (
            await session.execute(
                select(ProcessorUsage, ProcessorActivity, Processor)
                .join(
                    ProcessorActivity,
                    ProcessorActivity.id == ProcessorUsage.processor_activity_id,
                )
                .join(Processor, Processor.id == ProcessorActivity.processor_id)
                .where(ProcessorUsage.account_id == account_id)
                .order_by(ProcessorUsage.registered_at, ProcessorUsage.id)
            )
        ).all()
        audits = list(
            (
                await session.scalars(
                    select(AuditEvent)
                    .where(AuditEvent.owner_id == account_id)
                    .order_by(AuditEvent.occurred_at, AuditEvent.id)
                )
            ).all()
        )
        stored_files = await self._file_lifecycle.export_account_metadata(
            session,
            account_id=account_id,
        )
        candidate_preparations = await self._candidate_data_lifecycle.export_account_metadata(
            session,
            account_id=account_id,
        )
        candidate_documents = (
            await self._candidate_document_lifecycle.export_account_document_metadata(
                session,
                account_id=account_id,
            )
        )
        candidate_document_intakes = (
            await self._candidate_document_intake_lifecycle.export_account_intake_metadata(
                session,
                account_id=account_id,
            )
        )
        candidate_source_texts = (
            await self._candidate_source_text_lifecycle.export_account_source_text_metadata(
                session,
                account_id=account_id,
            )
        )
        candidate_extraction_jobs = (
            await self._candidate_extraction_job_lifecycle.export_account_job_metadata(
                session,
                account_id=account_id,
            )
        )
        candidate_profiles = (
            await self._candidate_profile_lifecycle.export_account_profile_metadata(
                session,
                account_id=account_id,
            )
        )
        candidate_profiling_jobs = (
            await self._candidate_profiling_job_lifecycle.export_account_profiling_job_metadata(
                session,
                account_id=account_id,
            )
        )
        return {
            "schema_version": "phase-1b-c2",
            "generated_at": generated_at.isoformat(),
            "account": {
                "account_id": str(account.id),
                "identity_issuer": account.issuer,
                "identity_subject": account.subject,
                "status": account.status,
                "created_at": account.created_at.isoformat(),
            },
            "privacy_profile": {
                "residence_country_code": profile.residence_country_code,
                "residence_subdivision_code": profile.residence_subdivision_code,
                "jurisdiction_codes": profile.jurisdiction_codes,
                "jurisdiction_versions": profile.jurisdiction_versions,
                "storage_region": profile.storage_region,
                "adult_attested_at": profile.adult_attested_at.isoformat(),
                "privacy_policy_version_id": str(profile.privacy_policy_version_id),
            },
            "consents": [
                {
                    "record_id": str(record.id),
                    "notice_key": notice.notice_key,
                    "notice_version": notice.notice_version,
                    "purpose": notice.purpose,
                    "data_category": notice.data_category,
                    "document_uri": notice.document_uri,
                    "content_sha256": notice.content_sha256,
                    "granted_at": record.granted_at.isoformat(),
                    "withdrawn_at": (
                        record.withdrawn_at.isoformat() if record.withdrawn_at else None
                    ),
                }
                for record, notice in consent_rows
            ],
            "privacy_requests": [
                {
                    "request_id": str(item.id),
                    "request_type": item.request_type,
                    "status": item.status,
                    "requested_at": item.requested_at.isoformat(),
                    "due_at": item.due_at.isoformat(),
                    "completed_at": item.completed_at.isoformat() if item.completed_at else None,
                }
                for item in requests
            ],
            "processor_disclosures": [
                {
                    "processor_key": processor.processor_key,
                    "processor_name": processor.legal_name,
                    "data_category": activity.data_category,
                    "purpose": activity.purpose,
                    "processing_region": activity.processing_region,
                    "storage_region": activity.storage_region,
                    "cross_border": activity.cross_border,
                    "transfer_mechanism": activity.transfer_mechanism,
                    "registered_at": usage.registered_at.isoformat(),
                }
                for usage, activity, processor in processor_rows
            ],
            "stored_files": stored_files,
            "candidate_preparations": candidate_preparations,
            "candidate_documents": candidate_documents,
            "candidate_document_intakes": candidate_document_intakes,
            "candidate_source_texts": candidate_source_texts,
            "candidate_extraction_jobs": candidate_extraction_jobs,
            "candidate_profiles": candidate_profiles,
            "candidate_profiling_jobs": candidate_profiling_jobs,
            "audit_evidence": [
                {
                    "action": event.action,
                    "resource_type": event.resource_type,
                    "occurred_at": event.occurred_at.isoformat(),
                    "details": event.details,
                }
                for event in audits
            ],
        }

    @staticmethod
    def _result(request: PrivacyRequest, data: dict[str, Any] | None) -> PrivacyRequestResult:
        return PrivacyRequestResult(
            request_id=request.id,
            request_type=request.request_type,
            status=request.status,
            requested_at=request.requested_at,
            due_at=request.due_at,
            completed_at=request.completed_at,
            data=data,
        )

    @staticmethod
    def _manifest_entry(marker: BackupDeletionMarker) -> DeletionManifestEntry:
        return DeletionManifestEntry(
            marker_id=marker.id,
            account_id=marker.account_id,
            subject_key_id=marker.subject_key_id,
            subject_fingerprint=marker.subject_fingerprint,
            privacy_request_id=marker.privacy_request_id,
            privacy_policy_version_id=marker.privacy_policy_version_id,
            cutoff_at=marker.cutoff_at,
            backups_expire_at=marker.backups_expire_at,
        )

    @staticmethod
    def _canonical_manifest_payload(
        *,
        schema_version: str,
        generated_at: datetime,
        key_id: str,
        entries: tuple[DeletionManifestEntry, ...],
    ) -> bytes:
        document = {
            "schema_version": schema_version,
            "generated_at": generated_at.astimezone(UTC).isoformat(),
            "key_id": key_id,
            "entries": [
                {
                    "marker_id": str(entry.marker_id),
                    "account_id": str(entry.account_id),
                    "subject_key_id": entry.subject_key_id,
                    "subject_fingerprint": entry.subject_fingerprint,
                    "privacy_request_id": str(entry.privacy_request_id),
                    "privacy_policy_version_id": str(entry.privacy_policy_version_id),
                    "cutoff_at": entry.cutoff_at.astimezone(UTC).isoformat(),
                    "backups_expire_at": entry.backups_expire_at.astimezone(UTC).isoformat(),
                }
                for entry in entries
            ],
        }
        return json.dumps(
            document,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
        ).encode()


def build_privacy_service(
    settings: Settings,
    database: DatabaseRuntime,
    registry: JurisdictionPolicyRegistry,
    file_lifecycle: FileLifecycleAdapter | None = None,
    candidate_data_lifecycle: CandidateDataLifecycleAdapter | None = None,
    candidate_document_lifecycle: CandidateDocumentLifecycleAdapter | None = None,
    candidate_document_intake_lifecycle: CandidateDocumentIntakeLifecycleAdapter | None = None,
    candidate_source_text_lifecycle: CandidateSourceTextLifecycleAdapter | None = None,
    candidate_extraction_job_lifecycle: CandidateExtractionJobLifecycleAdapter | None = None,
    candidate_profile_lifecycle: CandidateProfileLifecycleAdapter | None = None,
    candidate_profiling_job_lifecycle: CandidateProfilingJobLifecycleAdapter | None = None,
    telemetry: TelemetryRuntime | None = None,
) -> PrivacyRuntime:
    if not settings.privacy_enabled:
        return FailClosedPrivacyService()
    legacy_key = settings.privacy_subject_hmac_key
    application_keyring = (
        ApplicationKeyring.from_secret(settings.privacy_keyring)
        if settings.privacy_keyring is not None
        else None
    )
    if legacy_key is None and application_keyring is None:
        raise RuntimeError("privacy lifecycle enabled without subject cryptography")
    return PrivacyLifecycleService(
        database=database,
        registry=registry,
        subject_hmac_key=(
            legacy_key.get_secret_value().encode() if legacy_key is not None else None
        ),
        application_keyring=application_keyring,
        file_lifecycle=file_lifecycle,
        candidate_data_lifecycle=candidate_data_lifecycle,
        candidate_document_lifecycle=candidate_document_lifecycle,
        candidate_document_intake_lifecycle=candidate_document_intake_lifecycle,
        candidate_source_text_lifecycle=candidate_source_text_lifecycle,
        candidate_extraction_job_lifecycle=candidate_extraction_job_lifecycle,
        candidate_profile_lifecycle=candidate_profile_lifecycle,
        candidate_profiling_job_lifecycle=candidate_profiling_job_lifecycle,
        max_processor_deletion_attempts=settings.privacy_max_processor_deletion_attempts,
        processor_retry_base_seconds=settings.privacy_processor_retry_base_seconds,
        telemetry=telemetry,
    )
