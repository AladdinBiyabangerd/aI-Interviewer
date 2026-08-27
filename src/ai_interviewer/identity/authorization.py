"""Deny-by-default authentication, scope, and ownership policies."""

from collections.abc import Callable, Coroutine
from typing import Annotated, Any, cast
from uuid import UUID

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from ai_interviewer.api.errors import request_id_from
from ai_interviewer.identity.service import (
    AccountAccessDeniedError,
    AuthenticationRuntime,
    AuthenticationUnavailableError,
    Principal,
)
from ai_interviewer.identity.tokens import AccessTokenError

bearer_scheme = HTTPBearer(auto_error=False)


async def current_principal(
    request: Request,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer_scheme)],
) -> Principal:
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication credentials are required.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    authentication = cast(AuthenticationRuntime, request.app.state.authentication)
    try:
        principal = await authentication.authenticate(
            credentials.credentials,
            request_id_from(request),
        )
    except AccessTokenError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication credentials are invalid.",
            headers={"WWW-Authenticate": 'Bearer error="invalid_token"'},
        ) from exc
    except AuthenticationUnavailableError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Authentication is temporarily unavailable.",
        ) from exc
    except AccountAccessDeniedError as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Account access is disabled.",
        ) from exc
    request.state.account_id = principal.account_id
    return principal


PrincipalDependency = Callable[..., Coroutine[Any, Any, Principal]]


def require_scopes(*required_scopes: str) -> PrincipalDependency:
    """Build a dependency that authenticates first and then enforces every scope."""
    required = frozenset(required_scopes)
    if not required or any(not scope or len(scope) > 100 for scope in required):
        raise ValueError("at least one valid required scope is needed")

    async def dependency(
        principal: Annotated[Principal, Depends(current_principal)],
    ) -> Principal:
        if not required.issubset(principal.scopes):
            scope_value = " ".join(sorted(required))
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="The token does not grant the required permission.",
                headers={
                    "WWW-Authenticate": (
                        f'Bearer error="insufficient_scope", scope="{scope_value}"'
                    )
                },
            )
        return principal

    return dependency


def enforce_owner(principal: Principal, owner_id: UUID) -> None:
    """Hide another owner's resource instead of revealing its existence."""
    if principal.account_id != owner_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="The requested resource was not found.",
        )
