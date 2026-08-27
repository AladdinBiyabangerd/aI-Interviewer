"""Privacy-profile configuration and exact versioned consent lifecycle."""

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from ai_interviewer.identity.models import Account
from ai_interviewer.privacy.audit import record_privacy_audit
from ai_interviewer.privacy.models import (
    ConsentNotice,
    ConsentRecord,
    PrivacyPolicyVersion,
    PrivacyProfile,
)
from ai_interviewer.privacy.policy import JurisdictionPolicyRegistry
from ai_interviewer.privacy.rules import (
    PrivacyPolicyUnavailableError,
    require_privacy_profile,
    resolve_retention_for_context,
)


class AdultAttestationRequiredError(Exception):
    """The 18+ product gate was not affirmed."""


class ConsentUnavailableError(Exception):
    """A notice is not published for the account's current policy."""


class ConsentNotFoundError(Exception):
    """The account does not own the requested active grant."""


@dataclass(frozen=True, slots=True)
class ProfileInput:
    residence_country_code: str
    residence_subdivision_code: str | None
    storage_region: str
    adult_attested: bool
    privacy_policy_version_id: UUID


async def configure_privacy_profile(
    session: AsyncSession,
    *,
    registry: JurisdictionPolicyRegistry,
    account_id: UUID,
    profile_input: ProfileInput,
    request_id: str | None,
    now: datetime | None = None,
) -> PrivacyProfile:
    evaluated_at = now or datetime.now(UTC)
    if not profile_input.adult_attested:
        raise AdultAttestationRequiredError("the product is restricted to adults")
    storage_region = profile_input.storage_region.strip().lower()
    if not storage_region or len(storage_region) > 64:
        raise ValueError("storage_region must contain 1-64 characters")
    selection = registry.resolve(
        profile_input.residence_country_code,
        profile_input.residence_subdivision_code,
    )
    policy = await session.get(PrivacyPolicyVersion, profile_input.privacy_policy_version_id)
    if (
        policy is None
        or policy.status != "active"
        or policy.legal_review_status != "approved"
        or policy.jurisdiction_code not in selection.policy_codes
        or policy.effective_at > evaluated_at
        or (policy.retired_at is not None and policy.retired_at <= evaluated_at)
        or policy.minimum_age < selection.minimum_age
    ):
        raise PrivacyPolicyUnavailableError(
            "the selected policy is not approved for this jurisdiction"
        )
    account = await session.scalar(
        select(Account).where(Account.id == account_id).with_for_update()
    )
    if account is None or account.status != "active":
        raise PrivacyPolicyUnavailableError("the account cannot configure privacy settings")

    profile = await session.get(PrivacyProfile, account_id)
    if profile is None:
        profile = PrivacyProfile(
            account_id=account_id,
            residence_country_code=selection.country_code,
            residence_subdivision_code=selection.subdivision_code,
            jurisdiction_codes=list(selection.policy_codes),
            jurisdiction_versions=selection.policy_versions,
            storage_region=storage_region,
            adult_attested_at=evaluated_at,
            privacy_policy_version_id=policy.id,
        )
        session.add(profile)
        await session.flush()
        action = "privacy.profile.created"
    else:
        profile.residence_country_code = selection.country_code
        profile.residence_subdivision_code = selection.subdivision_code
        profile.jurisdiction_codes = list(selection.policy_codes)
        profile.jurisdiction_versions = selection.policy_versions
        profile.storage_region = storage_region
        profile.adult_attested_at = evaluated_at
        profile.privacy_policy_version_id = policy.id
        await session.flush()
        action = "privacy.profile.updated"

    await record_privacy_audit(
        session,
        profile=profile,
        occurred_at=evaluated_at,
        actor_id=account_id,
        action=action,
        resource_type="privacy_profile",
        resource_id=account_id,
        owner_id=account_id,
        request_id=request_id,
        details={
            "jurisdiction_code": policy.jurisdiction_code,
            "policy_version": policy.policy_version,
        },
    )
    return profile


