import asyncio
import hashlib
import json
from dataclasses import dataclass, field

import pytest
from pydantic import Field, ValidationError

from ai_interviewer.core.config import Settings
from ai_interviewer.main import create_app
from ai_interviewer.model_gateway import (
    DisabledModelGateway,
    ModelGatewayConfigurationError,
    ModelGatewayError,
    ModelGatewayPolicy,
    ModelGatewayRequest,
    ModelGatewayUnavailableError,
    ModelProviderError,
    ModelProviderRequest,
    ModelProviderResponse,
    ModelReleaseIdentity,
    PromptReleaseIdentity,
    StrictModelOutput,
    StructuredModelGateway,
    build_model_gateway,
)
from ai_interviewer.model_gateway import gateway as gateway_module
from tests.fakes import ReadyDatabase


class EvidenceSpan(StrictModelOutput):
    start: int = Field(ge=0)
    end: int = Field(gt=0)


class ExampleProfile(StrictModelOutput):
    title: str = Field(min_length=1, max_length=100)
    confidence: float = Field(ge=0, le=1)
    evidence: EvidenceSpan


_VALID_OUTPUT = '{"title":"Senior Engineer","confidence":0.9,"evidence":{"start":0,"end":15}}'


def _model_release(**overrides: str) -> ModelReleaseIdentity:
    values = {
        "provider": "example-provider",
        "model_id": "structured-model",
        "model_version": "2026-08-31",
    }
    values.update(overrides)
    return ModelReleaseIdentity(**values)


def _prompt_release() -> PromptReleaseIdentity:
    return PromptReleaseIdentity(
        prompt_id="cv-profile",
        prompt_version="1.0.0",
        schema_id="candidate-profile",
        schema_version="1.0.0",
    )


def _request(**overrides: object) -> ModelGatewayRequest:
    values: dict[str, object] = {
        "operation": "cv_profile",
        "prompt_release": _prompt_release(),
        "instructions": "Return a grounded profile as JSON.",
        "input_text": "Senior engineer with ten years of Python experience.",
        "max_output_tokens": 1_024,
    }
    values.update(overrides)
    return ModelGatewayRequest(**values)  # type: ignore[arg-type]


def _response(
    output_json: str = _VALID_OUTPUT,
    *,
    model_release: ModelReleaseIdentity | None = None,
    finish_reason: str = "stop",
) -> ModelProviderResponse:
    return ModelProviderResponse(
        output_json=output_json,
        model_release=model_release or _model_release(),
        finish_reason=finish_reason,  # type: ignore[arg-type]
    )


@dataclass
class SequencedProvider:
    outcomes: list[ModelProviderResponse | Exception]
    requests: list[ModelProviderRequest] = field(default_factory=list)

    async def generate(self, request: ModelProviderRequest) -> ModelProviderResponse:
        self.requests.append(request)
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


def _gateway(
    provider: SequencedProvider,
    **policy_overrides: object,
) -> StructuredModelGateway:
    policy_values: dict[str, object] = {
        "attempt_timeout_seconds": 1,
        "max_attempts": 3,
        "retry_base_seconds": 0,
        "max_input_characters": 10_000,
        "max_output_characters": 10_000,
    }
    policy_values.update(policy_overrides)
    return StructuredModelGateway(
        provider,
        _model_release(),
        ModelGatewayPolicy(**policy_values),  # type: ignore[arg-type]
    )


