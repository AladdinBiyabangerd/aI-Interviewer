import base64
import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from ai_interviewer.core.config import Settings


def _write_secret(path: Path, value: str) -> Path:
    path.write_text(value, encoding="utf-8")
    path.chmod(0o600)
    return path


def _keyring_json() -> str:
    def material(byte: bytes) -> str:
        return base64.b64encode(byte * 32).decode()

    return json.dumps(
        {
            "version": 1,
            "active": {
                "subject_hmac": "subject-v1",
                "field_encryption": "field-v1",
                "manifest_hmac": "manifest-v1",
            },
            "keys": [
                {"id": "subject-v1", "purpose": "subject_hmac", "material": material(b"s")},
                {
                    "id": "field-v1",
                    "purpose": "field_encryption",
                    "material": material(b"f"),
                },
                {
                    "id": "manifest-v1",
                    "purpose": "manifest_hmac",
                    "material": material(b"m"),
                },
            ],
        }
    )


def _production_values(tmp_path: Path) -> dict[str, object]:
    database_file = _write_secret(
        tmp_path / "database-url",
        "postgresql+psycopg://app:strong@db.example.com/app",
    )
    keyring_file = _write_secret(tmp_path / "privacy-keyring", _keyring_json())
    return {
        "_env_file": None,
        "environment": "production",
        "release_id": "2026.08.24-phase0d-a",
        "release_revision": "a" * 40,
        "telemetry_enabled": True,
        "telemetry_otlp_endpoint": "https://telemetry.example.com",
        "allowed_hosts": ("api.example.com",),
        "database_url": None,
        "database_url_file": database_file,
        "database_tls_mode": "verify-full",
        "auth_enabled": True,
        "auth_oidc_issuer": "https://identity.example.com/",
        "auth_oidc_audience": "https://api.example.com",
        "auth_oidc_jwks_url": "https://identity.example.com/.well-known/jwks.json",
        "privacy_enabled": True,
        "privacy_keyring_file": keyring_file,
        "file_security_enabled": True,
        "object_storage_bucket": "private-interview-files",
        "object_storage_region": "eu-central-1",
        "object_storage_kms_key_id": "alias/interview-files",
        "malware_scanner_unix_socket": tmp_path / "clamd.sock",
    }


def test_allowed_hosts_are_normalized() -> None:
    settings = Settings(_env_file=None, allowed_hosts=(" EXAMPLE.COM ", "localhost"))

    assert settings.allowed_hosts == ("example.com", "localhost")


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("release_id", "contains spaces", "bounded immutable release label"),
        ("release_id", "x" * 129, "bounded immutable release label"),
        ("release_revision", "abc123", "full 40-character lowercase Git SHA"),
    ],
)
def test_release_identity_is_strictly_validated(field: str, value: str, message: str) -> None:
    with pytest.raises(ValidationError, match=message):
        Settings(_env_file=None, **{field: value})


def test_release_revision_is_normalized() -> None:
    settings = Settings(_env_file=None, release_revision="A" * 40)

    assert settings.release_revision == "a" * 40


@pytest.mark.parametrize(
    "endpoint",
    [
        "ftp://telemetry.example.com",
        "https://user:secret@telemetry.example.com",
        "https://telemetry.example.com/v1/traces",
        "https://telemetry.example.com?token=secret",
    ],
)
def test_telemetry_endpoint_is_a_credential_free_origin(endpoint: str) -> None:
    with pytest.raises(ValidationError, match=r"credential-free HTTP\(S\) origin"):
        Settings(_env_file=None, telemetry_enabled=True, telemetry_otlp_endpoint=endpoint)


def test_telemetry_coordinates_and_batch_bounds_fail_closed() -> None:
    with pytest.raises(ValidationError, match="requires an OTLP endpoint"):
        Settings(_env_file=None, telemetry_enabled=True)

    with pytest.raises(ValidationError, match="requires telemetry to be enabled"):
        Settings(_env_file=None, telemetry_otlp_endpoint="http://127.0.0.1:4318")

    with pytest.raises(ValidationError, match="batch size must not exceed queue size"):
        Settings(
            _env_file=None,
            telemetry_enabled=True,
            telemetry_otlp_endpoint="http://127.0.0.1:4318",
            telemetry_span_queue_size=128,
            telemetry_span_batch_size=129,
        )


