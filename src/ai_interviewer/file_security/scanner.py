"""Fail-closed ClamAV streaming malware scanner adapter."""

from __future__ import annotations

import asyncio
import hashlib
import re
import struct
from collections.abc import Awaitable, Callable
from contextlib import suppress
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Literal, Protocol, cast

ScanVerdict = Literal["clean", "infected"]
_MAX_RESPONSE_BYTES = 4_096
_STREAM_CHUNK_BYTES = 64 * 1024
_VERSION_PATTERN = re.compile(r"^ClamAV ([^/]+)/([^/]+)/(.+)$")


class MalwareScannerError(RuntimeError):
    """Scanning was unavailable or returned an untrusted response."""


@dataclass(frozen=True, slots=True)
class ScannerVersion:
    engine_version: str
    signature_version: str
    signature_date: datetime


@dataclass(frozen=True, slots=True)
class ScanResult:
    verdict: ScanVerdict
    version: ScannerVersion
    malware_signature_sha256: str | None = None


class MalwareScanner(Protocol):
    async def is_ready(self, *, now: datetime | None = None) -> bool: ...

    async def scan(self, content: bytes, *, now: datetime | None = None) -> ScanResult: ...


class ClamAVScanner:
    """Use clamd INSTREAM over a local socket or explicitly configured TCP endpoint."""

    def __init__(
        self,
        *,
        maximum_stream_bytes: int,
        maximum_signature_age: timedelta,
        timeout_seconds: float,
        unix_socket: Path | None = None,
        tcp_host: str | None = None,
        tcp_port: int = 3310,
    ) -> None:
        if (unix_socket is None) == (tcp_host is None):
            raise ValueError("exactly one ClamAV transport is required")
        self._maximum_stream_bytes = maximum_stream_bytes
        self._maximum_signature_age = maximum_signature_age
        self._timeout_seconds = timeout_seconds
        self._unix_socket = unix_socket
        self._tcp_host = tcp_host
        self._tcp_port = tcp_port

    async def is_ready(self, *, now: datetime | None = None) -> bool:
        try:
            pong = await self._command(b"zPING\0")
            version = await self._version()
            evaluated_at = now or datetime.now(UTC)
            return pong == "PONG" and self._is_signature_fresh(version, evaluated_at)
        except MalwareScannerError:
            return False

    async def scan(self, content: bytes, *, now: datetime | None = None) -> ScanResult:
        if not content or len(content) > self._maximum_stream_bytes:
            raise MalwareScannerError("scan content is empty or exceeds the configured limit")
        evaluated_at = now or datetime.now(UTC)
        version = await self._version()
        if not self._is_signature_fresh(version, evaluated_at):
            raise MalwareScannerError("malware signatures are stale")

        reader, writer = await self._connect()
        try:
            writer.write(b"zINSTREAM\0")
            for offset in range(0, len(content), _STREAM_CHUNK_BYTES):
                chunk = content[offset : offset + _STREAM_CHUNK_BYTES]
                writer.write(struct.pack("!I", len(chunk)))
                writer.write(chunk)
                await asyncio.wait_for(writer.drain(), timeout=self._timeout_seconds)
            writer.write(struct.pack("!I", 0))
            await asyncio.wait_for(writer.drain(), timeout=self._timeout_seconds)
            response = await self._read_response(reader)
        except (OSError, TimeoutError, asyncio.IncompleteReadError) as exc:
            raise MalwareScannerError("malware scan transport failed") from exc
        finally:
            writer.close()
            with suppress(OSError):
                await writer.wait_closed()

        if response == "stream: OK":
            return ScanResult(verdict="clean", version=version)
        if response.startswith("stream: ") and response.endswith(" FOUND"):
            signature = response[len("stream: ") : -len(" FOUND")]
            if not signature or len(signature) > 512:
                raise MalwareScannerError("malware scanner returned an invalid signature")
            return ScanResult(
                verdict="infected",
                version=version,
                malware_signature_sha256=hashlib.sha256(signature.encode()).hexdigest(),
            )
        raise MalwareScannerError("malware scanner returned an error or unknown verdict")

    async def _version(self) -> ScannerVersion:
        response = await self._command(b"zVERSION\0")
        match = _VERSION_PATTERN.fullmatch(response)
        if match is None:
            raise MalwareScannerError("malware scanner version response is malformed")
        try:
            signature_date = parsedate_to_datetime(match.group(3))
        except (TypeError, ValueError) as exc:
            raise MalwareScannerError("malware signature timestamp is malformed") from exc
        if signature_date.tzinfo is None:
            signature_date = signature_date.replace(tzinfo=UTC)
        return ScannerVersion(
            engine_version=match.group(1)[:64],
            signature_version=match.group(2)[:64],
            signature_date=signature_date.astimezone(UTC),
        )

    def _is_signature_fresh(self, version: ScannerVersion, now: datetime) -> bool:
        age = now - version.signature_date
        return timedelta(0) <= age <= self._maximum_signature_age

    async def _command(self, command: bytes) -> str:
        reader, writer = await self._connect()
        try:
            writer.write(command)
            await asyncio.wait_for(writer.drain(), timeout=self._timeout_seconds)
            return await self._read_response(reader)
        except (OSError, TimeoutError, asyncio.IncompleteReadError) as exc:
            raise MalwareScannerError("malware scanner command failed") from exc
        finally:
            writer.close()
            with suppress(OSError):
                await writer.wait_closed()

    async def _connect(self) -> tuple[asyncio.StreamReader, asyncio.StreamWriter]:
        try:
            if self._unix_socket is not None:
                unix_connector = getattr(asyncio, "open_unix_connection", None)
                if unix_connector is None:
                    raise MalwareScannerError("Unix sockets are unavailable on this platform")
                connector = cast(
                    Callable[..., Awaitable[tuple[asyncio.StreamReader, asyncio.StreamWriter]]],
                    unix_connector,
                )
                connection = connector(path=self._unix_socket)
            else:
                connection = asyncio.open_connection(host=self._tcp_host, port=self._tcp_port)
            return await asyncio.wait_for(connection, timeout=self._timeout_seconds)
        except (OSError, TimeoutError) as exc:
            raise MalwareScannerError("malware scanner is unavailable") from exc

    async def _read_response(self, reader: asyncio.StreamReader) -> str:
        try:
            payload = await asyncio.wait_for(
                reader.readuntil(b"\0"),
                timeout=self._timeout_seconds,
            )
        except (asyncio.LimitOverrunError, ValueError) as exc:
            raise MalwareScannerError("malware scanner response exceeded its limit") from exc
        if len(payload) > _MAX_RESPONSE_BYTES:
            raise MalwareScannerError("malware scanner response exceeded its limit")
        try:
            return payload[:-1].decode("utf-8")
        except UnicodeDecodeError as exc:
            raise MalwareScannerError("malware scanner response is not UTF-8") from exc
