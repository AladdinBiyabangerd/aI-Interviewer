"""Secure persistence boundary for evidence-linked candidate profiles."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import NoReturn, Protocol
from uuid import UUID

from pydantic import ValidationError
from sqlalchemy import select
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
from ai_interviewer.candidate_inputs.source_texts import (
    CandidateSourceTextService,
    CandidateSourceTextUnavailableError,
)
from ai_interviewer.core.config import Settings
from ai_interviewer.core.crypto import ApplicationKeyring, EncryptedValue, KeyringError
from ai_interviewer.identity.models import Account
from ai_interviewer.model_gateway import ModelGatewayResult
from ai_interviewer.persistence.database import DatabaseRuntime
from ai_interviewer.persistence.repositories import NewOutboxEvent, enqueue_outbox
from ai_interviewer.privacy.audit import record_privacy_audit
from ai_interviewer.privacy.models import PrivacyProfile
from ai_interviewer.privacy.rules import authorize_processing, require_privacy_profile
from ai_interviewer.profiling.contracts import (
    CV_PROFILE_SCHEMA_ID,
    JOB_DESCRIPTION_PROFILE_SCHEMA_ID,
    PROFILE_SCHEMA_VERSION,
    CandidateProfileOutput,
    CvProfileOutput,
    JobDescriptionProfileOutput,
    profile_output_type,
)
from ai_interviewer.profiling.evidence import validate_profile_evidence
from ai_interviewer.profiling.models import (
    MAX_PROFILE_JSON_UTF8_BYTES,
    CandidateProfile,
    CandidateProfileVersion,
)

DATA_CATEGORY = "candidate_document"
PROCESSING_PURPOSE = "interview_preparation"
_SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")


class CandidateProfileUnavailableError(RuntimeError):
    """The profile boundary is disabled or encrypted content is unavailable."""


class CandidateProfileNotFoundError(LookupError):
    """An owner-scoped source revision or profile was not found."""


class CandidateProfileConflictError(RuntimeError):
    """A profile conflicts with its exact source, release, or privacy snapshot."""


class CandidateProfilePreconditionError(RuntimeError):
    """The profile aggregate changed before an owner correction could be appended."""


@dataclass(frozen=True, slots=True)
class CandidateProfileVersionRecord:
    profile_version_id: UUID
    version_number: int
    origin: str
    previous_version_id: UUID | None
    schema_id: str
    schema_version: str
    model_provider: str | None
    model_id: str | None
    model_version: str | None
    prompt_id: str | None
    prompt_version: str | None
    instructions_sha256: str | None
    output_schema_sha256: str | None
    model_attempts: int | None
    claim_count: int
    evidence_span_count: int
    evidence_character_count: int
    created_at: datetime
    profile: CandidateProfileOutput = field(repr=False)


@dataclass(frozen=True, slots=True)
class CandidateProfileRecord:
    profile_id: UUID
    source_text_id: UUID
    source_text_version_id: UUID
    document_version_id: UUID
    document_type: str
    latest_version_number: int
    aggregate_version: int
    privacy_policy_version_id: UUID
    retention_rule_id: UUID
    jurisdiction_code: str
    legal_basis: str
    retain_until: datetime
    retention_action: str
    created_at: datetime
    updated_at: datetime
    versions: tuple[CandidateProfileVersionRecord, ...]


@dataclass(frozen=True, slots=True)
class StoreModelProfileResult:
    candidate_profile: CandidateProfileRecord
    created: bool


class CandidateProfileRuntime(Protocol):
    async def store_model_profile(
        self,
        account_id: UUID,
        preparation_id: UUID,
        document_version_id: UUID,
        source_text_version_id: UUID,
        result: ModelGatewayResult[CandidateProfileOutput],
        request_id: str | None,
        *,
        now: datetime | None = None,
    ) -> StoreModelProfileResult: ...

    async def get_profile(
        self,
        account_id: UUID,
        preparation_id: UUID,
        document_version_id: UUID,
        source_text_version_id: UUID,
    ) -> CandidateProfileRecord: ...

    async def append_correction(
        self,
        account_id: UUID,
        preparation_id: UUID,
        document_version_id: UUID,
        source_text_version_id: UUID,
        corrected_profile: CandidateProfileOutput,
        expected_version: int,
        request_id: str | None,
        *,
        now: datetime | None = None,
    ) -> CandidateProfileRecord: ...

    async def export_account_profile_metadata(
        self,
        session: AsyncSession,
        *,
        account_id: UUID,
    ) -> list[dict[str, object]]: ...


class FailClosedCandidateProfileService:
    """Reject profile commands until privacy cryptography is available."""

    @staticmethod
    def _unavailable() -> NoReturn:
        raise CandidateProfileUnavailableError("candidate profiles are not configured")

    async def store_model_profile(
        self,
        account_id: UUID,
        preparation_id: UUID,
        document_version_id: UUID,
        source_text_version_id: UUID,
        result: ModelGatewayResult[CandidateProfileOutput],
        request_id: str | None,
        *,
        now: datetime | None = None,
    ) -> StoreModelProfileResult:
        del account_id, preparation_id, document_version_id, source_text_version_id
        del result, request_id, now
        self._unavailable()

    async def get_profile(
        self,
        account_id: UUID,
        preparation_id: UUID,
        document_version_id: UUID,
        source_text_version_id: UUID,
    ) -> CandidateProfileRecord:
        del account_id, preparation_id, document_version_id, source_text_version_id
        self._unavailable()

    async def append_correction(
        self,
        account_id: UUID,
        preparation_id: UUID,
        document_version_id: UUID,
        source_text_version_id: UUID,
        corrected_profile: CandidateProfileOutput,
        expected_version: int,
        request_id: str | None,
        *,
        now: datetime | None = None,
    ) -> CandidateProfileRecord:
        del account_id, preparation_id, document_version_id, source_text_version_id
        del corrected_profile, expected_version, request_id, now
        self._unavailable()

    async def export_account_profile_metadata(
        self,
        session: AsyncSession,
        *,
        account_id: UUID,
    ) -> list[dict[str, object]]:
        del session, account_id
        return []


class CandidateProfileService:
    """Persist only model profiles re-verified against an exact retained source revision."""

    def __init__(
        self,
        database: DatabaseRuntime,
        application_keyring: ApplicationKeyring,
    ) -> None:
        self._database = database
        self._keyring = application_keyring
        self._source_texts = CandidateSourceTextService(database, application_keyring)

    async def store_model_profile(
        self,
        account_id: UUID,
        preparation_id: UUID,
        document_version_id: UUID,
        source_text_version_id: UUID,
        result: ModelGatewayResult[CandidateProfileOutput],
        request_id: str | None,
        *,
        now: datetime | None = None,
    ) -> StoreModelProfileResult:
        self._validate_gateway_result(result)
        recorded_at = now or datetime.now(UTC)

        async with self._database.transaction() as session:
            account = await session.scalar(
                select(Account).where(Account.id == account_id).with_for_update()
            )
            if account is None or account.status != "active":
                raise CandidateProfileConflictError("the account cannot create profiles")

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
                recorded_at,
            )
            self._require_release_matches_document(result, document.document_type)

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
                raise CandidateProfileConflictError(
                    "the source no longer matches the active privacy decision"
                )

            try:
                source_record = self._source_texts._version_record(
                    source_text,
                    document_version,
                    source_version,
                )
            except CandidateSourceTextUnavailableError as exc:
                raise CandidateProfileUnavailableError(
                    "candidate source text is unavailable"
                ) from exc
            verified = validate_profile_evidence(
                result.output,
                source_record.content,
                document.document_type,
            )

            existing = await session.scalar(
                select(CandidateProfile)
                .where(CandidateProfile.source_text_version_id == source_version.id)
                .with_for_update()
            )
            if existing is not None:
                if existing.owner_id != account_id:
                    raise CandidateProfileNotFoundError("candidate profile was not found")
                record = await self._record(session, existing)
                if not self._same_model_result(record, result):
                    raise CandidateProfileConflictError(
                        "the source revision already has a different profile"
                    )
                return StoreModelProfileResult(candidate_profile=record, created=False)

            canonical_json = self._canonical_profile_json(result.output)
            profile_json = canonical_json.encode("utf-8")
            if len(profile_json) > MAX_PROFILE_JSON_UTF8_BYTES:
                raise ValueError("profile JSON exceeds the UTF-8 byte limit")

            profile_id = uuid7()
            profile_version_id = uuid7()
            digest_key_id = self._keyring.active_key_id("subject_hmac")
            profile_digest = self._keyring.hmac_digest(
                "subject_hmac",
                self._profile_digest_material(account_id, source_version.id, profile_json),
            )
            encryption_key_id = self._keyring.active_key_id("field_encryption")
            profile = CandidateProfile(
                id=profile_id,
                owner_id=account_id,
                source_text_id=source_text.id,
                source_text_version_id=source_version.id,
                document_version_id=document_version.id,
                document_type=document.document_type,
                latest_version_number=1,
                privacy_policy_version_id=document_version.privacy_policy_version_id,
                retention_rule_id=document_version.retention_rule_id,
                jurisdiction_code=document_version.jurisdiction_code,
                legal_basis=document_version.legal_basis,
                retain_until=document_version.retain_until,
                retention_action="delete",
                created_at=recorded_at,
                updated_at=recorded_at,
            )
            version = CandidateProfileVersion(
                id=profile_version_id,
                owner_id=account_id,
                profile_id=profile_id,
                version_number=1,
                origin="model_generation",
                previous_version_id=None,
                schema_id=result.prompt_release.schema_id,
                schema_version=result.prompt_release.schema_version,
                model_provider=result.model_release.provider,
                model_id=result.model_release.model_id,
                model_version=result.model_release.model_version,
                prompt_id=result.prompt_release.prompt_id,
                prompt_version=result.prompt_release.prompt_version,
                instructions_sha256=result.instructions_sha256,
                output_schema_sha256=result.output_schema_sha256,
                model_attempts=result.attempts,
                claim_count=verified.claim_count,
                evidence_span_count=verified.evidence_span_count,
                evidence_character_count=verified.evidence_character_count,
                profile_json_utf8_bytes=len(profile_json),
                profile_digest=profile_digest,
                profile_digest_key_id=digest_key_id,
                profile_ciphertext=b"pending",
                profile_nonce=b"0" * 12,
                profile_encryption_key_id=encryption_key_id,
                created_at=recorded_at,
            )
            aad = self._version_aad(profile, version)
            encrypted = self._keyring.encrypt_field(canonical_json, aad=aad)
            if encrypted.key_id != encryption_key_id:
                raise CandidateProfileUnavailableError("field-encryption key changed")
            version.profile_ciphertext = encrypted.ciphertext
            version.profile_nonce = encrypted.nonce

            session.add_all((profile, version))
            await session.flush()
            privacy_profile, _ = await require_privacy_profile(
                session,
                account_id,
                now=recorded_at,
            )
            await self._record_version_event(
                session,
                profile=profile,
                version=version,
                privacy_profile=privacy_profile,
                request_id=request_id,
                occurred_at=recorded_at,
                action="candidate_profile.model_generation_stored",
                actor_id=None,
            )
            await session.flush()
            return StoreModelProfileResult(
                candidate_profile=await self._record(session, profile),
                created=True,
            )

    async def get_profile(
        self,
        account_id: UUID,
        preparation_id: UUID,
        document_version_id: UUID,
        source_text_version_id: UUID,
    ) -> CandidateProfileRecord:
        async with self._database.transaction() as session:
            document_version = await session.scalar(
                select(CandidateDocumentVersion).where(
                    CandidateDocumentVersion.id == document_version_id,
                    CandidateDocumentVersion.owner_id == account_id,
                )
            )
            if document_version is None:
                raise CandidateProfileNotFoundError("candidate profile was not found")
            document = await session.scalar(
                select(CandidateDocument).where(
                    CandidateDocument.id == document_version.document_id,
                    CandidateDocument.owner_id == account_id,
                    CandidateDocument.preparation_id == preparation_id,
                )
            )
            if document is None:
                raise CandidateProfileNotFoundError("candidate profile was not found")
            profile = await session.scalar(
                select(CandidateProfile).where(
                    CandidateProfile.owner_id == account_id,
                    CandidateProfile.document_version_id == document_version_id,
                    CandidateProfile.source_text_version_id == source_text_version_id,
                )
            )
            if profile is None:
                raise CandidateProfileNotFoundError("candidate profile was not found")
            return await self._record(session, profile)

    async def append_correction(
        self,
        account_id: UUID,
        preparation_id: UUID,
        document_version_id: UUID,
        source_text_version_id: UUID,
        corrected_profile: CandidateProfileOutput,
        expected_version: int,
        request_id: str | None,
        *,
        now: datetime | None = None,
    ) -> CandidateProfileRecord:
        if not isinstance(corrected_profile, (CvProfileOutput, JobDescriptionProfileOutput)):
            raise TypeError("corrected_profile must be a candidate profile")
        canonical_json = self._canonical_profile_json(corrected_profile)
        profile_json = canonical_json.encode("utf-8")
        if len(profile_json) > MAX_PROFILE_JSON_UTF8_BYTES:
            raise ValueError("profile JSON exceeds the UTF-8 byte limit")
        corrected_at = now or datetime.now(UTC)

        async with self._database.transaction() as session:
            account = await session.scalar(
                select(Account).where(Account.id == account_id).with_for_update()
            )
            if account is None or account.status != "active":
                raise CandidateProfileConflictError("the account cannot correct profiles")

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
                corrected_at,
            )
            if corrected_profile.document_type != document.document_type:
                raise CandidateProfileConflictError(
                    "the correction does not match the document type"
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
                raise CandidateProfileConflictError(
                    "the source no longer matches the active privacy decision"
                )

            profile = await session.scalar(
                select(CandidateProfile)
                .where(
                    CandidateProfile.owner_id == account_id,
                    CandidateProfile.document_version_id == document_version_id,
                    CandidateProfile.source_text_version_id == source_text_version_id,
                )
                .with_for_update()
            )
            if profile is None:
                raise CandidateProfileNotFoundError("candidate profile was not found")
            latest_version = await session.scalar(
                select(CandidateProfileVersion).where(
                    CandidateProfileVersion.profile_id == profile.id,
                    CandidateProfileVersion.version_number == profile.latest_version_number,
                )
            )
            if latest_version is None:
                raise CandidateProfileUnavailableError("candidate profile lineage is incomplete")

            try:
                source_record = self._source_texts._version_record(
                    source_text,
                    document_version,
                    source_version,
                )
            except CandidateSourceTextUnavailableError as exc:
                raise CandidateProfileUnavailableError(
                    "candidate profile source is unavailable"
                ) from exc
            verified = validate_profile_evidence(
                corrected_profile,
                source_record.content,
                document.document_type,
            )

            if expected_version < 1:
                raise CandidateProfilePreconditionError("candidate profile version changed")
            if profile.version != expected_version:
                if profile.version == expected_version + 1 and self._is_repeat_correction(
                    profile,
                    latest_version,
                    source_record.content,
                    corrected_profile,
                    expected_version + 1,
                ):
                    return await self._record(session, profile)
                raise CandidateProfilePreconditionError("candidate profile version changed")

            new_version_number = profile.latest_version_number + 1
            profile_version_id = uuid7()
            digest_key_id = self._keyring.active_key_id("subject_hmac")
            profile_digest = self._keyring.hmac_digest(
                "subject_hmac",
                self._profile_digest_material(account_id, source_version.id, profile_json),
            )
            encryption_key_id = self._keyring.active_key_id("field_encryption")
            version = CandidateProfileVersion(
                id=profile_version_id,
                owner_id=account_id,
                profile_id=profile.id,
                version_number=new_version_number,
                origin="user_correction",
                previous_version_id=latest_version.id,
                schema_id=(
                    CV_PROFILE_SCHEMA_ID
                    if document.document_type == "cv"
                    else JOB_DESCRIPTION_PROFILE_SCHEMA_ID
                ),
                schema_version=PROFILE_SCHEMA_VERSION,
                model_provider=None,
                model_id=None,
                model_version=None,
                prompt_id=None,
                prompt_version=None,
                instructions_sha256=None,
                output_schema_sha256=None,
                model_attempts=None,
                claim_count=verified.claim_count,
                evidence_span_count=verified.evidence_span_count,
                evidence_character_count=verified.evidence_character_count,
                profile_json_utf8_bytes=len(profile_json),
                profile_digest=profile_digest,
                profile_digest_key_id=digest_key_id,
                profile_ciphertext=b"pending",
                profile_nonce=b"0" * 12,
                profile_encryption_key_id=encryption_key_id,
                created_at=corrected_at,
            )
            encrypted = self._keyring.encrypt_field(
                canonical_json,
                aad=self._version_aad(profile, version),
            )
            if encrypted.key_id != encryption_key_id:
                raise CandidateProfileUnavailableError("field-encryption key changed")
            version.profile_ciphertext = encrypted.ciphertext
            version.profile_nonce = encrypted.nonce

            profile.latest_version_number = new_version_number
            profile.updated_at = corrected_at
            session.add(version)
            await session.flush()
            privacy_profile, _ = await require_privacy_profile(
                session,
                account_id,
                now=corrected_at,
            )
            await self._record_version_event(
                session,
                profile=profile,
                version=version,
                privacy_profile=privacy_profile,
                request_id=request_id,
                occurred_at=corrected_at,
                action="candidate_profile.correction_appended",
                actor_id=account_id,
            )
            await session.flush()
            return await self._record(session, profile)

    async def export_account_profile_metadata(
        self,
        session: AsyncSession,
        *,
        account_id: UUID,
    ) -> list[dict[str, object]]:
        profiles = list(
            (
                await session.scalars(
                    select(CandidateProfile)
                    .where(CandidateProfile.owner_id == account_id)
                    .order_by(CandidateProfile.created_at, CandidateProfile.id)
                )
            ).all()
        )
        return [self._export_record(await self._record(session, item)) for item in profiles]

    @staticmethod
    def _export_record(record: CandidateProfileRecord) -> dict[str, object]:
        return {
            "profile_id": str(record.profile_id),
            "source_text_id": str(record.source_text_id),
            "source_text_version_id": str(record.source_text_version_id),
            "document_version_id": str(record.document_version_id),
            "document_type": record.document_type,
            "latest_version_number": record.latest_version_number,
            "created_at": record.created_at.isoformat(),
            "updated_at": record.updated_at.isoformat(),
            "versions": [
                {
                    "version_number": version.version_number,
                    "origin": version.origin,
                    "schema_id": version.schema_id,
                    "schema_version": version.schema_version,
                    "model_provider": version.model_provider,
                    "model_id": version.model_id,
                    "model_version": version.model_version,
                    "prompt_id": version.prompt_id,
                    "prompt_version": version.prompt_version,
                    "claim_count": version.claim_count,
                    "evidence_span_count": version.evidence_span_count,
                    "evidence_character_count": version.evidence_character_count,
                    "created_at": version.created_at.isoformat(),
                    "profile": version.profile.model_dump(mode="json"),
                }
                for version in record.versions
            ],
        }

    async def _locked_lineage(
        self,
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
        document_version = await session.scalar(
            select(CandidateDocumentVersion)
            .where(
                CandidateDocumentVersion.id == document_version_id,
                CandidateDocumentVersion.owner_id == account_id,
            )
            .with_for_update()
        )
        if document_version is None:
            raise CandidateProfileNotFoundError("candidate source revision was not found")
        document = await session.scalar(
            select(CandidateDocument)
            .where(
                CandidateDocument.id == document_version.document_id,
                CandidateDocument.owner_id == account_id,
                CandidateDocument.preparation_id == preparation_id,
            )
            .with_for_update()
        )
        preparation = await session.scalar(
            select(CandidatePreparation)
            .where(
                CandidatePreparation.id == preparation_id,
                CandidatePreparation.owner_id == account_id,
            )
            .with_for_update()
        )
        if document is None or preparation is None:
            raise CandidateProfileNotFoundError("candidate source revision was not found")
        source_text = await session.scalar(
            select(CandidateSourceText)
            .where(
                CandidateSourceText.owner_id == account_id,
                CandidateSourceText.document_version_id == document_version_id,
            )
            .with_for_update()
        )
        if source_text is None:
            raise CandidateProfileNotFoundError("candidate source revision was not found")
        source_version = await session.scalar(
            select(CandidateSourceTextVersion)
            .where(
                CandidateSourceTextVersion.id == source_text_version_id,
                CandidateSourceTextVersion.owner_id == account_id,
                CandidateSourceTextVersion.source_text_id == source_text.id,
            )
            .with_for_update()
        )
        if source_version is None:
            raise CandidateProfileNotFoundError("candidate source revision was not found")
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
            raise CandidateProfileConflictError("archived documents cannot be profiled")
        if (
            preparation.retain_until <= evaluated_at
            or preparation.retention_action != "delete"
            or preparation.privacy_policy_version_id != document_version.privacy_policy_version_id
            or preparation.jurisdiction_code != document_version.jurisdiction_code
        ):
            raise CandidateProfileConflictError(
                "the preparation privacy snapshot is no longer processable"
            )
        if document.latest_version_number != document_version.version_number:
            raise CandidateProfileConflictError("only the latest document version can be profiled")
        if document_version.retain_until <= evaluated_at:
            raise CandidateProfileConflictError("the document retention deadline has passed")
        if (
            source_text.latest_version_number != source_version.version_number
            or source_text.document_version_id != document_version.id
        ):
            raise CandidateProfileConflictError("only the latest source revision can be profiled")

    @staticmethod
    def _validate_gateway_result(result: ModelGatewayResult[CandidateProfileOutput]) -> None:
        if not isinstance(result, ModelGatewayResult):
            raise TypeError("result must be a model gateway result")
        if not isinstance(result.output, (CvProfileOutput, JobDescriptionProfileOutput)):
            raise TypeError("model gateway result must contain a candidate profile")
        if not _SHA256_PATTERN.fullmatch(result.instructions_sha256):
            raise ValueError("instructions_sha256 must be a lowercase SHA-256 digest")
        if not _SHA256_PATTERN.fullmatch(result.output_schema_sha256):
            raise ValueError("output_schema_sha256 must be a lowercase SHA-256 digest")
        if not 1 <= result.attempts <= 5:
            raise ValueError("model attempts must be between 1 and 5")

    @staticmethod
    def _require_release_matches_document(
        result: ModelGatewayResult[CandidateProfileOutput],
        document_type: str,
    ) -> None:
        expected_schema_id = (
            CV_PROFILE_SCHEMA_ID if document_type == "cv" else JOB_DESCRIPTION_PROFILE_SCHEMA_ID
        )
        if (
            result.prompt_release.schema_id != expected_schema_id
            or result.prompt_release.schema_version != PROFILE_SCHEMA_VERSION
            or result.output.document_type != document_type
        ):
            raise CandidateProfileConflictError(
                "the model result does not match the document profile release"
            )

    async def _record(
        self,
        session: AsyncSession,
        profile: CandidateProfile,
    ) -> CandidateProfileRecord:
        source_text = await session.get(CandidateSourceText, profile.source_text_id)
        source_version = await session.get(
            CandidateSourceTextVersion,
            profile.source_text_version_id,
        )
        document_version = await session.get(
            CandidateDocumentVersion,
            profile.document_version_id,
        )
        if (
            source_text is None
            or source_version is None
            or document_version is None
            or source_text.owner_id != profile.owner_id
            or source_text.document_version_id != profile.document_version_id
            or source_version.source_text_id != source_text.id
        ):
            raise CandidateProfileUnavailableError("candidate profile lineage is unavailable")
        try:
            source_record = self._source_texts._version_record(
                source_text,
                document_version,
                source_version,
            )
        except CandidateSourceTextUnavailableError as exc:
            raise CandidateProfileUnavailableError(
                "candidate profile source is unavailable"
            ) from exc
        versions = list(
            (
                await session.scalars(
                    select(CandidateProfileVersion)
                    .where(CandidateProfileVersion.profile_id == profile.id)
                    .order_by(CandidateProfileVersion.version_number)
                )
            ).all()
        )
        if (
            not versions
            or versions[-1].version_number != profile.latest_version_number
            or [item.version_number for item in versions]
            != list(range(1, profile.latest_version_number + 1))
        ):
            raise CandidateProfileUnavailableError("candidate profile lineage is incomplete")
        version_records = tuple(
            self._version_record(profile, item, source_record.content) for item in versions
        )
        return CandidateProfileRecord(
            profile_id=profile.id,
            source_text_id=profile.source_text_id,
            source_text_version_id=profile.source_text_version_id,
            document_version_id=profile.document_version_id,
            document_type=profile.document_type,
            latest_version_number=profile.latest_version_number,
            aggregate_version=profile.version,
            privacy_policy_version_id=profile.privacy_policy_version_id,
            retention_rule_id=profile.retention_rule_id,
            jurisdiction_code=profile.jurisdiction_code,
            legal_basis=profile.legal_basis,
            retain_until=profile.retain_until,
            retention_action=profile.retention_action,
            created_at=profile.created_at,
            updated_at=profile.updated_at,
            versions=version_records,
        )

    def _version_record(
        self,
        profile: CandidateProfile,
        version: CandidateProfileVersion,
        source_content: str,
    ) -> CandidateProfileVersionRecord:
        try:
            plaintext = self._keyring.decrypt_field(
                EncryptedValue(
                    key_id=version.profile_encryption_key_id,
                    nonce=version.profile_nonce,
                    ciphertext=version.profile_ciphertext,
                ),
                aad=self._version_aad(profile, version),
            )
        except KeyringError as exc:
            raise CandidateProfileUnavailableError("candidate profile decryption failed") from exc
        try:
            output_type = profile_output_type(profile.document_type)
            output = output_type.model_validate_json(plaintext, strict=True)
        except (ValidationError, ValueError) as exc:
            raise CandidateProfileUnavailableError("candidate profile schema is invalid") from exc
        canonical_json = self._canonical_profile_json(output)
        profile_json = canonical_json.encode("utf-8")
        if (
            plaintext != canonical_json
            or len(profile_json) != version.profile_json_utf8_bytes
            or not self._keyring.verify_hmac(
                "subject_hmac",
                key_id=version.profile_digest_key_id,
                data=self._profile_digest_material(
                    profile.owner_id,
                    profile.source_text_version_id,
                    profile_json,
                ),
                digest=version.profile_digest,
            )
        ):
            raise CandidateProfileUnavailableError("candidate profile integrity check failed")
        verified = validate_profile_evidence(
            output,
            source_content,
            profile.document_type,
        )
        if (
            verified.claim_count != version.claim_count
            or verified.evidence_span_count != version.evidence_span_count
            or verified.evidence_character_count != version.evidence_character_count
        ):
            raise CandidateProfileUnavailableError("candidate profile evidence counts changed")
        return CandidateProfileVersionRecord(
            profile_version_id=version.id,
            version_number=version.version_number,
            origin=version.origin,
            previous_version_id=version.previous_version_id,
            schema_id=version.schema_id,
            schema_version=version.schema_version,
            model_provider=version.model_provider,
            model_id=version.model_id,
            model_version=version.model_version,
            prompt_id=version.prompt_id,
            prompt_version=version.prompt_version,
            instructions_sha256=version.instructions_sha256,
            output_schema_sha256=version.output_schema_sha256,
            model_attempts=version.model_attempts,
            claim_count=version.claim_count,
            evidence_span_count=version.evidence_span_count,
            evidence_character_count=version.evidence_character_count,
            created_at=version.created_at,
            profile=output,
        )

    @staticmethod
    def _canonical_profile_json(profile: CandidateProfileOutput) -> str:
        return json.dumps(
            profile.model_dump(mode="json"),
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )

    @staticmethod
    def _profile_digest_material(
        owner_id: UUID,
        source_text_version_id: UUID,
        profile_json: bytes,
    ) -> bytes:
        return (
            b"candidate-profile-json-v1\x00"
            + owner_id.bytes
            + source_text_version_id.bytes
            + profile_json
        )

    @staticmethod
    def _version_aad(
        profile: CandidateProfile,
        version: CandidateProfileVersion,
    ) -> bytes:
        document = {
            "claim_count": version.claim_count,
            "document_type": profile.document_type,
            "document_version_id": str(profile.document_version_id),
            "evidence_character_count": version.evidence_character_count,
            "evidence_span_count": version.evidence_span_count,
            "instructions_sha256": version.instructions_sha256,
            "jurisdiction_code": profile.jurisdiction_code,
            "legal_basis": profile.legal_basis,
            "model_attempts": version.model_attempts,
            "model_id": version.model_id,
            "model_provider": version.model_provider,
            "model_version": version.model_version,
            "origin": version.origin,
            "output_schema_sha256": version.output_schema_sha256,
            "owner_id": str(profile.owner_id),
            "previous_version_id": (
                str(version.previous_version_id) if version.previous_version_id else None
            ),
            "privacy_policy_version_id": str(profile.privacy_policy_version_id),
            "profile_digest": version.profile_digest,
            "profile_digest_key_id": version.profile_digest_key_id,
            "profile_encryption_key_id": version.profile_encryption_key_id,
            "profile_id": str(profile.id),
            "profile_json_utf8_bytes": version.profile_json_utf8_bytes,
            "profile_version_id": str(version.id),
            "prompt_id": version.prompt_id,
            "prompt_version": version.prompt_version,
            "retain_until": profile.retain_until.isoformat(),
            "retention_action": profile.retention_action,
            "retention_rule_id": str(profile.retention_rule_id),
            "schema_id": version.schema_id,
            "schema_version": version.schema_version,
            "source_text_id": str(profile.source_text_id),
            "source_text_version_id": str(profile.source_text_version_id),
            "version": 1,
            "version_number": version.version_number,
        }
        return json.dumps(document, sort_keys=True, separators=(",", ":")).encode()

    @staticmethod
    def _same_model_result(
        record: CandidateProfileRecord,
        result: ModelGatewayResult[CandidateProfileOutput],
    ) -> bool:
        if not record.versions:
            return False
        version = record.versions[0]
        return (
            version.origin == "model_generation"
            and version.profile == result.output
            and version.schema_id == result.prompt_release.schema_id
            and version.schema_version == result.prompt_release.schema_version
            and version.model_provider == result.model_release.provider
            and version.model_id == result.model_release.model_id
            and version.model_version == result.model_release.model_version
            and version.prompt_id == result.prompt_release.prompt_id
            and version.prompt_version == result.prompt_release.prompt_version
            and version.instructions_sha256 == result.instructions_sha256
            and version.output_schema_sha256 == result.output_schema_sha256
            and version.model_attempts == result.attempts
        )

    def _is_repeat_correction(
        self,
        profile: CandidateProfile,
        latest_version: CandidateProfileVersion,
        source_content: str,
        corrected_profile: CandidateProfileOutput,
        expected_next_version_number: int,
    ) -> bool:
        if (
            latest_version.origin != "user_correction"
            or latest_version.version_number != expected_next_version_number
        ):
            return False
        try:
            record = self._version_record(profile, latest_version, source_content)
        except CandidateProfileUnavailableError:
            return False
        return record.profile == corrected_profile

    @staticmethod
    async def _record_version_event(
        session: AsyncSession,
        *,
        profile: CandidateProfile,
        version: CandidateProfileVersion,
        privacy_profile: PrivacyProfile,
        request_id: str | None,
        occurred_at: datetime,
        action: str,
        actor_id: UUID | None,
    ) -> None:
        safe_details = {
            "version_number": version.version_number,
            "origin": version.origin,
            "document_type": profile.document_type,
            "schema_id": version.schema_id,
            "schema_version": version.schema_version,
            "model_provider": version.model_provider,
            "model_id": version.model_id,
            "model_version": version.model_version,
            "prompt_id": version.prompt_id,
            "prompt_version": version.prompt_version,
            "claim_count": version.claim_count,
            "evidence_span_count": version.evidence_span_count,
            "evidence_character_count": version.evidence_character_count,
        }
        await record_privacy_audit(
            session,
            profile=privacy_profile,
            occurred_at=occurred_at,
            actor_id=actor_id,
            action=action,
            resource_type="candidate_profile_version",
            resource_id=version.id,
            owner_id=profile.owner_id,
            request_id=request_id,
            details=safe_details,
        )
        await enqueue_outbox(
            session,
            NewOutboxEvent(
                aggregate_type="candidate_profile",
                aggregate_id=profile.id,
                event_type=action,
                owner_id=profile.owner_id,
                payload={
                    "candidate_profile_id": str(profile.id),
                    "candidate_profile_version_id": str(version.id),
                    "candidate_source_text_version_id": str(profile.source_text_version_id),
                    "candidate_document_version_id": str(profile.document_version_id),
                    **safe_details,
                },
            ),
        )


def build_candidate_profiles(
    settings: Settings,
    database: DatabaseRuntime,
) -> CandidateProfileRuntime:
    if (
        not settings.privacy_enabled
        or not settings.file_security_enabled
        or settings.privacy_keyring is None
    ):
        return FailClosedCandidateProfileService()
    return CandidateProfileService(
        database,
        ApplicationKeyring.from_secret(settings.privacy_keyring),
    )
