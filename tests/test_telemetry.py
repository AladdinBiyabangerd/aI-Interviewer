import asyncio
import json
import logging
import sys
from collections.abc import Sequence
from datetime import UTC, datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Thread
from typing import Any, ClassVar, cast

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from opentelemetry.sdk.metrics.export import (
    InMemoryMetricReader,
    MetricExporter,
    MetricExportResult,
    MetricsData,
)
from opentelemetry.sdk.trace import ReadableSpan
from opentelemetry.sdk.trace.export import (
    SpanExporter,
    SpanExportResult,
)
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from ai_interviewer.core.config import Settings
from ai_interviewer.core.logging import JsonFormatter
from ai_interviewer.core.operational_monitor import OperationalMonitor
from ai_interviewer.core.reliability import (
    OPERATIONAL_HTTP_ROUTES,
    PRODUCT_HTTP_ROUTES,
    classify_http_request,
)
from ai_interviewer.core.telemetry import (
    DatabasePoolSnapshot,
    DeletionQueueSnapshot,
    DisabledTelemetry,
    FailureIsolatedMetricExporter,
    FailureIsolatedSpanExporter,
    OpenTelemetryRuntime,
    build_telemetry,
    normalize_http_method,
    normalize_route,
)
from ai_interviewer.file_security.object_store import StoredObject
from ai_interviewer.file_security.scanner import ScannerVersion, ScanResult
from ai_interviewer.file_security.telemetry import (
    InstrumentedMalwareScanner,
    InstrumentedObjectStore,
)
from ai_interviewer.main import create_app
from ai_interviewer.persistence.database import Database
from tests.fakes import ReadyDatabase


def _runtime() -> tuple[OpenTelemetryRuntime, InMemorySpanExporter, InMemoryMetricReader]:
    span_exporter = InMemorySpanExporter()
    metric_reader = InMemoryMetricReader()
    settings = Settings(
        _env_file=None,
        environment="test",
        telemetry_enabled=True,
        telemetry_otlp_endpoint="http://127.0.0.1:4318",
        telemetry_trace_sample_ratio=1,
    )
    runtime = build_telemetry(
        settings,
        span_exporter=span_exporter,
        metric_reader=metric_reader,
    )
    return cast(OpenTelemetryRuntime, runtime), span_exporter, metric_reader


def _metric_names(data: MetricsData) -> set[str]:
    return {
        metric.name
        for resource_metrics in data.resource_metrics
        for scope_metrics in resource_metrics.scope_metrics
        for metric in scope_metrics.metrics
    }


def test_http_telemetry_uses_route_templates_and_propagates_trace_context() -> None:
    runtime, span_exporter, metric_reader = _runtime()
    settings = Settings(
        _env_file=None,
        environment="test",
        allowed_hosts=("testserver",),
        telemetry_enabled=True,
        telemetry_otlp_endpoint="http://127.0.0.1:4318",
        telemetry_trace_sample_ratio=1,
    )
    app: FastAPI = create_app(
        settings,
        database=ReadyDatabase(),
        telemetry=runtime,
    )

    @app.get("/test/items/{item_id}")
    async def item(item_id: str) -> dict[str, str]:
        return {"item_id": item_id}

    trace_id = "0af7651916cd43dd8448eb211c80319c"
    parent_span_id = "b7ad6b7169203331"
    secret_item = "candidate-secret-identifier"
    with TestClient(app) as client:
        response = client.get(
            f"/test/items/{secret_item}?token=must-not-appear",
            headers={
                "traceparent": f"00-{trace_id}-{parent_span_id}-01",
                "authorization": "Bearer must-not-appear",
            },
        )
        assert response.status_code == 200
        assert runtime.force_flush()
        metrics_data = metric_reader.get_metrics_data()

    spans = span_exporter.get_finished_spans()
    server_span = next(span for span in spans if span.name.startswith("GET "))
    assert format(server_span.context.trace_id, "032x") == trace_id
    assert server_span.parent is not None
    assert format(server_span.parent.span_id, "016x") == parent_span_id
    assert server_span.name == "GET /test/items/{item_id}"
    assert server_span.attributes is not None
    assert server_span.attributes["http.route"] == "/test/items/{item_id}"
    assert server_span.attributes["ai_interviewer.request.population"] == "other"
    serialized_spans = repr(spans)
    assert secret_item not in serialized_spans
    assert "must-not-appear" not in serialized_spans
    assert metrics_data is not None
    assert {
        "http.server.request.duration",
        "http.server.active_requests",
    }.issubset(_metric_names(metrics_data))