async def grant_consent(
    session: AsyncSession,
    *,
    account_id: UUID,
    consent_notice_id: UUID,
    request_id: str | None,
    now: datetime | None = None,
) -> ConsentRecord:
    evaluated_at = now or datetime.now(UTC)
    profile, policy = await require_privacy_profile(session, account_id, now=evaluated_at)
    notice = await session.get(ConsentNotice, consent_notice_id)
    if (
        notice is None
        or notice.privacy_policy_version_id != policy.id
        or notice.status != "active"
        or notice.effective_at > evaluated_at
        or (notice.retired_at is not None and notice.retired_at <= evaluated_at)
    ):
        raise ConsentUnavailableError("the consent notice is unavailable")
    retention = await resolve_retention_for_context(
        session,
        privacy_policy_version_id=policy.id,
        jurisdiction_codes=profile.jurisdiction_codes,
        data_category="consent_evidence",
        purpose=notice.purpose,
    )
    statement = (
        insert(ConsentRecord)
        .values(
            account_id=account_id,
            consent_notice_id=notice.id,
            granted_at=evaluated_at,
            retain_until=evaluated_at + timedelta(days=retention.retention_days),
            retention_action=retention.action,
            request_id=request_id,
        )
        .on_conflict_do_nothing(
            index_elements=[ConsentRecord.account_id, ConsentRecord.consent_notice_id],
            index_where=ConsentRecord.withdrawn_at.is_(None),
        )
        .returning(ConsentRecord)
    )
    record = (await session.scalars(statement)).one_or_none()
    if record is None:
        existing: ConsentRecord | None = await session.scalar(
            select(ConsentRecord).where(
                ConsentRecord.account_id == account_id,
                ConsentRecord.consent_notice_id == notice.id,
                ConsentRecord.withdrawn_at.is_(None),
            )
        )
        if existing is None:
            raise RuntimeError("consent conflict resolved without an active row")
        return existing

    await record_privacy_audit(
        session,
        profile=profile,
        occurred_at=evaluated_at,
        actor_id=account_id,
        action="consent.granted",
        resource_type="consent_record",
        resource_id=record.id,
        owner_id=account_id,
        request_id=request_id,
        details={
            "notice_key": notice.notice_key,
            "notice_version": notice.notice_version,
            "policy_version": policy.policy_version,
            "purpose": notice.purpose,
        },
    )
    return record


async def withdraw_consent(
    session: AsyncSession,
    *,
    account_id: UUID,
    consent_record_id: UUID,
    request_id: str | None,
    now: datetime | None = None,
) -> ConsentRecord:
    evaluated_at = now or datetime.now(UTC)
    profile, policy = await require_privacy_profile(session, account_id, now=evaluated_at)
    record = await session.scalar(
        select(ConsentRecord)
        .where(
            ConsentRecord.id == consent_record_id,
            ConsentRecord.account_id == account_id,
        )
        .with_for_update()
    )
    if record is None or record.withdrawn_at is not None:
        raise ConsentNotFoundError("the active consent record was not found")
    notice = await session.get(ConsentNotice, record.consent_notice_id)
    if notice is None or notice.privacy_policy_version_id != policy.id:
        raise ConsentUnavailableError("the consent notice is unavailable")
    record.withdrawn_at = evaluated_at
    await session.flush()
    await record_privacy_audit(
        session,
        profile=profile,
        occurred_at=evaluated_at,
        actor_id=account_id,
        action="consent.withdrawn",
        resource_type="consent_record",
        resource_id=record.id,
        owner_id=account_id,
        request_id=request_id,
        details={
            "notice_key": notice.notice_key,
            "notice_version": notice.notice_version,
            "policy_version": policy.policy_version,
            "purpose": notice.purpose,
        },
    )
    return record
