"""Request correlation, safe failures, security headers, and access metadata."""

import logging
from time import perf_counter
from uuid import UUID, uuid4

from starlette.datastructures import Headers, MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from ai_interviewer.api.errors import problem_response
from ai_interviewer.core.config import Environment
from ai_interviewer.core.logging import request_id_context
from ai_interviewer.core.telemetry import TelemetryRuntime, normalize_route

logger = logging.getLogger("ai_interviewer.http")


def _request_id(headers: Headers) -> str:
    supplied = headers.get("x-request-id", "")
    try:
        return str(UUID(supplied))
    except ValueError:
        pass
    return str(uuid4())


class OperationalMiddleware:
    """Apply the operational HTTP contract without buffering request/response bodies."""

    def __init__(
        self,
        app: ASGIApp,
        environment: Environment,
        telemetry: TelemetryRuntime,
    ) -> None:
        self.app = app
        self.environment = environment
        self.telemetry = telemetry

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        request_id = _request_id(Headers(scope=scope))
        scope.setdefault("state", {})["request_id"] = request_id
        context_token = request_id_context.set(request_id)
        started_at = perf_counter()
        status_code = 500
        response_started = False

        async def send_with_headers(message: Message) -> None:
            nonlocal response_started, status_code
            if message["type"] == "http.response.start":
                response_started = True
                status_code = int(message["status"])
                headers = MutableHeaders(scope=message)
                headers["x-request-id"] = request_id
                headers["x-content-type-options"] = "nosniff"
                headers["x-frame-options"] = "DENY"
                headers["referrer-policy"] = "no-referrer"
                headers["permissions-policy"] = "camera=(), microphone=(), geolocation=()"
                if self.environment in {"staging", "production"}:
                    headers["strict-transport-security"] = "max-age=31536000; includeSubDomains"
            await send(message)

        headers = Headers(scope=scope)
        trace_headers = {
            name: value
            for name in ("traceparent", "tracestate")
            if (value := headers.get(name)) is not None
        }
        with self.telemetry.http_server(
            method=scope["method"],
            scheme=scope.get("scheme", "http"),
            trace_headers=trace_headers,
        ) as observation:
            try:
                await self.app(scope, receive, send_with_headers)
            except Exception:
                logger.exception("Unhandled request exception")
                if response_started:
                    raise
                response = problem_response(
                    status=500,
                    title="Internal server error",
                    detail="The request could not be completed.",
                    request_id=request_id,
                )
                await response(scope, receive, send_with_headers)
            finally:
                route = normalize_route(scope.get("route"), scope.get("root_path", ""))
                observation.finish(route=route, status_code=status_code)
                duration_ms = round((perf_counter() - started_at) * 1000, 2)
                logger.info(
                    "Request completed",
                    extra={
                        "method": scope["method"],
                        "route": route,
                        "status_code": status_code,
                        "duration_ms": duration_ms,
                    },
                )
                request_id_context.reset(context_token)
