"""Owner-bound, privacy-aware candidate preparation context service."""

from __future__ import annotations

import hashlib
import re
import unicodedata
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import NoReturn, Protocol
from uuid import UUID

from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from ai_interviewer.candidate_inputs.models import (
    INTERVIEW_LANGUAGES,
    INTERVIEW_ROUNDS,
    ROLE_FAMILIES,
    SENIORITY_LEVELS,
    CandidatePreparation,
    InterviewLanguage,
    InterviewRound,
    RoleFamily,
    Seniority,
)
from ai_interviewer.core.config import Settings
from ai_interviewer.identity.models import Account
from ai_interviewer.persistence.database import DatabaseRuntime
from ai_interviewer.persistence.repositories import NewOutboxEvent, enqueue_outbox
from ai_interviewer.privacy.audit import record_privacy_audit
from ai_interviewer.privacy.models import PrivacyProfile
from ai_interviewer.privacy.rules import authorize_processing, require_privacy_profile

DATA_CATEGORY = "candidate_preparation_context"
PROCESSING_PURPOSE = "interview_preparation"
_COUNTRY_CODE = re.compile(r"^[A-Za-z]{2}$")


class CandidateInputUnavailableError(Exception):
    """The candidate-input boundary is disabled or unavailable."""


class CandidatePreparationNotFoundError(Exception):
    """An owned preparation was not found."""


class CandidatePreparationConflictError(Exception):
    """A preparation command conflicts with durable state or policy."""


class CandidatePreparationPreconditionError(Exception):
    """The supplied aggregate version is stale."""


@dataclass(frozen=True, slots=True)
class PreparationInput:
    company_name: str
    role_family: RoleFamily
    role_family_other: str | None
    role_title: str
    seniority: Seniority
    seniority_other: str | None
    target_country_code: str
    target_office: str | None
    interview_round: InterviewRound
    interview_round_other: str | None
    interview_language: InterviewLanguage


@dataclass(frozen=True, slots=True)
class CreatePreparationResult:
    preparation: CandidatePreparation
    created: bool


@dataclass(frozen=True, slots=True)
class PreparationPage:
    items: tuple[CandidatePreparation, ...]
    next_after: UUID | None


class CandidateInputRuntime(Protocol):
    async def create_preparation(
        self,
        account_id: UUID,
        preparation_input: PreparationInput,
        idempotency_key: str,
        request_id: str | None,
        *,
        now: datetime | None = None,
    ) -> CreatePreparationResult: ...

    async def list_preparations(
        self,
        account_id: UUID,
        *,
        limit: int,
        after: UUID | None,
    ) -> PreparationPage: ...

    async def get_preparation(
        self,
        account_id: UUID,
        preparation_id: UUID,
    ) -> CandidatePreparation: ...

    async def replace_preparation(
        self,
        account_id: UUID,
        preparation_id: UUID,
        preparation_input: PreparationInput,
        expected_version: int,
        request_id: str | None,
        *,
        now: datetime | None = None,
    ) -> CandidatePreparation: ...

    async def archive_preparation(
        self,
        account_id: UUID,
        preparation_id: UUID,
        expected_version: int,
        request_id: str | None,
        *,
        now: datetime | None = None,
    ) -> CandidatePreparation: ...

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


def _normalize_text(value: str, field_name: str, maximum: int) -> str:
    normalized = unicodedata.normalize("NFKC", value)
    if any(unicodedata.category(character) in {"Cc", "Cf", "Cs"} for character in normalized):
        raise ValueError(f"{field_name} contains unsupported control characters")
    normalized = normalized.strip()
    if not normalized or len(normalized) > maximum:
        raise ValueError(f"{field_name} must contain 1-{maximum} characters")
    return normalized


def _normalize_optional_text(value: str | None, field_name: str, maximum: int) -> str | None:
    return None if value is None else _normalize_text(value, field_name, maximum)


