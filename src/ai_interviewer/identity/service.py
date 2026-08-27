"""Authentication orchestration and minimal principal creation."""

from dataclasses import dataclass
from typing import Protocol
from uuid import UUID

from ai_interviewer.core.config import Settings
from ai_interviewer.identity.repositories import resolve_account
from ai_interviewer.identity.tokens import (
    AccessTokenVerifier,
    JWTAccessTokenVerifier,
)
from ai_interviewer.persistence.database import DatabaseRuntime


class AuthenticationUnavailableError(Exception):
    """Authentication is intentionally unavailable in this environment."""


class AccountAccessDeniedError(Exception):
    """The external identity maps to a locally disabled account."""


@dataclass(frozen=True, slots=True)
class Principal:
    account_id: UUID
    scopes: frozenset[str]


class AuthenticationRuntime(Protocol):
    async def authenticate(self, access_token: str, request_id: str | None) -> Principal: ...


class FailClosedAuthentication:
    """Reject protected requests when authentication is not configured."""

    async def authenticate(self, access_token: str, request_id: str | None) -> Principal:
        del access_token, request_id
        raise AuthenticationUnavailableError("authentication is not configured")


class AuthenticationService:
    def __init__(self, database: DatabaseRuntime, verifier: AccessTokenVerifier) -> None:
        self._database = database
        self._verifier = verifier

    async def authenticate(self, access_token: str, request_id: str | None) -> Principal:
        verified = await self._verifier.verify(access_token)
        async with self._database.transaction() as session:
            resolution = await resolve_account(
                session,
                issuer=verified.issuer,
                subject=verified.subject,
                request_id=request_id,
            )
            if resolution.account.status != "active":
                raise AccountAccessDeniedError("account is disabled")
            account_id = resolution.account.id
        return Principal(account_id=account_id, scopes=verified.scopes)


def build_authentication(settings: Settings, database: DatabaseRuntime) -> AuthenticationRuntime:
    if not settings.auth_enabled:
        return FailClosedAuthentication()
    return AuthenticationService(database, JWTAccessTokenVerifier(settings))
