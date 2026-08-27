"""Fail-closed policy, purpose, legal-basis, consent, and retention resolution."""

import re
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ai_interviewer.privacy.models import (
    ConsentNotice,
    ConsentRecord,
    PrivacyPolicyVersion,
    PrivacyProfile,
    ProcessingRule,
    RetentionAction,
    RetentionRule,
)

_CONTEXT_CODE = re.compile(r"^[a-z][a-z0-9_.:-]{0,99}$")


class PrivacyPolicyError(Exception):
    """Base fail-closed policy resolution error."""


class PrivacyProfileRequiredError(PrivacyPolicyError):
    """Processing cannot proceed without a verified privacy profile."""


class PrivacyPolicyUnavailableError(PrivacyPolicyError):
    """No approved, active policy or retention rule covers the context."""


class ProcessingDeniedError(PrivacyPolicyError):
    """The applicable policy explicitly denies the processing activity."""


class ConsentRequiredError(PrivacyPolicyError):
    """The exact consent notice required by the processing rule is not active."""


@dataclass(frozen=True, slots=True)
class ProcessingDecision:
    allowed: bool
    privacy_policy_version_id: UUID
    jurisdiction_code: str
    data_category: str
    purpose: str
    legal_basis: str
    consent_notice_id: UUID | None
    retention_rule_id: UUID
    retention_days: int
    retention_action: RetentionAction


def validate_context_code(value: str, field_name: str) -> str:
    normalized = value.strip().lower()
    if _CONTEXT_CODE.fullmatch(normalized) is None:
        raise ValueError(f"{field_name} must use a bounded lowercase policy code")
    return normalized


async def active_policy_for_profile(
    session: AsyncSession,
    profile: PrivacyProfile,
    *,
    now: datetime | None = None,
) -> PrivacyPolicyVersion:
    evaluated_at = now or datetime.now(UTC)
    policy = await session.get(PrivacyPolicyVersion, profile.privacy_policy_version_id)
    if (
        policy is None
        or policy.status != "active"
        or policy.legal_review_status != "approved"
        or policy.effective_at > evaluated_at
        or (policy.retired_at is not None and policy.retired_at <= evaluated_at)
        or policy.jurisdiction_code not in profile.jurisdiction_codes
    ):
        raise PrivacyPolicyUnavailableError("the selected privacy policy is not active")
    return policy


async def require_privacy_profile(
    session: AsyncSession,
    account_id: UUID,
    *,
    now: datetime | None = None,
) -> tuple[PrivacyProfile, PrivacyPolicyVersion]:
    profile = await session.get(PrivacyProfile, account_id)
    if profile is None:
        raise PrivacyProfileRequiredError("a privacy profile is required")
    return profile, await active_policy_for_profile(session, profile, now=now)


async def resolve_retention_for_context(
    session: AsyncSession,
    *,
    privacy_policy_version_id: UUID,
    jurisdiction_codes: list[str] | tuple[str, ...],
    data_category: str,
    purpose: str,
) -> RetentionRule:
    category = validate_context_code(data_category, "data_category")
    processing_purpose = validate_context_code(purpose, "purpose")
    if not jurisdiction_codes:
        raise PrivacyPolicyUnavailableError("no jurisdiction routing snapshot is available")
    rules = list(
        (
            await session.scalars(
                select(RetentionRule).where(
                    RetentionRule.privacy_policy_version_id == privacy_policy_version_id,
                    RetentionRule.jurisdiction_code.in_(jurisdiction_codes),
                    RetentionRule.data_category == category,
                    RetentionRule.purpose.in_((processing_purpose, "*")),
                )
            )
        ).all()
    )
    by_context = {(rule.jurisdiction_code, rule.purpose): rule for rule in rules}
    for jurisdiction_code in jurisdiction_codes:
        for candidate_purpose in (processing_purpose, "*"):
            rule = by_context.get((jurisdiction_code, candidate_purpose))
            if rule is not None:
                return rule
    raise PrivacyPolicyUnavailableError(
        "no approved retention rule covers this category and purpose"
    )


async def authorize_processing(
    session: AsyncSession,
    *,
    account_id: UUID,
    data_category: str,
    purpose: str,
    now: datetime | None = None,
) -> ProcessingDecision:
    category = validate_context_code(data_category, "data_category")
    processing_purpose = validate_context_code(purpose, "purpose")
    profile, policy = await require_privacy_profile(session, account_id, now=now)
    rules = list(
        (
            await session.scalars(
                select(ProcessingRule).where(
                    ProcessingRule.privacy_policy_version_id == policy.id,
                    ProcessingRule.jurisdiction_code.in_(profile.jurisdiction_codes),
                    ProcessingRule.data_category == category,
                    ProcessingRule.purpose == processing_purpose,
                )
            )
        ).all()
    )
    by_jurisdiction = {rule.jurisdiction_code: rule for rule in rules}
    rule = next(
        (
            by_jurisdiction[jurisdiction]
            for jurisdiction in profile.jurisdiction_codes
            if jurisdiction in by_jurisdiction
        ),
        None,
    )
    if rule is None:
        raise PrivacyPolicyUnavailableError("no processing rule covers this context")
    if not rule.allowed:
        raise ProcessingDeniedError("the applicable policy denies this processing")

    if rule.consent_notice_id is not None:
        notice = await session.get(ConsentNotice, rule.consent_notice_id)
        active_consent = await session.scalar(
            select(ConsentRecord.id).where(
                ConsentRecord.account_id == account_id,
                ConsentRecord.consent_notice_id == rule.consent_notice_id,
                ConsentRecord.withdrawn_at.is_(None),
            )
        )
        if (
            notice is None
            or notice.privacy_policy_version_id != policy.id
            or active_consent is None
        ):
            raise ConsentRequiredError("the required consent notice is not active")

    retention = await resolve_retention_for_context(
        session,
        privacy_policy_version_id=policy.id,
        jurisdiction_codes=profile.jurisdiction_codes,
        data_category=category,
        purpose=processing_purpose,
    )
    return ProcessingDecision(
        allowed=True,
        privacy_policy_version_id=policy.id,
        jurisdiction_code=rule.jurisdiction_code,
        data_category=category,
        purpose=processing_purpose,
        legal_basis=rule.legal_basis,
        consent_notice_id=rule.consent_notice_id,
        retention_rule_id=retention.id,
        retention_days=retention.retention_days,
        retention_action=retention.action,
    )
