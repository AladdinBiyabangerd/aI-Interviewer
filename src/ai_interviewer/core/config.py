"""Typed environment configuration with hosted-environment safety checks."""

import re
from functools import lru_cache
from pathlib import Path
from typing import Any, Literal, Self
from urllib.parse import urlsplit

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy.engine import make_url

from ai_interviewer.core.crypto import ApplicationKeyring, KeyringError
from ai_interviewer.core.secrets import SecretFileError, read_secret_file

Environment = Literal["development", "test", "staging", "production"]
LogLevel = Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]
DatabaseTLSMode = Literal["disable", "require", "verify-ca", "verify-full"]
OIDCAlgorithm = Literal["RS256", "ES256"]
_RELEASE_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_RELEASE_REVISION_PATTERN = re.compile(r"^[0-9a-f]{40}$")
_MODEL_COORDINATE_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,127}$")
_WORKER_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")


def normalize_release_id(value: str) -> str:
    """Validate a human-readable immutable deployment label."""
    normalized = value.strip()
    if not _RELEASE_ID_PATTERN.fullmatch(normalized):
        raise ValueError("release_id must be a bounded immutable release label")
    return normalized


def normalize_release_revision(value: str) -> str:
    """Validate the full source revision attached to a release artifact."""
    normalized = value.strip().lower()
    if normalized != "unknown" and not _RELEASE_REVISION_PATTERN.fullmatch(normalized):
        raise ValueError("release_revision must be a full 40-character lowercase Git SHA")
    return normalized


