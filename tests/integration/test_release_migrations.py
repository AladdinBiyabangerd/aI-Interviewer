from pathlib import Path

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.pool import NullPool

from ai_interviewer.persistence.migrate import (
    MigrationReleaseError,
    MigrationSettings,
    upgrade_schema,
)
from ai_interviewer.persistence.schema import (
    EXPECTED_SCHEMA_REVISION,
    SCHEMA_MIGRATION_LOCK_ID,
)

pytestmark = pytest.mark.integration


def _settings(database_url: str, **overrides: object) -> MigrationSettings:
    return MigrationSettings(
        _env_file=None,
        environment="test",
        database_url=database_url,
        database_tls_mode="disable",
        release_id="integration-test",
        release_revision="c" * 40,
        **overrides,
    )


def test_release_runner_applies_and_verifies_the_expected_head(
    migrated_database: str,
) -> None:
    result = upgrade_schema(_settings(migrated_database), config_path=Path("alembic.ini"))

    assert result.release_id == "integration-test"
    assert result.release_revision == "c" * 40
    assert result.schema_revision == EXPECTED_SCHEMA_REVISION


def test_release_runner_serializes_competing_migrations(migrated_database: str) -> None:
    holder_engine = create_engine(migrated_database, poolclass=NullPool)
    try:
        with holder_engine.connect() as holder:
            acquired = holder.scalar(
                text("SELECT pg_try_advisory_lock(:lock_id)"),
                {"lock_id": SCHEMA_MIGRATION_LOCK_ID},
            )
            holder.commit()
            assert acquired is True
            try:
                with pytest.raises(MigrationReleaseError, match="lock acquisition timed out"):
                    upgrade_schema(
                        _settings(
                            migrated_database,
                            migration_lock_timeout_seconds=0.05,
                            migration_lock_poll_seconds=0.01,
                        )
                    )
            finally:
                released = holder.scalar(
                    text("SELECT pg_advisory_unlock(:lock_id)"),
                    {"lock_id": SCHEMA_MIGRATION_LOCK_ID},
                )
                holder.commit()
                assert released is True
    finally:
        holder_engine.dispose()
