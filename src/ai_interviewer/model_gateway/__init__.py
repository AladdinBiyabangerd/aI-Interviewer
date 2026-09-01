"""Provider-neutral model gateway public surface."""

from __future__ import annotations

from typing import TYPE_CHECKING

from ai_interviewer.model_gateway.contracts import (
    ModelGatewayRequest,
    ModelProviderRequest,
    ModelProviderResponse,
    ModelReleaseIdentity,
    PromptReleaseIdentity,
    StrictModelOutput,
)
from ai_interviewer.model_gateway.gateway import (
    DisabledModelGateway,
    ModelGatewayConfigurationError,
    ModelGatewayError,
    ModelGatewayPolicy,
    ModelGatewayResult,
    ModelGatewayRuntime,
    ModelGatewayUnavailableError,
    ModelProvider,
    ModelProviderError,
    StructuredModelGateway,
    model_instructions_sha256,
    model_output_schema_sha256,
)
from ai_interviewer.model_gateway.openai import OpenAIResponsesProvider

if TYPE_CHECKING:
    from ai_interviewer.core.config import Settings


def build_model_gateway(
    settings: Settings,
    provider: ModelProvider | None = None,
) -> ModelGatewayRuntime:
    """Build a disabled gateway or one explicitly configured provider adapter."""
    if not settings.model_gateway_enabled:
        return DisabledModelGateway()
    if provider is None and settings.model_gateway_provider == "openai":
        assert settings.openai_api_key is not None
        provider = OpenAIResponsesProvider(settings.openai_api_key)
    elif provider is None:
        raise ModelGatewayConfigurationError(
            "enabled model gateway requires an explicit provider adapter"
        )
    assert settings.model_gateway_provider is not None
    assert settings.model_gateway_model_id is not None
    assert settings.model_gateway_model_version is not None
    return StructuredModelGateway(
        provider,
        ModelReleaseIdentity(
            provider=settings.model_gateway_provider,
            model_id=settings.model_gateway_model_id,
            model_version=settings.model_gateway_model_version,
        ),
        ModelGatewayPolicy(
            attempt_timeout_seconds=settings.model_gateway_timeout_seconds,
            max_attempts=settings.model_gateway_max_attempts,
            retry_base_seconds=settings.model_gateway_retry_base_seconds,
            max_input_characters=settings.model_gateway_max_input_characters,
            max_output_characters=settings.model_gateway_max_output_characters,
        ),
    )


__all__ = [
    "DisabledModelGateway",
    "ModelGatewayConfigurationError",
    "ModelGatewayError",
    "ModelGatewayPolicy",
    "ModelGatewayRequest",
    "ModelGatewayResult",
    "ModelGatewayRuntime",
    "ModelGatewayUnavailableError",
    "ModelProvider",
    "ModelProviderError",
    "ModelProviderRequest",
    "ModelProviderResponse",
    "ModelReleaseIdentity",
    "OpenAIResponsesProvider",
    "PromptReleaseIdentity",
    "StrictModelOutput",
    "StructuredModelGateway",
    "build_model_gateway",
    "model_instructions_sha256",
    "model_output_schema_sha256",
]