def test_dependency_pool_scan_and_deletion_metrics_are_bounded() -> None:
    runtime, span_exporter, metric_reader = _runtime()
    runtime.register_database_pool(
        lambda: DatabasePoolSnapshot(idle=3, used=2, base_limit=5, overflow_limit=5)
    )
    with runtime.dependency_operation(
        dependency="object_store", operation="readiness"
    ) as observation:
        observation.set_outcome("unavailable")
    runtime.record_scan("clean")
    runtime.record_scan("infected")
    runtime.record_deletion_transition("file", "retry", 2)
    runtime.record_deletion_snapshot(
        [
            DeletionQueueSnapshot(
                task_type="file",
                state="pending",
                count=4,
                oldest_age_seconds=12.5,
            )
        ]
    )
    runtime.record_operational_snapshot("success")

    assert runtime.force_flush()
    metrics_data = metric_reader.get_metrics_data()

    assert metrics_data is not None
    assert {
        "ai_interviewer.dependency.operation.duration",
        "ai_interviewer.database.pool.connections",
        "ai_interviewer.database.pool.limit",
        "ai_interviewer.file.scan.attempts",
        "ai_interviewer.deletion.task.transitions",
        "ai_interviewer.deletion.queue.tasks",
        "ai_interviewer.deletion.queue.oldest_age",
        "ai_interviewer.operational.snapshot.attempts",
        "ai_interviewer.operational.snapshot.last_success_age",
    }.issubset(_metric_names(metrics_data))
    dependency_span = next(
        span for span in span_exporter.get_finished_spans() if span.name == "object_store readiness"
    )
    assert dependency_span.attributes is not None
    assert dependency_span.attributes["ai_interviewer.dependency.outcome"] == "unavailable"
    assert len(dependency_span.attributes) == 3
    runtime.shutdown()


def test_json_logging_redacts_content_and_correlates_trace_ids() -> None:
    runtime, _, _ = _runtime()
    formatter = JsonFormatter()
    with runtime.http_server(method="GET", scheme="https", trace_headers={}) as observation:
        try:
            raise RuntimeError("database password=top-secret candidate@example.com")
        except RuntimeError:
            record = logging.LogRecord(
                name="ai_interviewer.test",
                level=logging.ERROR,
                pathname=__file__,
                lineno=1,
                msg="Bearer top-secret https://user:password@example.com/private",
                args=(),
                exc_info=sys.exc_info(),
            )
        document = json.loads(formatter.format(record))
        observation.finish(route="/safe/{id}", status_code=500)

    serialized = json.dumps(document)
    runtime.shutdown()
    assert "top-secret" not in serialized
    assert "candidate@example.com" not in serialized
    assert "password@example.com" not in serialized
    assert document["exception_type"] == "RuntimeError"
    assert document["exception_frames"]
    assert len(document["trace_id"]) == 32
    assert len(document["span_id"]) == 16

    external = logging.LogRecord(
        name="third_party.client",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg="connection to https://user:secret@example.com failed",
        args=(),
        exc_info=None,
    )
    assert json.loads(formatter.format(external))["message"] == "External component event"


