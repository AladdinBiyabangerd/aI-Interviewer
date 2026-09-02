"""OpenAI Responses adapter contract tests; every call uses a local mock transport."""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from uuid import UUID

import httpx2
import pytest
from pydantic import SecretStr, ValidationError

from ai_interviewer.core.config import Settings
from ai_interviewer.model_gateway import (
    ModelProviderError,
    ModelProviderRequest,
    ModelReleaseIdentity,
    OpenAIResponsesProvider,
    PromptReleaseIdentity,
    StructuredModelGateway,
    build_model_gateway,
)
from ai_interviewer.model_gateway import openai as openai_module
from ai_interviewer.model_gateway.openai import (
    OPENAI_RESPONSES_URL,
    openai_strict_output_schema,
)

_REQUEST_ID = UUID("018f6d79-4db5-7b91-9d21-54d6f60ec601")
_FAKE_KEY = "test-openai-key-1234567890"


def _provider_request(*, provider: str = "openai") -> ModelProviderRequest:
    return ModelProviderRequest(
        operation="profile_cv",
        model_release=ModelReleaseIdentity(
            provider=provider,
            model_id="gpt-5.6-sol",
            model_version="gpt-5.6-sol",
        ),
        prompt_release=PromptReleaseIdentity(
            prompt_id="cv-profile-extraction",
            prompt_version="1.0.0",
            schema_id="cv-profile",
            schema_version="1.0.0",
        ),
        instructions="Return the structured profile.",
        input_text="Python",
        output_schema={
            "type": "object",
            "properties": {
                "answer": {"type": "string"},
                "optional": {"type": "string", "default": ""},
                "nested": {
                    "type": "object",
                    "properties": {"count": {"type": "integer"}},
                    "required": [],
                },
            },
            "required": ["answer"],
            "additionalProperties": True,
        },
        max_output_tokens=512,
        request_id=_REQUEST_ID,
    )


def _response_document(
    *,
    model: str = "gpt-5.6-sol",
    status: str = "completed",
    content: list[dict[str, object]] | None = None,
    incomplete_reason: str | None = None,
    error: object = None,
) -> dict[str, object]:
    return {
        "id": "resp_test",
        "model": model,
        "status": status,
        "error": error,
        "incomplete_details": (
            {"reason": incomplete_reason} if incomplete_reason is not None else None
        ),
        "output": [
            {
                "type": "message",
                "content": content
                if content is not None
                else [
                    {
                        "type": "output_text",
                        "text": '{"answer":"yes","optional":"","nested":{"count":1}}',
                    }
                ],
            }
        ],
    }


def _provider(handler: Callable[[httpx2.Request], httpx2.Response]) -> OpenAIResponsesProvider:
    return OpenAIResponsesProvider(
        SecretStr(_FAKE_KEY),
        transport=httpx2.MockTransport(handler),
    )


@pytest.mark.asyncio
async def test_openai_provider_sends_bounded_nonstored_strict_response_request() -> None:
    captured: dict[str, object] = {}

    def handler(request: httpx2.Request) -> httpx2.Response:
        captured["method"] = request.method
        captured["url"] = str(request.url)
        captured["authorization"] = request.headers["authorization"]
        captured["request_id"] = request.headers["x-client-request-id"]
        captured["payload"] = json.loads(request.content)
        return httpx2.Response(200, json=_response_document())

    provider = _provider(handler)
    response = await provider.generate(_provider_request())

    assert captured == {
        "method": "POST",
        "url": OPENAI_RESPONSES_URL,
        "authorization": f"Bearer {_FAKE_KEY}",
        "request_id": str(_REQUEST_ID),
        "payload": {
            "model": "gpt-5.6-sol",
            "instructions": "Return the structured profile.",
            "input": "Python",
            "max_output_tokens": 512,
            "store": False,
            "background": False,
            "truncation": "disabled",
            "text": {
                "format": {
                    "type": "json_schema",
                    "name": "cv-profile_1_0_0_c63428cf5f6e",
                    "strict": True,
                    "schema": {
                        "type": "object",
                        "properties": {
                            "answer": {"type": "string"},
                            "optional": {"type": "string"},
                            "nested": {
                                "type": "object",
                                "properties": {"count": {"type": "integer"}},
                                "required": ["count"],
                                "additionalProperties": False,
                            },
                        },
                        "required": ["answer", "optional", "nested"],
                        "additionalProperties": False,
                    },
                }
            },
        },
    }
    assert response.output_json == '{"answer":"yes","optional":"","nested":{"count":1}}'
    assert response.finish_reason == "stop"
    assert response.model_release == _provider_request().model_release
    assert repr(provider) == "OpenAIResponsesProvider()"
    assert _FAKE_KEY not in repr(provider)


