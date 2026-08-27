"""Strict JWT access-token verification against an operator-configured OIDC issuer."""

import asyncio
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Protocol

import jwt
from jwt import PyJWK, PyJWKClient
from jwt.exceptions import InvalidTokenError, PyJWKClientError

from ai_interviewer.core.config import Settings


class AccessTokenError(Exception):
    """An access token cannot be trusted or does not meet the local policy."""


@dataclass(frozen=True, slots=True)
class VerifiedAccessToken:
    """Only claims the application is allowed to use for identity and authorization."""

    issuer: str
    subject: str
    scopes: frozenset[str]


class AccessTokenVerifier(Protocol):
    async def verify(self, token: str) -> VerifiedAccessToken: ...


class SigningKeyProvider(Protocol):
    async def get_signing_key(self, token: str) -> PyJWK: ...


class CachedJWKSigningKeyProvider:
    """Fetch and rotate OIDC signing keys with bounded network time and caching."""

    def __init__(self, settings: Settings) -> None:
        self._timeout_seconds = settings.auth_jwks_timeout_seconds
        self._client = PyJWKClient(
            settings.auth_oidc_jwks_url or "",
            cache_keys=False,
            cache_jwk_set=True,
            lifespan=settings.auth_jwks_cache_seconds,
            timeout=settings.auth_jwks_timeout_seconds,
            headers={"User-Agent": "ai-interviewer-platform/0.1"},
        )

    async def get_signing_key(self, token: str) -> PyJWK:
        try:
            async with asyncio.timeout(self._timeout_seconds):
                return await asyncio.to_thread(self._client.get_signing_key_from_jwt, token)
        except (TimeoutError, PyJWKClientError) as exc:
            raise AccessTokenError("signing key is unavailable") from exc


class JWTAccessTokenVerifier:
    """Verify signature, token type, issuer, audience, lifetime, subject, and scopes."""

    def __init__(
        self,
        settings: Settings,
        signing_keys: SigningKeyProvider | None = None,
    ) -> None:
        if not settings.auth_enabled:
            raise ValueError("JWT verifier requires authentication to be enabled")
        self._issuer = settings.auth_oidc_issuer or ""
        self._audience = settings.auth_oidc_audience or ""
        self._algorithms = settings.auth_oidc_algorithms
        self._required_token_type = settings.auth_required_token_type.lower()
        self._clock_skew_seconds = settings.auth_clock_skew_seconds
        self._max_token_age_seconds = settings.auth_max_token_age_seconds
        self._max_token_length = settings.auth_max_token_length
        self._signing_keys = signing_keys or CachedJWKSigningKeyProvider(settings)

    async def verify(self, token: str) -> VerifiedAccessToken:
        if not token or len(token) > self._max_token_length:
            raise AccessTokenError("access token length is invalid")

        try:
            header = jwt.get_unverified_header(token)
        except InvalidTokenError as exc:
            raise AccessTokenError("access token header is invalid") from exc

        algorithm = header.get("alg")
        token_type = header.get("typ")
        key_id = header.get("kid")
        if algorithm not in self._algorithms:
            raise AccessTokenError("access token algorithm is not allowed")
        if not isinstance(token_type, str) or token_type.lower() != self._required_token_type:
            raise AccessTokenError("access token type is invalid")
        if not isinstance(key_id, str) or not key_id or len(key_id) > 255:
            raise AccessTokenError("access token key identifier is invalid")

        signing_key = await self._signing_keys.get_signing_key(token)
        try:
            decoded = jwt.decode(
                token,
                signing_key,
                algorithms=list(self._algorithms),
                audience=self._audience,
                issuer=self._issuer,
                leeway=self._clock_skew_seconds,
                options={"require": ["aud", "client_id", "exp", "iat", "iss", "jti", "sub"]},
            )
        except InvalidTokenError as exc:
            raise AccessTokenError("access token claims are invalid") from exc

        claims = decoded
        subject = claims.get("sub")
        client_id = claims.get("client_id")
        token_id = claims.get("jti")
        issued_at = claims.get("iat")
        expires_at = claims.get("exp")
        if not isinstance(subject, str) or not subject or len(subject) > 255:
            raise AccessTokenError("access token subject is invalid")
        if not isinstance(client_id, str) or not client_id or len(client_id) > 255:
            raise AccessTokenError("access token client identifier is invalid")
        if not isinstance(token_id, str) or not token_id or len(token_id) > 255:
            raise AccessTokenError("access token identifier is invalid")
        if (
            not isinstance(issued_at, int)
            or isinstance(issued_at, bool)
            or not isinstance(expires_at, int)
            or isinstance(expires_at, bool)
        ):
            raise AccessTokenError("access token timestamps are invalid")

        now = int(datetime.now(UTC).timestamp())
        maximum_age = self._max_token_age_seconds + self._clock_skew_seconds
        if now - issued_at > maximum_age or expires_at - issued_at > maximum_age:
            raise AccessTokenError("access token lifetime exceeds policy")

        return VerifiedAccessToken(
            issuer=self._issuer,
            subject=subject,
            scopes=_extract_scopes(claims),
        )


def _extract_scopes(claims: dict[str, Any]) -> frozenset[str]:
    scope_value = claims.get("scope")
    scp_value = claims.get("scp")
    oauth_scopes = _parse_scope_value(scope_value, "scope") if scope_value is not None else None
    provider_scopes = _parse_scope_value(scp_value, "scp") if scp_value is not None else None
    if oauth_scopes is not None and provider_scopes is not None and oauth_scopes != provider_scopes:
        raise AccessTokenError("access token scope claims conflict")
    return oauth_scopes or provider_scopes or frozenset()


def _parse_scope_value(value: object, claim_name: str) -> frozenset[str]:
    if isinstance(value, str):
        raw_scopes = value.split()
    elif (
        claim_name == "scp"
        and isinstance(value, list)
        and all(isinstance(item, str) for item in value)
    ):
        raw_scopes = value
    else:
        raise AccessTokenError(f"access token {claim_name} claim is invalid")
    if len(raw_scopes) > 100 or any(
        not scope or len(scope) > 100 or any(character.isspace() for character in scope)
        for scope in raw_scopes
    ):
        raise AccessTokenError(f"access token {claim_name} claim is invalid")
    return frozenset(raw_scopes)
