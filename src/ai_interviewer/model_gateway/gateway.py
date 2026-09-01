"""Strict structured-output gateway with bounded, fail-closed retries."""

from __future__ import annotations

import asyncio
import hashlib
import json
from dataclasses import dataclass, field
from typing import Protocol, TypeVar

from pydantic import ValidationError

from ai_interviewer.model_gateway.contracts import (
    GatewayFailureCode,
    ModelGatewayRequest,
    ModelProviderRequest,
    ModelProviderResponse,
    ModelReleaseIdentity,
    PromptReleaseIdentity,
    ProviderFailureCode,
    StrictModelOutput,
)

OutputT = TypeVar("OutputT", bound=StrictModelOutput)

_RETRYABLE_FAILURES: frozenset[GatewayFailureCode] = frozenset(
    {
        "rate_limited",
        "provider_timeout",
        "provider_unavailable",
        "provider_failure",
        "invalid_output",
        "output_too_large",
        "incomplete_output",
    }
)
_PROVIDER_FAILURES: frozenset[ProviderFailureCode] = frozenset(
    {
        "rate_limited",
        "provider_timeout",
        "provider_unavailable",
        "provider_rejected",
        "provider_failure",
    }
)


def model_instructions_sha256(instructions: str) -> str:
    """Return the canonical instruction digest used in release snapshots."""
    return hashlib.sha256(instructions.encode("utf-8")).hexdigest()


