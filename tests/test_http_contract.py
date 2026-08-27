import re
from typing import Annotated

from fastapi import FastAPI, Query
from fastapi.testclient import TestClient

from ai_interviewer.core.config import Settings
from ai_interviewer.main import create_app
from tests.fakes import ReadyDatabase


def test_request_id_is_preserved(client: TestClient) -> None:
    request_id = "018f47a2-4b9d-7d2e-8f31-5c6a7b8d9e01"
    response = client.get("/api/v1/health/live", headers={"x-request-id": request_id})

    assert response.headers["x-request-id"] == request_id


def test_invalid_request_id_is_replaced(client: TestClient) -> None:
    response = client.get("/api/v1/health/live", headers={"x-request-id": "not valid\n"})

    assert response.headers["x-request-id"] != "not valid\n"
    assert re.fullmatch(r"[0-9a-f-]{36}", response.headers["x-request-id"])


def test_security_headers_are_applied(client: TestClient) -> None:
    response = client.get("/api/v1/health/live")

    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["x-frame-options"] == "DENY"
    assert response.headers["referrer-policy"] == "no-referrer"
    assert response.headers["permissions-policy"] == "camera=(), microphone=(), geolocation=()"
    assert "strict-transport-security" not in response.headers


def test_hsts_is_applied_in_staging() -> None:
    settings = Settings(
        _env_file=None, environment="test", allowed_hosts=("testserver",)
    ).model_copy(update={"environment": "staging"})
    with TestClient(create_app(settings)) as staging_client:
        response = staging_client.get("/api/v1/health/live")

    assert response.headers["strict-transport-security"] == "max-age=31536000; includeSubDomains"


def test_untrusted_host_is_rejected_with_operational_headers(client: TestClient) -> None:
    response = client.get("/api/v1/health/live", headers={"host": "attacker.example"})

    assert response.status_code == 400
    assert "x-request-id" in response.headers
    assert response.headers["x-content-type-options"] == "nosniff"


def test_validation_response_does_not_echo_input(test_settings: Settings) -> None:
    app = create_app(test_settings, database=ReadyDatabase())

    async def validate(limit: Annotated[int, Query(gt=0)]) -> dict[str, int]:
        return {"limit": limit}

    app.add_api_route("/test/validate", validate)
    with TestClient(app) as test_client:
        response = test_client.get("/test/validate?limit=secret-value")

    body = response.json()
    assert response.status_code == 422
    assert response.headers["content-type"].startswith("application/problem+json")
    assert body["title"] == "Request validation failed"
    assert body["request_id"] == response.headers["x-request-id"]
    assert "secret-value" not in response.text
    assert body["errors"][0]["location"] == "query.limit"


def test_unhandled_error_is_opaque_and_correlated(test_settings: Settings) -> None:
    app: FastAPI = create_app(test_settings, database=ReadyDatabase())

    async def fail() -> None:
        raise RuntimeError("sensitive internal detail")

    app.add_api_route("/test/error", fail)
    with TestClient(app, raise_server_exceptions=False) as test_client:
        response = test_client.get("/test/error")

    body = response.json()
    assert response.status_code == 500
    assert response.headers["content-type"].startswith("application/problem+json")
    assert body["detail"] == "The request could not be completed."
    assert body["request_id"] == response.headers["x-request-id"]
    assert "sensitive internal detail" not in response.text
