"""Durable scheduling and fenced transitions for exact-source profiling work."""

from __future__ import annotations

import re
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
from ai_interviewer.candidate_inputs.models import CandidatePreparation
from ai_interviewer.candidate_inputs.source_text_models import (
    CandidateSourceText,
    CandidateSourceTextVersion,
)
from ai_interviewer.core.config import Settings
from ai_interviewer.core.crypto import ApplicationKeyring
from ai_interviewer.identity.models import Account
from ai_interviewer.model_gateway import ModelReleaseIdentity, PromptReleaseIdentity
from ai_interviewer.persistence.database import DatabaseRuntime
from ai_interviewer.persistence.repositories import NewOutboxEvent, enqueue_outbox
from ai_interviewer.privacy.audit import record_privacy_audit
from ai_interviewer.privacy.models import PrivacyProfile, Processor, ProcessorActivity
from ai_interviewer.privacy.rules import authorize_processing, require_privacy_profile
from ai_interviewer.profiling.contracts import (
    CV_PROFILE_SCHEMA_ID,
    JOB_DESCRIPTION_PROFILE_SCHEMA_ID,
    PROFILE_SCHEMA_VERSION,
)
from ai_interviewer.profiling.job_models import (
    MAX_PROFILING_ATTEMPTS,
    PROFILING_LEASE_SECONDS,
    RETRYABLE_PROFILING_FAILURES,
    CandidateProfilingJob,
    ProfilingFailureCode,
)
from ai_interviewer.profiling.models import CandidateProfile, CandidateProfileVersion

DATA_CATEGORY = "candidate_document"
PROCESSING_PURPOSE = "interview_preparation"
_SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")
_FAILURE_CODES = frozenset(
    {
        "rate_limited",
        "provider_timeout",
        "provider_unavailable",
        "provider_rejected",
        "provider_failure",
        "model_identity_mismatch",
        "invalid_output",
        "output_too_large",
        "incomplete_output",
        "content_filtered",
        "source_unavailable",
        "policy_unavailable",
        "persistence_conflict",
        "internal_failure",
        "lease_expired",
    }
)


class CandidateProfilingJobUnavailableError(RuntimeError):
    """The profiling-job boundary is disabled."""


class CandidateProfilingJobNotFoundError(LookupError):
    """An owner-scoped profiling job was not found."""


class CandidateProfilingJobConflictError(RuntimeError):
    """A profiling-job snapshot or fenced transition is invalid."""


@dataclass(frozen=True, slots=True)
class CandidateProfilingReleaseSnapshot:
    """Exact reviewed execution coordinates captured before a job is scheduled."""

    model_release: ModelReleaseIdentity
    prompt_release: PromptReleaseIdentity
    processor_activity_id: UUID
    instructions_sha256: str
    output_schema_sha256: str
    max_output_tokens: int = 4_096

    def __post_init__(self) -> None:
        if not isinstance(self.model_release, ModelReleaseIdentity):
            raise TypeError("model_release must be a model release identity")
        if not isinstance(self.prompt_release, PromptReleaseIdentity):
            raise TypeError("prompt_release must be a prompt release identity")
        if not isinstance(self.processor_activity_id, UUID):
            raise TypeError("processor_activity_id must be a UUID")
        if not _SHA256_PATTERN.fullmatch(self.instructions_sha256):
            raise ValueError("instructions_sha256 must be a lowercase SHA-256 digest")
        if not _SHA256_PATTERN.fullmatch(self.output_schema_sha256):
            raise ValueError("output_schema_sha256 must be a lowercase SHA-256 digest")
        if not 1 <= self.max_output_tokens <= 32_768:
            raise ValueError("max_output_tokens must be between 1 and 32768")


