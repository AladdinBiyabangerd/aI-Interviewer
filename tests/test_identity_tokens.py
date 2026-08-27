from datetime import UTC, datetime
from typing import Any, cast

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from jwt import PyJWK
from jwt.algorithms import RSAAlgorithm

from ai_interviewer.core.config import Settings
from ai_interviewer.identity.tokens import (
    AccessTokenError,
    CachedJWKSigningKeyProvider,
    JWTAccessTokenVerifier,
)

ISSUER = "https://identity.example.com/"
AUDIENCE = "https://api.example.com"


class StaticSigningKeys:
    def __init__(self, key: PyJWK) -> None:
        self.key = key

    async def get_signing_key(self, token: str) -> PyJWK:
        del token
        return self.key


@pytest.fixture(scope="module")
def signing_material() -> tuple[rsa.RSAPrivateKey, PyJWK]:
    private_key = rsa.generate_private_key(public_exponent=65_537, key_size=2_048)
    jwk_data = cast(
        dict[str, Any],
        RSAAlgorithm.to_jwk(private_key.public_key(), as_dict=True),
    )
    jwk_data.update({"alg": "RS256", "kid": "test-key", "use": "sig"})
    return private_key, PyJWK.from_dict(jwk_data, algorithm="RS256")


@pytest.fixture
def auth_settings() -> Settings:
    return Settings(
        _env_file=None,
        environment="test",
        auth_enabled=True,
        auth_oidc_issuer=ISSUER,
        auth_oidc_audience=AUDIENCE,
        auth_oidc_jwks_url="https://identity.example.com/.well-known/jwks.json",
        auth_max_token_age_seconds=3_600,
    )


def make_token(
    private_key: rsa.RSAPrivateKey,
    *,
    claim_overrides: dict[str, Any] | None = None,
    header_overrides: dict[str, Any] | None = None,
) -> str:
    now = int(datetime.now(UTC).timestamp())
    claims: dict[str, Any] = {
        "iss": ISSUER,
        "sub": "external-subject-1",
        "aud": AUDIENCE,
        "client_id": "first-party-web",
        "iat": now,
        "exp": now + 300,
        "jti": "token-id-1",
        "scope": "profile:read interview:write",
    }
    headers: dict[str, Any] = {"alg": "RS256", "kid": "test-key", "typ": "at+jwt"}
    if claim_overrides:
        claims.update(claim_overrides)
    if header_overrides:
        headers.update(header_overrides)
    return jwt.encode(claims, private_key, algorithm="RS256", headers=headers)


@pytest.mark.asyncio
async def test_valid_access_token_is_minimized_to_identity_and_scopes(
    auth_settings: Settings,
    signing_material: tuple[rsa.RSAPrivateKey, PyJWK],
) -> None:
    private_key, public_jwk = signing_material
    verifier = JWTAccessTokenVerifier(auth_settings, StaticSigningKeys(public_jwk))

    verified = await verifier.verify(make_token(private_key))

    assert verified.issuer == ISSUER
    assert verified.subject == "external-subject-1"
    assert verified.scopes == frozenset({"profile:read", "interview:write"})


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "claim_overrides",
    [
        {"iss": "https://attacker.example/"},
        {"aud": "https://other-api.example.com"},
        {"exp": 1},
        {"sub": ""},
        {"client_id": ""},
        {"jti": ""},
        {"iat": "not-a-timestamp"},
        {"scope": "profile:read", "scp": ["admin"]},
        {"scope": {"profile:read": True}},
        {"scope": ["profile:read"]},
        {"scope": None, "scp": ["profile:read admin"]},
    ],
)
async def test_invalid_or_ambiguous_claims_are_rejected(
    auth_settings: Settings,
    signing_material: tuple[rsa.RSAPrivateKey, PyJWK],
    claim_overrides: dict[str, Any],
) -> None:
    private_key, public_jwk = signing_material
    verifier = JWTAccessTokenVerifier(auth_settings, StaticSigningKeys(public_jwk))

    with pytest.raises(AccessTokenError):
        await verifier.verify(make_token(private_key, claim_overrides=claim_overrides))


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "header_overrides",
    [
        {"typ": "JWT"},
        {"kid": ""},
        {"kid": "x" * 256},
    ],
)
async def test_untrusted_token_headers_are_rejected_before_key_use(
    auth_settings: Settings,
    signing_material: tuple[rsa.RSAPrivateKey, PyJWK],
    header_overrides: dict[str, Any],
) -> None:
    private_key, public_jwk = signing_material
    verifier = JWTAccessTokenVerifier(auth_settings, StaticSigningKeys(public_jwk))

    with pytest.raises(AccessTokenError):
        await verifier.verify(make_token(private_key, header_overrides=header_overrides))