def normalize_preparation_input(value: PreparationInput) -> PreparationInput:
    role_family = value.role_family.strip().lower()
    seniority = value.seniority.strip().lower()
    interview_round = value.interview_round.strip().lower()
    interview_language = value.interview_language.strip().lower()
    if role_family not in ROLE_FAMILIES:
        raise ValueError("role_family is not supported")
    if seniority not in SENIORITY_LEVELS:
        raise ValueError("seniority is not supported")
    if interview_round not in INTERVIEW_ROUNDS:
        raise ValueError("interview_round is not supported")
    if interview_language not in INTERVIEW_LANGUAGES:
        raise ValueError("interview_language is not supported")
    country = value.target_country_code.strip().upper()
    if _COUNTRY_CODE.fullmatch(country) is None:
        raise ValueError("target_country_code must be two ASCII letters")

    role_other = _normalize_optional_text(value.role_family_other, "role_family_other", 100)
    seniority_other = _normalize_optional_text(value.seniority_other, "seniority_other", 100)
    round_other = _normalize_optional_text(
        value.interview_round_other, "interview_round_other", 100
    )
    for code, fallback, name in (
        (role_family, role_other, "role_family_other"),
        (seniority, seniority_other, "seniority_other"),
        (interview_round, round_other, "interview_round_other"),
    ):
        if (code == "other") != (fallback is not None):
            raise ValueError(f"{name} is required only when its controlled value is other")

    return PreparationInput(
        company_name=_normalize_text(value.company_name, "company_name", 200),
        role_family=role_family,  # type: ignore[arg-type]
        role_family_other=role_other,
        role_title=_normalize_text(value.role_title, "role_title", 200),
        seniority=seniority,  # type: ignore[arg-type]
        seniority_other=seniority_other,
        target_country_code=country,
        target_office=_normalize_optional_text(value.target_office, "target_office", 200),
        interview_round=interview_round,  # type: ignore[arg-type]
        interview_round_other=round_other,
        interview_language=interview_language,  # type: ignore[arg-type]
    )


class FailClosedCandidateInputService:
    """Reject candidate-input routes until the privacy boundary is enabled."""

    @staticmethod
    def _unavailable() -> NoReturn:
        raise CandidateInputUnavailableError("candidate inputs are not configured")

    async def create_preparation(
        self,
        account_id: UUID,
        preparation_input: PreparationInput,
        idempotency_key: str,
        request_id: str | None,
        *,
        now: datetime | None = None,
    ) -> CreatePreparationResult:
        del account_id, preparation_input, idempotency_key, request_id, now
        self._unavailable()

    async def list_preparations(
        self, account_id: UUID, *, limit: int, after: UUID | None
    ) -> PreparationPage:
        del account_id, limit, after
        self._unavailable()

    async def get_preparation(self, account_id: UUID, preparation_id: UUID) -> CandidatePreparation:
        del account_id, preparation_id
        self._unavailable()

    async def replace_preparation(
        self,
        account_id: UUID,
        preparation_id: UUID,
        preparation_input: PreparationInput,
        expected_version: int,
        request_id: str | None,
        *,
        now: datetime | None = None,
    ) -> CandidatePreparation:
        del account_id, preparation_id, preparation_input, expected_version, request_id, now
        self._unavailable()

    async def archive_preparation(
        self,
        account_id: UUID,
        preparation_id: UUID,
        expected_version: int,
        request_id: str | None,
        *,
        now: datetime | None = None,
    ) -> CandidatePreparation:
        del account_id, preparation_id, expected_version, request_id, now
        self._unavailable()

    async def export_account_metadata(
        self, session: AsyncSession, *, account_id: UUID
    ) -> list[dict[str, object]]:
        del session, account_id
        return []

    async def erase_account_metadata(self, session: AsyncSession, *, account_id: UUID) -> int:
        del session, account_id
        return 0


