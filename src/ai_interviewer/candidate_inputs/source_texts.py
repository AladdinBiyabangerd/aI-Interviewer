"""Secure persistence boundary for immutable candidate source text."""

from __future__ import annotations

import json
import unicodedata
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import NoReturn, Protocol
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from uuid6 import uuid7

from ai_interviewer.candidate_inputs.document_models import (
    CandidateDocument,
    CandidateDocumentVersion,
)
from ai_interviewer.candidate_inputs.models import CandidatePreparation
from ai_interviewer.candidate_inputs.source_text_models import (
    MAX_SOURCE_TEXT_CHARACTERS,
    MAX_SOURCE_TEXT_UTF8_BYTES,
    CandidateSourceText,
    CandidateSourceTextVersion,
)
from ai_interviewer.core.config import Settings
from ai_interviewer.core.crypto import ApplicationKeyring, EncryptedValue, KeyringError
from ai_interviewer.file_security.models import FileAsset, ParserReleasePolicy
from ai_interviewer.identity.models import Account
from ai_interviewer.persistence.database import DatabaseRuntime
from ai_interviewer.persistence.repositories import NewOutboxEvent, enqueue_outbox
from ai_interviewer.privacy.audit import record_privacy_audit
from ai_interviewer.privacy.models import PrivacyProfile
from ai_interviewer.privacy.rules import authorize_processing, require_privacy_profile

DATA_CATEGORY = "candidate_document"
PROCESSING_PURPOSE = "interview_preparation"


class CandidateSourceTextUnavailableError(RuntimeError):
    """The source-text boundary is disabled or encrypted content is unavailable."""


class CandidateSourceTextNotFoundError(LookupError):
    """An owner-scoped document version or its source text was not found."""


class CandidateSourceTextConflictError(RuntimeError):
    """A parser result conflicts with document, policy, or existing text state."""


class CandidateSourceTextPreconditionError(RuntimeError):
    """A correction's expected aggregate version does not match the current one."""


@dataclass(frozen=True, slots=True)
class ParserExecutionIdentity:
    parser_release_policy_id: UUID
    parser_adapter: str
    parser_version: str
    isolation_profile: str


@dataclass(frozen=True, slots=True)
class CandidateSourceTextVersionRecord:
    text_version_id: UUID
    version_number: int
    origin: str
    previous_version_id: UUID | None
    parser_release_policy_id: UUID | None
    parser_adapter: str | None
    parser_version: str | None
    isolation_profile: str | None
    character_count: int
    utf8_byte_count: int
    line_count: int
    created_at: datetime
    content: str = field(repr=False)


@dataclass(frozen=True, slots=True)
class CandidateSourceTextRecord:
    source_text_id: UUID
    document_version_id: UUID
    latest_version_number: int
    aggregate_version: int
    created_at: datetime
    updated_at: datetime
    versions: tuple[CandidateSourceTextVersionRecord, ...]


@dataclass(frozen=True, slots=True)
class StoreParserExtractionResult:
    source_text: CandidateSourceTextRecord
    created: bool


class CandidateSourceTextRuntime(Protocol):
    async def store_parser_extraction(
        self,
        account_id: UUID,
        document_version_id: UUID,
        content: str,
        parser: ParserExecutionIdentity,
        request_id: str | None,
        *,
        now: datetime | None = None,
    ) -> StoreParserExtractionResult: ...

    async def get_source_text(
        self,
        account_id: UUID,
        preparation_id: UUID,
        document_version_id: UUID,
    ) -> CandidateSourceTextRecord: ...

    async def append_correction(
        self,
        account_id: UUID,
        preparation_id: UUID,
        document_version_id: UUID,
        content: str,
        expected_version: int,
        request_id: str | None,
        *,
        now: datetime | None = None,
    ) -> CandidateSourceTextRecord: ...

    async def export_account_source_text_metadata(
        self,
        session: AsyncSession,
        *,
        account_id: UUID,
    ) -> list[dict[str, object]]: ...


