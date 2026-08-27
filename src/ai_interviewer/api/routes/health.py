"""Orchestrator-facing health contracts."""

import asyncio
import logging
from collections.abc import Awaitable, Callable
from typing import Literal, Protocol, cast

from fastapi import APIRouter, Request, Response, status
from pydantic import BaseModel, ConfigDict

from ai_interviewer.core.telemetry import TelemetryRuntime
from ai_interviewer.persistence.database import DatabaseRuntime

logger = logging.getLogger("ai_interviewer.health")

router = APIRouter(prefix="/health", tags=["operations"])


class FileSecurityHealth(Protocol):
    async def is_ready(self) -> bool: ...


class LiveResponse(BaseModel):
    """Liveness means the process can serve HTTP."""

    model_config = ConfigDict(extra="forbid")

    status: Literal["ok"] = "ok"


class ReadyResponse(BaseModel):
    """Readiness reports all currently required runtime dependencies."""

    model_config = ConfigDict(extra="forbid")

    status: Literal["ready", "not_ready"]
    checks: dict[str, Literal["up", "down"]]


@router.get("/live", response_model=LiveResponse, summary="Process liveness")
async def live() -> LiveResponse:
    return LiveResponse()


@router.get(
    "/ready",
    response_model=ReadyResponse,
    summary="Service readiness",
    responses={status.HTTP_503_SERVICE_UNAVAILABLE: {"model": ReadyResponse}},
)
async def ready(request: Request, response: Response) -> ReadyResponse:
    database = cast(DatabaseRuntime, request.app.state.database)
    file_security = cast(FileSecurityHealth, request.app.state.file_security)
    telemetry = cast(TelemetryRuntime, request.app.state.telemetry)

    async def dependency_ready(name: str, check: Callable[[], Awaitable[bool]]) -> bool:
        with telemetry.dependency_operation(
            dependency=name,
            operation="readiness",
        ) as observation:
            try:
                available = await check()
            except Exception:
                observation.set_outcome("error")
                logger.exception("Dependency readiness check raised unexpectedly")
                return False
            if not available:
                observation.set_outcome("unavailable")
            return available

    database_ready, file_security_ready = await asyncio.gather(
        dependency_ready("database", database.is_ready),
        dependency_ready("file_security", file_security.is_ready),
    )
    checks: dict[str, Literal["up", "down"]] = {
        "runtime": "up",
        "database": "up" if database_ready else "down",
        "file_security": "up" if file_security_ready else "down",
    }
    if database_ready and file_security_ready:
        return ReadyResponse(status="ready", checks=checks)

    response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return ReadyResponse(status="not_ready", checks=checks)