def test_openai_schema_conversion_is_nonmutating_and_requires_root_object() -> None:
    original = _provider_request().output_schema
    converted = openai_strict_output_schema(original)

    assert original["additionalProperties"] is True
    assert converted["additionalProperties"] is False
    with pytest.raises(ValueError, match="root object"):
        openai_strict_output_schema({"type": "array", "items": {"type": "string"}})


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("status_code", "expected_code"),
    [
        (400, "provider_rejected"),
        (408, "provider_timeout"),
        (409, "provider_unavailable"),
        (429, "rate_limited"),
        (503, "provider_unavailable"),
        (302, "provider_failure"),
    ],
)
async def test_openai_provider_maps_http_status_without_reading_error_payload(
    status_code: int,
    expected_code: str,
) -> None:
    provider = _provider(
        lambda _: httpx2.Response(status_code, text="candidate-secret-provider-detail")
    )

    with pytest.raises(ModelProviderError) as captured:
        await provider.generate(_provider_request())

    assert captured.value.code == expected_code
    assert "candidate-secret" not in str(captured.value)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("error_type", "expected_code"),
    [
        (httpx2.ConnectTimeout, "provider_timeout"),
        (httpx2.ConnectError, "provider_unavailable"),
    ],
)
async def test_openai_provider_maps_transport_failures(
    error_type: type[httpx2.RequestError],
    expected_code: str,
) -> None:
    def handler(request: httpx2.Request) -> httpx2.Response:
        raise error_type("candidate-secret", request=request)

    with pytest.raises(ModelProviderError) as captured:
        await _provider(handler).generate(_provider_request())

    assert captured.value.code == expected_code
    assert "candidate-secret" not in str(captured.value)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("document", "expected_code"),
    [
        (_response_document(status="incomplete", incomplete_reason="unknown"), "provider_failure"),
        (_response_document(status="failed"), "provider_failure"),
        (_response_document(error={"message": "candidate-secret"}), "provider_failure"),
        ({"model": "gpt-5.6-sol", "status": "completed", "output": {}}, "provider_failure"),
        ({"model": 123, "status": "completed", "output": []}, "provider_failure"),
        ({"model": "unsafe model", "status": "completed", "output": []}, "provider_failure"),
        (_response_document(content=[]), "provider_failure"),
        (
            _response_document(content=[{"type": "output_text", "text": 123}]),
            "provider_failure",
        ),
        (
            _response_document(content=[{"type": "output_text", "text": ""}]),
            "provider_failure",
        ),
    ],
)
async def test_openai_provider_rejects_malformed_or_failed_success_documents(
    document: dict[str, object],
    expected_code: str,
) -> None:
    provider = _provider(lambda _: httpx2.Response(200, json=document))

    with pytest.raises(ModelProviderError) as captured:
        await provider.generate(_provider_request())

    assert captured.value.code == expected_code


@pytest.mark.asyncio
async def test_openai_provider_maps_incomplete_refusal_and_model_drift() -> None:
    length = await _provider(
        lambda _: httpx2.Response(
            200,
            json=_response_document(
                status="incomplete",
                incomplete_reason="max_output_tokens",
            ),
        )
    ).generate(_provider_request())
    filtered = await _provider(
        lambda _: httpx2.Response(
            200,
            json=_response_document(
                status="incomplete",
                incomplete_reason="content_filter",
            ),
        )
    ).generate(_provider_request())
    refused = await _provider(
        lambda _: httpx2.Response(
            200,
            json=_response_document(content=[{"type": "refusal", "refusal": "no"}]),
        )
    ).generate(_provider_request())
    drifted = await _provider(
        lambda _: httpx2.Response(200, json=_response_document(model="gpt-5.6"))
    ).generate(_provider_request())

    assert length.finish_reason == "length"
    assert filtered.finish_reason == "content_filter"
    assert refused.finish_reason == "content_filter"
    assert drifted.model_release.model_version == "gpt-5.6"


