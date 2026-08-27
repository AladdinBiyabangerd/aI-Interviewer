"""Safe, consistent HTTP problem responses."""

from collections.abc import Mapping
from typing import Any

from fastapi import Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse


def request_id_from(request: Request) -> str | None:
    """Return the correlation identifier installed by operational middleware."""
    return getattr(request.state, "request_id", None)


def problem_response(
    *,
    status: int,
    title: str,
    detail: str,
    request_id: str | None = None,
    errors: list[dict[str, str]] | None = None,
    headers: Mapping[str, str] | None = None,
) -> JSONResponse:
    """Build an RFC 9457-style response without leaking internal details."""
    content: dict[str, Any] = {
        "type": "about:blank",
        "title": title,
        "status": status,
        "detail": detail,
    }
    if request_id is not None:
        content["request_id"] = request_id
    if errors is not None:
        content["errors"] = errors

    return JSONResponse(
        status_code=status,
        content=content,
        media_type="application/problem+json",
        headers=headers,
    )


def validation_problem(request: Request, exc: RequestValidationError) -> JSONResponse:
    """Convert validation failures to a stable response with no echoed input values."""
    errors = [
        {
            "location": ".".join(str(part) for part in error["loc"]),
            "message": error["msg"],
            "code": error["type"],
        }
        for error in exc.errors()
    ]
    return problem_response(
        status=422,
        title="Request validation failed",
        detail="One or more request fields are invalid.",
        request_id=request_id_from(request),
        errors=errors,
    )