def test_production_rejects_wildcard_hosts() -> None:
    with pytest.raises(ValidationError, match="wildcard hosts"):
        Settings(
            _env_file=None,
            environment="production",
            allowed_hosts=("*",),
            database_url="postgresql+psycopg://app:strong@db.example.com/app",
            database_tls_mode="verify-full",
        )


def test_production_rejects_interactive_docs() -> None:
    with pytest.raises(ValidationError, match="interactive API documentation"):
        Settings(
            _env_file=None,
            environment="production",
            allowed_hosts=("api.example.com",),
            docs_enabled=True,
            database_url="postgresql+psycopg://app:strong@db.example.com/app",
            database_tls_mode="verify-full",
        )


def test_production_rejects_debug_logging() -> None:
    with pytest.raises(ValidationError, match="debug logging"):
        Settings(
            _env_file=None,
            environment="production",
            allowed_hosts=("api.example.com",),
            log_level="DEBUG",
            database_url="postgresql+psycopg://app:strong@db.example.com/app",
            database_tls_mode="verify-full",
        )


def test_production_rejects_database_without_tls() -> None:
    with pytest.raises(ValidationError, match="database TLS"):
        Settings(
            _env_file=None,
            environment="production",
            allowed_hosts=("api.example.com",),
            database_url="postgresql+psycopg://app:strong@db.example.com/app",
            database_tls_mode="disable",
        )


def test_production_rejects_local_database_credentials(tmp_path: Path) -> None:
    values = _production_values(tmp_path)
    values["database_url_file"] = _write_secret(
        tmp_path / "local-database-url",
        "postgresql+psycopg://app:local-only@db.example.com/app",
    )
    with pytest.raises(ValidationError, match="local database credentials"):
        Settings(**values)


def test_production_accepts_secret_files_and_safe_file_security(tmp_path: Path) -> None:
    settings = Settings(**_production_values(tmp_path))

    assert settings.environment == "production"
    assert settings.database_url.get_secret_value().endswith("@db.example.com/app")
    assert settings.privacy_keyring is not None


def test_staging_uses_the_same_hosted_safety_contract(tmp_path: Path) -> None:
    unsafe = _production_values(tmp_path)
    unsafe["environment"] = "staging"
    unsafe["docs_enabled"] = True
    with pytest.raises(ValidationError, match="interactive API documentation"):
        Settings(**unsafe)

    safe = _production_values(tmp_path)
    safe["environment"] = "staging"
    settings = Settings(**safe)

    assert settings.environment == "staging"


def test_hosted_telemetry_requires_encrypted_or_loopback_export(tmp_path: Path) -> None:
    remote_http = _production_values(tmp_path)
    remote_http["telemetry_otlp_endpoint"] = "http://telemetry.example.com"
    with pytest.raises(ValidationError, match="HTTPS or a loopback collector"):
        Settings(**remote_http)

    no_sampling = _production_values(tmp_path)
    no_sampling["telemetry_trace_sample_ratio"] = 0
    with pytest.raises(ValidationError, match="sampling must be greater than zero"):
        Settings(**no_sampling)


@pytest.mark.parametrize(
    ("field", "value"),
    [("release_id", "development"), ("release_revision", "unknown")],
)
def test_hosted_environment_requires_release_identity(
    tmp_path: Path, field: str, value: str
) -> None:
    values = _production_values(tmp_path)
    values[field] = value

    with pytest.raises(ValidationError, match="immutable release_id and release_revision"):
        Settings(**values)


def test_production_requires_authentication(tmp_path: Path) -> None:
    values = _production_values(tmp_path)
    values["auth_enabled"] = False
    values["auth_oidc_issuer"] = None
    values["auth_oidc_audience"] = None
    values["auth_oidc_jwks_url"] = None
    with pytest.raises(ValidationError, match="authentication is required"):
        Settings(**values)