def model_output_schema_sha256(output_type: type[StrictModelOutput]) -> str:
    """Return the digest for the exact canonical application-owned JSON schema."""
    output_schema = output_type.model_json_schema(mode="validation")
    return hashlib.sha256(
        json.dumps(
            output_schema,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    ).hexdigest()


class ModelGatewayConfigurationError(RuntimeError):
    """Raised when an enabled gateway has no usable provider boundary."""


class ModelProviderError(RuntimeError):
    """Payload-free provider failure normalized by a concrete adapter."""

    def __init__(self, code: ProviderFailureCode) -> None:
        if code not in _PROVIDER_FAILURES:
            raise ValueError("unsupported model provider failure code")
        self.code = code
        super().__init__(f"model provider call failed: {code}")


class ModelGatewayError(RuntimeError):
    """Safe terminal failure after the gateway applies its retry policy."""

    def __init__(self, code: GatewayFailureCode, attempts: int) -> None:
        self.code = code
        self.attempts = attempts
        super().__init__(f"model gateway failed after {attempts} attempt(s): {code}")


class ModelGatewayUnavailableError(ModelGatewayError):
    """Raised when model execution is disabled."""

    def __init__(self) -> None:
        super().__init__("provider_unavailable", 0)


class ModelProvider(Protocol):
    """Provider adapter port; implementations translate one exact JSON-schema call."""

    async def generate(self, request: ModelProviderRequest) -> ModelProviderResponse: ...


@dataclass(frozen=True, slots=True)
class ModelGatewayPolicy:
    attempt_timeout_seconds: float = 30.0
    max_attempts: int = 3
    retry_base_seconds: float = 0.25
    max_input_characters: int = 250_000
    max_output_characters: int = 100_000

    def __post_init__(self) -> None:
        if not 0 < self.attempt_timeout_seconds <= 120:
            raise ValueError("model attempt timeout must be greater than zero and at most 120")
        if not 1 <= self.max_attempts <= 5:
            raise ValueError("model max attempts must be between 1 and 5")
        if not 0 <= self.retry_base_seconds <= 5:
            raise ValueError("model retry base must be between 0 and 5 seconds")
        if not 1_000 <= self.max_input_characters <= 1_000_000:
            raise ValueError("model input character limit must be between 1000 and 1000000")
        if not 1_000 <= self.max_output_characters <= 1_000_000:
            raise ValueError("model output character limit must be between 1000 and 1000000")


@dataclass(frozen=True, slots=True)
class ModelGatewayResult[ResultT: StrictModelOutput]:
    output: ResultT = field(repr=False)
    model_release: ModelReleaseIdentity
    prompt_release: PromptReleaseIdentity
    instructions_sha256: str
    output_schema_sha256: str
    attempts: int


class ModelGatewayRuntime(Protocol):
    enabled: bool

    @property
    def model_release(self) -> ModelReleaseIdentity | None: ...

    async def generate(
        self,
        request: ModelGatewayRequest,
        output_type: type[OutputT],
    ) -> ModelGatewayResult[OutputT]: ...


class DisabledModelGateway:
    """Fail-closed local runtime used until a provider adapter is explicitly enabled."""

    enabled = False

    @property
    def model_release(self) -> None:
        return None

    async def generate(
        self,
        request: ModelGatewayRequest,
        output_type: type[OutputT],
    ) -> ModelGatewayResult[OutputT]:
        del request, output_type
        raise ModelGatewayUnavailableError


class StructuredModelGateway:
    """Validate every response against an application-owned strict output model."""

    enabled = True

    def __init__(
        self,
        provider: ModelProvider,
        model_release: ModelReleaseIdentity,
        policy: ModelGatewayPolicy,
    ) -> None:
        self._provider = provider
        self._model_release = model_release
        self._policy = policy

    async def generate(
        self,
        request: ModelGatewayRequest,
        output_type: type[OutputT],
    ) -> ModelGatewayResult[OutputT]:
        if not issubclass(output_type, StrictModelOutput):
            raise TypeError("output_type must inherit StrictModelOutput")
        if len(request.input_text) > self._policy.max_input_characters:
            raise ModelGatewayError("provider_rejected", 0)

        output_schema = output_type.model_json_schema(mode="validation")
        instructions_sha256 = model_instructions_sha256(request.instructions)
        output_schema_sha256 = model_output_schema_sha256(output_type)
        provider_request = ModelProviderRequest(
            operation=request.operation,
            model_release=self._model_release,
            prompt_release=request.prompt_release,
            instructions=request.instructions,
            input_text=request.input_text,
            output_schema=output_schema,
            max_output_tokens=request.max_output_tokens,
            request_id=request.request_id,
        )

        for attempt in range(1, self._policy.max_attempts + 1):
            failure, response = await self._attempt(provider_request)
            if failure is None and response is not None:
                try:
                    output = output_type.model_validate_json(response.output_json, strict=True)
                except ValidationError:
                    failure = "invalid_output"
                else:
                    return ModelGatewayResult(
                        output=output,
                        model_release=response.model_release,
                        prompt_release=request.prompt_release,
                        instructions_sha256=instructions_sha256,
                        output_schema_sha256=output_schema_sha256,
                        attempts=attempt,
                    )

            assert failure is not None
            if failure not in _RETRYABLE_FAILURES or attempt == self._policy.max_attempts:
                raise ModelGatewayError(failure, attempt)
            delay = min(self._policy.retry_base_seconds * (2 ** (attempt - 1)), 10.0)
            if delay:
                await asyncio.sleep(delay)

        raise AssertionError(  # pragma: no cover
            "bounded model gateway loop exhausted unexpectedly"
        )

    async def _attempt(
        self,
        request: ModelProviderRequest,
    ) -> tuple[GatewayFailureCode | None, ModelProviderResponse | None]:
        try:
            response = await asyncio.wait_for(
                self._provider.generate(request),
                timeout=self._policy.attempt_timeout_seconds,
            )
        except TimeoutError:
            return "provider_timeout", None
        except ModelProviderError as exc:
            return exc.code, None
        except asyncio.CancelledError:
            raise
        except Exception:
            return "provider_failure", None

        if response.model_release != self._model_release:
            return "model_identity_mismatch", None
        if response.finish_reason == "content_filter":
            return "content_filtered", None
        if response.finish_reason == "length":
            return "incomplete_output", None
        if len(response.output_json) > self._policy.max_output_characters:
            return "output_too_large", None
        return None, response

    @property
    def model_release(self) -> ModelReleaseIdentity:
        return self._model_release
