"""Secure file state machine and durable object-deletion orchestration."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Protocol
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from uuid6 import uuid7

from ai_interviewer.core.config import Settings
from ai_interviewer.core.telemetry import DisabledTelemetry, TelemetryRuntime
from ai_interviewer.file_security.models import (
    FileAsset,
    FileDeletionTask,
    FileScanAttempt,
    ParserReleasePolicy,
)
from ai_interviewer.file_security.object_store import (
    ObjectStoreError,
    S3EncryptedObjectStore,
    SecureObjectStore,
)
from ai_interviewer.file_security.scanner import (
    ClamAVScanner,
    MalwareScanner,
    MalwareScannerError,
    ScanResult,
)
from ai_interviewer.file_security.telemetry import (
    InstrumentedMalwareScanner,
    InstrumentedObjectStore,
)
from ai_interviewer.file_security.validation import validate_upload
from ai_interviewer.persistence.database import DatabaseRuntime
from ai_interviewer.persistence.repositories import NewOutboxEvent, enqueue_outbox
from ai_interviewer.privacy.models import PrivacyProfile, RetentionAction
from ai_interviewer.privacy.rules import authorize_processing, resolve_retention_for_context


class FileSecurityUnavailableError(RuntimeError):
    """The file-security subsystem is disabled or cannot safely process content."""


class FileAssetNotFoundError(LookupError):
    """An owner-scoped file asset was not found."""


class FileStateConflictError(RuntimeError):
    """A file operation is invalid for the persisted state."""


@dataclass(frozen=True, slots=True)
class FileExportRecord:
    id: UUID
    data_category: str
    purpose: str
    media_type: str
    content_length: int
    content_sha256: str
    status: str
    created_at: datetime
    retain_until: datetime

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": str(self.id),
            "data_category": self.data_category,
            "purpose": self.purpose,
            "media_type": self.media_type,
            "content_length": self.content_length,
            "content_sha256": self.content_sha256,
            "status": self.status,
            "created_at": self.created_at.isoformat(),
            "retain_until": self.retain_until.isoformat(),
        }


class FileLifecycleAdapter(Protocol):
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


class FileAssetReferenceLifecycleAdapter(Protocol):
    """Release product metadata references immediately before an asset row is erased."""

    async def release_file_asset_reference(
        self,
        session: AsyncSession,
        *,
        file_asset_id: UUID,
    ) -> int: ...


class _NoFileAssetReferenceLifecycle:
    async def release_file_asset_reference(
        self,
        session: AsyncSession,
        *,
        file_asset_id: UUID,
    ) -> int:
        del session, file_asset_id
        return 0


class DisabledFileSecurity:
    """No-op deletion/export adapter plus fail-closed content operations."""

    async def is_ready(self) -> bool:
        return True

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
    ) -> FileAsset:
        del (
            account_id,
            data_category,
            purpose,
            declared_media_type,
            content,
            file_asset_id,
            now,
        )
        raise FileSecurityUnavailableError("file security is disabled")

    async def scan_and_release(
        self,
        *,
        account_id: UUID,
        file_asset_id: UUID,
        now: datetime | None = None,
    ) -> FileAsset:
        del account_id, file_asset_id, now
        raise FileSecurityUnavailableError("file security is disabled")

    async def read_for_parser(
        self,
        *,
        account_id: UUID,
        file_asset_id: UUID,
        parser_adapter: str,
        parser_version: str,
        isolation_profile: str,
        now: datetime | None = None,
    ) -> bytes:
        del (
            account_id,
            file_asset_id,
            parser_adapter,
            parser_version,
            isolation_profile,
            now,
        )
        raise FileSecurityUnavailableError("file security is disabled")

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


class FileSecurityService:
    """Coordinates policy-gated quarantine, scanning, release, and erasure."""

    def __init__(
        self,
        *,
        database: DatabaseRuntime,
        object_store: SecureObjectStore,
        scanner: MalwareScanner,
        bucket: str,
        kms_key_id: str,
        maximum_upload_bytes: int,
        maximum_archive_entries: int,
        maximum_archive_uncompressed_bytes: int,
        maximum_deletion_attempts: int = 10,
        deletion_retry_base_seconds: int = 60,
        reference_lifecycle: FileAssetReferenceLifecycleAdapter | None = None,
        telemetry: TelemetryRuntime | None = None,
    ) -> None:
        self._database = database
        self._object_store = object_store
        self._scanner = scanner
        self._bucket = bucket
        self._kms_key_id = kms_key_id
        self._maximum_upload_bytes = maximum_upload_bytes
        self._maximum_archive_entries = maximum_archive_entries
        self._maximum_archive_uncompressed_bytes = maximum_archive_uncompressed_bytes
        self._maximum_deletion_attempts = maximum_deletion_attempts
        self._deletion_retry_base_seconds = deletion_retry_base_seconds
        self._reference_lifecycle = reference_lifecycle or _NoFileAssetReferenceLifecycle()
        self._telemetry = telemetry or DisabledTelemetry()

    async def is_ready(self) -> bool:
        storage_ready, scanner_ready = await self._readiness_checks()
        return storage_ready and scanner_ready

    async def _readiness_checks(self) -> tuple[bool, bool]:
        results = await asyncio.gather(self._object_store.is_ready(), self._scanner.is_ready())
        return results[0], results[1]

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
    ) -> FileAsset:
        created_at = now or datetime.now(UTC)
        async with self._database.transaction() as session:
            decision = await authorize_processing(
                session,
                account_id=account_id,
                data_category=data_category,
                purpose=purpose,
                now=created_at,
            )
            profile = await session.get(PrivacyProfile, account_id)
            if profile is None:
                raise FileStateConflictError("privacy profile is unavailable")
            policy = await self._resolve_parser_policy(
                session,
                privacy_policy_version_id=profile.privacy_policy_version_id,
                data_category=data_category,
                purpose=purpose,
                media_type=declared_media_type.strip().lower(),
                now=created_at,
            )
            validated = validate_upload(
                content,
                declared_media_type=declared_media_type,
                maximum_bytes=min(self._maximum_upload_bytes, policy.maximum_bytes),
                maximum_archive_entries=self._maximum_archive_entries,
                maximum_archive_uncompressed_bytes=self._maximum_archive_uncompressed_bytes,
            )
            retention = await resolve_retention_for_context(
                session,
                privacy_policy_version_id=profile.privacy_policy_version_id,
                jurisdiction_codes=profile.jurisdiction_codes,
                data_category=data_category,
                purpose=purpose,
            )
            asset_id = file_asset_id or uuid7()
            asset = await session.scalar(
                select(FileAsset).where(FileAsset.id == asset_id).with_for_update()
            )
            if asset is not None:
                self._require_resumable_asset(
                    asset,
                    account_id=account_id,
                    privacy_policy_version_id=profile.privacy_policy_version_id,
                    jurisdiction_code=decision.jurisdiction_code,
                    data_category=data_category,
                    purpose=purpose,
                    media_type=validated.media_type,
                    content_length=validated.content_length,
                    content_sha256=validated.content_sha256,
                    parser_release_policy_id=policy.id,
                    evaluated_at=created_at,
                )
                if asset.status != "upload_pending":
                    return asset
            else:
                asset = FileAsset(
                    id=asset_id,
                    account_id=account_id,
                    privacy_policy_version_id=profile.privacy_policy_version_id,
                    jurisdiction_code=decision.jurisdiction_code,
                    data_category=data_category,
                    purpose=purpose,
                    status="upload_pending",
                    bucket=self._bucket,
                    quarantine_object_key=f"quarantine/{asset_id.hex[:2]}/{asset_id}",
                    kms_key_id=self._kms_key_id,
                    media_type=validated.media_type,
                    content_length=validated.content_length,
                    content_sha256=validated.content_sha256,
                    parser_release_policy_id=policy.id,
                    retain_until=created_at + timedelta(days=retention.retention_days),
                    retention_action=retention.action,
                )
                session.add(asset)
                await session.flush()

        try:
            stored = await self._object_store.put_quarantined(
                key=asset.quarantine_object_key,
                content=validated.content,
                content_type=validated.media_type,
                content_sha256=validated.content_sha256,
            )
        except ObjectStoreError:
            await self._schedule_failed_upload_cleanup(asset.id, created_at)
            raise

        try:
            async with self._database.transaction() as session:
                persisted = await self._locked_asset(session, asset.id)
                if persisted.status != "upload_pending":
                    self._require_resumable_asset(
                        persisted,
                        account_id=account_id,
                        privacy_policy_version_id=profile.privacy_policy_version_id,
                        jurisdiction_code=decision.jurisdiction_code,
                        data_category=data_category,
                        purpose=purpose,
                        media_type=validated.media_type,
                        content_length=validated.content_length,
                        content_sha256=validated.content_sha256,
                        parser_release_policy_id=policy.id,
                        evaluated_at=created_at,
                    )
                    return persisted
                persisted.quarantine_version_id = stored.version_id
                persisted.status = "quarantined"
                await enqueue_outbox(
                    session,
                    NewOutboxEvent(
                        aggregate_type="file_asset",
                        aggregate_id=persisted.id,
                        event_type="file.quarantine.ready_for_scan",
                        owner_id=persisted.account_id,
                        payload={"file_asset_id": str(persisted.id)},
                    ),
                )
                await session.flush()
                return persisted
        except Exception:
            await self._schedule_failed_upload_cleanup(asset.id, created_at)
            raise

    async def scan_and_release(
        self,
        *,
        account_id: UUID,
        file_asset_id: UUID,
        now: datetime | None = None,
    ) -> FileAsset:
        scanned_at = now or datetime.now(UTC)
        clean_asset: FileAsset | None = None
        async with self._database.transaction() as session:
            asset = await self._owned_asset(session, account_id, file_asset_id)
            if asset.status == "clean":
                clean_asset = asset
            elif asset.status not in {"quarantined", "scan_failed"}:
                raise FileStateConflictError("file is not eligible for malware scanning")
            if clean_asset is None and asset.quarantine_version_id is None:
                raise FileStateConflictError("quarantine object version is missing")
            snapshot = self._snapshot(asset)

        if clean_asset is not None:
            return await self._promote_clean(clean_asset, scanned_at)

        try:
            content = await self._object_store.read_verified(
                key=snapshot.quarantine_object_key,
                version_id=snapshot.quarantine_version_id or "",
                expected_sha256=snapshot.content_sha256,
                maximum_bytes=min(self._maximum_upload_bytes, snapshot.content_length),
            )
            result = await self._scanner.scan(content, now=scanned_at)
        except (ObjectStoreError, MalwareScannerError) as exc:
            error_code = (
                "storage_verification_failed"
                if isinstance(exc, ObjectStoreError)
                else "scan_failed"
            )
            return await self._record_scan_error(account_id, file_asset_id, error_code, scanned_at)

        asset = await self._record_scan_result(account_id, file_asset_id, result, scanned_at)
        if result.verdict == "infected":
            return asset
        return await self._promote_clean(asset, scanned_at)

    async def read_for_parser(
        self,
        *,
        account_id: UUID,
        file_asset_id: UUID,
        parser_adapter: str,
        parser_version: str,
        isolation_profile: str,
        now: datetime | None = None,
    ) -> bytes:
        evaluated_at = now or datetime.now(UTC)
        async with self._database.transaction() as session:
            asset = await self._owned_asset(session, account_id, file_asset_id)
            if (
                asset.status != "released"
                or asset.released_object_key is None
                or asset.released_version_id is None
                or asset.parser_release_policy_id is None
            ):
                raise FileStateConflictError("file is not released for parsing")
            policy = await session.get(ParserReleasePolicy, asset.parser_release_policy_id)
            if (
                policy is None
                or policy.status != "active"
                or policy.approved_at > evaluated_at
                or policy.parser_adapter != parser_adapter
                or policy.parser_version != parser_version
                or policy.isolation_profile != isolation_profile
            ):
                raise FileStateConflictError("parser release policy is unavailable or mismatched")
            snapshot = self._snapshot(asset)
        return await self._object_store.read_verified(
            key=snapshot.released_object_key or "",
            version_id=snapshot.released_version_id or "",
            expected_sha256=snapshot.content_sha256,
            maximum_bytes=min(self._maximum_upload_bytes, snapshot.content_length),
        )

    async def claim_deletion_tasks(
        self,
        *,
        worker_id: str,
        limit: int,
        now: datetime | None = None,
    ) -> list[FileDeletionTask]:
        if not worker_id or len(worker_id) > 128:
            raise ValueError("worker_id must contain 1-128 characters")
        if limit < 1 or limit > 100:
            raise ValueError("limit must be between 1 and 100")
        claimed_at = now or datetime.now(UTC)
        stale_before = claimed_at - timedelta(minutes=5)
        async with self._database.transaction() as session:
            statement = (
                select(FileDeletionTask)
                .where(
                    FileDeletionTask.status.in_(("pending", "retry", "processing")),
                    FileDeletionTask.available_at <= claimed_at,
                    (
                        FileDeletionTask.locked_at.is_(None)
                        | (FileDeletionTask.locked_at < stale_before)
                    ),
                )
                .order_by(FileDeletionTask.available_at, FileDeletionTask.id)
                .limit(limit)
                .with_for_update(skip_locked=True)
            )
            tasks = list((await session.scalars(statement)).all())
            for task in tasks:
                task.status = "processing"
                task.locked_at = claimed_at
                task.locked_by = worker_id
            await session.flush()
        if tasks:
            self._telemetry.record_deletion_transition("file", "processing", len(tasks))
        return tasks

    async def schedule_due_retention(
        self,
        *,
        limit: int = 100,
        now: datetime | None = None,
    ) -> int:
        if limit < 1 or limit > 1_000:
            raise ValueError("retention batch limit must be between 1 and 1000")
        evaluated_at = now or datetime.now(UTC)
        async with self._database.transaction() as session:
            assets = list(
                (
                    await session.scalars(
                        select(FileAsset)
                        .where(
                            FileAsset.retain_until <= evaluated_at,
                            FileAsset.status != "deletion_pending",
                        )
                        .order_by(FileAsset.retain_until, FileAsset.id)
                        .limit(limit)
                        .with_for_update(skip_locked=True)
                    )
                ).all()
            )
            for asset in assets:
                profile = await session.get(PrivacyProfile, asset.account_id)
                if profile is None:
                    raise FileStateConflictError("retention deletion requires a privacy profile")
                task_retention = await resolve_retention_for_context(
                    session,
                    privacy_policy_version_id=profile.privacy_policy_version_id,
                    jurisdiction_codes=profile.jurisdiction_codes,
                    data_category="file_deletion_evidence",
                    purpose="privacy_administration",
                )
                await self._schedule_deletion_task(
                    session,
                    asset=asset,
                    task_kind="asset_deletion",
                    privacy_request_id=None,
                    retain_until=evaluated_at + timedelta(days=task_retention.retention_days),
                    retention_action=task_retention.action,
                    now=evaluated_at,
                )
                asset.status = "deletion_pending"
            return len(assets)

    async def purge_due_deletion_evidence(
        self,
        *,
        limit: int = 100,
        now: datetime | None = None,
    ) -> int:
        if limit < 1 or limit > 1_000:
            raise ValueError("retention batch limit must be between 1 and 1000")
        evaluated_at = now or datetime.now(UTC)
        async with self._database.transaction() as session:
            tasks = list(
                (
                    await session.scalars(
                        select(FileDeletionTask)
                        .where(
                            FileDeletionTask.status == "completed",
                            FileDeletionTask.retain_until <= evaluated_at,
                        )
                        .order_by(FileDeletionTask.retain_until, FileDeletionTask.id)
                        .limit(limit)
                        .with_for_update(skip_locked=True)
                    )
                ).all()
            )
            for task in tasks:
                await session.delete(task)
            return len(tasks)

    async def execute_deletion_task(
        self,
        *,
        task_id: UUID,
        worker_id: str,
        now: datetime | None = None,
    ) -> FileDeletionTask:
        completed_at = now or datetime.now(UTC)
        async with self._database.transaction() as session:
            task = await self._locked_task(session, task_id)
            if task.status != "processing" or task.locked_by != worker_id:
                raise FileStateConflictError("file deletion task is not claimed by this worker")
            quarantine_key = task.quarantine_object_key
            released_key = task.released_object_key

        try:
            if quarantine_key is not None:
                await self._object_store.delete_all_versions(key=quarantine_key)
            if released_key is not None and released_key != quarantine_key:
                await self._object_store.delete_all_versions(key=released_key)
        except ObjectStoreError:
            failed_task = await self._fail_deletion_task(task_id, worker_id, completed_at)
            self._telemetry.record_deletion_transition(
                "file",
                "escalated" if failed_task.status == "escalated" else "retry",
            )
            return failed_task

        async with self._database.transaction() as session:
            task = await self._locked_task(session, task_id)
            if task.status != "processing" or task.locked_by != worker_id:
                raise FileStateConflictError("file deletion task claim was lost")
            asset = (
                await self._locked_asset(session, task.file_asset_id)
                if task.file_asset_id is not None
                else None
            )
            task.status = "completed"
            task.completed_at = completed_at
            task.locked_at = None
            task.locked_by = None
            task.last_error_code = None
            task.quarantine_object_key = None
            task.released_object_key = None
            task.account_id = None
            if task.task_kind == "asset_deletion" and asset is not None:
                await self._reference_lifecycle.release_file_asset_reference(
                    session,
                    file_asset_id=asset.id,
                )
                await session.delete(asset)
            if task.privacy_request_id is not None:
                await enqueue_outbox(
                    session,
                    NewOutboxEvent(
                        aggregate_type="privacy_request",
                        aggregate_id=task.privacy_request_id,
                        event_type="privacy.file_deletion.completed",
                        payload={"privacy_request_id": str(task.privacy_request_id)},
                    ),
                )
            await session.flush()
        self._telemetry.record_deletion_transition("file", "completed")
        return task

    async def requeue_escalated_deletion_task(
        self,
        *,
        task_id: UUID,
        now: datetime | None = None,
    ) -> FileDeletionTask:
        requeued_at = now or datetime.now(UTC)
        async with self._database.transaction() as session:
            task = await self._locked_task(session, task_id)
            if task.status != "escalated" or (
                task.quarantine_object_key is None and task.released_object_key is None
            ):
                raise FileStateConflictError(
                    "only an escalated task with object keys can be requeued"
                )
            task.status = "retry"
            task.available_at = requeued_at
            task.last_error_code = None
            await enqueue_outbox(
                session,
                NewOutboxEvent(
                    aggregate_type="file_deletion_task",
                    aggregate_id=task.id,
                    event_type="file.deletion.manually_requeued",
                    payload={"file_deletion_task_id": str(task.id)},
                ),
            )
            await session.flush()
        self._telemetry.record_deletion_transition("file", "retry")
        return task

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
        assets = list(
            (
                await session.scalars(
                    select(FileAsset)
                    .where(FileAsset.account_id == account_id)
                    .order_by(FileAsset.id)
                    .with_for_update()
                )
            ).all()
        )
        for asset in assets:
            await self._schedule_deletion_task(
                session,
                asset=asset,
                task_kind="asset_deletion",
                privacy_request_id=privacy_request_id,
                retain_until=retain_until,
                retention_action=retention_action,
                now=now,
            )
            asset.status = "deletion_pending"
        return len(assets)

    async def has_pending_account_deletion(
        self,
        session: AsyncSession,
        *,
        privacy_request_id: UUID,
    ) -> bool:
        count = await session.scalar(
            select(func.count())
            .select_from(FileDeletionTask)
            .where(
                FileDeletionTask.privacy_request_id == privacy_request_id,
                FileDeletionTask.task_kind == "asset_deletion",
                FileDeletionTask.status != "completed",
            )
        )
        return bool(count)

    async def export_account_metadata(
        self,
        session: AsyncSession,
        *,
        account_id: UUID,
    ) -> list[dict[str, Any]]:
        assets = list(
            (
                await session.scalars(
                    select(FileAsset)
                    .where(FileAsset.account_id == account_id)
                    .order_by(FileAsset.created_at, FileAsset.id)
                )
            ).all()
        )
        return [
            FileExportRecord(
                id=asset.id,
                data_category=asset.data_category,
                purpose=asset.purpose,
                media_type=asset.media_type,
                content_length=asset.content_length,
                content_sha256=asset.content_sha256,
                status=asset.status,
                created_at=asset.created_at,
                retain_until=asset.retain_until,
            ).as_dict()
            for asset in assets
        ]

    async def _record_scan_error(
        self,
        account_id: UUID,
        file_asset_id: UUID,
        error_code: str,
        scanned_at: datetime,
    ) -> FileAsset:
        async with self._database.transaction() as session:
            asset = await self._owned_locked_asset(session, account_id, file_asset_id)
            attempt = await self._next_scan_attempt(session, asset.id)
            session.add(
                FileScanAttempt(
                    file_asset_id=asset.id,
                    attempt_number=attempt,
                    status="error",
                    error_code=error_code,
                    scanned_at=scanned_at,
                )
            )
            asset.status = "scan_failed"
            await session.flush()
            return asset

    async def _record_scan_result(
        self,
        account_id: UUID,
        file_asset_id: UUID,
        result: ScanResult,
        scanned_at: datetime,
    ) -> FileAsset:
        async with self._database.transaction() as session:
            asset = await self._owned_locked_asset(session, account_id, file_asset_id)
            if asset.status not in {"quarantined", "scan_failed"}:
                raise FileStateConflictError("file scan state changed before acknowledgement")
            attempt = await self._next_scan_attempt(session, asset.id)
            session.add(
                FileScanAttempt(
                    file_asset_id=asset.id,
                    attempt_number=attempt,
                    status=result.verdict,
                    scanner_engine_version=result.version.engine_version,
                    scanner_signature_version=result.version.signature_version,
                    scanner_signature_date=result.version.signature_date,
                    malware_signature_sha256=result.malware_signature_sha256,
                    scanned_at=scanned_at,
                )
            )
            if result.verdict == "infected":
                asset.status = "deletion_pending"
                await self._schedule_deletion_task(
                    session,
                    asset=asset,
                    task_kind="asset_deletion",
                    privacy_request_id=None,
                    retain_until=asset.retain_until,
                    retention_action=asset.retention_action,
                    now=scanned_at,
                )
                event_type = "file.quarantine.infected"
            else:
                asset.status = "clean"
                asset.released_object_key = f"released/{asset.id.hex[:2]}/{asset.id}"
                event_type = "file.quarantine.clean"
            await enqueue_outbox(
                session,
                NewOutboxEvent(
                    aggregate_type="file_asset",
                    aggregate_id=asset.id,
                    event_type=event_type,
                    owner_id=asset.account_id,
                    payload={"file_asset_id": str(asset.id)},
                ),
            )
            await session.flush()
            return asset

    async def _promote_clean(self, asset: FileAsset, now: datetime) -> FileAsset:
        if asset.status != "clean" or asset.quarantine_version_id is None:
            raise FileStateConflictError("only a clean file can be promoted")
        destination_key = asset.released_object_key or f"released/{asset.id.hex[:2]}/{asset.id}"
        stored = await self._object_store.promote_clean(
            source_key=asset.quarantine_object_key,
            source_version_id=asset.quarantine_version_id,
            destination_key=destination_key,
            content_type=asset.media_type,
            content_sha256=asset.content_sha256,
        )
        try:
            async with self._database.transaction() as session:
                persisted = await self._owned_locked_asset(session, asset.account_id, asset.id)
                if persisted.status != "clean":
                    raise FileStateConflictError(
                        "clean file state changed before promotion acknowledgement"
                    )
                policy = await session.get(ParserReleasePolicy, persisted.parser_release_policy_id)
                if policy is None or policy.status != "active" or policy.approved_at > now:
                    raise FileStateConflictError("parser release policy is no longer active")
                persisted.status = "released"
                persisted.released_object_key = destination_key
                persisted.released_version_id = stored.version_id
                persisted.released_at = now
                await self._schedule_deletion_task(
                    session,
                    asset=persisted,
                    task_kind="quarantine_cleanup",
                    privacy_request_id=None,
                    retain_until=persisted.retain_until,
                    retention_action=persisted.retention_action,
                    now=now,
                )
                await enqueue_outbox(
                    session,
                    NewOutboxEvent(
                        aggregate_type="file_asset",
                        aggregate_id=persisted.id,
                        event_type="file.released_for_parser",
                        owner_id=persisted.account_id,
                        payload={
                            "file_asset_id": str(persisted.id),
                            "parser_release_policy_id": str(persisted.parser_release_policy_id),
                        },
                    ),
                )
                await session.flush()
                return persisted
        except Exception:
            await self._schedule_failed_upload_cleanup(asset.id, now)
            raise

    async def _schedule_failed_upload_cleanup(self, asset_id: UUID, now: datetime) -> None:
        async with self._database.transaction() as session:
            asset = await self._locked_asset(session, asset_id)
            asset.status = "deletion_pending"
            await self._schedule_deletion_task(
                session,
                asset=asset,
                task_kind="asset_deletion",
                privacy_request_id=None,
                retain_until=asset.retain_until,
                retention_action=asset.retention_action,
                now=now,
            )

    async def _schedule_deletion_task(
        self,
        session: AsyncSession,
        *,
        asset: FileAsset,
        task_kind: str,
        privacy_request_id: UUID | None,
        retain_until: datetime,
        retention_action: RetentionAction,
        now: datetime,
    ) -> FileDeletionTask:
        existing = await session.scalar(
            select(FileDeletionTask).where(
                FileDeletionTask.file_asset_id == asset.id,
                FileDeletionTask.task_kind == task_kind,
            )
        )
        if existing is not None:
            return existing
        task = FileDeletionTask(
            file_asset_id=asset.id,
            privacy_request_id=privacy_request_id,
            account_id=asset.account_id,
            task_kind=task_kind,
            bucket=asset.bucket,
            quarantine_object_key=asset.quarantine_object_key,
            released_object_key=(
                asset.released_object_key if task_kind == "asset_deletion" else None
            ),
            status="pending",
            available_at=now,
            retain_until=retain_until,
            retention_action=retention_action,
        )
        session.add(task)
        await session.flush()
        await enqueue_outbox(
            session,
            NewOutboxEvent(
                aggregate_type="file_deletion_task",
                aggregate_id=task.id,
                event_type=f"file.deletion.{task_kind}.requested",
                owner_id=asset.account_id,
                payload={
                    "file_deletion_task_id": str(task.id),
                    "privacy_request_id": (
                        str(privacy_request_id) if privacy_request_id is not None else None
                    ),
                },
            ),
        )
        return task

    async def _fail_deletion_task(
        self,
        task_id: UUID,
        worker_id: str,
        failed_at: datetime,
    ) -> FileDeletionTask:
        async with self._database.transaction() as session:
            task = await self._locked_task(session, task_id)
            if task.status != "processing" or task.locked_by != worker_id:
                raise FileStateConflictError("file deletion task claim was lost")
            task.attempts += 1
            task.last_error_code = "object_deletion_failed"
            task.locked_at = None
            task.locked_by = None
            if task.attempts >= self._maximum_deletion_attempts:
                task.status = "escalated"
                event_type = "file.deletion.escalated"
            else:
                task.status = "retry"
                delay = min(
                    self._deletion_retry_base_seconds * (2 ** (task.attempts - 1)),
                    86_400,
                )
                task.available_at = failed_at + timedelta(seconds=delay)
                event_type = "file.deletion.retry_scheduled"
            await enqueue_outbox(
                session,
                NewOutboxEvent(
                    aggregate_type="file_deletion_task",
                    aggregate_id=task.id,
                    event_type=event_type,
                    payload={"file_deletion_task_id": str(task.id), "attempt": task.attempts},
                    available_at=task.available_at if task.status == "retry" else None,
                ),
            )
            await session.flush()
            return task

    @staticmethod
    async def _resolve_parser_policy(
        session: AsyncSession,
        *,
        privacy_policy_version_id: UUID,
        data_category: str,
        purpose: str,
        media_type: str,
        now: datetime,
    ) -> ParserReleasePolicy:
        policies = list(
            (
                await session.scalars(
                    select(ParserReleasePolicy).where(
                        ParserReleasePolicy.privacy_policy_version_id == privacy_policy_version_id,
                        ParserReleasePolicy.data_category == data_category,
                        ParserReleasePolicy.purpose == purpose,
                        ParserReleasePolicy.media_type == media_type,
                        ParserReleasePolicy.status == "active",
                        ParserReleasePolicy.approved_at <= now,
                    )
                )
            ).all()
        )
        if len(policies) != 1 or not policies[0].malware_scan_required:
            raise FileStateConflictError(
                "exactly one scan-required parser release policy is required"
            )
        return policies[0]

    @staticmethod
    async def _next_scan_attempt(session: AsyncSession, asset_id: UUID) -> int:
        current = await session.scalar(
            select(func.max(FileScanAttempt.attempt_number)).where(
                FileScanAttempt.file_asset_id == asset_id
            )
        )
        return int(current or 0) + 1

    @staticmethod
    async def _owned_asset(
        session: AsyncSession,
        account_id: UUID,
        file_asset_id: UUID,
    ) -> FileAsset:
        asset = await session.scalar(
            select(FileAsset).where(
                FileAsset.id == file_asset_id,
                FileAsset.account_id == account_id,
            )
        )
        if asset is None:
            raise FileAssetNotFoundError("file asset was not found")
        return asset

    @staticmethod
    async def _owned_locked_asset(
        session: AsyncSession,
        account_id: UUID,
        file_asset_id: UUID,
    ) -> FileAsset:
        asset = await session.scalar(
            select(FileAsset)
            .where(FileAsset.id == file_asset_id, FileAsset.account_id == account_id)
            .with_for_update()
        )
        if asset is None:
            raise FileAssetNotFoundError("file asset was not found")
        return asset

    @staticmethod
    async def _locked_asset(session: AsyncSession, file_asset_id: UUID) -> FileAsset:
        asset = await session.scalar(
            select(FileAsset).where(FileAsset.id == file_asset_id).with_for_update()
        )
        if asset is None:
            raise FileAssetNotFoundError("file asset was not found")
        return asset

    @staticmethod
    async def _locked_task(session: AsyncSession, task_id: UUID) -> FileDeletionTask:
        task = await session.scalar(
            select(FileDeletionTask).where(FileDeletionTask.id == task_id).with_for_update()
        )
        if task is None:
            raise FileAssetNotFoundError("file deletion task was not found")
        return task

    @staticmethod
    def _snapshot(asset: FileAsset) -> FileAsset:
        return asset

    @staticmethod
    def _require_resumable_asset(
        asset: FileAsset,
        *,
        account_id: UUID,
        privacy_policy_version_id: UUID,
        jurisdiction_code: str,
        data_category: str,
        purpose: str,
        media_type: str,
        content_length: int,
        content_sha256: str,
        parser_release_policy_id: UUID,
        evaluated_at: datetime,
    ) -> None:
        if asset.status == "deletion_pending":
            raise FileStateConflictError("the reserved file asset is pending deletion")
        if (
            asset.account_id != account_id
            or asset.privacy_policy_version_id != privacy_policy_version_id
            or asset.jurisdiction_code != jurisdiction_code
            or asset.data_category != data_category
            or asset.purpose != purpose
            or asset.media_type != media_type
            or asset.content_length != content_length
            or asset.content_sha256 != content_sha256
            or asset.parser_release_policy_id != parser_release_policy_id
            or asset.retention_action != "delete"
            or asset.retain_until <= evaluated_at
        ):
            raise FileStateConflictError("the reserved file asset does not match this upload")


def build_file_security(
    settings: Settings,
    database: DatabaseRuntime,
    *,
    object_store: SecureObjectStore | None = None,
    scanner: MalwareScanner | None = None,
    reference_lifecycle: FileAssetReferenceLifecycleAdapter | None = None,
    telemetry: TelemetryRuntime | None = None,
) -> DisabledFileSecurity | FileSecurityService:
    if not settings.file_security_enabled:
        return DisabledFileSecurity()
    if (
        settings.object_storage_bucket is None
        or settings.object_storage_region is None
        or settings.object_storage_kms_key_id is None
    ):
        raise RuntimeError("file security enabled without complete object storage settings")
    resolved_store = object_store or S3EncryptedObjectStore(
        bucket=settings.object_storage_bucket,
        region=settings.object_storage_region,
        kms_key_id=settings.object_storage_kms_key_id,
        endpoint_url=settings.object_storage_endpoint_url,
        connect_timeout_seconds=settings.object_storage_connect_timeout_seconds,
        read_timeout_seconds=settings.object_storage_read_timeout_seconds,
    )
    resolved_scanner = scanner or ClamAVScanner(
        maximum_stream_bytes=settings.file_security_max_upload_bytes,
        maximum_signature_age=timedelta(hours=settings.malware_scanner_max_signature_age_hours),
        timeout_seconds=settings.malware_scanner_timeout_seconds,
        unix_socket=settings.malware_scanner_unix_socket,
        tcp_host=settings.malware_scanner_tcp_host,
        tcp_port=settings.malware_scanner_tcp_port,
    )
    resolved_telemetry = telemetry or DisabledTelemetry()
    return FileSecurityService(
        database=database,
        object_store=InstrumentedObjectStore(resolved_store, resolved_telemetry),
        scanner=InstrumentedMalwareScanner(resolved_scanner, resolved_telemetry),
        bucket=settings.object_storage_bucket,
        kms_key_id=settings.object_storage_kms_key_id,
        maximum_upload_bytes=settings.file_security_max_upload_bytes,
        maximum_archive_entries=settings.file_security_max_archive_entries,
        maximum_archive_uncompressed_bytes=settings.file_security_max_archive_uncompressed_bytes,
        reference_lifecycle=reference_lifecycle,
        telemetry=resolved_telemetry,
    )