class FailClosedCandidateSourceTextService:
    """Reject source-text commands until privacy cryptography is available."""

    @staticmethod
    def _unavailable() -> NoReturn:
        raise CandidateSourceTextUnavailableError("candidate source text is not configured")

    async def store_parser_extraction(
        self,
        account_id: UUID,
        document_version_id: UUID,
        content: str,
        parser: ParserExecutionIdentity,
        request_id: str | None,
        *,
        now: datetime | None = None,
    ) -> StoreParserExtractionResult:
        del account_id, document_version_id, content, parser, request_id, now
        self._unavailable()

    async def get_source_text(
        self,
        account_id: UUID,
        preparation_id: UUID,
        document_version_id: UUID,
    ) -> CandidateSourceTextRecord:
        del account_id, preparation_id, document_version_id
        self._unavailable()

    async def append_correction(
        self,
        account_id: UUID,
        preparation_id: UUID,
        document_version_id: UUID,
        content: str,
        expected_version: int,
        request_id: str | None,
        *,
        now: datetime | None = None,
    ) -> CandidateSourceTextRecord:
        del account_id, preparation_id, document_version_id, content, request_id, now
        del expected_version
        self._unavailable()

    async def export_account_source_text_metadata(
        self,
        session: AsyncSession,
        *,
        account_id: UUID,
    ) -> list[dict[str, object]]:
        del session, account_id
        return []