class Settings(BaseSettings):
    """Runtime settings loaded from `AI_INTERVIEWER_*` environment variables."""

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
    log_level: LogLevel = "INFO"
    docs_enabled: bool = False
    telemetry_enabled: bool = False
    telemetry_otlp_endpoint: str | None = None
    telemetry_trace_sample_ratio: float = Field(default=0.1, ge=0, le=1)
    telemetry_export_interval_seconds: int = Field(default=30, ge=5, le=300)
    telemetry_export_timeout_seconds: int = Field(default=5, ge=1, le=30)
    telemetry_span_schedule_delay_ms: int = Field(default=5_000, ge=100, le=60_000)
    telemetry_span_queue_size: int = Field(default=2_048, ge=128, le=16_384)
    telemetry_span_batch_size: int = Field(default=512, ge=1, le=2_048)
    telemetry_monitor_interval_seconds: int = Field(default=30, ge=5, le=300)
    allowed_hosts: tuple[str, ...] = ("localhost", "127.0.0.1", "testserver")
    database_url: SecretStr = SecretStr(
        "postgresql+psycopg://ai_interviewer:local-only@127.0.0.1:55432/ai_interviewer"
    )
    database_url_file: Path | None = None
    database_tls_mode: DatabaseTLSMode = "disable"
    database_pool_size: int = Field(default=5, ge=1, le=50)
    database_max_overflow: int = Field(default=5, ge=0, le=50)
    database_pool_timeout_seconds: float = Field(default=5.0, gt=0, le=60)
    database_pool_recycle_seconds: int = Field(default=1_800, ge=60, le=86_400)
    database_connect_timeout_seconds: int = Field(default=5, ge=1, le=30)
    database_healthcheck_timeout_seconds: float = Field(default=2.0, gt=0, le=10)
    database_statement_timeout_ms: int = Field(default=30_000, ge=1_000, le=300_000)
    auth_enabled: bool = False
    auth_oidc_issuer: str | None = None
    auth_oidc_audience: str | None = None
    auth_oidc_jwks_url: str | None = None
    auth_oidc_algorithms: tuple[OIDCAlgorithm, ...] = ("RS256",)
    auth_required_token_type: str = Field(default="at+jwt", min_length=1, max_length=32)
    auth_clock_skew_seconds: int = Field(default=30, ge=0, le=60)
    auth_max_token_age_seconds: int = Field(default=3_600, ge=300, le=86_400)
    auth_max_token_length: int = Field(default=8_192, ge=1_024, le=32_768)
    auth_jwks_timeout_seconds: float = Field(default=3.0, gt=0, le=10)
    auth_jwks_cache_seconds: int = Field(default=300, ge=60, le=3_600)
    privacy_enabled: bool = False
    privacy_subject_hmac_key: SecretStr | None = None
    privacy_keyring: SecretStr | None = None
    privacy_keyring_file: Path | None = None
    privacy_max_processor_deletion_attempts: int = Field(default=10, ge=1, le=100)
    privacy_processor_retry_base_seconds: int = Field(default=60, ge=1, le=86_400)
    file_security_enabled: bool = False
    object_storage_bucket: str | None = None
    object_storage_region: str | None = None
    object_storage_endpoint_url: str | None = None
    object_storage_kms_key_id: str | None = None
    object_storage_connect_timeout_seconds: float = Field(default=3.0, gt=0, le=30)
    object_storage_read_timeout_seconds: float = Field(default=10.0, gt=0, le=120)
    file_security_max_upload_bytes: int = Field(
        default=10 * 1024 * 1024,
        ge=1_024,
        le=25 * 1024 * 1024,
    )
    file_security_max_archive_entries: int = Field(default=2_000, ge=1, le=10_000)
    file_security_max_archive_uncompressed_bytes: int = Field(
        default=50 * 1024 * 1024,
        ge=1_024,
        le=250 * 1024 * 1024,
    )
    malware_scanner_unix_socket: Path | None = None
    malware_scanner_tcp_host: str | None = None
    malware_scanner_tcp_port: int = Field(default=3310, ge=1, le=65_535)
    malware_scanner_timeout_seconds: float = Field(default=15.0, gt=0, le=120)
    malware_scanner_max_signature_age_hours: int = Field(default=48, ge=1, le=168)
    model_gateway_enabled: bool = False
    model_gateway_provider: str | None = None
    model_gateway_model_id: str | None = None
    model_gateway_model_version: str | None = None
    openai_api_key: SecretStr | None = None
    openai_api_key_file: Path | None = None
    model_gateway_timeout_seconds: float = Field(default=30.0, gt=0, le=120)
    model_gateway_max_attempts: int = Field(default=3, ge=1, le=5)
    model_gateway_retry_base_seconds: float = Field(default=0.25, ge=0, le=5)
    model_gateway_max_input_characters: int = Field(
        default=250_000,
        ge=1_000,
        le=1_000_000,
    )
    model_gateway_max_output_characters: int = Field(
        default=100_000,
        ge=1_000,
        le=1_000_000,
    )
    profiling_worker_enabled: bool = False
    profiling_worker_id: str = "candidate-profiling-worker"

    @model_validator(mode="before")
    @classmethod
    def resolve_secret_files(cls, raw: Any) -> Any:
        if not isinstance(raw, dict):
            return raw
        values = dict(raw)
        hosted = str(values.get("environment", "development")).lower() in {
            "staging",
            "production",
        }
        secret_pairs = (
            ("database_url", "database_url_file"),
            ("privacy_keyring", "privacy_keyring_file"),
            ("openai_api_key", "openai_api_key_file"),
        )
        for value_field, file_field in secret_pairs:
            file_value = values.get(file_field)
            if file_value is None:
                continue
            if value_field in values and values[value_field] is not None:
                raise ValueError(f"{value_field} and {file_field} are mutually exclusive")
            try:
                values[value_field] = read_secret_file(file_value, hosted=hosted)
            except SecretFileError as exc:
                raise ValueError(f"{file_field} is invalid: {exc}") from exc
        return values

    @field_validator("allowed_hosts")
    @classmethod
    def validate_allowed_hosts(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        normalized = tuple(host.strip().lower() for host in value if host.strip())
        if not normalized:
            raise ValueError("at least one allowed host is required")
        if len(set(normalized)) != len(normalized):
            raise ValueError("allowed hosts must be unique")
        return normalized

    @field_validator("release_id")
    @classmethod
    def validate_release_id(cls, value: str) -> str:
        return normalize_release_id(value)

    @field_validator("release_revision")
    @classmethod
    def validate_release_revision(cls, value: str) -> str:
        return normalize_release_revision(value)

    @field_validator("telemetry_otlp_endpoint")
    @classmethod
    def validate_telemetry_endpoint(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip().rstrip("/")
        parsed = urlsplit(normalized)
        if (
            parsed.scheme not in {"http", "https"}
            or not parsed.hostname
            or parsed.username is not None
            or parsed.password is not None
            or parsed.query
            or parsed.fragment
            or parsed.path not in {"", "/"}
        ):
            raise ValueError(
                "telemetry endpoint must be an absolute credential-free HTTP(S) origin"
            )
        return normalized

    @field_validator("database_url")
    @classmethod
    def validate_database_url(cls, value: SecretStr) -> SecretStr:
        try:
            url = make_url(value.get_secret_value())
        except Exception as exc:
            raise ValueError("database URL is invalid") from exc
        if url.drivername != "postgresql+psycopg":
            raise ValueError("database URL must use the postgresql+psycopg driver")
        if not url.database:
            raise ValueError("database URL must include a database name")
        return value

    @field_validator("auth_oidc_issuer", "auth_oidc_jwks_url")
    @classmethod
    def validate_auth_url(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        parsed = urlsplit(normalized)
        if (
            parsed.scheme not in {"http", "https"}
            or not parsed.hostname
            or parsed.username is not None
            or parsed.password is not None
            or parsed.query
            or parsed.fragment
        ):
            raise ValueError("OIDC URLs must be absolute HTTP(S) URLs without credentials or query")
        return normalized

    @field_validator("auth_oidc_audience")
    @classmethod
    def validate_auth_audience(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        if (
            not normalized
            or len(normalized) > 255
            or any(character.isspace() for character in normalized)
        ):
            raise ValueError("OIDC audience must contain 1-255 non-whitespace characters")
        return normalized

    @field_validator("auth_oidc_algorithms")
    @classmethod
    def validate_auth_algorithms(
        cls, value: tuple[OIDCAlgorithm, ...]
    ) -> tuple[OIDCAlgorithm, ...]:
        if not value or len(set(value)) != len(value) or "RS256" not in value:
            raise ValueError("OIDC algorithms must be unique and include RS256")
        return value

    @field_validator("privacy_subject_hmac_key")
    @classmethod
    def validate_privacy_hmac_key(cls, value: SecretStr | None) -> SecretStr | None:
        if value is None:
            return None
        secret = value.get_secret_value()
        if len(secret.encode()) < 32:
            raise ValueError("privacy HMAC key must contain at least 32 bytes")
        if secret.lower() in {"change-me", "local-only", "password", "secret"}:
            raise ValueError("placeholder privacy HMAC keys are forbidden")
        return value

    @field_validator("privacy_keyring")
    @classmethod
    def validate_privacy_keyring(cls, value: SecretStr | None) -> SecretStr | None:
        if value is None:
            return None
        try:
            ApplicationKeyring.from_secret(value)
        except KeyringError as exc:
            raise ValueError(str(exc)) from exc
        return value

    @field_validator("object_storage_bucket")
    @classmethod
    def validate_object_storage_bucket(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip().lower()
        if (
            len(normalized) < 3
            or len(normalized) > 63
            or not normalized[0].isalnum()
            or not normalized[-1].isalnum()
            or any(
                character not in "abcdefghijklmnopqrstuvwxyz0123456789.-"
                for character in normalized
            )
            or ".." in normalized
        ):
            raise ValueError("object storage bucket must be a DNS-compatible name")
        return normalized

    @field_validator("object_storage_region", "object_storage_kms_key_id")
    @classmethod
    def validate_nonempty_storage_value(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        if (
            not normalized
            or len(normalized) > 255
            or any(character.isspace() for character in normalized)
        ):
            raise ValueError("object storage values must contain 1-255 non-whitespace characters")
        return normalized

    @field_validator("object_storage_endpoint_url")
    @classmethod
    def validate_object_storage_endpoint(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip().rstrip("/")
        parsed = urlsplit(normalized)
        if (
            parsed.scheme not in {"http", "https"}
            or not parsed.hostname
            or parsed.username is not None
            or parsed.password is not None
            or parsed.query
            or parsed.fragment
        ):
            raise ValueError(
                "object storage endpoint must be an absolute credential-free HTTP(S) URL"
            )
        return normalized

    @field_validator("malware_scanner_tcp_host")
    @classmethod
    def validate_scanner_host(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        if (
            not normalized
            or len(normalized) > 253
            or any(character.isspace() or character in "/:@" for character in normalized)
        ):
            raise ValueError("malware scanner host is invalid")
        return normalized

    @field_validator(
        "model_gateway_provider",
        "model_gateway_model_id",
        "model_gateway_model_version",
    )
    @classmethod
    def validate_model_gateway_coordinate(cls, value: str | None, info: Any) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        if not _MODEL_COORDINATE_PATTERN.fullmatch(normalized):
            raise ValueError("model gateway coordinates must be bounded release identifiers")
        if info.field_name == "model_gateway_provider":
            return normalized.lower()
        return normalized

    @field_validator("openai_api_key")
    @classmethod
    def validate_openai_api_key(cls, value: SecretStr | None) -> SecretStr | None:
        if value is None:
            return None
        secret = value.get_secret_value()
        if (
            not 20 <= len(secret.encode("utf-8")) <= 512
            or any(character.isspace() or ord(character) < 32 for character in secret)
            or secret.casefold() in {"change-me", "local-only", "password", "secret"}
        ):
            raise ValueError("OpenAI API key must be a bounded non-placeholder secret")
        return value

    @field_validator("profiling_worker_id")
    @classmethod
    def validate_profiling_worker_id(cls, value: str) -> str:
        normalized = value.strip()
        if not _WORKER_ID_PATTERN.fullmatch(normalized):
            raise ValueError("profiling worker ID must be a bounded operational identifier")
        return normalized

    @model_validator(mode="after")
    def validate_hosted_safety(self) -> Self:
        hosted = self.environment in {"staging", "production"}
        if hosted:
            environment_name = self.environment
            if "*" in self.allowed_hosts:
                raise ValueError("wildcard hosts are forbidden in hosted environments")
            if self.docs_enabled:
                raise ValueError(
                    "interactive API documentation is forbidden in hosted environments"
                )
            if self.log_level == "DEBUG":
                raise ValueError("debug logging is forbidden in hosted environments")
            if self.database_tls_mode == "disable":
                raise ValueError("database TLS is required in hosted environments")
            if self.database_url_file is None:
                raise ValueError("hosted database credentials require database_url_file")
            database_url = make_url(self.database_url.get_secret_value())
            if database_url.password == "local-only":
                raise ValueError("local database credentials are forbidden in hosted environments")
            if not self.auth_enabled:
                raise ValueError("OIDC authentication is required in hosted environments")
            if not self.privacy_enabled:
                raise ValueError("privacy lifecycle is required in hosted environments")
            if self.privacy_keyring_file is None:
                raise ValueError("hosted privacy cryptography requires privacy_keyring_file")
            if self.privacy_subject_hmac_key is not None:
                raise ValueError("raw privacy HMAC keys are forbidden in hosted environments")
            if not self.file_security_enabled:
                raise ValueError("file security is required in hosted environments")
            if self.release_id == "development" or self.release_revision == "unknown":
                raise ValueError(
                    f"{environment_name} requires immutable release_id and release_revision"
                )
            if not self.telemetry_enabled:
                raise ValueError("telemetry is required in hosted environments")

        auth_coordinates = (
            self.auth_oidc_issuer,
            self.auth_oidc_audience,
            self.auth_oidc_jwks_url,
        )
        if self.auth_enabled and not all(auth_coordinates):
            raise ValueError("enabled OIDC authentication requires issuer, audience, and JWKS URL")
        if not self.auth_enabled and any(auth_coordinates):
            raise ValueError("OIDC coordinates require authentication to be enabled")
        if hosted and self.auth_enabled:
            if urlsplit(self.auth_oidc_issuer or "").scheme != "https":
                raise ValueError("hosted OIDC issuer must use HTTPS")
            if urlsplit(self.auth_oidc_jwks_url or "").scheme != "https":
                raise ValueError("hosted OIDC JWKS URL must use HTTPS")
        if (
            self.privacy_enabled
            and self.privacy_subject_hmac_key is None
            and self.privacy_keyring is None
        ):
            raise ValueError(
                "enabled privacy lifecycle requires a subject HMAC key or privacy keyring"
            )
        if not self.privacy_enabled and (
            self.privacy_subject_hmac_key is not None or self.privacy_keyring is not None
        ):
            raise ValueError("privacy cryptographic keys require privacy lifecycle to be enabled")
        if self.privacy_subject_hmac_key is not None and self.privacy_keyring is not None:
            raise ValueError("legacy privacy HMAC key and privacy keyring are mutually exclusive")

        storage_coordinates = (
            self.object_storage_bucket,
            self.object_storage_region,
            self.object_storage_kms_key_id,
        )
        scanner_coordinates = (
            self.malware_scanner_unix_socket,
            self.malware_scanner_tcp_host,
        )
        if self.file_security_enabled:
            if not self.privacy_enabled or self.privacy_keyring is None:
                raise ValueError("file security requires privacy lifecycle and a privacy keyring")
            if not all(storage_coordinates):
                raise ValueError(
                    "file security requires object storage bucket, region, and KMS key"
                )
            if sum(value is not None for value in scanner_coordinates) != 1:
                raise ValueError("file security requires exactly one malware scanner transport")
        elif (
            any(storage_coordinates)
            or self.object_storage_endpoint_url is not None
            or any(scanner_coordinates)
        ):
            raise ValueError("object storage and malware scanner coordinates require file security")

        if hosted and self.file_security_enabled:
            if (
                self.object_storage_endpoint_url is not None
                and urlsplit(self.object_storage_endpoint_url).scheme != "https"
            ):
                raise ValueError("hosted object storage endpoint must use HTTPS")
            if self.malware_scanner_unix_socket is None:
                raise ValueError("hosted malware scanning requires a local Unix socket")
            if not self.malware_scanner_unix_socket.is_absolute():
                raise ValueError("hosted malware scanner socket path must be absolute")

        model_coordinates = (
            self.model_gateway_provider,
            self.model_gateway_model_id,
            self.model_gateway_model_version,
        )
        if self.model_gateway_enabled and not all(model_coordinates):
            raise ValueError("enabled model gateway requires provider, model ID, and model version")
        if not self.model_gateway_enabled and any(model_coordinates):
            raise ValueError("model gateway coordinates require the gateway to be enabled")
        openai_credentials_configured = (
            self.openai_api_key is not None or self.openai_api_key_file is not None
        )
        if self.model_gateway_enabled and self.model_gateway_provider == "openai":
            if self.openai_api_key is None:
                raise ValueError("enabled OpenAI model gateway requires an API key")
            if hosted and self.openai_api_key_file is None:
                raise ValueError("hosted OpenAI credentials require openai_api_key_file")
        elif openai_credentials_configured:
            raise ValueError("OpenAI credentials require the enabled OpenAI model gateway")
        if self.profiling_worker_enabled:
            if (
                not self.model_gateway_enabled
                or not self.privacy_enabled
                or not self.file_security_enabled
            ):
                raise ValueError(
                    "profiling worker requires model gateway, privacy, and file security"
                )
            retry_delay = self.model_gateway_retry_base_seconds * sum(
                2**attempt for attempt in range(self.model_gateway_max_attempts - 1)
            )
            maximum_gateway_seconds = (
                self.model_gateway_timeout_seconds * self.model_gateway_max_attempts + retry_delay
            )
            if maximum_gateway_seconds > 240:
                raise ValueError(
                    "profiling worker model retry budget must fit within the fenced lease"
                )
        if self.telemetry_enabled and self.telemetry_otlp_endpoint is None:
            raise ValueError("enabled telemetry requires an OTLP endpoint")
        if not self.telemetry_enabled and self.telemetry_otlp_endpoint is not None:
            raise ValueError("an OTLP endpoint requires telemetry to be enabled")
        if self.telemetry_span_batch_size > self.telemetry_span_queue_size:
            raise ValueError("telemetry span batch size must not exceed queue size")
        if hosted and self.telemetry_enabled:
            endpoint = urlsplit(self.telemetry_otlp_endpoint or "")
            if endpoint.scheme != "https" and endpoint.hostname not in {
                "localhost",
                "127.0.0.1",
                "::1",
            }:
                raise ValueError("hosted OTLP export must use HTTPS or a loopback collector")
            if self.telemetry_trace_sample_ratio <= 0:
                raise ValueError("hosted trace sampling must be greater than zero")
        return self


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Load settings once for the process."""
    return Settings()