@pytest.mark.asyncio
async def test_gateway_returns_only_strictly_validated_structured_output() -> None:
    provider = SequencedProvider([_response()])
    request = _request()

    result = await _gateway(provider).generate(request, ExampleProfile)

    assert result.output.title == "Senior Engineer"
    assert result.output.evidence.start == 0
    assert result.model_release == _model_release()
    assert result.prompt_release == _prompt_release()
    assert (
        result.instructions_sha256
        == hashlib.sha256(b"Return a grounded profile as JSON.").hexdigest()
    )
    assert result.attempts == 1
    sent = provider.requests[0]
    assert sent.operation == "cv_profile"
    assert sent.model_release == _model_release()
    assert sent.prompt_release == _prompt_release()
    assert sent.request_id == request.request_id
    assert sent.output_schema["additionalProperties"] is False
    expected_schema_digest = hashlib.sha256(
        json.dumps(
            sent.output_schema,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode()
    ).hexdigest()
    assert result.output_schema_sha256 == expected_schema_digest
    assert sent.max_output_tokens == 1_024


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "invalid_json",
    [
        "not-json",
        '{"title":"Engineer","confidence":"0.9","evidence":{"start":0,"end":8}}',
        (
            '{"title":"Engineer","confidence":0.9,'
            '"evidence":{"start":0,"end":8},"unexpected":"forbidden"}'
        ),
    ],
)
async def test_invalid_outputs_are_retried_then_fail_closed(invalid_json: str) -> None:
    provider = SequencedProvider([_response(invalid_json), _response(invalid_json)])

    with pytest.raises(ModelGatewayError) as raised:
        await _gateway(provider, max_attempts=2).generate(_request(), ExampleProfile)

    assert raised.value.code == "invalid_output"
    assert raised.value.attempts == 2
    assert len(provider.requests) == 2
    assert invalid_json not in str(raised.value)


@pytest.mark.asyncio
async def test_gateway_can_recover_from_invalid_output_without_changing_release_identity() -> None:
    provider = SequencedProvider([_response("{}"), _response()])

    result = await _gateway(provider).generate(_request(), ExampleProfile)

    assert result.attempts == 2
    assert provider.requests[0] == provider.requests[1]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("provider_code", "expected_attempts"),
    [
        ("rate_limited", 2),
        ("provider_timeout", 2),
        ("provider_unavailable", 2),
        ("provider_failure", 2),
        ("provider_rejected", 1),
    ],
)
async def test_provider_failures_follow_the_bounded_retry_taxonomy(
    provider_code: str,
    expected_attempts: int,
) -> None:
    provider = SequencedProvider(
        [
            ModelProviderError(provider_code),  # type: ignore[arg-type]
            _response(),
        ]
    )

    if provider_code == "provider_rejected":
        with pytest.raises(ModelGatewayError) as raised:
            await _gateway(provider).generate(_request(), ExampleProfile)
        assert raised.value.code == provider_code
    else:
        result = await _gateway(provider).generate(_request(), ExampleProfile)
        assert result.attempts == expected_attempts
    assert len(provider.requests) == expected_attempts


@pytest.mark.asyncio
async def test_unexpected_provider_error_is_retried_without_leaking_its_detail() -> None:
    provider = SequencedProvider(
        [RuntimeError("candidate private text"), RuntimeError("candidate private text")]
    )

    with pytest.raises(ModelGatewayError) as raised:
        await _gateway(provider, max_attempts=2).generate(_request(), ExampleProfile)

    assert raised.value.code == "provider_failure"
    assert "candidate private text" not in str(raised.value)


@pytest.mark.asyncio
async def test_gateway_times_out_each_attempt_and_preserves_task_cancellation() -> None:
    class SlowProvider:
        async def generate(self, request: ModelProviderRequest) -> ModelProviderResponse:
            del request
            await asyncio.sleep(60)
            return _response()

    gateway = StructuredModelGateway(
        SlowProvider(),
        _model_release(),
        ModelGatewayPolicy(
            attempt_timeout_seconds=0.01,
            max_attempts=1,
            retry_base_seconds=0,
            max_input_characters=10_000,
            max_output_characters=10_000,
        ),
    )
    with pytest.raises(ModelGatewayError) as raised:
        await gateway.generate(_request(), ExampleProfile)
    assert raised.value.code == "provider_timeout"

    entered = asyncio.Event()

    class BlockingProvider:
        async def generate(self, request: ModelProviderRequest) -> ModelProviderResponse:
            del request
            entered.set()
            await asyncio.Event().wait()
            return _response()

    task = asyncio.create_task(
        StructuredModelGateway(
            BlockingProvider(),
            _model_release(),
            ModelGatewayPolicy(
                attempt_timeout_seconds=1,
                max_attempts=1,
                retry_base_seconds=0,
                max_input_characters=10_000,
                max_output_characters=10_000,
            ),
        ).generate(_request(), ExampleProfile)
    )
    await entered.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task


