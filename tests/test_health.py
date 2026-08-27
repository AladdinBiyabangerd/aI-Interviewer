from fastapi.testclient import TestClient

from ai_interviewer.core.config import Settings
from ai_interviewer.file_security.lifecycle import DisabledFileSecurity
from ai_interviewer.main import create_app
from tests.fakes import ReadyDatabase


def test_liveness_contract(client: TestClient) -> None:
    response = client.get("/api/v1/health/live")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_readiness_contract(client: TestClient) -> None:
    response = client.get("/api/v1/health/ready")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ready",
        "checks": {"runtime": "up", "database": "up", "file_security": "up"},
    }


def test_readiness_reports_database_failure() -> None:
    settings = Settings(_env_file=None, environment="test", allowed_hosts=("testserver",))
    with TestClient(create_app(settings, database=ReadyDatabase(ready=False))) as test_client:
        response = test_client.get("/api/v1/health/ready")

    assert response.status_code == 503
    assert response.json() == {
        "status": "not_ready",
        "checks": {"runtime": "up", "database": "down", "file_security": "up"},
    }


class UnavailableFileSecurity(DisabledFileSecurity):
    async def is_ready(self) -> bool:
        return False


class FailingFileSecurity(DisabledFileSecurity):
    async def is_ready(self) -> bool:
        raise RuntimeError("sensitive dependency detail")


def test_readiness_reports_file_security_failure() -> None:
    settings = Settings(_env_file=None, environment="test", allowed_hosts=("testserver",))
    with TestClient(
        create_app(
            settings,
            database=ReadyDatabase(),
            file_security=UnavailableFileSecurity(),
        )
    ) as test_client:
        response = test_client.get("/api/v1/health/ready")

    assert response.status_code == 503
    assert response.json() == {
        "status": "not_ready",
        "checks": {"runtime": "up", "database": "up", "file_security": "down"},
    }


def test_readiness_contains_unexpected_dependency_errors() -> None:
    settings = Settings(_env_file=None, environment="test", allowed_hosts=("testserver",))
    with TestClient(
        create_app(
            settings,
            database=ReadyDatabase(),
            file_security=FailingFileSecurity(),
        )
    ) as test_client:
        response = test_client.get("/api/v1/health/ready")

    assert response.status_code == 503
    assert response.json()["checks"]["file_security"] == "down"
    assert "sensitive dependency detail" not in response.text


def test_docs_are_disabled_by_default(client: TestClient) -> None:
    assert client.get("/docs").status_code == 404
    assert client.get("/openapi.json").status_code == 404
