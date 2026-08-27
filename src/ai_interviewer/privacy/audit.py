"""Minimal, retention-bounded privacy audit evidence."""

from datetime import datetime, timedelta
from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from ai_interviewer.persistence.models import AuditEvent
from ai_interviewer.persistence.repositories import NewAuditEvent, record_audit_event
from ai_interviewer.privacy.models import PrivacyProfile
from ai_interviewer.privacy.rules import resolve_retention_for_context


async def record_privacy_audit(
    session: AsyncSession,
    *,
    profile: PrivacyProfile,
    occurred_at: datetime,
    actor_id: UUID | None,
    action: str,
    resource_type: str,
    resource_id: UUID | None,
    owner_id: UUID | None,
    request_id: str | None,
    details: dict[str, Any] | None = None,
) -> AuditEvent:
    retention = await resolve_retention_for_context(
        session,
        privacy_policy_version_id=profile.privacy_policy_version_id,
        jurisdiction_codes=profile.jurisdiction_codes,
        data_category="audit_evidence",
        purpose="privacy_administration",
    )
    return await record_audit_event(
        session,
        NewAuditEvent(
            actor_type="user" if actor_id is not None else "system",
            actor_id=actor_id,
            action=action,
            resource_type=resource_type,
            resource_id=resource_id,
            owner_id=owner_id,
            request_id=request_id,
            details=details or {},
            evidence_category="privacy_lifecycle",
            retain_until=occurred_at + timedelta(days=retention.retention_days),
        ),
    )
