"""Durable, owner-bound extraction scheduling and lease transitions."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import NoReturn, Protocol
from uuid import UUID

from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from uuid6 import uuid7

from ai_interviewer.candidate_inputs.document_models import (
    CandidateDocument,
    CandidateDocumentVersion,
)
from ai_interviewer.candidate_inputs.extraction_models import (
    EXTRACTION_LEASE_SECONDS,
    MAX_EXTRACTION_ATTEMPTS,
    RETRYABLE_EXTRACTION_FAILURES,
    CandidateExtractionJob,
    ExtractionFailureCode,
)
from ai_interviewer.candidate_inputs.models import CandidatePreparation
from ai_interviewer.candidate_inputs.source_text_models import CandidateSourceText
from ai_interviewer.core.config import Settings
from ai_interviewer.core.crypto import ApplicationKeyring
from ai_interviewer.file_security.models import FileAsset, ParserReleasePolicy
from ai_interviewer.identity.models import Account
from ai_interviewer.persistence.database import DatabaseRuntime
from ai_interviewer.persistence.repositories import NewOutboxEvent, enqueue_outbox
from ai_interviewer.privacy.audit import record_privacy_audit
from ai_interviewer.privacy.models import PrivacyProfile
from ai_interviewer.privacy.rules import authorize_processing, require_privacy_profile

DATA_CATEGORY = "candidate_document"
PROCESSING_PURPOSE = "interview_preparation"
_FAILURE_CODES = frozenset(
    {
        "input_unsupported",
        "input_corrupt",
        "input_encrypted",
        "input_empty",
        "parser_timeout",
        "resource_exceeded",
        "parser_crashed",
        "source_unavailable",
        "policy_unavailable",
        "internal_failure",
        "lease_expired",
    }
)


class CandidateExtractionJobUnavailableError(RuntimeError):
    """The extraction job boundary is disabled."""


class CandidateExtractionJobNotFoundError(LookupError):
    """An owner-scoped extraction job was not found."""


class CandidateExtractionJobConflictError(RuntimeError):
    """A job transition or immutable snapshot check failed."""


@dataclass(frozen=True, slots=True)
class CandidateExtractionJobRecord:
    job_id: UUID
    owner_id: UUID
    document_version_id: UUID
    file_asset_id: UUID
    parser_release_policy_id: UUID
    privacy_policy_version_id: UUID
    retention_rule_id: UUID
    jurisdiction_code: str
    legal_basis: str
    retain_until: datetime
    retention_action: str
    media_type: str
    content_length: int
    content_sha256: str
    parser_adapter: str
    parser_version: str
    isolation_profile: str
    status: str
    attempts: int
    available_at: datetime
    locked_at: datetime | None
    locked_by: str | None
    lease_token: UUID | None
    error_code: str | None
    source_text_id: UUID | None
    completed_at: datetime | None
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True, slots=True)
class ScheduleExtractionResult:
    job: CandidateExtractionJobRecord
    created: bool


class CandidateExtractionJobRuntime(Protocol):
    async def schedule_extraction(
        self,
        account_id: UUID,
        document_version_id: UUID,
        request_id: str | None,
        *,
        now: datetime | None = None,
    ) -> ScheduleExtractionResult: ...

    async def claim_jobs(
        self,
        worker_id: str,
        limit: int,
        *,
        now: datetime | None = None,
    ) -> tuple[CandidateExtractionJobRecord, ...]: ...

    async def mark_succeeded(
        self,
        job_id: UUID,
        worker_id: str,
        lease_token: UUID,
        source_text_id: UUID,
        *,
        now: datetime | None = None,
    ) -> CandidateExtractionJobRecord: ...

    async def mark_failed(
        self,
        job_id: UUID,
        worker_id: str,
        lease_token: UUID,
        error_code: ExtractionFailureCode,
        *,
        now: datetime | None = None,
    ) -> CandidateExtractionJobRecord: ...

    async def export_account_job_metadata(
        self,
        session: AsyncSession,
        *,
        account_id: UUID,
    ) -> list[dict[str, object]]: ...


class FailClosedCandidateExtractionJobService:
    """Reject extraction work until all upstream security boundaries are configured."""

    @staticmethod
    def _unavailable() -> NoReturn:
        raise CandidateExtractionJobUnavailableError("extraction jobs are not configured")

    async def schedule_extraction(
        self,
        account_id: UUID,
        document_version_id: UUID,
        request_id: str | None,
        *,
        now: datetime | None = None,
    ) -> ScheduleExtractionResult:
        del account_id, document_version_id, request_id, now
        self._unavailable()

    async def claim_jobs(
        self,
        worker_id: str,
        limit: int,
        *,
        now: datetime | None = None,
    ) -> tuple[CandidateExtractionJobRecord, ...]:
        del worker_id, limit, now
        self._unavailable()

    async def mark_succeeded(
        self,
        job_id: UUID,
        worker_id: str,
        lease_token: UUID,
        source_text_id: UUID,
        *,
        now: datetime | None = None,
    ) -> CandidateExtractionJobRecord:
        del job_id, worker_id, lease_token, source_text_id, now
        self._unavailable()

    async def mark_failed(
        self,
        job_id: UUID,
        worker_id: str,
        lease_token: UUID,
        error_code: ExtractionFailureCode,
        *,
        now: datetime | None = None,
    ) -> CandidateExtractionJobRecord:
        del job_id, worker_id, lease_token, error_code, now
        self._unavailable()

    async def export_account_job_metadata(
        self,
        session: AsyncSession,
        *,
        account_id: UUID,
    ) -> list[dict[str, object]]:
        del session, account_id
        return []


class CandidateExtractionJobService:
    """Persist and transition one extraction job per exact document version."""

    def __init__(self, database: DatabaseRuntime) -> None:
        self._database = database

    async def schedule_extraction(
        self,
        account_id: UUID,
        document_version_id: UUID,
        request_id: str | None,
        *,
        now: datetime | None = None,
    ) -> ScheduleExtractionResult:
        scheduled_at = now or datetime.now(UTC)
        async with self._database.transaction() as session:
            account = await session.scalar(
                select(Account).where(Account.id == account_id).with_for_update()
            )
            if account is None or account.status != "active":
                raise CandidateExtractionJobConflictError("the account cannot process documents")

            document_version = await session.scalar(
                select(CandidateDocumentVersion)
                .where(
                    CandidateDocumentVersion.id == document_version_id,
                    CandidateDocumentVersion.owner_id == account_id,
                )
                .with_for_update()
            )
            if document_version is None:
                raise CandidateExtractionJobNotFoundError(
                    "candidate document version was not found"
                )
            document = await session.scalar(
                select(CandidateDocument)
                .where(
                    CandidateDocument.id == document_version.document_id,
                    CandidateDocument.owner_id == account_id,
                )
                .with_for_update()
            )
            if document is None:
                raise CandidateExtractionJobNotFoundError(
                    "candidate document version was not found"
                )
            preparation = await session.scalar(
                select(CandidatePreparation)
                .where(
                    CandidatePreparation.id == document.preparation_id,
                    CandidatePreparation.owner_id == account_id,
                )
                .with_for_update()
            )
            if preparation is None:
                raise CandidateExtractionJobNotFoundError(
                    "candidate document version was not found"
                )
            asset = await session.scalar(
                select(FileAsset)
                .where(
                    FileAsset.id == document_version.file_asset_id,
                    FileAsset.account_id == account_id,
                )
                .with_for_update()
            )
            policy = await session.scalar(
                select(ParserReleasePolicy)
                .where(ParserReleasePolicy.id == document_version.parser_release_policy_id)
                .with_for_update()
            )
            if asset is None or policy is None:
                raise CandidateExtractionJobConflictError("the exact parser input is unavailable")
            self._require_processable_snapshot(
                preparation,
                document,
                document_version,
                asset,
                policy,
                scheduled_at,
            )
            decision = await authorize_processing(
                session,
                account_id=account_id,
                data_category=DATA_CATEGORY,
                purpose=PROCESSING_PURPOSE,
                now=scheduled_at,
            )
            if (
                decision.retention_action != "delete"
                or decision.privacy_policy_version_id != document_version.privacy_policy_version_id
                or decision.jurisdiction_code != document_version.jurisdiction_code
                or decision.legal_basis != document_version.legal_basis
                or decision.retention_rule_id != document_version.retention_rule_id
            ):
                raise CandidateExtractionJobConflictError(
                    "the document no longer matches the active privacy decision"
                )

            existing = await session.scalar(
                select(CandidateExtractionJob)
                .where(CandidateExtractionJob.document_version_id == document_version.id)
                .with_for_update()
            )
            if existing is not None:
                if existing.owner_id != account_id:
                    raise CandidateExtractionJobNotFoundError("extraction job was not found")
                return ScheduleExtractionResult(job=self._record(existing), created=False)

            job = CandidateExtractionJob(
                id=uuid7(),
                owner_id=account_id,
                document_version_id=document_version.id,
                file_asset_id=document_version.file_asset_id,
                parser_release_policy_id=document_version.parser_release_policy_id,
                privacy_policy_version_id=document_version.privacy_policy_version_id,
                retention_rule_id=document_version.retention_rule_id,
                jurisdiction_code=document_version.jurisdiction_code,
                legal_basis=document_version.legal_basis,
                retain_until=document_version.retain_until,
                retention_action="delete",
                media_type=document_version.media_type,
                content_length=document_version.content_length,
                content_sha256=document_version.content_sha256,
                parser_adapter=policy.parser_adapter,
                parser_version=policy.parser_version,
                isolation_profile=policy.isolation_profile,
                status="pending",
                attempts=0,
                available_at=scheduled_at,
                created_at=scheduled_at,
                updated_at=scheduled_at,
            )
            session.add(job)
            await session.flush()
            profile, _ = await require_privacy_profile(session, account_id, now=scheduled_at)
            await self._record_transition(
                session,
                job,
                profile=profile,
                request_id=request_id,
                occurred_at=scheduled_at,
                action="candidate_extraction_job.scheduled",
                event_type="candidate_extraction_job.scheduled",
            )
            await session.flush()
            return ScheduleExtractionResult(job=self._record(job), created=True)

    async def claim_jobs(
        self,
        worker_id: str,
        limit: int,
        *,
        now: datetime | None = None,
    ) -> tuple[CandidateExtractionJobRecord, ...]:
        self._validate_worker(worker_id)
        if limit < 1 or limit > 100:
            raise ValueError("limit must be between 1 and 100")
        claimed_at = now or datetime.now(UTC)
        stale_before = claimed_at - timedelta(seconds=EXTRACTION_LEASE_SECONDS)
        async with self._database.transaction() as session:
            exhausted_leases = list(
                (
                    await session.scalars(
                        select(CandidateExtractionJob)
                        .where(
                            CandidateExtractionJob.status == "processing",
                            CandidateExtractionJob.locked_at < stale_before,
                            CandidateExtractionJob.attempts >= MAX_EXTRACTION_ATTEMPTS,
                        )
                        .with_for_update(skip_locked=True)
                    )
                ).all()
            )
            for job in exhausted_leases:
                job.status = "failed"
                job.error_code = "lease_expired"
                job.completed_at = claimed_at
                job.locked_at = None
                job.locked_by = None
                job.lease_token = None
                job.updated_at = claimed_at
                await self._record_transition(
                    session,
                    job,
                    profile=await session.get(PrivacyProfile, job.owner_id),
                    request_id=None,
                    occurred_at=claimed_at,
                    action="candidate_extraction_job.failed",
                    event_type="candidate_extraction_job.failed",
                )
            jobs = list(
                (
                    await session.scalars(
                        select(CandidateExtractionJob)
                        .where(
                            or_(
                                CandidateExtractionJob.status.in_(("pending", "retry")),
                                and_(
                                    CandidateExtractionJob.status == "processing",
                                    CandidateExtractionJob.locked_at < stale_before,
                                ),
                            ),
                            CandidateExtractionJob.available_at <= claimed_at,
                            CandidateExtractionJob.attempts < MAX_EXTRACTION_ATTEMPTS,
                        )
                        .order_by(CandidateExtractionJob.available_at, CandidateExtractionJob.id)
                        .limit(limit)
                        .with_for_update(skip_locked=True)
                    )
                ).all()
            )
            for job in jobs:
                job.status = "processing"
                job.attempts += 1
                job.locked_at = claimed_at
                job.locked_by = worker_id
                job.lease_token = uuid7()
                job.error_code = None
                job.updated_at = claimed_at
            await session.flush()
            # PostgreSQL may expire server-managed fields after the state update. Refresh
            # before synchronously building the dataclass so an async lazy-load is never
            # attempted while serializing the claim result.
            for job in jobs:
                await session.refresh(job)
            return tuple(self._record(job) for job in jobs)

    async def mark_succeeded(
        self,
        job_id: UUID,
        worker_id: str,
        lease_token: UUID,
        source_text_id: UUID,
        *,
        now: datetime | None = None,
    ) -> CandidateExtractionJobRecord:
        completed_at = now or datetime.now(UTC)
        self._validate_worker(worker_id)
        async with self._database.transaction() as session:
            job = await self._locked_job(session, job_id)
            self._require_claim(job, worker_id, lease_token)
            source_text = await session.scalar(
                select(CandidateSourceText).where(
                    CandidateSourceText.id == source_text_id,
                    CandidateSourceText.owner_id == job.owner_id,
                    CandidateSourceText.document_version_id == job.document_version_id,
                )
            )
            if source_text is None:
                raise CandidateExtractionJobConflictError(
                    "successful extraction requires the matching source text"
                )
            job.status = "succeeded"
            job.source_text_id = source_text.id
            job.completed_at = completed_at
            job.locked_at = None
            job.locked_by = None
            job.lease_token = None
            job.error_code = None
            job.updated_at = completed_at
            await session.flush()
            await self._record_transition(
                session,
                job,
                profile=await session.get(PrivacyProfile, job.owner_id),
                request_id=None,
                occurred_at=completed_at,
                action="candidate_extraction_job.succeeded",
                event_type="candidate_extraction_job.succeeded",
            )
            await session.flush()
            return self._record(job)

    async def mark_failed(
        self,
        job_id: UUID,
        worker_id: str,
        lease_token: UUID,
        error_code: ExtractionFailureCode,
        *,
        now: datetime | None = None,
    ) -> CandidateExtractionJobRecord:
        failed_at = now or datetime.now(UTC)
        self._validate_worker(worker_id)
        if error_code not in _FAILURE_CODES:
            raise ValueError("error_code is not supported")
        async with self._database.transaction() as session:
            job = await self._locked_job(session, job_id)
            self._require_claim(job, worker_id, lease_token)
            retry = error_code in RETRYABLE_EXTRACTION_FAILURES and (
                job.attempts < MAX_EXTRACTION_ATTEMPTS
            )
            job.status = "retry" if retry else "failed"
            job.error_code = error_code
            job.available_at = failed_at + self._retry_delay(job.attempts) if retry else failed_at
            job.completed_at = None if retry else failed_at
            job.locked_at = None
            job.locked_by = None
            job.lease_token = None
            job.updated_at = failed_at
            await session.flush()
            await self._record_transition(
                session,
                job,
                profile=await session.get(PrivacyProfile, job.owner_id),
                request_id=None,
                occurred_at=failed_at,
                action=(
                    "candidate_extraction_job.retry_scheduled"
                    if retry
                    else "candidate_extraction_job.failed"
                ),
                event_type=(
                    "candidate_extraction_job.retry_scheduled"
                    if retry
                    else "candidate_extraction_job.failed"
                ),
            )
            await session.flush()
            return self._record(job)

    async def export_account_job_metadata(
        self,
        session: AsyncSession,
        *,
        account_id: UUID,
    ) -> list[dict[str, object]]:
        jobs = list(
            (
                await session.scalars(
                    select(CandidateExtractionJob)
                    .where(CandidateExtractionJob.owner_id == account_id)
                    .order_by(CandidateExtractionJob.created_at, CandidateExtractionJob.id)
                )
            ).all()
        )
        return [self._export_job_record(job) for job in jobs]

    @staticmethod
    def _export_job_record(job: CandidateExtractionJob) -> dict[str, object]:
        return {
            "job_id": str(job.id),
            "document_version_id": str(job.document_version_id),
            "status": job.status,
            "attempts": job.attempts,
            "parser_adapter": job.parser_adapter,
            "parser_version": job.parser_version,
            "isolation_profile": job.isolation_profile,
            "error_code": job.error_code,
            "source_text_id": str(job.source_text_id) if job.source_text_id else None,
            "created_at": job.created_at.isoformat(),
            "updated_at": job.updated_at.isoformat(),
            "completed_at": job.completed_at.isoformat() if job.completed_at else None,
        }

    @staticmethod
    def _validate_worker(worker_id: str) -> None:
        if not worker_id or worker_id != worker_id.strip() or len(worker_id) > 128:
            raise ValueError("worker_id must contain 1-128 non-whitespace characters")

    @staticmethod
    def _retry_delay(attempts: int) -> timedelta:
        return timedelta(seconds=min(60 * (2 ** max(attempts - 1, 0)), 3_600))

    @staticmethod
    async def _locked_job(session: AsyncSession, job_id: UUID) -> CandidateExtractionJob:
        job = await session.scalar(
            select(CandidateExtractionJob)
            .where(CandidateExtractionJob.id == job_id)
            .with_for_update()
        )
        if job is None:
            raise CandidateExtractionJobNotFoundError("extraction job was not found")
        return job

    @staticmethod
    def _require_claim(
        job: CandidateExtractionJob,
        worker_id: str,
        lease_token: UUID,
    ) -> None:
        if (
            job.status != "processing"
            or job.locked_by != worker_id
            or job.lease_token != lease_token
        ):
            raise CandidateExtractionJobConflictError(
                "extraction job is not claimed by this worker lease"
            )

    @staticmethod
    def _require_processable_snapshot(
        preparation: CandidatePreparation,
        document: CandidateDocument,
        document_version: CandidateDocumentVersion,
        asset: FileAsset,
        policy: ParserReleasePolicy,
        evaluated_at: datetime,
    ) -> None:
        if preparation.status != "draft":
            raise CandidateExtractionJobConflictError("archived documents cannot be processed")
        if (
            preparation.retain_until <= evaluated_at
            or preparation.retention_action != "delete"
            or preparation.privacy_policy_version_id != document_version.privacy_policy_version_id
            or preparation.jurisdiction_code != document_version.jurisdiction_code
        ):
            raise CandidateExtractionJobConflictError(
                "the preparation privacy snapshot is no longer processable"
            )
        if document.latest_version_number != document_version.version_number:
            raise CandidateExtractionJobConflictError(
                "only the latest document version can be processed"
            )
        if document_version.retain_until <= evaluated_at:
            raise CandidateExtractionJobConflictError("the document retention deadline has passed")
        if (
            asset.status != "released"
            or asset.released_object_key is None
            or asset.released_version_id is None
            or asset.released_at is None
            or asset.released_at > evaluated_at
            or asset.parser_release_policy_id != document_version.parser_release_policy_id
            or asset.privacy_policy_version_id != document_version.privacy_policy_version_id
            or asset.jurisdiction_code != document_version.jurisdiction_code
            or asset.data_category != DATA_CATEGORY
            or asset.purpose != PROCESSING_PURPOSE
            or asset.content_sha256 != document_version.content_sha256
            or asset.content_length != document_version.content_length
            or asset.media_type != document_version.media_type
            or asset.retain_until != document_version.retain_until
            or asset.retention_action != "delete"
        ):
            raise CandidateExtractionJobConflictError("the exact released asset is unavailable")
        if (
            policy.status != "active"
            or policy.approved_at > evaluated_at
            or policy.id != document_version.parser_release_policy_id
            or policy.privacy_policy_version_id != document_version.privacy_policy_version_id
            or policy.data_category != DATA_CATEGORY
            or policy.purpose != PROCESSING_PURPOSE
            or policy.media_type != document_version.media_type
            or policy.maximum_bytes < document_version.content_length
            or not policy.malware_scan_required
        ):
            raise CandidateExtractionJobConflictError("the exact parser release is not active")

    @staticmethod
    def _record(job: CandidateExtractionJob) -> CandidateExtractionJobRecord:
        return CandidateExtractionJobRecord(
            job_id=job.id,
            owner_id=job.owner_id,
            document_version_id=job.document_version_id,
            file_asset_id=job.file_asset_id,
            parser_release_policy_id=job.parser_release_policy_id,
            privacy_policy_version_id=job.privacy_policy_version_id,
            retention_rule_id=job.retention_rule_id,
            jurisdiction_code=job.jurisdiction_code,
            legal_basis=job.legal_basis,
            retain_until=job.retain_until,
            retention_action=job.retention_action,
            media_type=job.media_type,
            content_length=job.content_length,
            content_sha256=job.content_sha256,
            parser_adapter=job.parser_adapter,
            parser_version=job.parser_version,
            isolation_profile=job.isolation_profile,
            status=job.status,
            attempts=job.attempts,
            available_at=job.available_at,
            locked_at=job.locked_at,
            locked_by=job.locked_by,
            lease_token=job.lease_token,
            error_code=job.error_code,
            source_text_id=job.source_text_id,
            completed_at=job.completed_at,
            created_at=job.created_at,
            updated_at=job.updated_at,
        )

    @staticmethod
    async def _record_transition(
        session: AsyncSession,
        job: CandidateExtractionJob,
        *,
        profile: PrivacyProfile | None,
        request_id: str | None,
        occurred_at: datetime,
        action: str,
        event_type: str,
    ) -> None:
        details = {
            "status": job.status,
            "attempts": job.attempts,
            "parser_adapter": job.parser_adapter,
            "parser_version": job.parser_version,
            "isolation_profile": job.isolation_profile,
            "error_code": job.error_code,
        }
        if profile is not None:
            await record_privacy_audit(
                session,
                profile=profile,
                occurred_at=occurred_at,
                actor_id=None,
                action=action,
                resource_type="candidate_extraction_job",
                resource_id=job.id,
                owner_id=job.owner_id,
                request_id=request_id,
                details=details,
            )
        await enqueue_outbox(
            session,
            NewOutboxEvent(
                aggregate_type="candidate_extraction_job",
                aggregate_id=job.id,
                event_type=event_type,
                owner_id=job.owner_id,
                payload={
                    "candidate_extraction_job_id": str(job.id),
                    "candidate_document_version_id": str(job.document_version_id),
                    **details,
                },
            ),
        )


def build_candidate_extraction_jobs(
    settings: Settings,
    database: DatabaseRuntime,
) -> CandidateExtractionJobRuntime:
    if (
        not settings.privacy_enabled
        or not settings.file_security_enabled
        or settings.privacy_keyring is None
    ):
        return FailClosedCandidateExtractionJobService()
    # Validate the mounted keyring at construction time even though D2.1 stores no plaintext.
    ApplicationKeyring.from_secret(settings.privacy_keyring)
    return CandidateExtractionJobService(database)
