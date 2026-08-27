from uuid import uuid4

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from ai_interviewer.core.config import Settings
from ai_interviewer.identity.authorization import enforce_owner, require_scopes
from ai_interviewer.identity.service import (
    AccountAccessDeniedError,
    AuthenticationService,
    AuthenticationUnavailableError,
    Principal,
    build_authentication,
)
from ai_interviewer.identity.tokens import AccessTokenError
from ai_interviewer.main import create_app
from tests.fakes import ReadyDatabase


class ControlledAuthentication:
    def __init__(self, result: Principal | Exception) -> None:
        self.result = result

    async def authenticate(self, access_token: str, request_id: str | None) -> Principal:
        del access_token, request_id
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


def identity_client(result: Principal | Exception) -> TestClient:
    settings = Settings(_env_file=None, environment="test", allowed_hosts=("testserver",))
    return TestClient(
        create_app(
            settings,
            database=ReadyDatabase(),
            authentication=ControlledAuthentication(result),
        )
    )


def test_identity_endpoint_requires_bearer_credentials() -> None:
    principal = Principal(account_id=uuid4(), scopes=frozenset({"profile:read"}))
    with identity_client(principal) as client:
        response = client.get("/api/v1/identity/me")

    assert response.status_code == 401
    assert response.headers["www-authenticate"] == "Bearer"


def test_invalid_token_is_opaque_and_not_echoed() -> None:
    with identity_client(AccessTokenError("sensitive verifier detail")) as client:
        response = client.get(
            "/api/v1/identity/me",
            headers={"authorization": "Bearer secret-token-value"},
        )

    assert response.status_code == 401
    assert response.headers["www-authenticate"] == 'Bearer error="invalid_token"'
    assert "secret-token-value" not in response.text
    assert "sensitive verifier detail" not in response.text


def test_scope_is_enforced_after_authentication() -> None:
    principal = Principal(account_id=uuid4(), scopes=frozenset({"interview:write"}))
    with identity_client(principal) as client:
        response = client.get(
            "/api/v1/identity/me",
            headers={"authorization": "Bearer valid-token"},
        )

    assert response.status_code == 403
    assert response.headers["www-authenticate"] == (
        'Bearer error="insufficient_scope", scope="profile:read"'
    )


def test_current_account_returns_only_the_local_opaque_identifier() -> None:
    account_id = uuid4()
    principal = Principal(account_id=account_id, scopes=frozenset({"profile:read"}))
    with identity_client(principal) as client:
        response = client.get(
            "/api/v1/identity/me",
            headers={"authorization": "Bearer valid-token"},
        )

    assert response.status_code == 200
    assert response.json() == {"account_id": str(account_id)}


@pytest.mark.parametrize(
    ("error", "expected_status"),
    [
        (AuthenticationUnavailableError(), 503),
        (AccountAccessDeniedError(), 403),
    ],
)
def test_authentication_availability_and_account_status_fail_closed(
    error: Exception,
    expected_status: int,
) -> None:
    with identity_client(error) as client:
        response = client.get(
            "/api/v1/identity/me",
            headers={"authorization": "Bearer valid-token"},
        )

    assert response.status_code == expected_status


def test_unconfigured_authentication_never_bypasses_protection() -> None:
    settings = Settings(_env_file=None, environment="test", allowed_hosts=("testserver",))
    with TestClient(create_app(settings, database=ReadyDatabase())) as client:
        response = client.get(
            "/api/v1/identity/me",
            headers={"authorization": "Bearer any-token"},
        )

    assert response.status_code == 503


def test_owner_policy_hides_cross_user_resources() -> None:
    principal = Principal(account_id=uuid4(), scopes=frozenset())

    enforce_owner(principal, principal.account_id)
    with pytest.raises(HTTPException) as raised:
        enforce_owner(principal, uuid4())

    assert raised.value.status_code == 404


def test_scope_dependency_rejects_empty_policy() -> None:
    with pytest.raises(ValueError, match="at least one"):
        require_scopes()


def test_enabled_authentication_builds_the_real_service() -> None:
    settings = Settings(
        _env_file=None,
        environment="test",
        auth_enabled=True,
        auth_oidc_issuer="https://identity.example.com/",
        auth_oidc_audience="https://api.example.com",
        auth_oidc_jwks_url="https://identity.example.com/.well-known/jwks.json",
    )

    authentication = build_authentication(settings, ReadyDatabase())

    assert isinstance(authentication, AuthenticationService)
