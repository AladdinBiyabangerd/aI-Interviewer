"""Owner-bound immutable candidate document-version service."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import NoReturn, Protocol
from uuid import UUID

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from ai_interviewer.candidate_inputs.asset_references import (
    release_candidate_file_asset_references,
)
from ai_interviewer.candidate_inputs.document_models import (
    DOCUMENT_SOURCES,
    DOCUMENT_TYPES,
    CandidateDocument,
    CandidateDocumentSource,
    CandidateDocumentType,
    CandidateDocumentVersion,
)
from ai_interviewer.candidate_inputs.models import CandidatePreparation
from ai_interviewer.core.config import Settings
from ai_interviewer.file_security.models import FileAsset
from ai_interviewer.identity.models import Account
from ai_interviewer.persistence.database import DatabaseRuntime
from ai_interviewer.persistence.repositories import NewOutboxEvent, enqueue_outbox
from ai_interviewer.privacy.audit import record_privacy_audit
from ai_interviewer.privacy.models import PrivacyProfile
from ai_interviewer.privacy.rules import authorize_processing, require_privacy_profile

DATA_CATEGORY = "candidate_document"
PROCESSING_PURPOSE = "interview_preparation"


class CandidateDocumentUnavailableError(RuntimeError):
    """The immutable document boundary is disabled or unavailable."""


class CandidateDocumentNotFoundError(LookupError):
    """An owner-scoped preparation or document was not found."""


class CandidateDocumentConflictError(RuntimeError):
    """A document command conflicts with durable state or privacy policy."""


@dataclass(frozen=True, slots=True)
class CandidateDocumentVersionRecord:
    version_id: UUID
    file_asset_id: UUID
    version_number: int
    source_kind: CandidateDocumentSource
    media_type: str
    content_length: int
    content_sha256: str
    created_at: datetime
    retain_until: datetime


@dataclass(frozen=True, slots=True)
class CandidateDocumentRecord:
    document_id: UUID
    preparation_id: UUID
    document_type: CandidateDocumentType
    latest_version_number: int
    aggregate_version: int
    created_at: datetime
    updated_at: datetime
    versions: tuple[CandidateDocumentVersionRecord, ...]


@dataclass(frozen=True, slots=True)
class AttachDocumentVersionResult:
    document: CandidateDocumentRecord
    attached_version: CandidateDocumentVersionRecord
    created: bool


class CandidateDocumentRuntime(Protocol):
    async def attach_released_asset(
        self,
        account_id: UUID,
        preparation_id: UUID,
        document_type: CandidateDocumentType,
        file_asset_id: UUID,
        source_kind: CandidateDocumentSource,
        request_id: str | None,
        *,
        now: datetime | None = None,
    ) -> AttachDocumentVersionResult: ...

    async def list_documents(
        self,
        account_id: UUID,
        preparation_id: UUID,
    ) -> tuple[CandidateDocumentRecord, ...]: ...

    async def get_document(
        self,
        account_id: UUID,
        preparation_id: UUID,
        document_id: UUID,
    ) -> CandidateDocumentRecord: ...

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

    async def release_file_asset_reference(
        self,
        session: AsyncSession,
        *,
        file_asset_id: UUID,
    ) -> int: ...


class FailClosedCandidateDocumentService:
    """Reject document commands until privacy and file security are enabled."""

    @staticmethod
    def _unavailable() -> NoReturn:
        raise CandidateDocumentUnavailableError("candidate documents are not configured")

    async def attach_released_asset(
        self,
        account_id: UUID,
        preparation_id: UUID,
        document_type: CandidateDocumentType,
        file_asset_id: UUID,
        source_kind: CandidateDocumentSource,
        request_id: str | None,
        *,
        now: datetime | None = None,
    ) -> AttachDocumentVersionResult:
        del account_id, preparation_id, document_type, file_asset_id, source_kind, request_id, now
        self._unavailable()

    async def list_documents(
        self,
        account_id: UUID,
        preparation_id: UUID,
    ) -> tuple[CandidateDocumentRecord, ...]:
        del account_id, preparation_id
        self._unavailable()

    async def get_document(
        self,
        account_id: UUID,
        preparation_id: UUID,
        document_id: UUID,
    ) -> CandidateDocumentRecord:
        del account_id, preparation_id, document_id
        self._unavailable()

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

    async def release_file_asset_reference(
        self,
        session: AsyncSession,
        *,
        file_asset_id: UUID,
    ) -> int:
        del session, file_asset_id
        return 0


class CandidateDocumentService:
    """Create immutable CV/JD lineage from already released, owner-matched assets."""

    def __init__(self, database: DatabaseRuntime) -> None:
        self._database = database

    async def attach_released_asset(
        self,
        account_id: UUID,
        preparation_id: UUID,
        document_type: CandidateDocumentType,
        file_asset_id: UUID,
        source_kind: CandidateDocumentSource,
        request_id: str | None,
        *,
        now: datetime | None = None,
    ) -> AttachDocumentVersionResult:
        normalized_type, normalized_source = self._normalize_codes(document_type, source_kind)
        attached_at = now or datetime.now(UTC)
        async with self._database.transaction() as session:
            account = await session.scalar(
                select(Account).where(Account.id == account_id).with_for_update()
            )
            if account is None or account.status != "active":
                raise CandidateDocumentConflictError("the account cannot attach documents")
            preparation = await session.scalar(
                select(CandidatePreparation)
                .where(
                    CandidatePreparation.id == preparation_id,
                    CandidatePreparation.owner_id == account_id,
                )
                .with_for_update()
            )
            if preparation is None:
                raise CandidateDocumentNotFoundError("candidate preparation was not found")
            if preparation.status != "draft":
                raise CandidateDocumentConflictError(
                    "documents cannot be attached to an archived preparation"
                )
            asset = await session.scalar(
                select(FileAsset)
                .where(FileAsset.id == file_asset_id, FileAsset.account_id == account_id)
                .with_for_update()
            )
            if asset is None:
                raise CandidateDocumentNotFoundError("released file asset was not found")
            self._require_attachable_asset(asset, attached_at)

            decision = await authorize_processing(
                session,
                account_id=account_id,
                data_category=DATA_CATEGORY,
                purpose=PROCESSING_PURPOSE,
                now=attached_at,
            )
            if (
                decision.retention_action != "delete"
                or asset.retention_action != "delete"
                or decision.privacy_policy_version_id != asset.privacy_policy_version_id
                or decision.jurisdiction_code != asset.jurisdiction_code
            ):
                raise CandidateDocumentConflictError(
                    "the released asset does not match the active delete-only privacy decision"
                )

            existing = await session.scalar(
                select(CandidateDocumentVersion).where(
                    CandidateDocumentVersion.file_asset_id == asset.id
                )
            )
            if existing is not None:
                document = await session.get(CandidateDocument, existing.document_id)
                if (
                    document is None
                    or document.owner_id != account_id
                    or document.preparation_id != preparation_id
                    or document.document_type != normalized_type
                    or existing.source_kind != normalized_source
                ):
                    raise CandidateDocumentConflictError(
                        "the released file asset is already attached elsewhere"
                    )
                record = await self._record(session, document)
                return AttachDocumentVersionResult(
                    document=record,
                    attached_version=self._version_record(existing),
                    created=False,
                )

            document = await session.scalar(
                select(CandidateDocument)
                .where(
                    CandidateDocument.preparation_id == preparation_id,
                    CandidateDocument.owner_id == account_id,
                    CandidateDocument.document_type == normalized_type,
                )
                .with_for_update()
            )
            if document is None:
                document = CandidateDocument(
                    owner_id=account_id,
                    preparation_id=preparation_id,
                    document_type=normalized_type,
                    latest_version_number=1,
                    created_at=attached_at,
                    updated_at=attached_at,
                )
                session.add(document)
                await session.flush()
                version_number = 1
            else:
                document.latest_version_number += 1
                document.updated_at = attached_at
                version_number = document.latest_version_number

            version = CandidateDocumentVersion(
                owner_id=account_id,
                document_id=document.id,
                file_asset_id=asset.id,
                version_number=version_number,
                source_kind=normalized_source,
                media_type=asset.media_type,
                content_length=asset.content_length,
                content_sha256=asset.content_sha256,
                parser_release_policy_id=asset.parser_release_policy_id,
                privacy_policy_version_id=asset.privacy_policy_version_id,
                jurisdiction_code=asset.jurisdiction_code,
                legal_basis=decision.legal_basis,
                retention_rule_id=decision.retention_rule_id,
                retain_until=asset.retain_until,
                retention_action="delete",
                created_at=attached_at,
            )
            session.add(version)
            await session.flush()
            profile, _ = await require_privacy_profile(session, account_id, now=attached_at)
            await self._record_attachment(
                session,
                document=document,
                document_version=version,
                profile=profile,
                account_id=account_id,
                request_id=request_id,
                occurred_at=attached_at,
            )
            await session.flush()
            record = await self._record(session, document)
            return AttachDocumentVersionResult(
                document=record,
                attached_version=self._version_record(version),
                created=True,
            )

    async def list_documents(
        self,
        account_id: UUID,
        preparation_id: UUID,
    ) -> tuple[CandidateDocumentRecord, ...]:
        async with self._database.transaction() as session:
            await self._owned_preparation(session, account_id, preparation_id)
            documents = list(
                (
                    await session.scalars(
                        select(CandidateDocument)
                        .where(
                            CandidateDocument.owner_id == account_id,
                            CandidateDocument.preparation_id == preparation_id,
                        )
                        .order_by(CandidateDocument.document_type, CandidateDocument.id)
                    )
                ).all()
            )
            return tuple([await self._record(session, item) for item in documents])

    async def get_document(
        self,
        account_id: UUID,
        preparation_id: UUID,
        document_id: UUID,
    ) -> CandidateDocumentRecord:
        async with self._database.transaction() as session:
            document = await self._owned_document(
                session,
                account_id,
                preparation_id,
                document_id,
            )
            return await self._record(session, document)

    async def export_account_document_metadata(
        self,
        session: AsyncSession,
        *,
        account_id: UUID,
    ) -> list[dict[str, object]]:
        documents = list(
            (
                await session.scalars(
                    select(CandidateDocument)
                    .where(CandidateDocument.owner_id == account_id)
                    .order_by(CandidateDocument.preparation_id, CandidateDocument.document_type)
                )
            ).all()
        )
        records = [await self._record(session, item) for item in documents]
        return [self._export_record(item) for item in records]

    async def erase_account_document_metadata(
        self,
        session: AsyncSession,
        *,
        account_id: UUID,
    ) -> int:
        result = await session.execute(
            delete(CandidateDocument)
            .where(CandidateDocument.owner_id == account_id)
            .returning(CandidateDocument.id)
        )
        return len(result.scalars().all())

    async def release_file_asset_reference(
        self,
        session: AsyncSession,
        *,
        file_asset_id: UUID,
    ) -> int:
        return await release_candidate_file_asset_references(
            session,
            file_asset_id=file_asset_id,
        )

    @staticmethod
    def _normalize_codes(
        document_type: CandidateDocumentType,
        source_kind: CandidateDocumentSource,
    ) -> tuple[CandidateDocumentType, CandidateDocumentSource]:
        normalized_type = document_type.strip().lower()
        normalized_source = source_kind.strip().lower()
        if normalized_type not in DOCUMENT_TYPES:
            raise ValueError("document_type is not supported")
        if normalized_source not in DOCUMENT_SOURCES:
            raise ValueError("source_kind is not supported")
        return normalized_type, normalized_source  # type: ignore[return-value]

    @staticmethod
    def _require_attachable_asset(asset: FileAsset, attached_at: datetime) -> None:
        if (
            asset.status != "released"
            or asset.released_object_key is None
            or asset.released_version_id is None
            or asset.parser_release_policy_id is None
        ):
            raise CandidateDocumentConflictError("the file asset is not released")
        if asset.data_category != DATA_CATEGORY or asset.purpose != PROCESSING_PURPOSE:
            raise CandidateDocumentConflictError("the file asset purpose is incompatible")
        if asset.retain_until <= attached_at:
            raise CandidateDocumentConflictError("the file asset retention deadline has passed")

    @staticmethod
    async def _owned_preparation(
        session: AsyncSession,
        account_id: UUID,
        preparation_id: UUID,
    ) -> CandidatePreparation:
        preparation = await session.scalar(
            select(CandidatePreparation).where(
                CandidatePreparation.id == preparation_id,
                CandidatePreparation.owner_id == account_id,
            )
        )
        if preparation is None:
            raise CandidateDocumentNotFoundError("candidate preparation was not found")
        return preparation

    @staticmethod
    async def _owned_document(
        session: AsyncSession,
        account_id: UUID,
        preparation_id: UUID,
        document_id: UUID,
    ) -> CandidateDocument:
        document = await session.scalar(
            select(CandidateDocument).where(
                CandidateDocument.id == document_id,
                CandidateDocument.owner_id == account_id,
                CandidateDocument.preparation_id == preparation_id,
            )
        )
        if document is None:
            raise CandidateDocumentNotFoundError("candidate document was not found")
        return document

    @staticmethod
    async def _record(
        session: AsyncSession,
        document: CandidateDocument,
    ) -> CandidateDocumentRecord:
        versions = list(
            (
                await session.scalars(
                    select(CandidateDocumentVersion)
                    .where(CandidateDocumentVersion.document_id == document.id)
                    .order_by(CandidateDocumentVersion.version_number)
                )
            ).all()
        )
        return CandidateDocumentRecord(
            document_id=document.id,
            preparation_id=document.preparation_id,
            document_type=document.document_type,
            latest_version_number=document.latest_version_number,
            aggregate_version=document.version,
            created_at=document.created_at,
            updated_at=document.updated_at,
            versions=tuple(CandidateDocumentService._version_record(item) for item in versions),
        )

    @staticmethod
    def _version_record(version: CandidateDocumentVersion) -> CandidateDocumentVersionRecord:
        return CandidateDocumentVersionRecord(
            version_id=version.id,
            file_asset_id=version.file_asset_id,
            version_number=version.version_number,
            source_kind=version.source_kind,
            media_type=version.media_type,
            content_length=version.content_length,
            content_sha256=version.content_sha256,
            created_at=version.created_at,
            retain_until=version.retain_until,
        )

    @staticmethod
    async def _record_attachment(
        session: AsyncSession,
        *,
        document: CandidateDocument,
        document_version: CandidateDocumentVersion,
        profile: PrivacyProfile,
        account_id: UUID,
        request_id: str | None,
        occurred_at: datetime,
    ) -> None:
        safe_details = {
            "document_type": document.document_type,
            "source_kind": document_version.source_kind,
            "media_type": document_version.media_type,
            "version_number": document_version.version_number,
        }
        await record_privacy_audit(
            session,
            profile=profile,
            occurred_at=occurred_at,
            actor_id=account_id,
            action="candidate_document.version_attached",
            resource_type="candidate_document_version",
            resource_id=document_version.id,
            owner_id=account_id,
            request_id=request_id,
            details=safe_details,
        )
        await enqueue_outbox(
            session,
            NewOutboxEvent(
                aggregate_type="candidate_document",
                aggregate_id=document.id,
                event_type="candidate_document.version_attached",
                owner_id=account_id,
                payload={
                    "candidate_document_id": str(document.id),
                    "candidate_document_version_id": str(document_version.id),
                    "file_asset_id": str(document_version.file_asset_id),
                    **safe_details,
                },
            ),
        )

    @staticmethod
    def _export_record(document: CandidateDocumentRecord) -> dict[str, object]:
        return {
            "document_id": str(document.document_id),
            "preparation_id": str(document.preparation_id),
            "document_type": document.document_type,
            "latest_version_number": document.latest_version_number,
            "aggregate_version": document.aggregate_version,
            "created_at": document.created_at.isoformat(),
            "updated_at": document.updated_at.isoformat(),
            "versions": [
                {
                    "version_id": str(version.version_id),
                    "file_asset_id": str(version.file_asset_id),
                    "version_number": version.version_number,
                    "source_kind": version.source_kind,
                    "media_type": version.media_type,
                    "content_length": version.content_length,
                    "content_sha256": version.content_sha256,
                    "created_at": version.created_at.isoformat(),
                    "retain_until": version.retain_until.isoformat(),
                }
                for version in document.versions
            ],
        }


def build_candidate_documents(
    settings: Settings,
    database: DatabaseRuntime,
) -> CandidateDocumentRuntime:
    if not settings.privacy_enabled or not settings.file_security_enabled:
        return FailClosedCandidateDocumentService()
    return CandidateDocumentService(database)
