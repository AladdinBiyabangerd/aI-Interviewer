import json
from collections.abc import Iterator
from pathlib import Path
from typing import cast

import pytest
from pydantic import ValidationError
from sqlalchemy.engine import Connection

from ai_interviewer.persistence import migrate
from ai_interviewer.persistence.migrate import (
    MigrationReleaseError,
    MigrationResult,
    MigrationSettings,
    verify_migration_artifact,
)
from ai_interviewer.persistence.schema import EXPECTED_SCHEMA_REVISION


def _write_database_secret(path: Path) -> Path:
    path.write_text(
        "postgresql+psycopg://migration:strong@db.example.com/application",
        encoding="utf-8",
    )
    path.chmod(0o600)
    return path


def test_migration_settings_are_narrow_and_validate_database_url() -> None:
    settings = MigrationSettings(_env_file=None)

    assert settings.environment == "development"
    assert settings.database_url.get_secret_value().startswith("postgresql+psycopg://")

    with pytest.raises(ValidationError, match=r"postgresql\+psycopg"):
        MigrationSettings(_env_file=None, database_url="sqlite:///unsafe.db")

    marketplace_url = MigrationSettings(
        _env_file=None,
        database_url="postgresql://migration:strong@db.example.com/application",
    )
    assert marketplace_url.database_url.get_secret_value().startswith("postgresql+psycopg://")


def test_hosted_migrations_require_file_secret_tls_and_release_identity(
    tmp_path: Path,
) -> None:
    secret_file = _write_database_secret(tmp_path / "database-url")
    base: dict[str, object] = {
        "_env_file": None,
        "environment": "production",
        "database_url": None,
        "database_url_file": secret_file,
        "database_tls_mode": "verify-full",
        "release_id": "2026.08.24-phase0d-a",
        "release_revision": "a" * 40,
    }

    settings = MigrationSettings(**base)
    assert settings.database_url_file == secret_file

    no_tls = dict(base)
    no_tls["database_tls_mode"] = "disable"
    with pytest.raises(ValidationError, match="require database TLS"):
        MigrationSettings(**no_tls)

    no_release = dict(base)
    no_release["release_revision"] = "unknown"
    with pytest.raises(ValidationError, match="immutable release identity"):
        MigrationSettings(**no_release)

    with pytest.raises(ValidationError, match="require database_url_file"):
        MigrationSettings(
            _env_file=None,
            environment="production",
            database_url="postgresql+psycopg://migration:strong@db.example.com/application",
            database_tls_mode="verify-full",
            release_id="2026.08.24-phase0d-a",
            release_revision="a" * 40,
        )

    environment_secret = MigrationSettings(
        _env_file=None,
        environment="production",
        database_url="postgresql+psycopg://migration:strong@db.example.com/application",
        hosted_environment_secrets=True,
        database_tls_mode="verify-full",
        release_id="2026.09.02-vercel-runtime",
        release_revision="d" * 40,
    )
    assert environment_secret.database_url_file is None


def test_release_artifact_contains_exactly_the_expected_head() -> None:
    assert verify_migration_artifact() == EXPECTED_SCHEMA_REVISION


def test_release_image_verifier_pins_the_application_schema_head() -> None:
    verifier = Path("scripts/verify-release-image.ps1").read_text(encoding="utf-8")

    assert f'$expectedSchemaRevision = "{EXPECTED_SCHEMA_REVISION}"' in verifier


def test_release_artifact_rejects_an_unexpected_head(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class UnexpectedScript:
        def get_heads(self) -> list[str]:
            return [EXPECTED_SCHEMA_REVISION, "unexpected"]

    monkeypatch.setattr(
        migrate.ScriptDirectory,
        "from_config",
        lambda _: UnexpectedScript(),
    )

    with pytest.raises(MigrationReleaseError, match="unexpected migration head"):
        verify_migration_artifact()


def test_migration_lock_has_a_bounded_wait(monkeypatch: pytest.MonkeyPatch) -> None:
    class UnavailableLockConnection:
        def scalar(self, *_: object, **__: object) -> bool:
            return False

        def commit(self) -> None:
            return None

    clock: Iterator[float] = iter((10.0, 11.0))
    monkeypatch.setattr(migrate.time, "monotonic", lambda: next(clock))
    settings = MigrationSettings(
        _env_file=None,
        migration_lock_timeout_seconds=0.5,
        migration_lock_poll_seconds=0.01,
    )

    with pytest.raises(MigrationReleaseError, match="lock acquisition timed out"):
        migrate._acquire_lock(cast(Connection, UnavailableLockConnection()), settings)


def test_migration_cli_emits_machine_readable_success(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    result = MigrationResult(
        release_id="release-1",
        release_revision="b" * 40,
        schema_revision=EXPECTED_SCHEMA_REVISION,
    )
    monkeypatch.setattr(migrate, "upgrade_schema", lambda _: result)
    monkeypatch.setattr(migrate.sys, "argv", ["ai-interviewer-migrate", "upgrade"])

    migrate.main()

    output = json.loads(capsys.readouterr().out)
    assert output == {
        "event": "database_migration_completed",
        "release_id": "release-1",
        "release_revision": "b" * 40,
        "schema_revision": EXPECTED_SCHEMA_REVISION,
    }


def test_migration_cli_never_emits_exception_details(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    def fail(_: MigrationSettings) -> MigrationResult:
        raise RuntimeError("postgresql://user:secret@database/private")

    monkeypatch.setattr(migrate, "upgrade_schema", fail)
    monkeypatch.setattr(migrate.sys, "argv", ["ai-interviewer-migrate", "upgrade"])

    with pytest.raises(SystemExit) as exit_info:
        migrate.main()

    captured = capsys.readouterr()
    assert exit_info.value.code == 1
    assert captured.out == ""
    assert json.loads(captured.err) == {
        "error_type": "RuntimeError",
        "event": "database_migration_failed",
    }
    assert "secret" not in captured.err


def test_migration_cli_checks_artifact_without_database_access(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(migrate.sys, "argv", ["ai-interviewer-migrate", "check-artifact"])

    migrate.main()

    assert json.loads(capsys.readouterr().out) == {
        "event": "migration_artifact_verified",
        "schema_revision": EXPECTED_SCHEMA_REVISION,
    }
