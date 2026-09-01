"""OpenAI Responses API adapter for strict, non-stored structured output."""

from __future__ import annotations

import hashlib
import json
import re
from typing import Final

import httpx2
from pydantic import SecretStr, ValidationError

from ai_interviewer.model_gateway.contracts import (
    FinishReason,
    ModelProviderRequest,
    ModelProviderResponse,
    ModelReleaseIdentity,
    ProviderFailureCode,
)
from ai_interviewer.model_gateway.gateway import ModelProviderError

OPENAI_PROVIDER: Final = "openai"
OPENAI_RESPONSES_URL: Final = "https://api.openai.com/v1/responses"
_MAX_RESPONSE_BYTES: Final = 8 * 1024 * 1024
_SCHEMA_NAME_CHARACTER = re.compile(r"[^A-Za-z0-9_-]")


def openai_strict_output_schema(schema: dict[str, object]) -> dict[str, object]:
    """Convert an application schema into the Responses strict-output subset."""
    converted = _convert_schema_value(schema)
    if not isinstance(converted, dict) or converted.get("type") != "object":
        raise ValueError("OpenAI structured output requires a root object schema")
    return converted


def _convert_schema_value(value: object) -> object:
    if isinstance(value, dict):
        converted: dict[str, object] = {
            str(key): _convert_schema_value(item) for key, item in value.items() if key != "default"
        }
        properties = converted.get("properties")
        if converted.get("type") == "object" and isinstance(properties, dict):
            converted["additionalProperties"] = False
            converted["required"] = list(properties)
        return converted
    if isinstance(value, list):
        return [_convert_schema_value(item) for item in value]
    return value


def _schema_name(request: ModelProviderRequest) -> str:
    raw_name = f"{request.prompt_release.schema_id}_{request.prompt_release.schema_version}"
    normalized = _SCHEMA_NAME_CHARACTER.sub("_", raw_name).strip("_-") or "schema"
    digest = hashlib.sha256(raw_name.encode("utf-8")).hexdigest()[:12]
    return f"{normalized[:47]}_{digest}"


class OpenAIResponsesProvider:
    """Translate the provider-neutral request into one OpenAI Responses call."""

    def __init__(
        self,
        api_key: SecretStr,
        *,
        transport: httpx2.AsyncBaseTransport | None = None,
    ) -> None:
        self._api_key = api_key
        self._transport = transport

    def __repr__(self) -> str:
        return "OpenAIResponsesProvider()"

    async def generate(self, request: ModelProviderRequest) -> ModelProviderResponse:
        if request.model_release.provider != OPENAI_PROVIDER:
            raise ModelProviderError("provider_rejected")

        payload: dict[str, object] = {
            "model": request.model_release.model_version,
            "instructions": request.instructions,
            "input": request.input_text,
            "max_output_tokens": request.max_output_tokens,
            "store": False,
            "background": False,
            "truncation": "disabled",
            "text": {
                "format": {
                    "type": "json_schema",
                    "name": _schema_name(request),
                    "strict": True,
                    "schema": openai_strict_output_schema(request.output_schema),
                }
            },
        }
        headers = {
            "Authorization": f"Bearer {self._api_key.get_secret_value()}",
            "Content-Type": "application/json",
            "X-Client-Request-Id": str(request.request_id),
        }

        try:
            async with (
                httpx2.AsyncClient(
                    follow_redirects=False,
                    http2=False,
                    timeout=120.0,
                    transport=self._transport,
                    trust_env=False,
                ) as client,
                client.stream(
                    "POST",
                    OPENAI_RESPONSES_URL,
                    headers=headers,
                    json=payload,
                ) as response,
            ):
                if response.status_code != 200:
                    raise ModelProviderError(_failure_code(response.status_code))
                raw_response = bytearray()
                async for chunk in response.aiter_bytes():
                    raw_response.extend(chunk)
                    if len(raw_response) > _MAX_RESPONSE_BYTES:
                        raise ModelProviderError("provider_failure")
        except httpx2.TimeoutException as exc:
            raise ModelProviderError("provider_timeout") from exc
        except httpx2.RequestError as exc:
            raise ModelProviderError("provider_unavailable") from exc

        try:
            document = json.loads(raw_response)
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ModelProviderError("provider_failure") from exc
        if not isinstance(document, dict):
            raise ModelProviderError("provider_failure")
        return _normalize_response(document, request)


def _failure_code(status_code: int) -> ProviderFailureCode:
    if status_code == 408:
        return "provider_timeout"
    if status_code == 429:
        return "rate_limited"
    if status_code == 409 or 500 <= status_code <= 599:
        return "provider_unavailable"
    if 400 <= status_code <= 499:
        return "provider_rejected"
    return "provider_failure"


def _normalize_response(
    document: dict[object, object],
    request: ModelProviderRequest,
) -> ModelProviderResponse:
    response_model = document.get("model")
    status = document.get("status")
    if not isinstance(response_model, str) or not isinstance(status, str):
        raise ModelProviderError("provider_failure")
    try:
        model_release = ModelReleaseIdentity(
            provider=OPENAI_PROVIDER,
            model_id=request.model_release.model_id,
            model_version=response_model,
        )
    except ValidationError as exc:
        raise ModelProviderError("provider_failure") from exc

    if status == "incomplete":
        details = document.get("incomplete_details")
        reason = details.get("reason") if isinstance(details, dict) else None
        if reason == "max_output_tokens":
            finish_reason: FinishReason = "length"
        elif reason == "content_filter":
            finish_reason = "content_filter"
        else:
            raise ModelProviderError("provider_failure")
        return ModelProviderResponse(
            output_json="",
            model_release=model_release,
            finish_reason=finish_reason,
        )
    if status != "completed" or document.get("error") is not None:
        raise ModelProviderError("provider_failure")

    output = document.get("output")
    if not isinstance(output, list):
        raise ModelProviderError("provider_failure")
    output_text: list[str] = []
    refused = False
    for item in output:
        if not isinstance(item, dict) or item.get("type") != "message":
            continue
        content = item.get("content")
        if not isinstance(content, list):
            raise ModelProviderError("provider_failure")
        for part in content:
            if not isinstance(part, dict):
                raise ModelProviderError("provider_failure")
            if part.get("type") == "refusal":
                refused = True
            elif part.get("type") == "output_text":
                text = part.get("text")
                if not isinstance(text, str):
                    raise ModelProviderError("provider_failure")
                output_text.append(text)
    if refused:
        return ModelProviderResponse(
            output_json="",
            model_release=model_release,
            finish_reason="content_filter",
        )
    serialized_output = "".join(output_text)
    if not serialized_output:
        raise ModelProviderError("provider_failure")
    return ModelProviderResponse(
        output_json=serialized_output,
        model_release=model_release,
        finish_reason="stop",
    )


__all__ = [
    "OPENAI_PROVIDER",
    "OPENAI_RESPONSES_URL",
    "OpenAIResponsesProvider",
    "openai_strict_output_schema",
]
