import os
from collections.abc import AsyncIterator, Iterator

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, text

from ai_interviewer.core.config import Settings
from ai_interviewer.persistence.database import Database


def _test_database_url() -> str:
    value = os.getenv("AI_INTERVIEWER_TEST_DATABASE_URL")
    if not value:
        pytest.skip("AI_INTERVIEWER_TEST_DATABASE_URL is required for integration tests")
    return value


def _rebuild_public_schema(database_url: str) -> None:
    """Give every integration test a fresh schema without touching any other database."""
    engine = create_engine(database_url)
    try:
        with engine.begin() as connection:
            connection.execute(text("DROP SCHEMA public CASCADE"))
            connection.execute(text("CREATE SCHEMA public"))
    finally:
        engine.dispose()

    command.upgrade(Config("alembic.ini"), "head")


@pytest.fixture(scope="session", autouse=True)
def migrated_database() -> Iterator[str]:
    database_url = _test_database_url()
    previous_url = os.getenv("AI_INTERVIEWER_DATABASE_URL")
    os.environ["AI_INTERVIEWER_DATABASE_URL"] = database_url
    alembic_config = Config("alembic.ini")

    command.downgrade(alembic_config, "base")
    command.upgrade(alembic_config, "head")
    yield database_url
    command.upgrade(alembic_config, "head")

    if previous_url is None:
        os.environ.pop("AI_INTERVIEWER_DATABASE_URL", None)
    else:
        os.environ["AI_INTERVIEWER_DATABASE_URL"] = previous_url


@pytest.fixture(autouse=True)
def isolated_database_schema(migrated_database: str) -> None:
    """Prevent durable rows from one integration test affecting another test's assertions."""
    _rebuild_public_schema(migrated_database)


@pytest.fixture
async def database(migrated_database: str) -> AsyncIterator[Database]:
    settings = Settings(
        _env_file=None,
        environment="test",
        database_url=migrated_database,
        database_tls_mode="disable",
    )
    runtime = Database(settings)
    try:
        yield runtime
    finally:
        await runtime.close()
