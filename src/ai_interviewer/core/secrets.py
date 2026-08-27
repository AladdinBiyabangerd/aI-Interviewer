"""Bounded startup-only secret-file delivery.

Secret files are compatible with container and orchestrator mounts. Values are
loaded once during settings construction, never logged, and intentionally do
not support network lookups in the request path.
"""

from __future__ import annotations

import os
import stat
from pathlib import Path

_MAX_SECRET_BYTES = 65_536


class SecretFileError(ValueError):
    """A configured secret file is unsafe or cannot be read."""


def read_secret_file(path_value: str | Path, *, hosted: bool) -> str:
    """Read a small UTF-8 secret from a regular file with conservative checks."""
    path = Path(path_value)
    if hosted and not path.is_absolute():
        raise SecretFileError("hosted-environment secret-file paths must be absolute")

    try:
        resolved = path.resolve(strict=True)
        descriptor = os.open(resolved, os.O_RDONLY | getattr(os, "O_CLOEXEC", 0))
    except (OSError, RuntimeError) as exc:
        raise SecretFileError("secret file is unavailable") from exc

    try:
        metadata = os.fstat(descriptor)
        if not stat.S_ISREG(metadata.st_mode):
            raise SecretFileError("secret file must resolve to a regular file")
        if metadata.st_size > _MAX_SECRET_BYTES:
            raise SecretFileError("secret file exceeds the 65536-byte limit")
        if os.name != "nt":
            permissions = stat.S_IMODE(metadata.st_mode)
            if permissions & 0o007 or permissions & 0o020:
                raise SecretFileError(
                    "secret file must not be accessible by others or group-writable"
                )
        chunks: list[bytes] = []
        remaining = _MAX_SECRET_BYTES + 1
        while remaining > 0:
            chunk = os.read(descriptor, min(remaining, 8_192))
            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)
        payload = b"".join(chunks)
    except OSError as exc:
        raise SecretFileError("secret file could not be read") from exc
    finally:
        os.close(descriptor)

    if len(payload) > _MAX_SECRET_BYTES:
        raise SecretFileError("secret file exceeds the 65536-byte limit")
    try:
        value = payload.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise SecretFileError("secret file must contain valid UTF-8") from exc
    if value.endswith("\r\n"):
        value = value[:-2]
    elif value.endswith("\n"):
        value = value[:-1]
    if not value or "\x00" in value or value != value.strip():
        raise SecretFileError("secret file contains an empty or malformed value")
    return value