@pytest.mark.asyncio
async def test_retry_backoff_is_exponential_and_bounded(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    delays: list[float] = []

    async def record_delay(delay: float) -> None:
        delays.append(delay)

    monkeypatch.setattr(gateway_module.asyncio, "sleep", record_delay)
    provider = SequencedProvider(
        [
            ModelProviderError("provider_unavailable"),
            ModelProviderError("rate_limited"),
            _response(),
        ]
    )

    result = await _gateway(provider, retry_base_seconds=0.25).generate(
        _request(),
        ExampleProfile,
    )

    assert result.attempts == 3
    assert delays == [0.25, 0.5]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("response", "expected_code", "expected_attempts"),
    [
        (
            _response(model_release=_model_release(model_version="different")),
            "model_identity_mismatch",
            1,
        ),
        (_response(finish_reason="content_filter"), "content_filtered", 1),
        (_response(finish_reason="length"), "incomplete_output", 2),
        (_response("x" * 1_001), "output_too_large", 2),
    ],
)
async def test_response_envelope_failures_are_safe_and_bounded(
    response: ModelProviderResponse,
    expected_code: str,
    expected_attempts: int,
) -> None:
    provider = SequencedProvider([response, response])

    with pytest.raises(ModelGatewayError) as raised:
        await _gateway(
            provider,
            max_attempts=2,
            max_output_characters=1_000,
        ).generate(_request(), ExampleProfile)

    assert raised.value.code == expected_code
    assert raised.value.attempts == expected_attempts
    assert len(provider.requests) == expected_attempts


@pytest.mark.asyncio
async def test_gateway_rejects_oversized_input_before_calling_provider() -> None:
    provider = SequencedProvider([_response()])

    with pytest.raises(ModelGatewayError) as raised:
        await _gateway(provider, max_input_characters=1_000).generate(
            _request(input_text="x" * 1_001),
            ExampleProfile,
        )

    assert raised.value.code == "provider_rejected"
    assert raised.value.attempts == 0
    assert provider.requests == []


@pytest.mark.asyncio
async def test_gateway_requires_the_strict_output_base() -> None:
    class UnsafeOutput(StrictModelOutput):
        value: str

    class NotAnOutput:
        pass

    provider = SequencedProvider([_response('{"value":"ok"}')])
    result = await _gateway(provider).generate(_request(), UnsafeOutput)
    assert result.output.value == "ok"

    with pytest.raises(TypeError, match="StrictModelOutput"):
        await _gateway(provider).generate(_request(), NotAnOutput)  # type: ignore[type-var]


@pytest.mark.asyncio
async def test_disabled_gateway_fails_closed_without_inspecting_payload() -> None:
    request = _request(input_text="candidate-sensitive-marker")

    with pytest.raises(ModelGatewayUnavailableError) as raised:
        await DisabledModelGateway().generate(request, ExampleProfile)

    assert raised.value.attempts == 0
    assert "candidate-sensitive-marker" not in str(raised.value)


def test_sensitive_request_and_response_fields_are_excluded_from_repr() -> None:
    request = _request(
        instructions="secret-instructions-marker",
        input_text="candidate-sensitive-marker",
    )
    provider_request = ModelProviderRequest(
        operation=request.operation,
        model_release=_model_release(),
        prompt_release=request.prompt_release,
        instructions=request.instructions,
        input_text=request.input_text,
        output_schema={"private-schema-marker": "value"},
        max_output_tokens=request.max_output_tokens,
    )
    response = _response("candidate-output-marker")

    combined = repr(request) + repr(provider_request) + repr(response)
    assert "secret-instructions-marker" not in combined
    assert "candidate-sensitive-marker" not in combined
    assert "private-schema-marker" not in combined
    assert "candidate-output-marker" not in combined