def test_production_requires_privacy_lifecycle(tmp_path: Path) -> None:
    values = _production_values(tmp_path)
    values["privacy_enabled"] = False
    values["privacy_keyring_file"] = None
    with pytest.raises(ValidationError, match="privacy lifecycle is required"):
        Settings(**values)


def test_enabled_privacy_requires_non_placeholder_hmac_key() -> None:
    with pytest.raises(ValidationError, match="requires a subject HMAC key"):
        Settings(_env_file=None, privacy_enabled=True)

    with pytest.raises(ValidationError, match="at least 32 bytes"):
        Settings(_env_file=None, privacy_enabled=True, privacy_subject_hmac_key="too-short")

    with pytest.raises(ValidationError, match="require privacy lifecycle"):
        Settings(
            _env_file=None,
            privacy_enabled=False,
            privacy_subject_hmac_key="a-secure-privacy-key-with-at-least-32-bytes",
        )


def test_enabled_authentication_requires_complete_coordinates() -> None:
    with pytest.raises(ValidationError, match="requires issuer, audience, and JWKS"):
        Settings(
            _env_file=None,
            auth_enabled=True,
            auth_oidc_issuer="https://identity.example.com/",
        )


def test_disabled_authentication_rejects_partial_coordinates() -> None:
    with pytest.raises(ValidationError, match="require authentication to be enabled"):
        Settings(
            _env_file=None,
            auth_oidc_audience="https://api.example.com",
        )


@pytest.mark.parametrize(
    "field_value",
    [
        "https://user:password@identity.example.com/",
        "https://identity.example.com/keys?tenant=unsafe",
        "file:///tmp/keys.json",
    ],
)
def test_oidc_urls_reject_credentials_queries_and_non_http_schemes(field_value: str) -> None:
    with pytest.raises(ValidationError, match="OIDC URLs"):
        Settings(_env_file=None, auth_oidc_issuer=field_value)


def test_production_oidc_urls_require_https(tmp_path: Path) -> None:
    issuer_values = _production_values(tmp_path)
    issuer_values["auth_oidc_issuer"] = "http://identity.example.com/"
    with pytest.raises(ValidationError, match="issuer must use HTTPS"):
        Settings(**issuer_values)

    jwks_values = _production_values(tmp_path)
    jwks_values["auth_oidc_jwks_url"] = "http://identity.example.com/.well-known/jwks.json"
    with pytest.raises(ValidationError, match="JWKS URL must use HTTPS"):
        Settings(**jwks_values)


@pytest.mark.parametrize("audience", [" ", "has whitespace", "x" * 256])
def test_oidc_audience_is_bounded_and_has_no_whitespace(audience: str) -> None:
    with pytest.raises(ValidationError, match="OIDC audience"):
        Settings(_env_file=None, auth_oidc_audience=audience)


def test_oidc_algorithms_must_be_unique() -> None:
    with pytest.raises(ValidationError, match="unique and include RS256"):
        Settings(_env_file=None, auth_oidc_algorithms=("RS256", "RS256"))

    with pytest.raises(ValidationError, match="include RS256"):
        Settings(_env_file=None, auth_oidc_algorithms=("ES256",))


@pytest.mark.parametrize("allowed_hosts", [(), (" ",), ("example.com", "EXAMPLE.COM")])
def test_allowed_hosts_must_be_nonempty_and_unique(allowed_hosts: tuple[str, ...]) -> None:
    with pytest.raises(ValidationError):
        Settings(_env_file=None, allowed_hosts=allowed_hosts)


@pytest.mark.parametrize(
    "database_url",
    [
        "sqlite+aiosqlite:///test.db",
        "postgresql+asyncpg://app:password@localhost/app",
        "postgresql+psycopg://app:password@localhost",
        "not-a-url",
    ],
)
def test_database_url_requires_psycopg_and_database_name(database_url: str) -> None:
    with pytest.raises(ValidationError, match="database URL"):
        Settings(_env_file=None, database_url=database_url)


