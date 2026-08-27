"""Authenticated, idempotent, and recoverable CV/JD intake orchestration."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import NoReturn, Protocol
from uuid import UUID

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession
from uuid6 import uuid7

from ai_interviewer.candidate_inputs.document_models import (
    DOCUMENT_SOURCES,
    DOCUMENT_TYPES,
    CandidateDocumentSource,
    CandidateDocumentType,
)
from ai_interviewer.candidate_inputs.documents import (
    DATA_CATEGORY,
    PROCESSING_PURPOSE,
    CandidateDocumentConflictError,
    CandidateDocumentNotFoundError,
    CandidateDocumentRuntime,
)
from ai_interviewer.candidate_inputs.intake_models import (
    CandidateDocumentIntake,
    CandidateDocumentIntakeStatus,
)
from ai_interviewer.candidate_inputs.models import CandidatePreparation
from ai_interviewer.core.config import Settings
from ai_interviewer.file_security.lifecycle import (
    FileAssetNotFoundError,
    FileStateConflictError,
)
from ai_interviewer.file_security.models import FileAsset
from ai_interviewer.file_security.object_store import ObjectStoreError
from ai_interviewer.file_security.validation import (
    ALLOWED_MEDIA_TYPES,
    TEXT_MEDIA_TYPE,
    UploadValidationError,
)
from ai_interviewer.identity.models import Account
from ai_interviewer.persistence.database import DatabaseRuntime
from ai_interviewer.persistence.repositories import NewOutboxEvent, enqueue_outbox
from ai_interviewer.privacy.audit import record_privacy_audit
from ai_interviewer.privacy.models import PrivacyProfile
from ai_interviewer.privacy.rules import (
    PrivacyPolicyError,
    authorize_processing,
    require_privacy_profile,
)

PROCESSING_LEASE = timedelta(minutes=5)
_ROTATE_ASSET_ERRORS = frozenset({"storage_unavailable"})


class CandidateDocumentIntakeUnavailableError(RuntimeError):
    """The public document-intake boundary is disabled or temporarily unavailable."""


class CandidateDocumentIntakeNotFoundError(LookupError):
    """An owner-scoped intake was not found."""


class CandidateDocumentIntakeConflictError(RuntimeError):
    """An intake request conflicts with durable state, ownership, or policy."""


class FileIntakeRuntime(Protocol):
    async def stage_upload(
        self,
        *,
        account_id: UUID,
        data_category: str,
        purpose: str,
        declared_media_type: str,
        content: bytes,
        file_asset_id: UUID | None = None,
        now: datetime | None = None,
    ) -> FileAsset: ...

    async def scan_and_release(
        self,
        *,
        account_id: UUID,
        file_asset_id: UUID,
        now: datetime | None = None,
    ) -> FileAsset: ...


@dataclass(frozen=True, slots=True)
class CandidateDocumentIntakeRecord:
    intake_id: UUID
    preparation_id: UUID
    document_type: CandidateDocumentType
    source_kind: CandidateDocumentSource
    status: CandidateDocumentIntakeStatus
    declared_media_type: str
    content_length: int
    attempts: int
    last_error_code: str | None
    file_asset_id: UUID | None
    document_id: UUID | None
    document_version_id: UUID | None
    aggregate_version: int
    created_at: datetime
    updated_at: datetime
    completed_at: datetime | None
    retain_until: datetime

    @property
    def retryable(self) -> bool:
        return self.status == "scan_failed"


@dataclass(frozen=True, slots=True)
class SubmitCandidateDocumentIntakeResult:
    intake: CandidateDocumentIntakeRecord
    created: bool


@dataclass(frozen=True, slots=True)
class _IntakeClaim:
    intake_id: UUID
    reserved_file_asset_id: UUID
    processing_token: UUID | None
    created: bool
    should_process: bool
    record: CandidateDocumentIntakeRecord


class CandidateDocumentIntakeRuntime(Protocol):
    async def submit(
        self,
        account_id: UUID,
        preparation_id: UUID,
        document_type: CandidateDocumentType,
        source_kind: CandidateDocumentSource,
        declared_media_type: str,
        content: bytes,
        idempotency_key: str,
        request_id: str | None,
        *,
        now: datetime | None = None,
    ) -> SubmitCandidateDocumentIntakeResult: ...

    async def get_intake(
        self,
        account_id: UUID,
        preparation_id: UUID,
        intake_id: UUID,
    ) -> CandidateDocumentIntakeRecord: ...

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


class FailClosedCandidateDocumentIntakeService:
    @staticmethod
    def _unavailable() -> NoReturn:
        raise CandidateDocumentIntakeUnavailableError("candidate document intake is unavailable")

    async def submit(
        self,
        account_id: UUID,
        preparation_id: UUID,
        document_type: CandidateDocumentType,
        source_kind: CandidateDocumentSource,
        declared_media_type: str,
        content: bytes,
        idempotency_key: str,
        request_id: str | None,
        *,
        now: datetime | None = None,
    ) -> SubmitCandidateDocumentIntakeResult:
        del (
            account_id,
            preparation_id,
            document_type,
            source_kind,
            declared_media_type,
            content,
            idempotency_key,
            request_id,
            now,
        )
        self._unavailable()

    async def get_intake(
        self,
        account_id: UUID,
        preparation_id: UUID,
        intake_id: UUID,
    ) -> CandidateDocumentIntakeRecord:
        del account_id, preparation_id, intake_id
        self._unavailable()

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


class CandidateDocumentIntakeService:
    """Coordinate bounded bytes through file security into immutable document lineage."""

    def __init__(
        self,
        database: DatabaseRuntime,
        files: FileIntakeRuntime,
        documents: CandidateDocumentRuntime,
    ) -> None:
        self._database = database
        self._files = files
        self._documents = documents

    async def submit(
        self,
        account_id: UUID,
        preparation_id: UUID,
        document_type: CandidateDocumentType,
        source_kind: CandidateDocumentSource,
        declared_media_type: str,
        content: bytes,
        idempotency_key: str,
        request_id: str | None,
        *,
        now: datetime | None = None,
    ) -> SubmitCandidateDocumentIntakeResult:
        submitted_at = now or datetime.now(UTC)
        normalized_type, normalized_source, normalized_media = self._normalize_contract(
            document_type,
            source_kind,
            declared_media_type,
        )
        normalized_key = idempotency_key.strip()
        if len(normalized_key) < 8 or len(normalized_key) > 128:
            raise ValueError("idempotency key must contain 8-128 characters")
        if not content:
            raise UploadValidationError("empty_file")
        key_hash = hashlib.sha256(normalized_key.encode()).hexdigest()
        request_digest = self._request_digest(
            preparation_id,
            normalized_type,
            normalized_source,
            normalized_media,
            content,
        )
        claim = await self._claim(
            account_id=account_id,
            preparation_id=preparation_id,
            document_type=normalized_type,
            source_kind=normalized_source,
            declared_media_type=normalized_media,
            content_length=len(content),
            key_hash=key_hash,
            request_digest=request_digest,
            request_id=request_id,
            submitted_at=submitted_at,
        )
        if not claim.should_process or claim.processing_token is None:
            return SubmitCandidateDocumentIntakeResult(claim.record, claim.created)

        asset: FileAsset | None = None
        try:
            asset = await self._files.stage_upload(
                account_id=account_id,
                data_category=DATA_CATEGORY,
                purpose=PROCESSING_PURPOSE,
                declared_media_type=normalized_media,
                content=content,
                file_asset_id=claim.reserved_file_asset_id,
                now=submitted_at,
            )
            await self._record_asset(
                account_id,
                claim.intake_id,
                claim.processing_token,
                asset.id,
            )
            if asset.status != "released":
                asset = await self._files.scan_and_release(
                    account_id=account_id,
                    file_asset_id=asset.id,
                    now=submitted_at,
                )
            if asset.status == "scan_failed":
                record = await self._finish(
                    account_id,
                    claim.intake_id,
                    claim.processing_token,
                    status="scan_failed",
                    error_code="scan_unavailable",
                    request_id=request_id,
                    finished_at=submitted_at,
                )
                return SubmitCandidateDocumentIntakeResult(record, claim.created)
            if asset.status != "released":
                record = await self._finish(
                    account_id,
                    claim.intake_id,
                    claim.processing_token,
                    status="rejected",
                    error_code="unsafe_file",
                    request_id=request_id,
                    finished_at=submitted_at,
                )
                return SubmitCandidateDocumentIntakeResult(record, claim.created)

            attached = await self._documents.attach_released_asset(
                account_id,
                preparation_id,
                normalized_type,
                asset.id,
                normalized_source,
                request_id,
                now=submitted_at,
            )
            record = await self._finish(
                account_id,
                claim.intake_id,
                claim.processing_token,
                status="completed",
                error_code=None,
                request_id=request_id,
                finished_at=submitted_at,
                file_asset_id=asset.id,
                document_id=attached.document.document_id,
                document_version_id=attached.attached_version.version_id,
            )
            return SubmitCandidateDocumentIntakeResult(record, claim.created)
        except UploadValidationError as exc:
            record = await self._finish(
                account_id,
                claim.intake_id,
                claim.processing_token,
                status="rejected",
                error_code=exc.code,
                request_id=request_id,
                finished_at=submitted_at,
            )
            return SubmitCandidateDocumentIntakeResult(record, claim.created)
        except ObjectStoreError:
            record = await self._finish(
                account_id,
                claim.intake_id,
                claim.processing_token,
                status="scan_failed",
                error_code="storage_unavailable",
                request_id=request_id,
                finished_at=submitted_at,
            )
            return SubmitCandidateDocumentIntakeResult(record, claim.created)
        except (
            CandidateDocumentConflictError,
            CandidateDocumentNotFoundError,
            FileAssetNotFoundError,
            FileStateConflictError,
            PrivacyPolicyError,
        ) as exc:
            await self._finish(
                account_id,
                claim.intake_id,
                claim.processing_token,
                status="rejected",
                error_code="policy_or_state_changed",
                request_id=request_id,
                finished_at=submitted_at,
            )
            raise CandidateDocumentIntakeConflictError(
                "the document intake is no longer permitted"
            ) from exc
        except Exception as exc:
            error_code = "storage_unavailable" if asset is None else "internal_dependency_failure"
            await self._finish(
                account_id,
                claim.intake_id,
                claim.processing_token,
                status="scan_failed",
                error_code=error_code,
                request_id=request_id,
                finished_at=submitted_at,
            )
            raise CandidateDocumentIntakeUnavailableError(
                "the document intake could not be completed"
            ) from exc

    async def get_intake(
        self,
        account_id: UUID,
        preparation_id: UUID,
        intake_id: UUID,
    ) -> CandidateDocumentIntakeRecord:
        async with self._database.transaction() as session:
            intake = await session.scalar(
                select(CandidateDocumentIntake).where(
                    CandidateDocumentIntake.id == intake_id,
                    CandidateDocumentIntake.owner_id == account_id,
                    CandidateDocumentIntake.preparation_id == preparation_id,
                )
            )
            if intake is None:
                raise CandidateDocumentIntakeNotFoundError("document intake was not found")
            return self._record(intake)

    async def export_account_intake_metadata(
        self,
        session: AsyncSession,
        *,
        account_id: UUID,
    ) -> list[dict[str, object]]:
        rows = list(
            (
                await session.scalars(
                    select(CandidateDocumentIntake)
                    .where(CandidateDocumentIntake.owner_id == account_id)
                    .order_by(CandidateDocumentIntake.created_at, CandidateDocumentIntake.id)
                )
            ).all()
        )
        return [self._export_record(self._record(row)) for row in rows]

    async def erase_account_intake_metadata(
        self,
        session: AsyncSession,
        *,
        account_id: UUID,
    ) -> int:
        result = await session.execute(
            delete(CandidateDocumentIntake)
            .where(CandidateDocumentIntake.owner_id == account_id)
            .returning(CandidateDocumentIntake.id)
        )
        return len(result.scalars().all())

    async def _claim(
        self,
        *,
        account_id: UUID,
        preparation_id: UUID,
        document_type: CandidateDocumentType,
        source_kind: CandidateDocumentSource,
        declared_media_type: str,
        content_length: int,
        key_hash: str,
        request_digest: str,
        request_id: str | None,
        submitted_at: datetime,
    ) -> _IntakeClaim:
        async with self._database.transaction() as session:
            account = await session.scalar(
                select(Account).where(Account.id == account_id).with_for_update()
            )
            if account is None or account.status != "active":
                raise CandidateDocumentIntakeConflictError("the account cannot submit documents")
            intake = await session.scalar(
                select(CandidateDocumentIntake)
                .where(
                    CandidateDocumentIntake.owner_id == account_id,
                    CandidateDocumentIntake.idempotency_key_hash == key_hash,
                )
                .with_for_update()
            )
            if intake is not None:
                self._require_same_request(
                    intake,
                    preparation_id=preparation_id,
                    document_type=document_type,
                    source_kind=source_kind,
                    declared_media_type=declared_media_type,
                    content_length=content_length,
                    request_digest=request_digest,
                )
                if intake.status in {"completed", "rejected"} or (
                    intake.status == "processing"
                    and intake.processing_lease_until is not None
                    and intake.processing_lease_until > submitted_at
                ):
                    return _IntakeClaim(
                        intake.id,
                        intake.reserved_file_asset_id,
                        None,
                        False,
                        False,
                        self._record(intake),
                    )

            preparation = await session.scalar(
                select(CandidatePreparation)
                .where(
                    CandidatePreparation.id == preparation_id,
                    CandidatePreparation.owner_id == account_id,
                )
                .with_for_update()
            )
            if preparation is None:
                raise CandidateDocumentIntakeNotFoundError("preparation was not found")
            if preparation.status != "draft":
                raise CandidateDocumentIntakeConflictError(
                    "documents cannot be submitted to an archived preparation"
                )
            decision = await authorize_processing(
                session,
                account_id=account_id,
                data_category=DATA_CATEGORY,
                purpose=PROCESSING_PURPOSE,
                now=submitted_at,
            )
            if decision.retention_action != "delete":
                raise CandidateDocumentIntakeConflictError(
                    "candidate document intake requires delete retention"
                )

            created = intake is None
            processing_token = uuid7()
            if intake is None:
                intake = CandidateDocumentIntake(
                    owner_id=account_id,
                    preparation_id=preparation_id,
                    document_type=document_type,
                    source_kind=source_kind,
                    status="processing",
                    idempotency_key_hash=key_hash,
                    request_digest=request_digest,
                    declared_media_type=declared_media_type,
                    content_length=content_length,
                    reserved_file_asset_id=uuid7(),
                    attempts=1,
                    processing_lease_until=submitted_at + PROCESSING_LEASE,
                    processing_token=processing_token,
                    privacy_policy_version_id=decision.privacy_policy_version_id,
                    jurisdiction_code=decision.jurisdiction_code,
                    legal_basis=decision.legal_basis,
                    retention_rule_id=decision.retention_rule_id,
                    retain_until=submitted_at + timedelta(days=decision.retention_days),
                    retention_action="delete",
                    created_at=submitted_at,
                    updated_at=submitted_at,
                )
                session.add(intake)
                await session.flush()
                await self._record_transition(
                    session,
                    intake=intake,
                    profile=(await require_privacy_profile(session, account_id, now=submitted_at))[
                        0
                    ],
                    account_id=account_id,
                    request_id=request_id,
                    action="candidate_document.intake_started",
                    occurred_at=submitted_at,
                )
            else:
                if (
                    intake.status == "scan_failed"
                    and intake.last_error_code in _ROTATE_ASSET_ERRORS
                ):
                    intake.reserved_file_asset_id = uuid7()
                    intake.file_asset_id = None
                intake.status = "processing"
                intake.processing_lease_until = submitted_at + PROCESSING_LEASE
                intake.processing_token = processing_token
                intake.last_error_code = None
                intake.completed_at = None
                intake.attempts += 1
                intake.updated_at = submitted_at
            await session.flush()
            await session.refresh(intake)
            return _IntakeClaim(
                intake.id,
                intake.reserved_file_asset_id,
                processing_token,
                created,
                True,
                self._record(intake),
            )

    async def _record_asset(
        self,
        account_id: UUID,
        intake_id: UUID,
        processing_token: UUID,
        file_asset_id: UUID,
    ) -> None:
        async with self._database.transaction() as session:
            intake = await self._owned_claim(
                session,
                account_id,
                intake_id,
                processing_token,
            )
            if intake.reserved_file_asset_id != file_asset_id:
                raise CandidateDocumentIntakeConflictError(
                    "the file asset does not match the intake reservation"
                )
            intake.file_asset_id = file_asset_id
            await session.flush()

    async def _finish(
        self,
        account_id: UUID,
        intake_id: UUID,
        processing_token: UUID,
        *,
        status: CandidateDocumentIntakeStatus,
        error_code: str | None,
        request_id: str | None,
        finished_at: datetime,
        file_asset_id: UUID | None = None,
        document_id: UUID | None = None,
        document_version_id: UUID | None = None,
    ) -> CandidateDocumentIntakeRecord:
        if status not in {"scan_failed", "rejected", "completed"}:
            raise ValueError("the intake terminal transition is unsupported")
        async with self._database.transaction() as session:
            intake = await self._owned_claim(
                session,
                account_id,
                intake_id,
                processing_token,
            )
            intake.status = status
            intake.processing_lease_until = None
            intake.processing_token = None
            intake.last_error_code = error_code
            intake.completed_at = finished_at if status == "completed" else None
            intake.updated_at = finished_at
            if file_asset_id is not None:
                if intake.reserved_file_asset_id != file_asset_id:
                    raise CandidateDocumentIntakeConflictError(
                        "the completed file asset does not match the reservation"
                    )
                intake.file_asset_id = file_asset_id
            if document_id is not None:
                intake.document_id = document_id
            if document_version_id is not None:
                intake.document_version_id = document_version_id
            profile, _ = await require_privacy_profile(session, account_id, now=finished_at)
            await self._record_transition(
                session,
                intake=intake,
                profile=profile,
                account_id=account_id,
                request_id=request_id,
                action=f"candidate_document.intake_{status}",
                occurred_at=finished_at,
            )
            await session.flush()
            await session.refresh(intake)
            return self._record(intake)

    @staticmethod
    async def _owned_claim(
        session: AsyncSession,
        account_id: UUID,
        intake_id: UUID,
        processing_token: UUID,
    ) -> CandidateDocumentIntake:
        intake = await session.scalar(
            select(CandidateDocumentIntake)
            .where(
                CandidateDocumentIntake.id == intake_id,
                CandidateDocumentIntake.owner_id == account_id,
                CandidateDocumentIntake.status == "processing",
                CandidateDocumentIntake.processing_token == processing_token,
            )
            .with_for_update()
        )
        if intake is None:
            raise CandidateDocumentIntakeConflictError("the intake processing claim was lost")
        return intake

    @staticmethod
    def _normalize_contract(
        document_type: CandidateDocumentType,
        source_kind: CandidateDocumentSource,
        declared_media_type: str,
    ) -> tuple[CandidateDocumentType, CandidateDocumentSource, str]:
        normalized_type = document_type.strip().lower()
        normalized_source = source_kind.strip().lower()
        normalized_media = declared_media_type.split(";", 1)[0].strip().lower()
        if normalized_type not in DOCUMENT_TYPES:
            raise ValueError("document_type is not supported")
        if normalized_source not in DOCUMENT_SOURCES:
            raise ValueError("source_kind is not supported")
        if normalized_media not in ALLOWED_MEDIA_TYPES:
            raise UploadValidationError("media_type_not_allowed")
        if normalized_source == "paste" and normalized_media != TEXT_MEDIA_TYPE:
            raise UploadValidationError("paste_must_be_plain_text")
        return normalized_type, normalized_source, normalized_media  # type: ignore[return-value]

    @staticmethod
    def _request_digest(
        preparation_id: UUID,
        document_type: CandidateDocumentType,
        source_kind: CandidateDocumentSource,
        media_type: str,
        content: bytes,
    ) -> str:
        content_digest = hashlib.sha256(content).hexdigest()
        canonical = "\x00".join(
            (str(preparation_id), document_type, source_kind, media_type, content_digest)
        )
        return hashlib.sha256(canonical.encode()).hexdigest()

    @staticmethod
    def _require_same_request(
        intake: CandidateDocumentIntake,
        *,
        preparation_id: UUID,
        document_type: CandidateDocumentType,
        source_kind: CandidateDocumentSource,
        declared_media_type: str,
        content_length: int,
        request_digest: str,
    ) -> None:
        if (
            intake.preparation_id != preparation_id
            or intake.document_type != document_type
            or intake.source_kind != source_kind
            or intake.declared_media_type != declared_media_type
            or intake.content_length != content_length
            or intake.request_digest != request_digest
        ):
            raise CandidateDocumentIntakeConflictError(
                "the idempotency key was used for another document request"
            )

    @staticmethod
    async def _record_transition(
        session: AsyncSession,
        *,
        intake: CandidateDocumentIntake,
        profile: PrivacyProfile,
        account_id: UUID,
        request_id: str | None,
        action: str,
        occurred_at: datetime,
    ) -> None:
        details = {
            "document_type": intake.document_type,
            "source_kind": intake.source_kind,
            "status": intake.status,
            "attempts": intake.attempts,
            "error_code": intake.last_error_code,
        }
        await record_privacy_audit(
            session,
            profile=profile,
            occurred_at=occurred_at,
            actor_id=account_id,
            action=action,
            resource_type="candidate_document_intake",
            resource_id=intake.id,
            owner_id=account_id,
            request_id=request_id,
            details=details,
        )
        await enqueue_outbox(
            session,
            NewOutboxEvent(
                aggregate_type="candidate_document_intake",
                aggregate_id=intake.id,
                event_type=action,
                owner_id=account_id,
                payload={"candidate_document_intake_id": str(intake.id), **details},
            ),
        )

    @staticmethod
    def _record(intake: CandidateDocumentIntake) -> CandidateDocumentIntakeRecord:
        return CandidateDocumentIntakeRecord(
            intake_id=intake.id,
            preparation_id=intake.preparation_id,
            document_type=intake.document_type,
            source_kind=intake.source_kind,
            status=intake.status,
            declared_media_type=intake.declared_media_type,
            content_length=intake.content_length,
            attempts=intake.attempts,
            last_error_code=intake.last_error_code,
            file_asset_id=intake.file_asset_id,
            document_id=intake.document_id,
            document_version_id=intake.document_version_id,
            aggregate_version=intake.version,
            created_at=intake.created_at,
            updated_at=intake.updated_at,
            completed_at=intake.completed_at,
            retain_until=intake.retain_until,
        )

    @staticmethod
    def _export_record(intake: CandidateDocumentIntakeRecord) -> dict[str, object]:
        return {
            "intake_id": str(intake.intake_id),
            "preparation_id": str(intake.preparation_id),
            "document_type": intake.document_type,
            "source_kind": intake.source_kind,
            "status": intake.status,
            "declared_media_type": intake.declared_media_type,
            "content_length": intake.content_length,
            "attempts": intake.attempts,
            "last_error_code": intake.last_error_code,
            "file_asset_id": str(intake.file_asset_id) if intake.file_asset_id else None,
            "document_id": str(intake.document_id) if intake.document_id else None,
            "document_version_id": (
                str(intake.document_version_id) if intake.document_version_id else None
            ),
            "created_at": intake.created_at.isoformat(),
            "updated_at": intake.updated_at.isoformat(),
            "completed_at": (
                intake.completed_at.isoformat() if intake.completed_at is not None else None
            ),
            "retain_until": intake.retain_until.isoformat(),
        }


async def apply_due_candidate_document_intake_retention(
    session: AsyncSession,
    *,
    now: datetime | None = None,
) -> int:
    evaluated_at = now or datetime.now(UTC)
    result = await session.execute(
        delete(CandidateDocumentIntake)
        .where(CandidateDocumentIntake.retain_until <= evaluated_at)
        .returning(CandidateDocumentIntake.id)
    )
    return len(result.scalars().all())


def build_candidate_document_intakes(
    settings: Settings,
    database: DatabaseRuntime,
    files: FileIntakeRuntime,
    documents: CandidateDocumentRuntime,
) -> CandidateDocumentIntakeRuntime:
    if not settings.privacy_enabled or not settings.file_security_enabled:
        return FailClosedCandidateDocumentIntakeService()
    return CandidateDocumentIntakeService(database, files, documents)
