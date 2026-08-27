import asyncio
from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from ai_interviewer.core.config import Settings
from ai_interviewer.main import create_app
from tests.fakes import ReadyDatabase


def pytest_asyncio_loop_factories() -> dict[str, object]:
    """Create selector loops, which work with psycopg on every supported OS."""
    return {"selector": asyncio.SelectorEventLoop}


@pytest.fixture
def test_settings() -> Settings:
    return Settings(
        _env_file=None,
        environment="test",
        allowed_hosts=("testserver",),
        docs_enabled=False,
    )


@pytest.fixture
def client(test_settings: Settings) -> Iterator[TestClient]:
    with TestClient(create_app(test_settings, database=ReadyDatabase())) as test_client:
        yield test_client
