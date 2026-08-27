"""Forward-only, serialized database migration release command."""

from __future__ import annotations

import argparse
import json
import sys
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Self

from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory
from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Connection, make_url
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.pool import NullPool

from ai_interviewer.core.config import (
    DatabaseTLSMode,
    Environment,
    normalize_release_id,
    normalize_release_revision,
)
from ai_interviewer.core.secrets import SecretFileError, read_secret_file
from ai_interviewer.persistence.schema import (
    EXPECTED_SCHEMA_REVISION,
    SCHEMA_MIGRATION_LOCK_ID,
)


class MigrationReleaseError(RuntimeError):
    """The release migration could not be applied or verified safely."""


class MigrationSettings(BaseSettings):
    """Least-privilege settings for the one-off migration process."""

    model_config = SettingsConfigDict(
        env_prefix="AI_INTERVIEWER_",
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
        frozen=True,
    )

    environment: Environment = "development"
    release_id: str = "development"
    release_revision: str = "unknown"
    database_url: SecretStr = SecretStr(
        "postgresql+psycopg://ai_interviewer:local-only@127.0.0.1:55432/ai_interviewer"
    )
    database_url_file: Path | None = None
    database_tls_mode: DatabaseTLSMode = "disable"
    database_connect_timeout_seconds: int = Field(default=5, ge=1, le=30)
    database_statement_timeout_ms: int = Field(default=300_000, ge=1_000, le=900_000)
    migration_lock_timeout_seconds: float = Field(default=60.0, gt=0, le=900)
    migration_lock_poll_seconds: float = Field(default=0.25, gt=0, le=5)

    @model_validator(mode="before")
    @classmethod
    def resolve_database_secret(cls, raw: Any) -> Any:
        if not isinstance(raw, dict):
            return raw
        values = dict(raw)
        file_value = values.get("database_url_file")
        if file_value is None:
            return values
        if values.get("database_url") is not None:
            raise ValueError("database_url and database_url_file are mutually exclusive")
        hosted = str(values.get("environment", "development")).lower() in {
            "staging",
            "production",
        }
        try:
            values["database_url"] = read_secret_file(file_value, hosted=hosted)
        except SecretFileError as exc:
            raise ValueError(f"database_url_file is invalid: {exc}") from exc
        return values

    @field_validator("release_id")
    @classmethod
    def validate_release_id(cls, value: str) -> str:
        return normalize_release_id(value)

    @field_validator("release_revision")
    @classmethod
    def validate_release_revision(cls, value: str) -> str:
        return normalize_release_revision(value)

    @field_validator("database_url")
    @classmethod
    def validate_database_url(cls, value: SecretStr) -> SecretStr:
        try:
            url = make_url(value.get_secret_value())
        except Exception as exc:
            raise ValueError("database URL is invalid") from exc
        if url.drivername != "postgresql+psycopg" or not url.database:
            raise ValueError("database URL must use postgresql+psycopg and include a database")
        return value

    @model_validator(mode="after")
    def validate_hosted_release(self) -> Self:
        if self.environment not in {"staging", "production"}:
            return self
        if self.database_url_file is None:
            raise ValueError("hosted migrations require database_url_file")
        if self.database_tls_mode == "disable":
            raise ValueError("hosted migrations require database TLS")
        if self.release_id == "development" or self.release_revision == "unknown":
            raise ValueError("hosted migrations require immutable release identity")
        if make_url(self.database_url.get_secret_value()).password == "local-only":
            raise ValueError("local database credentials are forbidden in hosted environments")
        return self


@dataclass(frozen=True, slots=True)
class MigrationResult:
    release_id: str
    release_revision: str
    schema_revision: str


def _alembic_config(config_path: Path) -> Config:
    resolved = config_path.resolve(strict=True)
    config = Config(str(resolved))
    script = ScriptDirectory.from_config(config)
    heads = script.get_heads()
    if heads != [EXPECTED_SCHEMA_REVISION]:
        raise MigrationReleaseError("release artifact has an unexpected migration head")
    return config


def verify_migration_artifact(config_path: Path = Path("alembic.ini")) -> str:
    """Verify the image contains exactly the schema head expected by its application code."""
    _alembic_config(config_path)
    return EXPECTED_SCHEMA_REVISION


def _connect_args(settings: MigrationSettings) -> dict[str, object]:
    return {
        "sslmode": settings.database_tls_mode,
        "options": f"-c statement_timeout={settings.database_statement_timeout_ms}",
        "connect_timeout": settings.database_connect_timeout_seconds,
    }


def _acquire_lock(connection: Connection, settings: MigrationSettings) -> None:
    deadline = time.monotonic() + settings.migration_lock_timeout_seconds
    while True:
        acquired = connection.scalar(
            text("SELECT pg_try_advisory_lock(:lock_id)"),
            {"lock_id": SCHEMA_MIGRATION_LOCK_ID},
        )
        connection.commit()
        if acquired is True:
            return
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise MigrationReleaseError("database migration lock acquisition timed out")
        time.sleep(min(settings.migration_lock_poll_seconds, remaining))


def upgrade_schema(
    settings: MigrationSettings,
    *,
    config_path: Path = Path("alembic.ini"),
) -> MigrationResult:
    """Acquire the release lock, upgrade to the sole head, and verify the result."""
    config = _alembic_config(config_path)
    engine = create_engine(
        settings.database_url.get_secret_value(),
        poolclass=NullPool,
        connect_args=_connect_args(settings),
    )
    acquired = False
    try:
        with engine.connect() as connection:
            try:
                _acquire_lock(connection, settings)
                acquired = True
                config.attributes["connection"] = connection
                command.upgrade(config, "head")
                current_revision = connection.scalar(
                    text("SELECT version_num FROM alembic_version")
                )
                connection.commit()
                if current_revision != EXPECTED_SCHEMA_REVISION:
                    raise MigrationReleaseError(
                        "database schema does not match the release after migration"
                    )
                return MigrationResult(
                    release_id=settings.release_id,
                    release_revision=settings.release_revision,
                    schema_revision=EXPECTED_SCHEMA_REVISION,
                )
            finally:
                failure_in_progress = sys.exc_info()[0] is not None
                if connection.in_transaction():
                    connection.rollback()
                if acquired:
                    try:
                        released = connection.scalar(
                            text("SELECT pg_advisory_unlock(:lock_id)"),
                            {"lock_id": SCHEMA_MIGRATION_LOCK_ID},
                        )
                        connection.commit()
                    except SQLAlchemyError:
                        if not failure_in_progress:
                            raise MigrationReleaseError(
                                "database migration lock release failed"
                            ) from None
                    else:
                        if released is not True and not failure_in_progress:
                            raise MigrationReleaseError("database migration lock release failed")
    finally:
        engine.dispose()


def _event(name: str, **fields: object) -> str:
    return json.dumps({"event": name, **fields}, sort_keys=True, separators=(",", ":"))


def main() -> None:
    """Run the only release-supported schema operations."""
    parser = argparse.ArgumentParser(prog="ai-interviewer-migrate")
    parser.add_argument("command", choices=("check-artifact", "upgrade"))
    arguments = parser.parse_args()
    try:
        if arguments.command == "check-artifact":
            revision = verify_migration_artifact()
            print(_event("migration_artifact_verified", schema_revision=revision))
            return
        result = upgrade_schema(MigrationSettings())
        print(_event("database_migration_completed", **asdict(result)))
    except Exception as exc:
        print(
            _event("database_migration_failed", error_type=type(exc).__name__),
            file=sys.stderr,
        )
        raise SystemExit(1) from None


if __name__ == "__main__":
    main()