class CandidateSourceTextService:
    """Persist one encrypted parser result per exact retained document version."""

    def __init__(
        self,
        database: DatabaseRuntime,
        application_keyring: ApplicationKeyring,
    ) -> None:
        self._database = database
        self._keyring = application_keyring

    async def store_parser_extraction(
        self,
        account_id: UUID,
        document_version_id: UUID,
        content: str,
        parser: ParserExecutionIdentity,
        request_id: str | None,
        *,
        now: datetime | None = None,
    ) -> StoreParserExtractionResult:
        content_bytes, character_count, line_count = self._validate_content(content)
        normalized_parser = self._validate_parser_identity(parser)
        recorded_at = now or datetime.now(UTC)

        async with self._database.transaction() as session:
            account = await session.scalar(
                select(Account).where(Account.id == account_id).with_for_update()
            )
            if account is None or account.status != "active":
                raise CandidateSourceTextConflictError("the account cannot process documents")

            initial_version = await session.scalar(
                select(CandidateDocumentVersion).where(
                    CandidateDocumentVersion.id == document_version_id,
                    CandidateDocumentVersion.owner_id == account_id,
                )
            )
            if initial_version is None:
                raise CandidateSourceTextNotFoundError("candidate document version was not found")
            document = await session.scalar(
                select(CandidateDocument).where(
                    CandidateDocument.id == initial_version.document_id,
                    CandidateDocument.owner_id == account_id,
                )
            )
            if document is None:
                raise CandidateSourceTextNotFoundError("candidate document version was not found")
            preparation = await session.scalar(
                select(CandidatePreparation)
                .where(
                    CandidatePreparation.id == document.preparation_id,
                    CandidatePreparation.owner_id == account_id,
                )
                .with_for_update()
            )
            if preparation is None:
                raise CandidateSourceTextNotFoundError("candidate document version was not found")

            asset = await session.scalar(
                select(FileAsset)
                .where(
                    FileAsset.id == initial_version.file_asset_id,
                    FileAsset.account_id == account_id,
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
            locked_document = await session.scalar(
                select(CandidateDocument)
                .where(
                    CandidateDocument.id == document.id,
                    CandidateDocument.owner_id == account_id,
                )
                .with_for_update()
            )
            if asset is None or document_version is None or locked_document is None:
                raise CandidateSourceTextConflictError("candidate document state changed")
            self._require_processable_document(
                preparation,
                locked_document,
                document_version,
                asset,
                recorded_at,
            )

            policy = await session.scalar(
                select(ParserReleasePolicy)
                .where(ParserReleasePolicy.id == document_version.parser_release_policy_id)
                .with_for_update()
            )
            self._require_exact_parser_policy(
                policy,
                document_version,
                asset,
                normalized_parser,
                recorded_at,
            )

            decision = await authorize_processing(
                session,
                account_id=account_id,
                data_category=DATA_CATEGORY,
                purpose=PROCESSING_PURPOSE,
                now=recorded_at,
            )
            if (
                decision.retention_action != "delete"
                or decision.privacy_policy_version_id != document_version.privacy_policy_version_id
                or decision.jurisdiction_code != document_version.jurisdiction_code
                or decision.legal_basis != document_version.legal_basis
                or decision.retention_rule_id != document_version.retention_rule_id
            ):
                raise CandidateSourceTextConflictError(
                    "the document no longer matches the active privacy decision"
                )

            existing = await session.scalar(
                select(CandidateSourceText)
                .where(CandidateSourceText.document_version_id == document_version.id)
                .with_for_update()
            )
            if existing is not None:
                record = await self._record(session, existing)
                if not self._same_parser_result(record, content, normalized_parser):
                    raise CandidateSourceTextConflictError(
                        "the document version already has a different parser result"
                    )
                return StoreParserExtractionResult(source_text=record, created=False)

            source_text_id = uuid7()
            text_version_id = uuid7()
            digest_key_id = self._keyring.active_key_id("subject_hmac")
            content_digest = self._keyring.hmac_digest(
                "subject_hmac",
                self._content_digest_material(account_id, document_version.id, content_bytes),
            )
            encryption_key_id = self._keyring.active_key_id("field_encryption")
            aad = self._version_aad(
                text_version_id=text_version_id,
                source_text_id=source_text_id,
                owner_id=account_id,
                document_version_id=document_version.id,
                version_number=1,
                origin="parser_extraction",
                previous_version_id=None,
                parser=normalized_parser,
                character_count=character_count,
                utf8_byte_count=len(content_bytes),
                line_count=line_count,
                content_digest=content_digest,
                content_digest_key_id=digest_key_id,
                content_encryption_key_id=encryption_key_id,
            )
            encrypted = self._keyring.encrypt_field(content, aad=aad)
            if encrypted.key_id != encryption_key_id:
                raise CandidateSourceTextUnavailableError("field-encryption key changed")

            source_text = CandidateSourceText(
                id=source_text_id,
                owner_id=account_id,
                document_version_id=document_version.id,
                latest_version_number=1,
                created_at=recorded_at,
                updated_at=recorded_at,
            )
            text_version = CandidateSourceTextVersion(
                id=text_version_id,
                owner_id=account_id,
                source_text_id=source_text_id,
                version_number=1,
                origin="parser_extraction",
                previous_version_id=None,
                parser_release_policy_id=normalized_parser.parser_release_policy_id,
                parser_adapter=normalized_parser.parser_adapter,
                parser_version=normalized_parser.parser_version,
                isolation_profile=normalized_parser.isolation_profile,
                character_count=character_count,
                utf8_byte_count=len(content_bytes),
                line_count=line_count,
                content_digest=content_digest,
                content_digest_key_id=digest_key_id,
                content_ciphertext=encrypted.ciphertext,
                content_nonce=encrypted.nonce,
                content_encryption_key_id=encrypted.key_id,
                created_at=recorded_at,
            )
            session.add_all((source_text, text_version))
            await session.flush()
            profile, _ = await require_privacy_profile(session, account_id, now=recorded_at)
            await self._record_version_event(
                session,
                source_text=source_text,
                text_version=text_version,
                profile=profile,
                request_id=request_id,
                occurred_at=recorded_at,
                action="candidate_source_text.parser_extraction_stored",
            )
            await session.flush()
            return StoreParserExtractionResult(
                source_text=await self._record(session, source_text),
                created=True,
            )

    async def get_source_text(
        self,
        account_id: UUID,
        preparation_id: UUID,
        document_version_id: UUID,
    ) -> CandidateSourceTextRecord:
        async with self._database.transaction() as session:
            document_version, _, _ = await self._owned_lineage(
                session,
                account_id,
                preparation_id,
                document_version_id,
            )
            source_text = await session.scalar(
                select(CandidateSourceText).where(
                    CandidateSourceText.document_version_id == document_version.id,
                    CandidateSourceText.owner_id == account_id,
                )
            )
            if source_text is None:
                raise CandidateSourceTextNotFoundError("candidate source text was not found")
            return await self._record(session, source_text)

    async def append_correction(
        self,
        account_id: UUID,
        preparation_id: UUID,
        document_version_id: UUID,
        content: str,
        expected_version: int,
        request_id: str | None,
        *,
        now: datetime | None = None,
    ) -> CandidateSourceTextRecord:
        content_bytes, character_count, line_count = self._validate_content(content)
        corrected_at = now or datetime.now(UTC)

        async with self._database.transaction() as session:
            account = await session.scalar(
                select(Account).where(Account.id == account_id).with_for_update()
            )
            if account is None or account.status != "active":
                raise CandidateSourceTextConflictError("the account cannot process documents")

            document_version, document, preparation = await self._owned_lineage(
                session,
                account_id,
                preparation_id,
                document_version_id,
                lock=True,
            )
            self._require_correctable_document(
                preparation,
                document,
                document_version,
                corrected_at,
            )

            decision = await authorize_processing(
                session,
                account_id=account_id,
                data_category=DATA_CATEGORY,
                purpose=PROCESSING_PURPOSE,
                now=corrected_at,
            )
            if (
                decision.retention_action != "delete"
                or decision.privacy_policy_version_id != document_version.privacy_policy_version_id
                or decision.jurisdiction_code != document_version.jurisdiction_code
                or decision.legal_basis != document_version.legal_basis
                or decision.retention_rule_id != document_version.retention_rule_id
            ):
                raise CandidateSourceTextConflictError(
                    "the document no longer matches the active privacy decision"
                )

            source_text = await session.scalar(
                select(CandidateSourceText)
                .where(
                    CandidateSourceText.document_version_id == document_version.id,
                    CandidateSourceText.owner_id == account_id,
                )
                .with_for_update()
            )
            if source_text is None:
                raise CandidateSourceTextNotFoundError("candidate source text was not found")

            latest_version = await session.scalar(
                select(CandidateSourceTextVersion).where(
                    CandidateSourceTextVersion.source_text_id == source_text.id,
                    CandidateSourceTextVersion.version_number == source_text.latest_version_number,
                )
            )
            if latest_version is None:
                raise CandidateSourceTextUnavailableError("source-text lineage is incomplete")

            if expected_version < 1:
                raise CandidateSourceTextPreconditionError("source-text version changed")
            if source_text.version != expected_version:
                if source_text.version == expected_version + 1 and self._is_repeat_correction(
                    source_text,
                    document_version,
                    latest_version,
                    content,
                    expected_version + 1,
                ):
                    return await self._record(session, source_text)
                raise CandidateSourceTextPreconditionError("source-text version changed")

            new_version_number = source_text.latest_version_number + 1
            text_version_id = uuid7()
            digest_key_id = self._keyring.active_key_id("subject_hmac")
            content_digest = self._keyring.hmac_digest(
                "subject_hmac",
                self._content_digest_material(account_id, document_version.id, content_bytes),
            )
            encryption_key_id = self._keyring.active_key_id("field_encryption")
            aad = self._version_aad(
                text_version_id=text_version_id,
                source_text_id=source_text.id,
                owner_id=account_id,
                document_version_id=document_version.id,
                version_number=new_version_number,
                origin="user_correction",
                previous_version_id=latest_version.id,
                parser=None,
                character_count=character_count,
                utf8_byte_count=len(content_bytes),
                line_count=line_count,
                content_digest=content_digest,
                content_digest_key_id=digest_key_id,
                content_encryption_key_id=encryption_key_id,
            )
            encrypted = self._keyring.encrypt_field(content, aad=aad)
            if encrypted.key_id != encryption_key_id:
                raise CandidateSourceTextUnavailableError("field-encryption key changed")

            text_version = CandidateSourceTextVersion(
                id=text_version_id,
                owner_id=account_id,
                source_text_id=source_text.id,
                version_number=new_version_number,
                origin="user_correction",
                previous_version_id=latest_version.id,
                parser_release_policy_id=None,
                parser_adapter=None,
                parser_version=None,
                isolation_profile=None,
                character_count=character_count,
                utf8_byte_count=len(content_bytes),
                line_count=line_count,
                content_digest=content_digest,
                content_digest_key_id=digest_key_id,
                content_ciphertext=encrypted.ciphertext,
                content_nonce=encrypted.nonce,
                content_encryption_key_id=encrypted.key_id,
                created_at=corrected_at,
            )
            source_text.latest_version_number = new_version_number
            source_text.updated_at = corrected_at
            session.add(text_version)
            await session.flush()
            profile, _ = await require_privacy_profile(session, account_id, now=corrected_at)
            await self._record_version_event(
                session,
                source_text=source_text,
                text_version=text_version,
                profile=profile,
                request_id=request_id,
                occurred_at=corrected_at,
                action="candidate_source_text.correction_appended",
            )
            await session.flush()
            return await self._record(session, source_text)

    async def export_account_source_text_metadata(
        self,
        session: AsyncSession,
        *,
        account_id: UUID,
    ) -> list[dict[str, object]]:
        source_texts = list(
            (
                await session.scalars(
                    select(CandidateSourceText)
                    .where(CandidateSourceText.owner_id == account_id)
                    .order_by(CandidateSourceText.created_at, CandidateSourceText.id)
                )
            ).all()
        )
        items: list[dict[str, object]] = []
        for source_text in source_texts:
            record = await self._record(session, source_text)
            items.append(self._export_record(record))
        return items

    @staticmethod
    def _export_record(record: CandidateSourceTextRecord) -> dict[str, object]:
        return {
            "source_text_id": str(record.source_text_id),
            "document_version_id": str(record.document_version_id),
            "latest_version_number": record.latest_version_number,
            "created_at": record.created_at.isoformat(),
            "updated_at": record.updated_at.isoformat(),
            "versions": [
                {
                    "version_number": version.version_number,
                    "origin": version.origin,
                    "parser_adapter": version.parser_adapter,
                    "parser_version": version.parser_version,
                    "isolation_profile": version.isolation_profile,
                    "character_count": version.character_count,
                    "line_count": version.line_count,
                    "created_at": version.created_at.isoformat(),
                    "content": version.content,
                }
                for version in record.versions
            ],
        }

    async def _owned_lineage(
        self,
        session: AsyncSession,
        account_id: UUID,
        preparation_id: UUID,
        document_version_id: UUID,
        *,
        lock: bool = False,
    ) -> tuple[CandidateDocumentVersion, CandidateDocument, CandidatePreparation]:
        version_statement = select(CandidateDocumentVersion).where(
            CandidateDocumentVersion.id == document_version_id,
            CandidateDocumentVersion.owner_id == account_id,
        )
        if lock:
            version_statement = version_statement.with_for_update()
        document_version = await session.scalar(version_statement)
        if document_version is None:
            raise CandidateSourceTextNotFoundError("candidate source text was not found")

        document_statement = select(CandidateDocument).where(
            CandidateDocument.id == document_version.document_id,
            CandidateDocument.owner_id == account_id,
        )
        if lock:
            document_statement = document_statement.with_for_update()
        document = await session.scalar(document_statement)
        if document is None:
            raise CandidateSourceTextNotFoundError("candidate source text was not found")

        preparation_statement = select(CandidatePreparation).where(
            CandidatePreparation.id == preparation_id,
            CandidatePreparation.owner_id == account_id,
        )
        if lock:
            preparation_statement = preparation_statement.with_for_update()
        preparation = await session.scalar(preparation_statement)
        if preparation is None or document.preparation_id != preparation_id:
            raise CandidateSourceTextNotFoundError("candidate source text was not found")
        return document_version, document, preparation

    @staticmethod
    def _require_correctable_document(
        preparation: CandidatePreparation,
        document: CandidateDocument,
        document_version: CandidateDocumentVersion,
        evaluated_at: datetime,
    ) -> None:
        if preparation.status != "draft":
            raise CandidateSourceTextConflictError("archived documents cannot be corrected")
        if (
            preparation.retain_until <= evaluated_at
            or preparation.retention_action != "delete"
            or preparation.privacy_policy_version_id != document_version.privacy_policy_version_id
            or preparation.jurisdiction_code != document_version.jurisdiction_code
        ):
            raise CandidateSourceTextConflictError(
                "the preparation privacy snapshot is no longer processable"
            )
        if document.latest_version_number != document_version.version_number:
            raise CandidateSourceTextConflictError(
                "only the latest document version can be corrected"
            )
        if document_version.retain_until <= evaluated_at:
            raise CandidateSourceTextConflictError("the document retention deadline has passed")

    def _is_repeat_correction(
        self,
        source_text: CandidateSourceText,
        document_version: CandidateDocumentVersion,
        latest_version: CandidateSourceTextVersion,
        content: str,
        expected_next_version_number: int,
    ) -> bool:
        if (
            latest_version.origin != "user_correction"
            or latest_version.version_number != expected_next_version_number
        ):
            return False
        try:
            record = self._version_record(source_text, document_version, latest_version)
        except CandidateSourceTextUnavailableError:
            return False
        return record.content == content

    @staticmethod
    def _validate_content(content: str) -> tuple[bytes, int, int]:
        if not isinstance(content, str):
            raise ValueError("source text must be Unicode text")
        if not content.strip():
            raise ValueError("source text must not be empty or whitespace-only")
        if "\r" in content:
            raise ValueError("source text must use LF newlines")
        if any(
            (unicodedata.category(character) == "Cc" and character not in {"\n", "\t"})
            or unicodedata.category(character) in {"Cf", "Cs"}
            for character in content
        ):
            raise ValueError("source text contains unsafe Unicode control characters")
        character_count = len(content)
        if character_count > MAX_SOURCE_TEXT_CHARACTERS:
            raise ValueError("source text exceeds the character limit")
        try:
            content_bytes = content.encode("utf-8")
        except UnicodeEncodeError as exc:
            raise ValueError("source text must be valid Unicode") from exc
        if len(content_bytes) > MAX_SOURCE_TEXT_UTF8_BYTES:
            raise ValueError("source text exceeds the UTF-8 byte limit")
        return content_bytes, character_count, content.count("\n") + 1

    @staticmethod
    def _validate_parser_identity(parser: ParserExecutionIdentity) -> ParserExecutionIdentity:
        values = (
            (parser.parser_adapter, 100, "parser_adapter"),
            (parser.parser_version, 64, "parser_version"),
            (parser.isolation_profile, 100, "isolation_profile"),
        )
        for value, maximum, label in values:
            if not value or value != value.strip() or len(value) > maximum or "\x00" in value:
                raise ValueError(f"{label} is invalid")
        return parser

    @staticmethod
    def _require_processable_document(
        preparation: CandidatePreparation,
        document: CandidateDocument,
        document_version: CandidateDocumentVersion,
        asset: FileAsset,
        evaluated_at: datetime,
    ) -> None:
        if preparation.status != "draft":
            raise CandidateSourceTextConflictError("archived documents cannot be processed")
        if (
            preparation.retain_until <= evaluated_at
            or preparation.retention_action != "delete"
            or preparation.privacy_policy_version_id != document_version.privacy_policy_version_id
            or preparation.jurisdiction_code != document_version.jurisdiction_code
        ):
            raise CandidateSourceTextConflictError(
                "the preparation privacy snapshot is no longer processable"
            )
        if document.latest_version_number != document_version.version_number:
            raise CandidateSourceTextConflictError(
                "only the latest document version can be processed"
            )
        if document_version.retain_until <= evaluated_at:
            raise CandidateSourceTextConflictError("the document retention deadline has passed")
        if (
            asset.status != "released"
            or asset.released_object_key is None
            or asset.released_version_id is None
            or asset.released_at is None
            or asset.released_at > evaluated_at
            or asset.parser_release_policy_id is None
            or asset.id != document_version.file_asset_id
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
            raise CandidateSourceTextConflictError("the exact released asset is unavailable")

    @staticmethod
    def _require_exact_parser_policy(
        policy: ParserReleasePolicy | None,
        document_version: CandidateDocumentVersion,
        asset: FileAsset,
        parser: ParserExecutionIdentity,
        evaluated_at: datetime,
    ) -> None:
        if (
            policy is None
            or policy.status != "active"
            or policy.approved_at > evaluated_at
            or policy.id != parser.parser_release_policy_id
            or policy.id != document_version.parser_release_policy_id
            or policy.id != asset.parser_release_policy_id
            or policy.parser_adapter != parser.parser_adapter
            or policy.parser_version != parser.parser_version
            or policy.isolation_profile != parser.isolation_profile
            or policy.privacy_policy_version_id != document_version.privacy_policy_version_id
            or policy.data_category != DATA_CATEGORY
            or policy.purpose != PROCESSING_PURPOSE
            or policy.media_type != document_version.media_type
            or policy.maximum_bytes < document_version.content_length
            or not policy.malware_scan_required
        ):
            raise CandidateSourceTextConflictError("the exact parser release is not active")

    @staticmethod
    def _content_digest_material(
        owner_id: UUID,
        document_version_id: UUID,
        content: bytes,
    ) -> bytes:
        return (
            b"candidate-source-text-content-v1\x00"
            + owner_id.bytes
            + document_version_id.bytes
            + content
        )

    @staticmethod
    def _version_aad(
        *,
        text_version_id: UUID,
        source_text_id: UUID,
        owner_id: UUID,
        document_version_id: UUID,
        version_number: int,
        origin: str,
        previous_version_id: UUID | None,
        parser: ParserExecutionIdentity | None,
        character_count: int,
        utf8_byte_count: int,
        line_count: int,
        content_digest: str,
        content_digest_key_id: str,
        content_encryption_key_id: str,
    ) -> bytes:
        document = {
            "content_digest": content_digest,
            "content_digest_key_id": content_digest_key_id,
            "content_encryption_key_id": content_encryption_key_id,
            "document_version_id": str(document_version_id),
            "isolation_profile": parser.isolation_profile if parser is not None else None,
            "origin": origin,
            "owner_id": str(owner_id),
            "parser_adapter": parser.parser_adapter if parser is not None else None,
            "parser_release_policy_id": (
                str(parser.parser_release_policy_id) if parser is not None else None
            ),
            "parser_version": parser.parser_version if parser is not None else None,
            "previous_version_id": (
                str(previous_version_id) if previous_version_id is not None else None
            ),
            "source_text_id": str(source_text_id),
            "text_version_id": str(text_version_id),
            "version": 1,
            "version_number": version_number,
            "character_count": character_count,
            "utf8_byte_count": utf8_byte_count,
            "line_count": line_count,
        }
        return json.dumps(document, sort_keys=True, separators=(",", ":")).encode()

    async def _record(
        self,
        session: AsyncSession,
        source_text: CandidateSourceText,
    ) -> CandidateSourceTextRecord:
        document_version = await session.get(
            CandidateDocumentVersion,
            source_text.document_version_id,
        )
        if document_version is None or document_version.owner_id != source_text.owner_id:
            raise CandidateSourceTextUnavailableError("source-text lineage is unavailable")
        versions = list(
            (
                await session.scalars(
                    select(CandidateSourceTextVersion)
                    .where(CandidateSourceTextVersion.source_text_id == source_text.id)
                    .order_by(CandidateSourceTextVersion.version_number)
                )
            ).all()
        )
        if (
            not versions
            or versions[-1].version_number != source_text.latest_version_number
            or [item.version_number for item in versions]
            != list(range(1, source_text.latest_version_number + 1))
        ):
            raise CandidateSourceTextUnavailableError("source-text lineage is incomplete")
        return CandidateSourceTextRecord(
            source_text_id=source_text.id,
            document_version_id=source_text.document_version_id,
            latest_version_number=source_text.latest_version_number,
            aggregate_version=source_text.version,
            created_at=source_text.created_at,
            updated_at=source_text.updated_at,
            versions=tuple(
                self._version_record(source_text, document_version, item) for item in versions
            ),
        )

    def _version_record(
        self,
        source_text: CandidateSourceText,
        document_version: CandidateDocumentVersion,
        version: CandidateSourceTextVersion,
    ) -> CandidateSourceTextVersionRecord:
        parser = (
            ParserExecutionIdentity(
                parser_release_policy_id=version.parser_release_policy_id,
                parser_adapter=version.parser_adapter,
                parser_version=version.parser_version,
                isolation_profile=version.isolation_profile,
            )
            if version.parser_release_policy_id is not None
            and version.parser_adapter is not None
            and version.parser_version is not None
            and version.isolation_profile is not None
            else None
        )
        aad = self._version_aad(
            text_version_id=version.id,
            source_text_id=source_text.id,
            owner_id=source_text.owner_id,
            document_version_id=document_version.id,
            version_number=version.version_number,
            origin=version.origin,
            previous_version_id=version.previous_version_id,
            parser=parser,
            character_count=version.character_count,
            utf8_byte_count=version.utf8_byte_count,
            line_count=version.line_count,
            content_digest=version.content_digest,
            content_digest_key_id=version.content_digest_key_id,
            content_encryption_key_id=version.content_encryption_key_id,
        )
        try:
            content = self._keyring.decrypt_field(
                EncryptedValue(
                    key_id=version.content_encryption_key_id,
                    nonce=version.content_nonce,
                    ciphertext=version.content_ciphertext,
                ),
                aad=aad,
            )
        except KeyringError as exc:
            raise CandidateSourceTextUnavailableError("source-text decryption failed") from exc
        content_bytes = content.encode("utf-8")
        if (
            len(content) != version.character_count
            or len(content_bytes) != version.utf8_byte_count
            or content.count("\n") + 1 != version.line_count
            or not self._keyring.verify_hmac(
                "subject_hmac",
                key_id=version.content_digest_key_id,
                data=self._content_digest_material(
                    source_text.owner_id,
                    document_version.id,
                    content_bytes,
                ),
                digest=version.content_digest,
            )
        ):
            raise CandidateSourceTextUnavailableError("source-text integrity check failed")
        return CandidateSourceTextVersionRecord(
            text_version_id=version.id,
            version_number=version.version_number,
            origin=version.origin,
            previous_version_id=version.previous_version_id,
            parser_release_policy_id=version.parser_release_policy_id,
            parser_adapter=version.parser_adapter,
            parser_version=version.parser_version,
            isolation_profile=version.isolation_profile,
            character_count=version.character_count,
            utf8_byte_count=version.utf8_byte_count,
            line_count=version.line_count,
            created_at=version.created_at,
            content=content,
        )

    @staticmethod
    def _same_parser_result(
        record: CandidateSourceTextRecord,
        content: str,
        parser: ParserExecutionIdentity,
    ) -> bool:
        if len(record.versions) != 1:
            return False
        version = record.versions[0]
        return (
            version.origin == "parser_extraction"
            and version.parser_release_policy_id == parser.parser_release_policy_id
            and version.parser_adapter == parser.parser_adapter
            and version.parser_version == parser.parser_version
            and version.isolation_profile == parser.isolation_profile
            and version.content == content
        )

    @staticmethod
    async def _record_version_event(
        session: AsyncSession,
        *,
        source_text: CandidateSourceText,
        text_version: CandidateSourceTextVersion,
        profile: PrivacyProfile,
        request_id: str | None,
        occurred_at: datetime,
        action: str,
    ) -> None:
        safe_details = {
            "origin": text_version.origin,
            "version_number": text_version.version_number,
            "parser_adapter": text_version.parser_adapter,
            "parser_version": text_version.parser_version,
            "isolation_profile": text_version.isolation_profile,
        }
        await record_privacy_audit(
            session,
            profile=profile,
            occurred_at=occurred_at,
            actor_id=None,
            action=action,
            resource_type="candidate_source_text_version",
            resource_id=text_version.id,
            owner_id=source_text.owner_id,
            request_id=request_id,
            details=safe_details,
        )
        await enqueue_outbox(
            session,
            NewOutboxEvent(
                aggregate_type="candidate_source_text",
                aggregate_id=source_text.id,
                event_type=action,
                owner_id=source_text.owner_id,
                payload={
                    "candidate_source_text_id": str(source_text.id),
                    "candidate_source_text_version_id": str(text_version.id),
                    "candidate_document_version_id": str(source_text.document_version_id),
                    **safe_details,
                },
            ),
        )


def build_candidate_source_texts(
    settings: Settings,
    database: DatabaseRuntime,
) -> CandidateSourceTextRuntime:
    if (
        not settings.privacy_enabled
        or not settings.file_security_enabled
        or settings.privacy_keyring is None
    ):
        return FailClosedCandidateSourceTextService()
    return CandidateSourceTextService(
        database,
        ApplicationKeyring.from_secret(settings.privacy_keyring),
    )