@pytest.mark.parametrize(
    "changes",
    [
        {"operation": "CV profile"},
        {"instructions": ""},
        {"input_text": ""},
        {"max_output_tokens": 0},
    ],
)
def test_request_contract_rejects_ambiguous_or_empty_values(changes: dict[str, object]) -> None:
    with pytest.raises(ValueError):
        _request(**changes)


@pytest.mark.parametrize(
    "constructor",
    [
        lambda: _model_release(provider="has whitespace"),
        lambda: _model_release(model_id=""),
        lambda: PromptReleaseIdentity(
            prompt_id="cv profile",
            prompt_version="1",
            schema_id="profile",
            schema_version="1",
        ),
    ],
)
def test_release_identities_are_strict_and_bounded(constructor: object) -> None:
    with pytest.raises(ValidationError):
        constructor()  # type: ignore[operator]


def test_provider_response_envelope_rejects_unknown_finish_reason() -> None:
    with pytest.raises(ValueError, match="finish reason"):
        _response(finish_reason="unknown")

    with pytest.raises(TypeError, match="provider output"):
        ModelProviderResponse(  # type: ignore[arg-type]
            output_json=123,
            model_release=_model_release(),
            finish_reason="stop",
        )

    with pytest.raises(TypeError, match="model release identity"):
        ModelProviderResponse(  # type: ignore[arg-type]
            output_json="{}",
            model_release="not-an-identity",
            finish_reason="stop",
        )

    with pytest.raises(ValueError, match="unsupported model provider failure code"):
        ModelProviderError("unsafe-detail")  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "values",
    [
        {"attempt_timeout_seconds": 0},
        {"max_attempts": 0},
        {"retry_base_seconds": -1},
        {"max_input_characters": 999},
        {"max_output_characters": 1_000_001},
    ],
)
def test_gateway_policy_is_bounded(values: dict[str, object]) -> None:
    with pytest.raises(ValueError):
        ModelGatewayPolicy(**values)  # type: ignore[arg-type]


def test_builder_requires_explicit_provider_only_when_enabled() -> None:
    assert isinstance(build_model_gateway(Settings(_env_file=None)), DisabledModelGateway)

    enabled = Settings(
        _env_file=None,
        model_gateway_enabled=True,
        model_gateway_provider="EXAMPLE-PROVIDER",
        model_gateway_model_id="structured-model",
        model_gateway_model_version="2026-08-31",
    )
    with pytest.raises(ModelGatewayConfigurationError, match="explicit provider adapter"):
        build_model_gateway(enabled)

    provider = SequencedProvider([_response()])
    gateway = build_model_gateway(enabled, provider)
    assert isinstance(gateway, StructuredModelGateway)
    assert gateway.enabled

    app = create_app(enabled, database=ReadyDatabase(), model_provider=provider)
    assert app.state.model_gateway.enabled


def test_model_gateway_settings_fail_closed_and_normalize_provider() -> None:
    with pytest.raises(ValidationError, match="requires provider, model ID, and model version"):
        Settings(_env_file=None, model_gateway_enabled=True)

    with pytest.raises(ValidationError, match="require the gateway to be enabled"):
        Settings(_env_file=None, model_gateway_provider="example-provider")

    with pytest.raises(ValidationError, match="bounded release identifiers"):
        Settings(
            _env_file=None,
            model_gateway_enabled=True,
            model_gateway_provider="unsafe provider",
            model_gateway_model_id="model",
            model_gateway_model_version="1",
        )

    settings = Settings(
        _env_file=None,
        model_gateway_enabled=True,
        model_gateway_provider="EXAMPLE-PROVIDER",
        model_gateway_model_id="namespace/model",
        model_gateway_model_version="2026-08-31",
    )
    assert settings.model_gateway_provider == "example-provider"