@dataclass(frozen=True, slots=True)
class CandidateProfilingJobRecord:
    job_id: UUID
    owner_id: UUID
    preparation_id: UUID
    document_version_id: UUID
    source_text_id: UUID
    source_text_version_id: UUID
    processor_activity_id: UUID
    document_type: str
    privacy_policy_version_id: UUID
    retention_rule_id: UUID
    jurisdiction_code: str
    legal_basis: str
    retain_until: datetime
    retention_action: str
    model_provider: str
    model_id: str
    model_version: str
    prompt_id: str
    prompt_version: str
    schema_id: str
    schema_version: str
    instructions_sha256: str
    output_schema_sha256: str
    max_output_tokens: int
    status: str
    attempts: int
    available_at: datetime
    locked_at: datetime | None
    locked_by: str | None
    lease_token: UUID | None
    error_code: str | None
    profile_id: UUID | None
    completed_at: datetime | None
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True, slots=True)
class ScheduleProfilingResult:
    job: CandidateProfilingJobRecord
    created: bool


class CandidateProfilingJobRuntime(Protocol):
    async def schedule_profiling(
        self,
        account_id: UUID,
        preparation_id: UUID,
        document_version_id: UUID,
        source_text_version_id: UUID,
        release: CandidateProfilingReleaseSnapshot,
        request_id: str | None,
        *,
        now: datetime | None = None,
    ) -> ScheduleProfilingResult: ...

    async def claim_jobs(
        self,
        worker_id: str,
        limit: int,
        *,
        now: datetime | None = None,
    ) -> tuple[CandidateProfilingJobRecord, ...]: ...

    async def get_profiling_job(
        self,
        account_id: UUID,
        preparation_id: UUID,
        document_version_id: UUID,
        source_text_version_id: UUID,
    ) -> CandidateProfilingJobRecord: ...

    async def mark_succeeded(
        self,
        job_id: UUID,
        worker_id: str,
        lease_token: UUID,
        profile_id: UUID,
        *,
        now: datetime | None = None,
    ) -> CandidateProfilingJobRecord: ...

    async def mark_failed(
        self,
        job_id: UUID,
        worker_id: str,
        lease_token: UUID,
        error_code: ProfilingFailureCode,
        *,
        now: datetime | None = None,
    ) -> CandidateProfilingJobRecord: ...

    async def export_account_profiling_job_metadata(
        self,
        session: AsyncSession,
        *,
        account_id: UUID,
    ) -> list[dict[str, object]]: ...


class FailClosedCandidateProfilingJobService:
    """Reject profiling work until upstream privacy cryptography is configured."""

    @staticmethod
    def _unavailable() -> NoReturn:
        raise CandidateProfilingJobUnavailableError("profiling jobs are not configured")

    async def schedule_profiling(
        self,
        account_id: UUID,
        preparation_id: UUID,
        document_version_id: UUID,
        source_text_version_id: UUID,
        release: CandidateProfilingReleaseSnapshot,
        request_id: str | None,
        *,
        now: datetime | None = None,
    ) -> ScheduleProfilingResult:
        del account_id, preparation_id, document_version_id, source_text_version_id
        del release, request_id, now
        self._unavailable()

    async def claim_jobs(
        self,
        worker_id: str,
        limit: int,
        *,
        now: datetime | None = None,
    ) -> tuple[CandidateProfilingJobRecord, ...]:
        del worker_id, limit, now
        self._unavailable()

    async def get_profiling_job(
        self,
        account_id: UUID,
        preparation_id: UUID,
        document_version_id: UUID,
        source_text_version_id: UUID,
    ) -> CandidateProfilingJobRecord:
        del account_id, preparation_id, document_version_id, source_text_version_id
        self._unavailable()

    async def mark_succeeded(
        self,
        job_id: UUID,
        worker_id: str,
        lease_token: UUID,
        profile_id: UUID,
        *,
        now: datetime | None = None,
    ) -> CandidateProfilingJobRecord:
        del job_id, worker_id, lease_token, profile_id, now
        self._unavailable()

    async def mark_failed(
        self,
        job_id: UUID,
        worker_id: str,
        lease_token: UUID,
        error_code: ProfilingFailureCode,
        *,
        now: datetime | None = None,
    ) -> CandidateProfilingJobRecord:
        del job_id, worker_id, lease_token, error_code, now
        self._unavailable()

    async def export_account_profiling_job_metadata(
        self,
        session: AsyncSession,
        *,
        account_id: UUID,
    ) -> list[dict[str, object]]:
        del session, account_id
        return []