class CandidateInputService:
    def __init__(self, database: DatabaseRuntime) -> None:
        self._database = database

    async def create_preparation(
        self,
        account_id: UUID,
        preparation_input: PreparationInput,
        idempotency_key: str,
        request_id: str | None,
        *,
        now: datetime | None = None,
    ) -> CreatePreparationResult:
        normalized = normalize_preparation_input(preparation_input)
        normalized_key = idempotency_key.strip()
        if len(normalized_key) < 8 or len(normalized_key) > 128:
            raise ValueError("idempotency key must contain 8-128 characters")
        key_hash = hashlib.sha256(normalized_key.encode()).hexdigest()
        created_at = now or datetime.now(UTC)
        async with self._database.transaction() as session:
            account = await session.scalar(
                select(Account).where(Account.id == account_id).with_for_update()
            )
            if account is None or account.status != "active":
                raise CandidatePreparationConflictError("the account cannot create preparations")
            decision = await authorize_processing(
                session,
                account_id=account_id,
                data_category=DATA_CATEGORY,
                purpose=PROCESSING_PURPOSE,
                now=created_at,
            )
            if decision.retention_action != "delete":
                raise CandidatePreparationConflictError(
                    "candidate preparation context requires delete retention"
                )
            values = self._creation_values(
                account_id,
                normalized,
                key_hash,
                created_at,
                decision.privacy_policy_version_id,
                decision.jurisdiction_code,
                decision.legal_basis,
                decision.retention_rule_id,
                decision.retention_days,
            )
            statement = (
                insert(CandidatePreparation)
                .values(**values)
                .on_conflict_do_nothing(constraint="uq_candidate_preparations_owner_idempotency")
                .returning(CandidatePreparation)
            )
            preparation = (await session.scalars(statement)).one_or_none()
            if preparation is None:
                preparation = await session.scalar(
                    select(CandidatePreparation).where(
                        CandidatePreparation.owner_id == account_id,
                        CandidatePreparation.idempotency_key_hash == key_hash,
                    )
                )
                if preparation is None:
                    raise RuntimeError("idempotency conflict resolved without a visible row")
                if not self._matches_input(preparation, normalized):
                    raise CandidatePreparationConflictError(
                        "the idempotency key was used for another preparation"
                    )
                return CreatePreparationResult(preparation=preparation, created=False)

            profile, _ = await require_privacy_profile(session, account_id, now=created_at)
            await self._record_change(
                session,
                preparation=preparation,
                profile=profile,
                account_id=account_id,
                action="candidate_preparation.created",
                event_type="candidate_preparation.created",
                request_id=request_id,
                occurred_at=created_at,
            )
            await session.flush()
            return CreatePreparationResult(preparation=preparation, created=True)

    async def list_preparations(
        self,
        account_id: UUID,
        *,
        limit: int,
        after: UUID | None,
    ) -> PreparationPage:
        if limit < 1 or limit > 100:
            raise ValueError("limit must be between 1 and 100")
        async with self._database.transaction() as session:
            statement = select(CandidatePreparation).where(
                CandidatePreparation.owner_id == account_id
            )
            if after is not None:
                statement = statement.where(CandidatePreparation.id > after)
            rows = list(
                (
                    await session.scalars(
                        statement.order_by(CandidatePreparation.id).limit(limit + 1)
                    )
                ).all()
            )
            has_more = len(rows) > limit
            items = rows[:limit]
            return PreparationPage(
                items=tuple(items),
                next_after=items[-1].id if has_more and items else None,
            )

    async def get_preparation(
        self,
        account_id: UUID,
        preparation_id: UUID,
    ) -> CandidatePreparation:
        async with self._database.transaction() as session:
            return await self._owned_preparation(session, account_id, preparation_id)

    async def replace_preparation(
        self,
        account_id: UUID,
        preparation_id: UUID,
        preparation_input: PreparationInput,
        expected_version: int,
        request_id: str | None,
        *,
        now: datetime | None = None,
    ) -> CandidatePreparation:
        normalized = normalize_preparation_input(preparation_input)
        changed_at = now or datetime.now(UTC)
        async with self._database.transaction() as session:
            preparation = await self._owned_preparation(
                session, account_id, preparation_id, lock=True
            )
            self._require_version(preparation, expected_version)
            if preparation.status != "draft":
                raise CandidatePreparationConflictError("archived preparation cannot be changed")
            decision = await authorize_processing(
                session,
                account_id=account_id,
                data_category=DATA_CATEGORY,
                purpose=PROCESSING_PURPOSE,
                now=changed_at,
            )
            if decision.retention_action != "delete":
                raise CandidatePreparationConflictError(
                    "candidate preparation context requires delete retention"
                )
            self._apply_input(preparation, normalized)
            preparation.privacy_policy_version_id = decision.privacy_policy_version_id
            preparation.jurisdiction_code = decision.jurisdiction_code
            preparation.legal_basis = decision.legal_basis
            preparation.retention_rule_id = decision.retention_rule_id
            preparation.retain_until = changed_at + timedelta(days=decision.retention_days)
            profile, _ = await require_privacy_profile(session, account_id, now=changed_at)
            await session.flush()
            await self._record_change(
                session,
                preparation=preparation,
                profile=profile,
                account_id=account_id,
                action="candidate_preparation.updated",
                event_type="candidate_preparation.updated",
                request_id=request_id,
                occurred_at=changed_at,
            )
            await session.flush()
            return preparation

    async def archive_preparation(
        self,
        account_id: UUID,
        preparation_id: UUID,
        expected_version: int,
        request_id: str | None,
        *,
        now: datetime | None = None,
    ) -> CandidatePreparation:
        archived_at = now or datetime.now(UTC)
        async with self._database.transaction() as session:
            preparation = await self._owned_preparation(
                session, account_id, preparation_id, lock=True
            )
            self._require_version(preparation, expected_version)
            if preparation.status == "archived":
                return preparation
            profile, _ = await require_privacy_profile(session, account_id, now=archived_at)
            preparation.status = "archived"
            await session.flush()
            await self._record_change(
                session,
                preparation=preparation,
                profile=profile,
                account_id=account_id,
                action="candidate_preparation.archived",
                event_type="candidate_preparation.archived",
                request_id=request_id,
                occurred_at=archived_at,
            )
            await session.flush()
            return preparation

    async def export_account_metadata(
        self,
        session: AsyncSession,
        *,
        account_id: UUID,
    ) -> list[dict[str, object]]:
        preparations = list(
            (
                await session.scalars(
                    select(CandidatePreparation)
                    .where(CandidatePreparation.owner_id == account_id)
                    .order_by(CandidatePreparation.id)
                )
            ).all()
        )
        return [self._export_item(item) for item in preparations]

    async def erase_account_metadata(
        self,
        session: AsyncSession,
        *,
        account_id: UUID,
    ) -> int:
        result = await session.execute(
            delete(CandidatePreparation)
            .where(CandidatePreparation.owner_id == account_id)
            .returning(CandidatePreparation.id)
        )
        return len(result.scalars().all())

    @staticmethod
    async def _owned_preparation(
        session: AsyncSession,
        account_id: UUID,
        preparation_id: UUID,
        *,
        lock: bool = False,
    ) -> CandidatePreparation:
        statement = select(CandidatePreparation).where(
            CandidatePreparation.id == preparation_id,
            CandidatePreparation.owner_id == account_id,
        )
        if lock:
            statement = statement.with_for_update()
        preparation = await session.scalar(statement)
        if preparation is None:
            raise CandidatePreparationNotFoundError("candidate preparation was not found")
        return preparation

    @staticmethod
    def _require_version(preparation: CandidatePreparation, expected_version: int) -> None:
        if expected_version < 1 or preparation.version != expected_version:
            raise CandidatePreparationPreconditionError("candidate preparation version changed")

    @staticmethod
    def _creation_values(
        account_id: UUID,
        value: PreparationInput,
        key_hash: str,
        created_at: datetime,
        policy_id: UUID,
        jurisdiction_code: str,
        legal_basis: str,
        retention_rule_id: UUID,
        retention_days: int,
    ) -> dict[str, object]:
        return {
            "owner_id": account_id,
            **CandidateInputService._input_values(value),
            "status": "draft",
            "privacy_policy_version_id": policy_id,
            "jurisdiction_code": jurisdiction_code,
            "legal_basis": legal_basis,
            "retention_rule_id": retention_rule_id,
            "retain_until": created_at + timedelta(days=retention_days),
            "retention_action": "delete",
            "idempotency_key_hash": key_hash,
            "created_at": created_at,
            "updated_at": created_at,
        }

    @staticmethod
    def _input_values(value: PreparationInput) -> dict[str, object]:
        return {
            "company_name": value.company_name,
            "role_family": value.role_family,
            "role_family_other": value.role_family_other,
            "role_title": value.role_title,
            "seniority": value.seniority,
            "seniority_other": value.seniority_other,
            "target_country_code": value.target_country_code,
            "target_office": value.target_office,
            "interview_round": value.interview_round,
            "interview_round_other": value.interview_round_other,
            "interview_language": value.interview_language,
        }

    @staticmethod
    def _apply_input(preparation: CandidatePreparation, value: PreparationInput) -> None:
        for field_name, field_value in CandidateInputService._input_values(value).items():
            setattr(preparation, field_name, field_value)

    @staticmethod
    def _matches_input(preparation: CandidatePreparation, value: PreparationInput) -> bool:
        return all(
            getattr(preparation, field_name) == field_value
            for field_name, field_value in CandidateInputService._input_values(value).items()
        )

    @staticmethod
    async def _record_change(
        session: AsyncSession,
        *,
        preparation: CandidatePreparation,
        profile: PrivacyProfile,
        account_id: UUID,
        action: str,
        event_type: str,
        request_id: str | None,
        occurred_at: datetime,
    ) -> None:
        safe_details = {
            "role_family": preparation.role_family,
            "seniority": preparation.seniority,
            "interview_round": preparation.interview_round,
            "interview_language": preparation.interview_language,
            "status": preparation.status,
        }
        await record_privacy_audit(
            session,
            profile=profile,
            occurred_at=occurred_at,
            actor_id=account_id,
            action=action,
            resource_type="candidate_preparation",
            resource_id=preparation.id,
            owner_id=account_id,
            request_id=request_id,
            details=safe_details,
        )
        await enqueue_outbox(
            session,
            NewOutboxEvent(
                aggregate_type="candidate_preparation",
                aggregate_id=preparation.id,
                event_type=event_type,
                owner_id=account_id,
                payload={
                    "candidate_preparation_id": str(preparation.id),
                    "version": preparation.version,
                    **safe_details,
                },
            ),
        )

    @staticmethod
    def _export_item(item: CandidatePreparation) -> dict[str, object]:
        return {
            "preparation_id": str(item.id),
            "company_name": item.company_name,
            "role_family": item.role_family,
            "role_family_other": item.role_family_other,
            "role_title": item.role_title,
            "seniority": item.seniority,
            "seniority_other": item.seniority_other,
            "target_country_code": item.target_country_code,
            "target_office": item.target_office,
            "interview_round": item.interview_round,
            "interview_round_other": item.interview_round_other,
            "interview_language": item.interview_language,
            "status": item.status,
            "created_at": item.created_at.isoformat(),
            "updated_at": item.updated_at.isoformat(),
            "retain_until": item.retain_until.isoformat(),
        }


async def apply_due_candidate_input_retention(
    session: AsyncSession,
    *,
    now: datetime | None = None,
) -> int:
    """Delete expired preparation contexts from stored delete-only snapshots."""
    evaluated_at = now or datetime.now(UTC)
    result = await session.execute(
        delete(CandidatePreparation)
        .where(CandidatePreparation.retain_until <= evaluated_at)
        .returning(CandidatePreparation.id)
    )
    return len(result.scalars().all())


def build_candidate_inputs(
    settings: Settings,
    database: DatabaseRuntime,
) -> CandidateInputRuntime:
    if not settings.privacy_enabled:
        return FailClosedCandidateInputService()
    return CandidateInputService(database)
