"""Payload-blind telemetry decorators for file-security dependencies."""

from datetime import datetime

from ai_interviewer.core.telemetry import TelemetryRuntime
from ai_interviewer.file_security.object_store import SecureObjectStore, StoredObject
from ai_interviewer.file_security.scanner import MalwareScanner, ScanResult


class InstrumentedObjectStore:
    def __init__(self, delegate: SecureObjectStore, telemetry: TelemetryRuntime) -> None:
        self._delegate = delegate
        self._telemetry = telemetry

    async def is_ready(self) -> bool:
        with self._telemetry.dependency_operation(
            dependency="object_store", operation="readiness"
        ) as observation:
            ready = await self._delegate.is_ready()
            if not ready:
                observation.set_outcome("unavailable")
            return ready

    async def put_quarantined(
        self,
        *,
        key: str,
        content: bytes,
        content_type: str,
        content_sha256: str,
    ) -> StoredObject:
        with self._telemetry.dependency_operation(
            dependency="object_store", operation="put_quarantined"
        ):
            return await self._delegate.put_quarantined(
                key=key,
                content=content,
                content_type=content_type,
                content_sha256=content_sha256,
            )

    async def read_verified(
        self,
        *,
        key: str,
        version_id: str,
        expected_sha256: str,
        maximum_bytes: int,
    ) -> bytes:
        with self._telemetry.dependency_operation(
            dependency="object_store", operation="read_verified"
        ):
            return await self._delegate.read_verified(
                key=key,
                version_id=version_id,
                expected_sha256=expected_sha256,
                maximum_bytes=maximum_bytes,
            )

    async def promote_clean(
        self,
        *,
        source_key: str,
        source_version_id: str,
        destination_key: str,
        content_type: str,
        content_sha256: str,
    ) -> StoredObject:
        with self._telemetry.dependency_operation(
            dependency="object_store", operation="promote_clean"
        ):
            return await self._delegate.promote_clean(
                source_key=source_key,
                source_version_id=source_version_id,
                destination_key=destination_key,
                content_type=content_type,
                content_sha256=content_sha256,
            )

    async def delete_all_versions(self, *, key: str) -> int:
        with self._telemetry.dependency_operation(
            dependency="object_store", operation="delete_all_versions"
        ):
            return await self._delegate.delete_all_versions(key=key)


class InstrumentedMalwareScanner:
    def __init__(self, delegate: MalwareScanner, telemetry: TelemetryRuntime) -> None:
        self._delegate = delegate
        self._telemetry = telemetry

    async def is_ready(self, *, now: datetime | None = None) -> bool:
        with self._telemetry.dependency_operation(
            dependency="malware_scanner", operation="readiness"
        ) as observation:
            ready = await self._delegate.is_ready(now=now)
            if not ready:
                observation.set_outcome("unavailable")
            return ready

    async def scan(self, content: bytes, *, now: datetime | None = None) -> ScanResult:
        try:
            with self._telemetry.dependency_operation(
                dependency="malware_scanner", operation="scan"
            ):
                result = await self._delegate.scan(content, now=now)
        except Exception:
            self._telemetry.record_scan("error")
            raise
        self._telemetry.record_scan(result.verdict)
        return result
