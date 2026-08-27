"""Identity persistence operations."""

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from ai_interviewer.identity.models import Account
from ai_interviewer.persistence.repositories import NewAuditEvent, record_audit_event


@dataclass(frozen=True, slots=True)
class AccountResolution:
    account: Account
    provisioned: bool


async def resolve_account(
    session: AsyncSession,
    *,
    issuer: str,
    subject: str,
    request_id: str | None,
) -> AccountResolution:
    """Provision an issuer/subject once and return the existing row on conflicts."""
    statement = (
        insert(Account)
        .values(issuer=issuer, subject=subject)
        .on_conflict_do_nothing(index_elements=[Account.issuer, Account.subject])
        .returning(Account)
    )
    account = (await session.scalars(statement)).one_or_none()
    if account is not None:
        await record_audit_event(
            session,
            NewAuditEvent(
                actor_type="user",
                actor_id=account.id,
                action="account.provisioned",
                resource_type="account",
                resource_id=account.id,
                owner_id=account.id,
                request_id=request_id,
                details={"authentication_method": "oidc"},
            ),
        )
        return AccountResolution(account=account, provisioned=True)

    account = await session.scalar(
        select(Account).where(Account.issuer == issuer, Account.subject == subject)
    )
    if account is None:
        raise RuntimeError("account conflict resolved without a visible row")
    return AccountResolution(account=account, provisioned=False)