def test_secret_file_coordinates_are_exclusive_and_validated(tmp_path: Path) -> None:
    missing = tmp_path / "missing-secret"
    with pytest.raises(ValidationError, match="secret file is unavailable"):
        Settings(_env_file=None, database_url=None, database_url_file=missing)

    database_file = _write_secret(
        tmp_path / "database-url",
        "postgresql+psycopg://app:strong@db.example.com/app",
    )
    with pytest.raises(ValidationError, match="mutually exclusive"):
        Settings(
            _env_file=None,
            database_url="postgresql+psycopg://app:other@db.example.com/app",
            database_url_file=database_file,
        )


@pytest.mark.parametrize(
    "bucket",
    ["ab", "-invalid", "invalid-", "has_upper!", "two..dots", "x" * 64],
)
def test_object_storage_bucket_validation(bucket: str) -> None:
    with pytest.raises(ValidationError, match="DNS-compatible"):
        Settings(_env_file=None, object_storage_bucket=bucket)


@pytest.mark.parametrize("value", [" ", "has whitespace", "x" * 256])
def test_object_storage_region_and_key_are_bounded(value: str) -> None:
    with pytest.raises(ValidationError, match="object storage values"):
        Settings(_env_file=None, object_storage_region=value)


@pytest.mark.parametrize(
    "endpoint",
    [
        "ftp://storage.example.com",
        "https://user:secret@storage.example.com",
        "https://storage.example.com/path?credential=bad",
    ],
)
def test_object_storage_endpoint_rejects_unsafe_urls(endpoint: str) -> None:
    with pytest.raises(ValidationError, match="credential-free"):
        Settings(_env_file=None, object_storage_endpoint_url=endpoint)


@pytest.mark.parametrize("host", [" ", "host name", "user@host", "host/path"])
def test_malware_scanner_host_validation(host: str) -> None:
    with pytest.raises(ValidationError, match="scanner host"):
        Settings(_env_file=None, malware_scanner_tcp_host=host)


def test_file_security_coordinates_fail_closed() -> None:
    with pytest.raises(ValidationError, match="requires privacy lifecycle"):
        Settings(_env_file=None, file_security_enabled=True)

    with pytest.raises(ValidationError, match="bucket, region, and KMS"):
        Settings(
            _env_file=None,
            privacy_enabled=True,
            privacy_keyring=_keyring_json(),
            file_security_enabled=True,
            malware_scanner_tcp_host="127.0.0.1",
        )

    with pytest.raises(ValidationError, match="exactly one malware scanner"):
        Settings(
            _env_file=None,
            privacy_enabled=True,
            privacy_keyring=_keyring_json(),
            file_security_enabled=True,
            object_storage_bucket="private-files",
            object_storage_region="eu-central-1",
            object_storage_kms_key_id="alias/files",
        )

    with pytest.raises(ValidationError, match="require file security"):
        Settings(_env_file=None, object_storage_bucket="private-files")


def test_production_rejects_raw_secrets_and_insecure_storage(tmp_path: Path) -> None:
    missing_keyring_file = _production_values(tmp_path)
    missing_keyring_file["privacy_keyring_file"] = None
    missing_keyring_file["privacy_keyring"] = _keyring_json()
    with pytest.raises(ValidationError, match="privacy_keyring_file"):
        Settings(**missing_keyring_file)

    raw_hmac = _production_values(tmp_path)
    raw_hmac["privacy_subject_hmac_key"] = "x" * 32
    with pytest.raises(ValidationError, match="raw privacy HMAC"):
        Settings(**raw_hmac)

    insecure_endpoint = _production_values(tmp_path)
    insecure_endpoint["object_storage_endpoint_url"] = "http://storage.example.com"
    with pytest.raises(ValidationError, match="must use HTTPS"):
        Settings(**insecure_endpoint)

    tcp_scanner = _production_values(tmp_path)
    tcp_scanner["malware_scanner_unix_socket"] = None
    tcp_scanner["malware_scanner_tcp_host"] = "127.0.0.1"
    with pytest.raises(ValidationError, match="local Unix socket"):
        Settings(**tcp_scanner)
