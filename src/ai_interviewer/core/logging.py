"""Minimal structured logging with request correlation."""

import json
import logging
import logging.config
import re
from contextvars import ContextVar
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import UUID

from opentelemetry import trace

request_id_context: ContextVar[str | None] = ContextVar("request_id", default=None)

_SENSITIVE_PATTERNS = (
    re.compile(r"(?i)\bbearer\s+[a-z0-9._~+/=-]+"),
    re.compile(r"\beyJ[a-zA-Z0-9_-]+\.[a-zA-Z0-9_-]+\.[a-zA-Z0-9_-]+\b"),
    re.compile(r"(?i)\b(?:password|passwd|secret|token|authorization|api[_-]?key)\s*[:=]\s*\S+"),
    re.compile(r"(?i)\b(?:postgres(?:ql)?|https?)://\S+"),
    re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b"),
    re.compile(r"\b[A-Za-z0-9_+/=-]{40,}\b"),
)


def _safe_message(record: logging.LogRecord) -> str:
    if not record.name.startswith("ai_interviewer"):
        return "External component event"
    if record.args:
        return "Parameterized application log suppressed"
    message = str(record.msg).replace("\r", " ").replace("\n", " ")[:300]
    for pattern in _SENSITIVE_PATTERNS:
        message = pattern.sub("[REDACTED]", message)
    return message


def _canonical_request_id(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    try:
        return str(UUID(value))
    except ValueError:
        return None


def _exception_metadata(record: logging.LogRecord) -> dict[str, object]:
    if record.exc_info is None:
        return {}
    exception_type = record.exc_info[0]
    traceback = record.exc_info[2]
    frames: list[dict[str, object]] = []
    while traceback is not None and len(frames) < 8:
        code = traceback.tb_frame.f_code
        frames.append(
            {
                "file": Path(code.co_filename).name[:100],
                "function": code.co_name[:100],
                "line": traceback.tb_lineno,
            }
        )
        traceback = traceback.tb_next
    return {
        "exception_type": exception_type.__name__ if exception_type is not None else "Exception",
        "exception_frames": frames,
    }


class JsonFormatter(logging.Formatter):
    """Serialize operational records as one JSON object per line."""

    _optional_fields = (
        "method",
        "route",
        "status_code",
        "duration_ms",
        "release_id",
        "release_revision",
    )

    def format(self, record: logging.LogRecord) -> str:
        event: dict[str, Any] = {
            "timestamp": datetime.now(UTC)
            .isoformat(timespec="milliseconds")
            .replace("+00:00", "Z"),
            "level": record.levelname,
            "logger": record.name[:100],
            "message": _safe_message(record),
        }
        request_id = _canonical_request_id(
            getattr(record, "request_id", None) or request_id_context.get()
        )
        if request_id is not None:
            event["request_id"] = request_id

        span_context = trace.get_current_span().get_span_context()
        if span_context.is_valid:
            event["trace_id"] = format(span_context.trace_id, "032x")
            event["span_id"] = format(span_context.span_id, "016x")

        for field in self._optional_fields:
            value = getattr(record, field, None)
            if value is not None:
                event[field] = value

        event.update(_exception_metadata(record))

        return json.dumps(event, ensure_ascii=False, separators=(",", ":"))


def configure_logging(level: str) -> None:
    """Install a single process-wide structured logging policy."""
    logging.config.dictConfig(
        {
            "version": 1,
            "disable_existing_loggers": False,
            "formatters": {"json": {"()": "ai_interviewer.core.logging.JsonFormatter"}},
            "handlers": {
                "default": {
                    "class": "logging.StreamHandler",
                    "formatter": "json",
                    "stream": "ext://sys.stdout",
                }
            },
            "root": {"handlers": ["default"], "level": level},
            "loggers": {
                "uvicorn": {"handlers": ["default"], "level": level, "propagate": False},
                "uvicorn.error": {"handlers": ["default"], "level": level, "propagate": False},
                "uvicorn.access": {"handlers": [], "level": level, "propagate": False},
            },
        }
    )