class _RaisingSpanExporter(SpanExporter):
    def export(self, spans: Sequence[ReadableSpan]) -> SpanExportResult:
        del spans
        raise RuntimeError("secret span exporter detail")

    def shutdown(self) -> None:
        raise RuntimeError("secret span shutdown detail")

    def force_flush(self, timeout_millis: int = 30_000) -> bool:
        del timeout_millis
        raise RuntimeError("secret span flush detail")


class _RaisingMetricExporter(MetricExporter):
    def export(
        self,
        metrics_data: MetricsData,
        timeout_millis: float = 10_000,
        **kwargs: Any,
    ) -> MetricExportResult:
        del metrics_data, timeout_millis, kwargs
        raise RuntimeError("secret metric exporter detail")

    def shutdown(self, timeout_millis: float = 30_000, **kwargs: Any) -> None:
        del timeout_millis, kwargs
        raise RuntimeError("secret metric shutdown detail")

    def force_flush(self, timeout_millis: float = 10_000) -> bool:
        del timeout_millis
        raise RuntimeError("secret metric flush detail")


def test_exporter_failures_are_isolated_from_application_work() -> None:
    spans = FailureIsolatedSpanExporter(_RaisingSpanExporter())
    metrics = FailureIsolatedMetricExporter(_RaisingMetricExporter())

    assert spans.export(()) is SpanExportResult.FAILURE
    assert spans.force_flush() is False
    spans.shutdown()
    assert metrics.export(cast(MetricsData, object())) is MetricExportResult.FAILURE
    assert metrics.force_flush() is False
    metrics.shutdown()


@pytest.mark.parametrize(
    ("method", "expected"),
    [("get", "GET"), ("CUSTOM-CANDIDATE-ID", "_OTHER")],
)
def test_http_method_cardinality_is_bounded(method: str, expected: str) -> None:
    assert normalize_http_method(method) == expected


def test_route_normalization_never_falls_back_to_raw_input() -> None:
    assert normalize_route(None) == "_unmatched"
    assert normalize_route(object()) == "_unmatched"

    class Route:
        path = "/items/{item_id}"

    assert normalize_route(Route(), "/api/v1") == "/api/v1/items/{item_id}"
    assert normalize_route(Route(), "untrusted") == "_unmatched"


def test_every_registered_api_route_has_an_explicit_sli_population(
    test_settings: Settings,
) -> None:
    app = create_app(test_settings, database=ReadyDatabase())
    registered_api_routes = {path for path in app.openapi()["paths"] if path.startswith("/api/v1/")}

    assert PRODUCT_HTTP_ROUTES.isdisjoint(OPERATIONAL_HTTP_ROUTES)
    assert registered_api_routes == PRODUCT_HTTP_ROUTES | OPERATIONAL_HTTP_ROUTES
    assert all(classify_http_request(route) == "product" for route in PRODUCT_HTTP_ROUTES)
    assert all(classify_http_request(route) == "operations" for route in OPERATIONAL_HTTP_ROUTES)
    assert classify_http_request("/api/v1/candidate/secret-id") == "other"


def test_disabled_telemetry_contract_is_complete() -> None:
    telemetry = DisabledTelemetry()
    with telemetry.http_server(method="GET", scheme="http", trace_headers={}) as request:
        request.finish(route="/ignored", status_code=200)
    with telemetry.dependency_operation(dependency="database", operation="readiness") as dependency:
        dependency.set_outcome("success")
    telemetry.register_database_pool(lambda: DatabasePoolSnapshot(0, 0, 0, 0))
    telemetry.record_scan("clean")
    telemetry.record_deletion_transition("file", "pending")
    telemetry.record_deletion_snapshot(())
    telemetry.record_operational_snapshot("success")
    assert telemetry.force_flush(1)
    telemetry.shutdown()