@pytest.mark.asyncio
async def test_openai_provider_rejects_wrong_provider_and_non_json() -> None:
    provider = _provider(lambda _: pytest.fail("transport must not be called"))
    with pytest.raises(ModelProviderError) as captured:
        await provider.generate(_provider_request(provider="other"))
    assert captured.value.code == "provider_rejected"

    malformed = _provider(lambda _: httpx2.Response(200, content=b"not-json"))
    with pytest.raises(ModelProviderError) as malformed_error:
        await malformed.generate(_provider_request())
    assert malformed_error.value.code == "provider_failure"

    non_object = _provider(lambda _: httpx2.Response(200, json=[]))
    with pytest.raises(ModelProviderError) as non_object_error:
        await non_object.generate(_provider_request())
    assert non_object_error.value.code == "provider_failure"


@pytest.mark.asyncio
async def test_openai_provider_bounds_raw_response(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(openai_module, "_MAX_RESPONSE_BYTES", 8)
    provider = _provider(lambda _: httpx2.Response(200, json=_response_document()))

    with pytest.raises(ModelProviderError) as captured:
        await provider.generate(_provider_request())

    assert captured.value.code == "provider_failure"


def test_openai_settings_require_scoped_secret_and_auto_build_adapter() -> None:
    with pytest.raises(ValidationError, match="requires an API key"):
        Settings(
            _env_file=None,
            model_gateway_enabled=True,
            model_gateway_provider="openai",
            model_gateway_model_id="gpt-5.6-sol",
            model_gateway_model_version="gpt-5.6-sol",
        )

    with pytest.raises(ValidationError, match="require the enabled OpenAI"):
        Settings(_env_file=None, openai_api_key=SecretStr(_FAKE_KEY))

    settings = Settings(
        _env_file=None,
        model_gateway_enabled=True,
        model_gateway_provider="OPENAI",
        model_gateway_model_id="gpt-5.6-sol",
        model_gateway_model_version="gpt-5.6-sol",
        openai_api_key=SecretStr(_FAKE_KEY),
    )
    gateway = build_model_gateway(settings)

    assert isinstance(gateway, StructuredModelGateway)
    assert gateway.model_release == ModelReleaseIdentity(
        provider="openai",
        model_id="gpt-5.6-sol",
        model_version="gpt-5.6-sol",
    )
    assert _FAKE_KEY not in repr(settings)


def test_blank_openai_environment_value_is_treated_as_not_configured() -> None:
    settings = Settings(_env_file=None, openai_api_key="  ")

    assert settings.openai_api_key is None


def test_openai_settings_load_secret_file_and_reject_ambiguous_or_malformed_key(
    tmp_path: Path,
) -> None:
    secret_file = tmp_path / "openai-api-key"
    secret_file.write_text(f"{_FAKE_KEY}\n", encoding="utf-8")
    secret_file.chmod(0o600)
    coordinates = {
        "model_gateway_enabled": True,
        "model_gateway_provider": "openai",
        "model_gateway_model_id": "gpt-5.6-sol",
        "model_gateway_model_version": "gpt-5.6-sol",
    }

    settings = Settings(
        _env_file=None,
        **coordinates,
        openai_api_key_file=secret_file,
    )
    assert settings.openai_api_key is not None
    assert settings.openai_api_key.get_secret_value() == _FAKE_KEY

    with pytest.raises(ValidationError, match="mutually exclusive"):
        Settings(
            _env_file=None,
            **coordinates,
            openai_api_key=SecretStr(_FAKE_KEY),
            openai_api_key_file=secret_file,
        )
    with pytest.raises(ValidationError, match="bounded non-placeholder"):
        Settings(
            _env_file=None,
            **coordinates,
            openai_api_key=SecretStr("too-short"),
        )