@pytest.mark.asyncio
async def test_token_lifetime_is_bounded_even_with_a_future_expiry(
    auth_settings: Settings,
    signing_material: tuple[rsa.RSAPrivateKey, PyJWK],
) -> None:
    private_key, public_jwk = signing_material
    now = int(datetime.now(UTC).timestamp())
    verifier = JWTAccessTokenVerifier(auth_settings, StaticSigningKeys(public_jwk))
    token = make_token(
        private_key,
        claim_overrides={"iat": now - 3_700, "exp": now + 100},
    )

    with pytest.raises(AccessTokenError, match="lifetime"):
        await verifier.verify(token)


@pytest.mark.asyncio
async def test_token_signed_by_an_untrusted_key_is_rejected(
    auth_settings: Settings,
    signing_material: tuple[rsa.RSAPrivateKey, PyJWK],
) -> None:
    _, public_jwk = signing_material
    attacker_key = rsa.generate_private_key(public_exponent=65_537, key_size=2_048)
    verifier = JWTAccessTokenVerifier(auth_settings, StaticSigningKeys(public_jwk))

    with pytest.raises(AccessTokenError):
        await verifier.verify(make_token(attacker_key))


@pytest.mark.asyncio
async def test_token_length_is_bounded_before_parsing(auth_settings: Settings) -> None:
    verifier = JWTAccessTokenVerifier(auth_settings)

    with pytest.raises(AccessTokenError, match="length"):
        await verifier.verify("x" * (auth_settings.auth_max_token_length + 1))


@pytest.mark.asyncio
async def test_malformed_and_disallowed_algorithm_tokens_fail_before_network(
    auth_settings: Settings,
) -> None:
    verifier = JWTAccessTokenVerifier(auth_settings)
    with pytest.raises(AccessTokenError, match="header"):
        await verifier.verify("not-a-jwt")

    now = int(datetime.now(UTC).timestamp())
    symmetric_token = jwt.encode(
        {
            "iss": ISSUER,
            "sub": "subject",
            "aud": AUDIENCE,
            "client_id": "attacker-client",
            "iat": now,
            "exp": now + 60,
            "jti": "attacker-token-id",
        },
        "attacker-secret-with-at-least-32-bytes",
        algorithm="HS256",
        headers={"kid": "attacker", "typ": "at+jwt"},
    )
    with pytest.raises(AccessTokenError, match="algorithm"):
        await verifier.verify(symmetric_token)


def test_verifier_rejects_disabled_authentication() -> None:
    with pytest.raises(ValueError, match="requires authentication"):
        JWTAccessTokenVerifier(Settings(_env_file=None))


@pytest.mark.asyncio
async def test_boolean_timestamps_and_oversized_scopes_are_rejected(
    auth_settings: Settings,
    signing_material: tuple[rsa.RSAPrivateKey, PyJWK],
) -> None:
    private_key, public_jwk = signing_material
    verifier = JWTAccessTokenVerifier(auth_settings, StaticSigningKeys(public_jwk))

    with pytest.raises(AccessTokenError, match="timestamps"):
        await verifier.verify(make_token(private_key, claim_overrides={"iat": True}))
    with pytest.raises(AccessTokenError, match="scope"):
        await verifier.verify(make_token(private_key, claim_overrides={"scope": "x" * 101}))


@pytest.mark.asyncio
async def test_scp_list_is_supported_when_standard_scope_is_absent(
    auth_settings: Settings,
    signing_material: tuple[rsa.RSAPrivateKey, PyJWK],
) -> None:
    private_key, public_jwk = signing_material
    verifier = JWTAccessTokenVerifier(auth_settings, StaticSigningKeys(public_jwk))
    now = int(datetime.now(UTC).timestamp())
    token = jwt.encode(
        {
            "iss": ISSUER,
            "sub": "external-subject-2",
            "aud": AUDIENCE,
            "client_id": "first-party-web",
            "iat": now,
            "exp": now + 300,
            "jti": "token-id-2",
            "scp": ["profile:read"],
        },
        private_key,
        algorithm="RS256",
        headers={"kid": "test-key", "typ": "at+jwt"},
    )

    verified = await verifier.verify(token)

    assert verified.scopes == frozenset({"profile:read"})


@pytest.mark.asyncio
async def test_cached_jwk_provider_wraps_key_lookup_failures(
    auth_settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    provider = CachedJWKSigningKeyProvider(auth_settings)

    def fail(_: str) -> PyJWK:
        raise jwt.PyJWKClientError("sensitive network detail")

    monkeypatch.setattr(provider._client, "get_signing_key_from_jwt", fail)

    with pytest.raises(AccessTokenError, match="unavailable"):
        await provider.get_signing_key("token")