def test_telemetry_internal_failure_branches_remain_bounded() -> None:
    runtime, _, _ = _runtime()
    with (
        pytest.raises(RuntimeError, match="request failure"),
        runtime.http_server(method="UNBOUNDED", scheme="ftp", trace_headers={}),
    ):
        raise RuntimeError("request failure")

    def failed_pool() -> DatabasePoolSnapshot:
        raise RuntimeError("pool secret detail")

    runtime.register_database_pool(failed_pool)
    with pytest.raises(RuntimeError, match="already registered"):
        runtime.register_database_pool(failed_pool)
    runtime.record_deletion_transition("file", "pending", 0)
    assert runtime.force_flush()
    runtime.shutdown()

    invalid_settings = Settings(
        _env_file=None,
        telemetry_enabled=True,
        telemetry_otlp_endpoint="http://127.0.0.1:4318",
    ).model_copy(update={"telemetry_otlp_endpoint": None})
    with pytest.raises(RuntimeError, match="without an OTLP endpoint"):
        build_telemetry(invalid_settings)


@pytest.mark.asyncio
async def test_operational_snapshot_health_is_explicit_and_fail_closed() -> None:
    runtime, _, metric_reader = _runtime()
    failing_monitor = OperationalMonitor(
        database=cast(Database, object()),
        telemetry=runtime,
        interval_seconds=5,
    )

    with pytest.raises(AttributeError):
        await failing_monitor.collect_once()
    assert runtime.force_flush()
    failed_data = metric_reader.get_metrics_data()
    assert failed_data is not None
    assert "ai_interviewer.operational.snapshot.last_success_age" not in _metric_names(failed_data)

    runtime.record_operational_snapshot("success")
    assert runtime.force_flush()
    recovered_data = metric_reader.get_metrics_data()
    assert recovered_data is not None
    metrics = {
        metric.name: metric
        for resource_metrics in recovered_data.resource_metrics
        for scope_metrics in resource_metrics.scope_metrics
        for metric in scope_metrics.metrics
    }
    attempts = metrics["ai_interviewer.operational.snapshot.attempts"].data.data_points
    assert {point.attributes["outcome"] for point in attempts} == {"error", "success"}
    assert all(point.attributes["monitor.name"] == "deletion_queues" for point in attempts)
    age_points = metrics["ai_interviewer.operational.snapshot.last_success_age"].data.data_points
    assert len(age_points) == 1
    assert age_points[0].value >= 0
    assert age_points[0].attributes == {"monitor.name": "deletion_queues"}
    runtime.shutdown()


class _CollectorHandler(BaseHTTPRequestHandler):
    received: ClassVar[list[tuple[str, str, bytes]]] = []

    def do_POST(self) -> None:
        content_length = int(self.headers.get("content-length", "0"))
        body = self.rfile.read(content_length)
        type(self).received.append((self.path, self.headers.get("content-type", ""), body))
        self.send_response(200)
        self.end_headers()

    def log_message(self, format: str, *args: object) -> None:
        del format, args


def test_real_otlp_http_export_reaches_bounded_signal_endpoints() -> None:
    _CollectorHandler.received.clear()
    collector = ThreadingHTTPServer(("127.0.0.1", 0), _CollectorHandler)
    thread = Thread(target=collector.serve_forever, daemon=True)
    thread.start()
    runtime = build_telemetry(
        Settings(
            _env_file=None,
            environment="test",
            telemetry_enabled=True,
            telemetry_otlp_endpoint=f"http://127.0.0.1:{collector.server_port}",
            telemetry_trace_sample_ratio=1,
            telemetry_export_timeout_seconds=2,
        )
    )
    try:
        with runtime.http_server(method="GET", scheme="http", trace_headers={}) as request:
            request.finish(route="/export-test", status_code=200)
        assert runtime.force_flush(2_000)
    finally:
        runtime.shutdown()
        collector.shutdown()
        collector.server_close()
        thread.join(timeout=2)

    paths = {path for path, _, _ in _CollectorHandler.received}
    assert {"/v1/traces", "/v1/metrics"}.issubset(paths)
    assert all(
        content_type == "application/x-protobuf"
        for _, content_type, _ in _CollectorHandler.received
    )
    assert all(body for _, _, body in _CollectorHandler.received)