class CandidateProfilingJobService:
    """Persist and transition one profiling job per exact source-text revision."""

    def __init__(self, database: DatabaseRuntime) -> None:
        self._database = database

    async def schedule_profiling(
        self,
        account_id: UUID,
        preparation_id: UUID,
        document_version_id: UUID,
        source_text_version_id: UUID,
        release: CandidateProfilingReleaseSnapshot,
        request_id: str | None,
        *,
        now: datetime | None = None,
    ) -> ScheduleProfilingResult:
        if not isinstance(release, CandidateProfilingReleaseSnapshot):
            raise TypeError("release must be a profiling release snapshot")
        scheduled_at = now or datetime.now(UTC)
        async with self._database.transaction() as session:
            account = await session.scalar(
                select(Account).where(Account.id == account_id).with_for_update()
            )
            if account is None or account.status != "active":
                raise CandidateProfilingJobConflictError("the account cannot profile documents")
            (
                preparation,
                document,
                document_version,
                source_text,
                source_version,
            ) = await self._locked_lineage(
                session,
                account_id=account_id,
                preparation_id=preparation_id,
                document_version_id=document_version_id,
                source_text_version_id=source_text_version_id,
            )
            self._require_processable_lineage(
                preparation,
                document,
                document_version,
                source_text,
                source_version,
                scheduled_at,
            )
            self._require_release_matches_document(release, document.document_type)
            privacy_profile, _ = await require_privacy_profile(
                session,
                account_id,
                now=scheduled_at,
            )
            await self._require_processor_activity(
                session,
                release,
                privacy_profile,
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
                or decision.retention_rule_id != document_version.retention_rule_id
                or decision.jurisdiction_code != document_version.jurisdiction_code
                or decision.legal_basis != document_version.legal_basis
            ):
                raise CandidateProfilingJobConflictError(
                    "the source no longer matches the active privacy decision"
                )

            existing = await session.scalar(
                select(CandidateProfilingJob)
                .where(CandidateProfilingJob.source_text_version_id == source_version.id)
                .with_for_update()
            )
            if existing is not None:
                if existing.owner_id != account_id:
                    raise CandidateProfilingJobNotFoundError("profiling job was not found")
                if not self._same_release(existing, release):
                    raise CandidateProfilingJobConflictError(
                        "the exact source revision already has a different profiling release"
                    )
                return ScheduleProfilingResult(job=self._record(existing), created=False)

            existing_profile = await session.scalar(
                select(CandidateProfile.id).where(
                    CandidateProfile.source_text_version_id == source_version.id
                )
            )
            if existing_profile is not None:
                raise CandidateProfilingJobConflictError(
                    "the exact source revision already has a candidate profile"
                )

            job = CandidateProfilingJob(
                id=uuid7(),
                owner_id=account_id,
                preparation_id=preparation.id,
                document_version_id=document_version.id,
                source_text_id=source_text.id,
                source_text_version_id=source_version.id,
                processor_activity_id=release.processor_activity_id,
                document_type=document.document_type,
                privacy_policy_version_id=document_version.privacy_policy_version_id,
                retention_rule_id=document_version.retention_rule_id,
                jurisdiction_code=document_version.jurisdiction_code,
                legal_basis=document_version.legal_basis,
                retain_until=document_version.retain_until,
                retention_action="delete",
                model_provider=release.model_release.provider,
                model_id=release.model_release.model_id,
                model_version=release.model_release.model_version,
                prompt_id=release.prompt_release.prompt_id,
                prompt_version=release.prompt_release.prompt_version,
                schema_id=release.prompt_release.schema_id,
                schema_version=release.prompt_release.schema_version,
                instructions_sha256=release.instructions_sha256,
                output_schema_sha256=release.output_schema_sha256,
                max_output_tokens=release.max_output_tokens,
                status="pending",
                attempts=0,
                available_at=scheduled_at,
                created_at=scheduled_at,
                updated_at=scheduled_at,
            )
            session.add(job)
            await session.flush()
            await self._record_transition(
                session,
                job,
                profile=privacy_profile,
                request_id=request_id,
                occurred_at=scheduled_at,
                action="candidate_profiling_job.scheduled",
                event_type="candidate_profiling_job.scheduled",
            )
            await session.flush()
            return ScheduleProfilingResult(job=self._record(job), created=True)

    async def claim_jobs(
        self,
        worker_id: str,
        limit: int,
        *,
        now: datetime | None = None,
    ) -> tuple[CandidateProfilingJobRecord, ...]:
        self._validate_worker(worker_id)
        if limit < 1 or limit > 100:
            raise ValueError("limit must be between 1 and 100")
        claimed_at = now or datetime.now(UTC)
        stale_before = claimed_at - timedelta(seconds=PROFILING_LEASE_SECONDS)
        async with self._database.transaction() as session:
            expired = list(
                (
                    await session.scalars(
                        select(CandidateProfilingJob)
                        .where(
                            CandidateProfilingJob.status.in_(("pending", "processing", "retry")),
                            CandidateProfilingJob.retain_until <= claimed_at,
                        )
                        .with_for_update(skip_locked=True)
                    )
                ).all()
            )
            for job in expired:
                await self._dead_letter(
                    session,
                    job,
                    "policy_unavailable",
                    occurred_at=claimed_at,
                )

            exhausted = list(
                (
                    await session.scalars(
                        select(CandidateProfilingJob)
                        .where(
                            CandidateProfilingJob.status == "processing",
                            CandidateProfilingJob.locked_at < stale_before,
                            CandidateProfilingJob.attempts >= MAX_PROFILING_ATTEMPTS,
                            CandidateProfilingJob.retain_until > claimed_at,
                        )
                        .with_for_update(skip_locked=True)
                    )
                ).all()
            )
            for job in exhausted:
                await self._dead_letter(
                    session,
                    job,
                    "lease_expired",
                    occurred_at=claimed_at,
                )

            jobs = list(
                (
                    await session.scalars(
                        select(CandidateProfilingJob)
                        .where(
                            or_(
                                and_(
                                    CandidateProfilingJob.status.in_(("pending", "retry")),
                                    CandidateProfilingJob.available_at <= claimed_at,
                                ),
                                and_(
                                    CandidateProfilingJob.status == "processing",
                                    CandidateProfilingJob.locked_at < stale_before,
                                ),
                            ),
                            CandidateProfilingJob.attempts < MAX_PROFILING_ATTEMPTS,
                            CandidateProfilingJob.retain_until > claimed_at,
                        )
                        .order_by(
                            CandidateProfilingJob.available_at,
                            CandidateProfilingJob.id,
                        )
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
            for job in jobs:
                await session.refresh(job)
            return tuple(self._record(job) for job in jobs)

    async def get_profiling_job(
        self,
        account_id: UUID,
        preparation_id: UUID,
        document_version_id: UUID,
        source_text_version_id: UUID,
    ) -> CandidateProfilingJobRecord:
        async with self._database.transaction() as session:
            job = await session.scalar(
                select(CandidateProfilingJob).where(
                    CandidateProfilingJob.owner_id == account_id,
                    CandidateProfilingJob.preparation_id == preparation_id,
                    CandidateProfilingJob.document_version_id == document_version_id,
                    CandidateProfilingJob.source_text_version_id == source_text_version_id,
                )
            )
            if job is None:
                raise CandidateProfilingJobNotFoundError("profiling job was not found")
            return self._record(job)

    async def mark_succeeded(
        self,
        job_id: UUID,
        worker_id: str,
        lease_token: UUID,
        profile_id: UUID,
        *,
        now: datetime | None = None,
    ) -> CandidateProfilingJobRecord:
        completed_at = now or datetime.now(UTC)
        self._validate_worker(worker_id)
        async with self._database.transaction() as session:
            job = await self._locked_job(session, job_id)
            self._require_claim(job, worker_id, lease_token)
            profile = await session.scalar(
                select(CandidateProfile)
                .where(
                    CandidateProfile.id == profile_id,
                    CandidateProfile.owner_id == job.owner_id,
                )
                .with_for_update()
            )
            version = (
                await session.scalar(
                    select(CandidateProfileVersion).where(
                        CandidateProfileVersion.profile_id == profile_id,
                        CandidateProfileVersion.version_number == 1,
                    )
                )
                if profile is not None
                else None
            )
            if (
                profile is None
                or version is None
                or not self._profile_matches(job, profile, version)
            ):
                raise CandidateProfilingJobConflictError(
                    "successful profiling requires the matching encrypted profile release"
                )
            job.status = "succeeded"
            job.profile_id = profile.id
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
                action="candidate_profiling_job.succeeded",
                event_type="candidate_profiling_job.succeeded",
            )
            await session.flush()
            return self._record(job)

    async def mark_failed(
        self,
        job_id: UUID,
        worker_id: str,
        lease_token: UUID,
        error_code: ProfilingFailureCode,
        *,
        now: datetime | None = None,
    ) -> CandidateProfilingJobRecord:
        failed_at = now or datetime.now(UTC)
        self._validate_worker(worker_id)
        if error_code not in _FAILURE_CODES:
            raise ValueError("error_code is not supported")
        async with self._database.transaction() as session:
            job = await self._locked_job(session, job_id)
            self._require_claim(job, worker_id, lease_token)
            retry = error_code in RETRYABLE_PROFILING_FAILURES and (
                job.attempts < MAX_PROFILING_ATTEMPTS
            )
            if retry:
                job.status = "retry"
                job.error_code = error_code
                job.available_at = failed_at + self._retry_delay(job.attempts)
                job.completed_at = None
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
                    action="candidate_profiling_job.retry_scheduled",
                    event_type="candidate_profiling_job.retry_scheduled",
                )
            else:
                await self._dead_letter(
                    session,
                    job,
                    error_code,
                    occurred_at=failed_at,
                )
            await session.flush()
            return self._record(job)

    async def export_account_profiling_job_metadata(
        self,
        session: AsyncSession,
        *,
        account_id: UUID,
    ) -> list[dict[str, object]]:
        jobs = list(
            (
                await session.scalars(
                    select(CandidateProfilingJob)
                    .where(CandidateProfilingJob.owner_id == account_id)
                    .order_by(CandidateProfilingJob.created_at, CandidateProfilingJob.id)
                )
            ).all()
        )
        return [self._export_record(job) for job in jobs]

    @staticmethod
    def _export_record(job: CandidateProfilingJob) -> dict[str, object]:
        return {
            "job_id": str(job.id),
            "preparation_id": str(job.preparation_id),
            "document_version_id": str(job.document_version_id),
            "source_text_id": str(job.source_text_id),
            "source_text_version_id": str(job.source_text_version_id),
            "processor_activity_id": str(job.processor_activity_id),
            "document_type": job.document_type,
            "model_provider": job.model_provider,
            "model_id": job.model_id,
            "model_version": job.model_version,
            "prompt_id": job.prompt_id,
            "prompt_version": job.prompt_version,
            "schema_id": job.schema_id,
            "schema_version": job.schema_version,
            "status": job.status,
            "attempts": job.attempts,
            "error_code": job.error_code,
            "profile_id": str(job.profile_id) if job.profile_id else None,
            "retain_until": job.retain_until.isoformat(),
            "retention_action": job.retention_action,
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
    async def _locked_job(session: AsyncSession, job_id: UUID) -> CandidateProfilingJob:
        job = await session.scalar(
            select(CandidateProfilingJob)
            .where(CandidateProfilingJob.id == job_id)
            .with_for_update()
        )
        if job is None:
            raise CandidateProfilingJobNotFoundError("profiling job was not found")
        return job

    @staticmethod
    def _require_claim(
        job: CandidateProfilingJob,
        worker_id: str,
        lease_token: UUID,
    ) -> None:
        if (
            job.status != "processing"
            or job.locked_by != worker_id
            or job.lease_token != lease_token
        ):
            raise CandidateProfilingJobConflictError(
                "profiling job is not claimed by this worker lease"
            )

    @staticmethod
    async def _locked_lineage(
        session: AsyncSession,
        *,
        account_id: UUID,
        preparation_id: UUID,
        document_version_id: UUID,
        source_text_version_id: UUID,
    ) -> tuple[
        CandidatePreparation,
        CandidateDocument,
        CandidateDocumentVersion,
        CandidateSourceText,
        CandidateSourceTextVersion,
    ]:
        preparation = await session.scalar(
            select(CandidatePreparation)
            .where(
                CandidatePreparation.id == preparation_id,
                CandidatePreparation.owner_id == account_id,
            )
            .with_for_update()
        )
        document_version = await session.scalar(
            select(CandidateDocumentVersion)
            .where(
                CandidateDocumentVersion.id == document_version_id,
                CandidateDocumentVersion.owner_id == account_id,
            )
            .with_for_update()
        )
        if preparation is None or document_version is None:
            raise CandidateProfilingJobNotFoundError("candidate source revision was not found")
        document = await session.scalar(
            select(CandidateDocument)
            .where(
                CandidateDocument.id == document_version.document_id,
                CandidateDocument.owner_id == account_id,
                CandidateDocument.preparation_id == preparation_id,
            )
            .with_for_update()
        )
        source_text = await session.scalar(
            select(CandidateSourceText)
            .where(
                CandidateSourceText.owner_id == account_id,
                CandidateSourceText.document_version_id == document_version_id,
            )
            .with_for_update()
        )
        if document is None or source_text is None:
            raise CandidateProfilingJobNotFoundError("candidate source revision was not found")
        source_version = await session.scalar(
            select(CandidateSourceTextVersion)
            .where(
                CandidateSourceTextVersion.id == source_text_version_id,
                CandidateSourceTextVersion.source_text_id == source_text.id,
                CandidateSourceTextVersion.owner_id == account_id,
            )
            .with_for_update()
        )
        if source_version is None:
            raise CandidateProfilingJobNotFoundError("candidate source revision was not found")
        return preparation, document, document_version, source_text, source_version

    @staticmethod
    def _require_processable_lineage(
        preparation: CandidatePreparation,
        document: CandidateDocument,
        document_version: CandidateDocumentVersion,
        source_text: CandidateSourceText,
        source_version: CandidateSourceTextVersion,
        evaluated_at: datetime,
    ) -> None:
        if preparation.status != "draft":
            raise CandidateProfilingJobConflictError("archived documents cannot be profiled")
        if (
            preparation.retain_until <= evaluated_at
            or preparation.retention_action != "delete"
            or preparation.privacy_policy_version_id != document_version.privacy_policy_version_id
            or preparation.jurisdiction_code != document_version.jurisdiction_code
        ):
            raise CandidateProfilingJobConflictError(
                "the preparation privacy snapshot is no longer processable"
            )
        if document.latest_version_number != document_version.version_number:
            raise CandidateProfilingJobConflictError(
                "only the latest document version can be profiled"
            )
        if document_version.retain_until <= evaluated_at:
            raise CandidateProfilingJobConflictError("the document retention deadline has passed")
        if (
            source_text.latest_version_number != source_version.version_number
            or source_text.document_version_id != document_version.id
        ):
            raise CandidateProfilingJobConflictError(
                "only the latest source revision can be profiled"
            )

    @staticmethod
    def _require_release_matches_document(
        release: CandidateProfilingReleaseSnapshot,
        document_type: str,
    ) -> None:
        expected_schema_id = (
            CV_PROFILE_SCHEMA_ID if document_type == "cv" else JOB_DESCRIPTION_PROFILE_SCHEMA_ID
        )
        if (
            release.prompt_release.schema_id != expected_schema_id
            or release.prompt_release.schema_version != PROFILE_SCHEMA_VERSION
        ):
            raise CandidateProfilingJobConflictError(
                "the profiling release does not match the document type"
            )

    @staticmethod
    async def _require_processor_activity(
        session: AsyncSession,
        release: CandidateProfilingReleaseSnapshot,
        privacy_profile: PrivacyProfile,
    ) -> None:
        activity = await session.scalar(
            select(ProcessorActivity)
            .where(ProcessorActivity.id == release.processor_activity_id)
            .with_for_update()
        )
        processor = (
            await session.scalar(
                select(Processor).where(Processor.id == activity.processor_id).with_for_update()
            )
            if activity is not None
            else None
        )
        if (
            activity is None
            or processor is None
            or activity.status != "active"
            or processor.status != "active"
            or processor.processor_key != release.model_release.provider
            or activity.privacy_policy_version_id != privacy_profile.privacy_policy_version_id
            or activity.data_category != DATA_CATEGORY
            or activity.purpose != PROCESSING_PURPOSE
            or activity.origin_region != privacy_profile.storage_region
        ):
            raise CandidateProfilingJobConflictError(
                "the model processor activity is not approved for this profile"
            )

    @staticmethod
    def _same_release(
        job: CandidateProfilingJob,
        release: CandidateProfilingReleaseSnapshot,
    ) -> bool:
        return (
            job.model_provider == release.model_release.provider
            and job.processor_activity_id == release.processor_activity_id
            and job.model_id == release.model_release.model_id
            and job.model_version == release.model_release.model_version
            and job.prompt_id == release.prompt_release.prompt_id
            and job.prompt_version == release.prompt_release.prompt_version
            and job.schema_id == release.prompt_release.schema_id
            and job.schema_version == release.prompt_release.schema_version
            and job.instructions_sha256 == release.instructions_sha256
            and job.output_schema_sha256 == release.output_schema_sha256
            and job.max_output_tokens == release.max_output_tokens
        )

    @staticmethod
    def _profile_matches(
        job: CandidateProfilingJob,
        profile: CandidateProfile,
        version: CandidateProfileVersion,
    ) -> bool:
        return (
            profile.owner_id == job.owner_id
            and profile.document_version_id == job.document_version_id
            and profile.source_text_id == job.source_text_id
            and profile.source_text_version_id == job.source_text_version_id
            and profile.document_type == job.document_type
            and profile.privacy_policy_version_id == job.privacy_policy_version_id
            and profile.retention_rule_id == job.retention_rule_id
            and profile.jurisdiction_code == job.jurisdiction_code
            and profile.legal_basis == job.legal_basis
            and profile.retain_until == job.retain_until
            and profile.retention_action == job.retention_action
            and version.origin == "model_generation"
            and version.model_provider == job.model_provider
            and version.model_id == job.model_id
            and version.model_version == job.model_version
            and version.prompt_id == job.prompt_id
            and version.prompt_version == job.prompt_version
            and version.schema_id == job.schema_id
            and version.schema_version == job.schema_version
            and version.instructions_sha256 == job.instructions_sha256
            and version.output_schema_sha256 == job.output_schema_sha256
        )

    @staticmethod
    def _record(job: CandidateProfilingJob) -> CandidateProfilingJobRecord:
        return CandidateProfilingJobRecord(
            job_id=job.id,
            owner_id=job.owner_id,
            preparation_id=job.preparation_id,
            document_version_id=job.document_version_id,
            source_text_id=job.source_text_id,
            source_text_version_id=job.source_text_version_id,
            processor_activity_id=job.processor_activity_id,
            document_type=job.document_type,
            privacy_policy_version_id=job.privacy_policy_version_id,
            retention_rule_id=job.retention_rule_id,
            jurisdiction_code=job.jurisdiction_code,
            legal_basis=job.legal_basis,
            retain_until=job.retain_until,
            retention_action=job.retention_action,
            model_provider=job.model_provider,
            model_id=job.model_id,
            model_version=job.model_version,
            prompt_id=job.prompt_id,
            prompt_version=job.prompt_version,
            schema_id=job.schema_id,
            schema_version=job.schema_version,
            instructions_sha256=job.instructions_sha256,
            output_schema_sha256=job.output_schema_sha256,
            max_output_tokens=job.max_output_tokens,
            status=job.status,
            attempts=job.attempts,
            available_at=job.available_at,
            locked_at=job.locked_at,
            locked_by=job.locked_by,
            lease_token=job.lease_token,
            error_code=job.error_code,
            profile_id=job.profile_id,
            completed_at=job.completed_at,
            created_at=job.created_at,
            updated_at=job.updated_at,
        )

    @staticmethod
    async def _dead_letter(
        session: AsyncSession,
        job: CandidateProfilingJob,
        error_code: ProfilingFailureCode,
        *,
        occurred_at: datetime,
    ) -> None:
        job.status = "dead_letter"
        job.error_code = error_code
        job.profile_id = None
        job.completed_at = occurred_at
        job.locked_at = None
        job.locked_by = None
        job.lease_token = None
        job.updated_at = occurred_at
        await session.flush()
        await CandidateProfilingJobService._record_transition(
            session,
            job,
            profile=await session.get(PrivacyProfile, job.owner_id),
            request_id=None,
            occurred_at=occurred_at,
            action="candidate_profiling_job.dead_lettered",
            event_type="candidate_profiling_job.dead_lettered",
        )

    @staticmethod
    async def _record_transition(
        session: AsyncSession,
        job: CandidateProfilingJob,
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
            "document_type": job.document_type,
            "model_provider": job.model_provider,
            "model_id": job.model_id,
            "model_version": job.model_version,
            "prompt_id": job.prompt_id,
            "prompt_version": job.prompt_version,
            "schema_id": job.schema_id,
            "schema_version": job.schema_version,
            "processor_activity_id": str(job.processor_activity_id),
            "error_code": job.error_code,
        }
        if profile is not None:
            await record_privacy_audit(
                session,
                profile=profile,
                occurred_at=occurred_at,
                actor_id=None,
                action=action,
                resource_type="candidate_profiling_job",
                resource_id=job.id,
                owner_id=job.owner_id,
                request_id=request_id,
                details=details,
            )
        await enqueue_outbox(
            session,
            NewOutboxEvent(
                aggregate_type="candidate_profiling_job",
                aggregate_id=job.id,
                event_type=event_type,
                owner_id=job.owner_id,
                payload={
                    "candidate_profiling_job_id": str(job.id),
                    "candidate_source_text_version_id": str(job.source_text_version_id),
                    **details,
                },
            ),
        )


def build_candidate_profiling_jobs(
    settings: Settings,
    database: DatabaseRuntime,
) -> CandidateProfilingJobRuntime:
    if (
        not settings.privacy_enabled
        or not settings.file_security_enabled
        or settings.privacy_keyring is None
    ):
        return FailClosedCandidateProfilingJobService()
    ApplicationKeyring.from_secret(settings.privacy_keyring)
    return CandidateProfilingJobService(database)
