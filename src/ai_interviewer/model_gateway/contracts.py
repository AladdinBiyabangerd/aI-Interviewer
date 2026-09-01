"""Provider-neutral, payload-safe model execution contracts."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, field_validator
from uuid6 import uuid7

_IDENTIFIER_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,127}$")
_OPERATION_PATTERN = re.compile(r"^[a-z][a-z0-9_]{0,63}$")
MAX_INSTRUCTIONS_CHARACTERS = 32_000
MAX_REQUEST_INPUT_CHARACTERS = 1_000_000

FinishReason = Literal["stop", "length", "content_filter"]
ProviderFailureCode = Literal[
    "rate_limited",
    "provider_timeout",
    "provider_unavailable",
    "provider_rejected",
    "provider_failure",
]
GatewayFailureCode = Literal[
    "rate_limited",
    "provider_timeout",
    "provider_unavailable",
    "provider_rejected",
    "provider_failure",
    "model_identity_mismatch",
    "invalid_output",
    "output_too_large",
    "incomplete_output",
    "content_filtered",
]


def _normalize_identifier(value: str, *, field_name: str, lowercase: bool = False) -> str:
    normalized = value.strip()
    if not _IDENTIFIER_PATTERN.fullmatch(normalized):
        raise ValueError(f"{field_name} must be a bounded release identifier")
    return normalized.lower() if lowercase else normalized


class _StrictIdentity(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)


class ModelReleaseIdentity(_StrictIdentity):
    """Exact provider/model release expected for a reproducible execution."""

    provider: str
    model_id: str
    model_version: str

    @field_validator("provider")
    @classmethod
    def validate_provider(cls, value: str) -> str:
        return _normalize_identifier(value, field_name="provider", lowercase=True)

    @field_validator("model_id", "model_version")
    @classmethod
    def validate_model_identity(cls, value: str, info: object) -> str:
        field_name = getattr(info, "field_name", "model identity")
        return _normalize_identifier(value, field_name=field_name)


class PromptReleaseIdentity(_StrictIdentity):
    """Immutable prompt and output-schema coordinates stored with derived data."""

    prompt_id: str
    prompt_version: str
    schema_id: str
    schema_version: str

    @field_validator("prompt_id", "prompt_version", "schema_id", "schema_version")
    @classmethod
    def validate_prompt_identity(cls, value: str, info: object) -> str:
        field_name = getattr(info, "field_name", "prompt identity")
        return _normalize_identifier(value, field_name=field_name)


class StrictModelOutput(BaseModel):
    """Required base for model outputs; coercion and unknown fields are forbidden."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    def __repr_args__(self) -> list[tuple[str, object]]:
        """Keep potentially sensitive structured output out of representations."""
        return []


@dataclass(frozen=True, slots=True)
class ModelGatewayRequest:
    """One structured execution request without provider-specific coordinates."""

    operation: str
    prompt_release: PromptReleaseIdentity
    instructions: str = field(repr=False)
    input_text: str = field(repr=False)
    max_output_tokens: int = 4_096
    request_id: UUID = field(default_factory=uuid7)

    def __post_init__(self) -> None:
        if not _OPERATION_PATTERN.fullmatch(self.operation):
            raise ValueError("operation must be a bounded lowercase identifier")
        if not self.instructions or len(self.instructions) > MAX_INSTRUCTIONS_CHARACTERS:
            raise ValueError("instructions must be nonempty and within the character limit")
        if not self.input_text or len(self.input_text) > MAX_REQUEST_INPUT_CHARACTERS:
            raise ValueError("input text must be nonempty and within the character limit")
        if not 1 <= self.max_output_tokens <= 32_768:
            raise ValueError("max output tokens must be between 1 and 32768")
        if not isinstance(self.request_id, UUID):
            raise TypeError("request_id must be a UUID")


@dataclass(frozen=True, slots=True)
class ModelProviderRequest:
    """Exact request delivered to a concrete provider adapter."""

    operation: str
    model_release: ModelReleaseIdentity
    prompt_release: PromptReleaseIdentity
    instructions: str = field(repr=False)
    input_text: str = field(repr=False)
    output_schema: dict[str, object] = field(repr=False)
    max_output_tokens: int
    request_id: UUID = field(default_factory=uuid7)


@dataclass(frozen=True, slots=True)
class ModelProviderResponse:
    """Normalized provider response; adapters must never return free-form metadata."""

    output_json: str = field(repr=False)
    model_release: ModelReleaseIdentity
    finish_reason: FinishReason

    def __post_init__(self) -> None:
        if not isinstance(self.output_json, str):
            raise TypeError("provider output must be text")
        if not isinstance(self.model_release, ModelReleaseIdentity):
            raise TypeError("provider response must carry a model release identity")
        if self.finish_reason not in {"stop", "length", "content_filter"}:
            raise ValueError("provider finish reason is not supported")