class _ObjectStore:
    async def is_ready(self) -> bool:
        return False

    async def put_quarantined(
        self,
        *,
        key: str,
        content: bytes,
        content_type: str,
        content_sha256: str,
    ) -> StoredObject:
        del content, content_type
        return StoredObject(key, "quarantine-version", content_sha256, 7)

    async def read_verified(
        self,
        *,
        key: str,
        version_id: str,
        expected_sha256: str,
        maximum_bytes: int,
    ) -> bytes:
        del key, version_id, expected_sha256, maximum_bytes
        return b"content"

    async def promote_clean(
        self,
        *,
        source_key: str,
        source_version_id: str,
        destination_key: str,
        content_type: str,
        content_sha256: str,
    ) -> StoredObject:
        del source_key, source_version_id, content_type
        return StoredObject(destination_key, "released-version", content_sha256, 7)

    async def delete_all_versions(self, *, key: str) -> int:
        del key
        return 2


class _Scanner:
    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail

    async def is_ready(self, *, now: datetime | None = None) -> bool:
        del now
        return False

    async def scan(self, content: bytes, *, now: datetime | None = None) -> ScanResult:
        del content, now
        if self.fail:
            raise RuntimeError("scanner secret detail")
        return ScanResult(
            verdict="clean",
            version=ScannerVersion("engine", "signature", datetime.now(UTC)),
        )


@pytest.mark.asyncio
async def test_file_dependency_decorators_capture_only_operation_metadata() -> None:
    runtime, span_exporter, _ = _runtime()
    store = InstrumentedObjectStore(_ObjectStore(), runtime)
    scanner = InstrumentedMalwareScanner(_Scanner(), runtime)

    assert await store.is_ready() is False
    stored = await store.put_quarantined(
        key="opaque-secret-key",
        content=b"candidate content",
        content_type="text/plain",
        content_sha256="a" * 64,
    )
    assert stored.version_id == "quarantine-version"
    assert (
        await store.read_verified(
            key=stored.key,
            version_id=stored.version_id,
            expected_sha256=stored.content_sha256,
            maximum_bytes=10,
        )
        == b"content"
    )
    promoted = await store.promote_clean(
        source_key=stored.key,
        source_version_id=stored.version_id,
        destination_key="released-secret-key",
        content_type="text/plain",
        content_sha256=stored.content_sha256,
    )
    assert await store.delete_all_versions(key=promoted.key) == 2
    assert await scanner.is_ready() is False
    assert (await scanner.scan(b"candidate content")).verdict == "clean"
    with pytest.raises(RuntimeError, match="scanner secret detail"):
        await InstrumentedMalwareScanner(_Scanner(fail=True), runtime).scan(b"secret")
    assert runtime.force_flush()

    serialized = repr(span_exporter.get_finished_spans())
    runtime.shutdown()
    assert "candidate content" not in serialized
    assert "opaque-secret-key" not in serialized
    assert "released-secret-key" not in serialized
    assert "scanner secret detail" not in serialized


@pytest.mark.asyncio
async def test_operational_monitor_lifecycle_is_idempotent_and_bounded(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runtime, _, _ = _runtime()
    monitor = OperationalMonitor(
        database=cast(Database, object()),
        telemetry=runtime,
        interval_seconds=5,
    )
    collected = asyncio.Event()

    async def collect() -> None:
        collected.set()

    monkeypatch.setattr(monitor, "collect_once", collect)
    monitor.start()
    with pytest.raises(RuntimeError, match="already started"):
        monitor.start()
    await asyncio.wait_for(collected.wait(), timeout=1)
    await monitor.stop()
    await monitor.stop()
    runtime.shutdown()
