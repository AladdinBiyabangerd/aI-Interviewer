"""Low-cardinality OpenTelemetry signals with strict payload exclusion."""

from __future__ import annotations

import logging
from collections.abc import Callable, Iterator, Mapping, Sequence
from contextlib import AbstractContextManager, contextmanager
from dataclasses import dataclass
from threading import Lock
from time import monotonic, perf_counter
from typing import Any, Literal, Protocol
from uuid import uuid4

from opentelemetry import metrics
from opentelemetry.exporter.otlp.proto.http.metric_exporter import OTLPMetricExporter
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.metrics import Counter, Histogram, Observation, UpDownCounter
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import (
    MetricExporter,
    MetricExportResult,
    MetricReader,
    MetricsData,
    PeriodicExportingMetricReader,
)
from opentelemetry.sdk.metrics.view import ExplicitBucketHistogramAggregation, View
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import ReadableSpan, SpanLimits, TracerProvider
from opentelemetry.sdk.trace.export import (
    BatchSpanProcessor,
    SpanExporter,
    SpanExportResult,
)
from opentelemetry.sdk.trace.sampling import ParentBased, TraceIdRatioBased
from opentelemetry.trace import Span, SpanKind, Status, StatusCode, Tracer
from opentelemetry.trace.propagation.tracecontext import TraceContextTextMapPropagator

from ai_interviewer.core.config import Settings
from ai_interviewer.core.reliability import (
    HTTP_DURATION_BUCKETS_SECONDS,
    classify_http_request,
)

logger = logging.getLogger("ai_interviewer.telemetry")

DependencyOutcome = Literal["success", "unavailable", "error"]
DeletionTaskType = Literal["file", "processor"]
DeletionTaskState = Literal["pending", "processing", "retry", "escalated", "completed"]
ScanOutcome = Literal["clean", "infected", "error"]
OperationalSnapshotOutcome = Literal["success", "error"]

_HTTP_METHODS = frozenset(
    {"CONNECT", "DELETE", "GET", "HEAD", "OPTIONS", "PATCH", "POST", "PUT", "TRACE"}
)
_DEPENDENCY_OPERATIONS: Mapping[str, frozenset[str]] = {
    "database": frozenset({"readiness", "operational_snapshot"}),
    "file_security": frozenset({"readiness"}),
    "object_store": frozenset(
        {
            "readiness",
            "put_quarantined",
            "read_verified",
            "promote_clean",
            "delete_all_versions",
        }
    ),
    "malware_scanner": frozenset({"readiness", "scan"}),
}
_DEPENDENCY_BUCKETS = (0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10, 30)
_QUEUE_STATES: tuple[DeletionTaskState, ...] = (
    "pending",
    "processing",
    "retry",
    "escalated",
)
_QUEUE_TASK_TYPES: tuple[DeletionTaskType, ...] = ("file", "processor")


def normalize_http_method(method: str) -> str:
    normalized = method.upper()
    return normalized if normalized in _HTTP_METHODS else "_OTHER"


def normalize_route(route: object, root_path: object = "") -> str:
    """Return a route template, never the raw request target."""
    path = getattr(route, "path", None)
    if not isinstance(path, str) or not path.startswith("/") or len(path) > 200:
        return "_unmatched"
    if not isinstance(root_path, str) or (
        root_path and (not root_path.startswith("/") or len(root_path) > 100)
    ):
        return "_unmatched"
    combined = f"{root_path.rstrip('/')}{path}"
    return combined if len(combined) <= 200 else "_unmatched"


@dataclass(frozen=True, slots=True)
class DatabasePoolSnapshot:
    idle: int
    used: int
    base_limit: int
    overflow_limit: int


@dataclass(frozen=True, slots=True)
class DeletionQueueSnapshot:
    task_type: DeletionTaskType
    state: DeletionTaskState
    count: int
    oldest_age_seconds: float


class DependencyObservation(Protocol):
    def set_outcome(self, outcome: DependencyOutcome) -> None: ...


class HttpObservation(Protocol):
    def finish(self, *, route: str, status_code: int) -> None: ...


class TelemetryRuntime(Protocol):
    enabled: bool

    def http_server(
        self,
        *,
        method: str,
        scheme: str,
        trace_headers: Mapping[str, str],
    ) -> AbstractContextManager[HttpObservation]: ...

    def dependency_operation(
        self, *, dependency: str, operation: str
    ) -> AbstractContextManager[DependencyObservation]: ...

    def register_database_pool(self, callback: Callable[[], DatabasePoolSnapshot]) -> None: ...

    def record_scan(self, outcome: ScanOutcome) -> None: ...

    def record_deletion_transition(
        self, task_type: DeletionTaskType, state: DeletionTaskState, count: int = 1
    ) -> None: ...

    def record_deletion_snapshot(self, snapshots: Sequence[DeletionQueueSnapshot]) -> None: ...

    def record_operational_snapshot(self, outcome: OperationalSnapshotOutcome) -> None: ...

    def force_flush(self, timeout_millis: int = 5_000) -> bool: ...

    def shutdown(self) -> None: ...


class _DisabledDependencyObservation:
    def set_outcome(self, outcome: DependencyOutcome) -> None:
        del outcome


class _DisabledHttpObservation:
    def finish(self, *, route: str, status_code: int) -> None:
        del route, status_code


class DisabledTelemetry:
    """No-allocation telemetry implementation for disabled local environments."""

    enabled = False

    @contextmanager
    def http_server(
        self,
        *,
        method: str,
        scheme: str,
        trace_headers: Mapping[str, str],
    ) -> Iterator[HttpObservation]:
        del method, scheme, trace_headers
        yield _DisabledHttpObservation()

    @contextmanager
    def dependency_operation(
        self, *, dependency: str, operation: str
    ) -> Iterator[DependencyObservation]:
        del dependency, operation
        yield _DisabledDependencyObservation()

    def register_database_pool(self, callback: Callable[[], DatabasePoolSnapshot]) -> None:
        del callback

    def record_scan(self, outcome: ScanOutcome) -> None:
        del outcome

    def record_deletion_transition(
        self, task_type: DeletionTaskType, state: DeletionTaskState, count: int = 1
    ) -> None:
        del task_type, state, count

    def record_deletion_snapshot(self, snapshots: Sequence[DeletionQueueSnapshot]) -> None:
        del snapshots

    def record_operational_snapshot(self, outcome: OperationalSnapshotOutcome) -> None:
        del outcome

    def force_flush(self, timeout_millis: int = 5_000) -> bool:
        del timeout_millis
        return True

    def shutdown(self) -> None:
        return None


class FailureIsolatedSpanExporter(SpanExporter):
    """Convert exporter faults into a bounded operational warning."""

    def __init__(self, delegate: SpanExporter) -> None:
        self._delegate = delegate

    def export(self, spans: Sequence[ReadableSpan]) -> SpanExportResult:
        try:
            return self._delegate.export(spans)
        except Exception:
            logger.warning("Telemetry span export failed")
            return SpanExportResult.FAILURE

    def shutdown(self) -> None:
        try:
            self._delegate.shutdown()
        except Exception:
            logger.warning("Telemetry span exporter shutdown failed")

    def force_flush(self, timeout_millis: int = 30_000) -> bool:
        try:
            return self._delegate.force_flush(timeout_millis)
        except Exception:
            logger.warning("Telemetry span exporter flush failed")
            return False


class FailureIsolatedMetricExporter(MetricExporter):
    """Prevent metrics transport faults from crossing into application work."""

    def __init__(self, delegate: MetricExporter) -> None:
        super().__init__()
        self._delegate = delegate

    def export(
        self,
        metrics_data: MetricsData,
        timeout_millis: float = 10_000,
        **kwargs: Any,
    ) -> MetricExportResult:
        try:
            return self._delegate.export(metrics_data, timeout_millis, **kwargs)
        except Exception:
            logger.warning("Telemetry metric export failed")
            return MetricExportResult.FAILURE

    def shutdown(self, timeout_millis: float = 30_000, **kwargs: Any) -> None:
        try:
            self._delegate.shutdown(timeout_millis, **kwargs)
        except Exception:
            logger.warning("Telemetry metric exporter shutdown failed")

    def force_flush(self, timeout_millis: float = 10_000) -> bool:
        try:
            return self._delegate.force_flush(timeout_millis)
        except Exception:
            logger.warning("Telemetry metric exporter flush failed")
            return False


class _HttpObservation:
    def __init__(
        self,
        *,
        span: Span,
        duration: Histogram,
        active: UpDownCounter,
        active_attributes: dict[str, str],
        method: str,
        scheme: str,
    ) -> None:
        self._span = span
        self._duration = duration
        self._active = active
        self._active_attributes = active_attributes
        self._method = method
        self._scheme = scheme
        self._started_at = perf_counter()
        self._finished = False

    def finish(self, *, route: str, status_code: int) -> None:
        if self._finished:
            return
        self._finished = True
        safe_route = route if route.startswith("/") and len(route) <= 200 else "_unmatched"
        attributes: dict[str, str | int] = {
            "http.request.method": self._method,
            "url.scheme": self._scheme,
            "http.route": safe_route,
            "http.response.status_code": status_code,
            "ai_interviewer.request.population": classify_http_request(safe_route),
        }
        if status_code >= 500:
            attributes["error.type"] = str(status_code)
            self._span.set_status(Status(StatusCode.ERROR))
        self._span.update_name(f"{self._method} {safe_route}")
        self._span.set_attributes(attributes)
        self._duration.record(perf_counter() - self._started_at, attributes)
        self._active.add(-1, self._active_attributes)


class _DependencyObservation:
    def __init__(self, *, span: Span, duration: Histogram, attributes: dict[str, str]) -> None:
        self._span = span
        self._duration = duration
        self._attributes = attributes
        self._started_at = perf_counter()
        self._outcome: DependencyOutcome = "success"

    def set_outcome(self, outcome: DependencyOutcome) -> None:
        self._outcome = outcome

    def finish(self) -> None:
        attributes = {**self._attributes, "ai_interviewer.dependency.outcome": self._outcome}
        if self._outcome != "success":
            self._span.set_status(Status(StatusCode.ERROR))
        self._span.set_attributes(attributes)
        self._duration.record(perf_counter() - self._started_at, attributes)


class OpenTelemetryRuntime:
    """Application-owned providers; no process-global mutation or payload capture."""

    enabled = True

    def __init__(self, tracer_provider: TracerProvider, meter_provider: MeterProvider) -> None:
        self._tracer_provider = tracer_provider
        self._meter_provider = meter_provider
        self._tracer: Tracer = tracer_provider.get_tracer("ai_interviewer", "0.1.0")
        meter = meter_provider.get_meter("ai_interviewer", "0.1.0")
        self._http_duration: Histogram = meter.create_histogram(
            "http.server.request.duration",
            unit="s",
            description="Duration of HTTP server requests.",
        )
        self._http_active: UpDownCounter = meter.create_up_down_counter(
            "http.server.active_requests",
            unit="{request}",
            description="Number of active HTTP server requests.",
        )
        self._dependency_duration: Histogram = meter.create_histogram(
            "ai_interviewer.dependency.operation.duration",
            unit="s",
            description="Duration of bounded platform dependency operations.",
        )
        self._scan_count: Counter = meter.create_counter(
            "ai_interviewer.file.scan.attempts",
            unit="{attempt}",
            description="File malware-scan attempts by bounded outcome.",
        )
        self._deletion_transitions: Counter = meter.create_counter(
            "ai_interviewer.deletion.task.transitions",
            unit="{transition}",
            description="Durable deletion task state transitions.",
        )
        self._operational_snapshot_attempts: Counter = meter.create_counter(
            "ai_interviewer.operational.snapshot.attempts",
            unit="{attempt}",
            description="Operational database snapshot attempts by bounded outcome.",
        )
        self._operational_snapshot_lock = Lock()
        self._operational_snapshot_last_success: float | None = None

        def snapshot_age_callback(_: metrics.CallbackOptions) -> Iterator[Observation]:
            with self._operational_snapshot_lock:
                last_success = self._operational_snapshot_last_success
            if last_success is not None:
                yield Observation(
                    max(monotonic() - last_success, 0),
                    {"monitor.name": "deletion_queues"},
                )

        self._operational_snapshot_age = meter.create_observable_gauge(
            "ai_interviewer.operational.snapshot.last_success_age",
            callbacks=[snapshot_age_callback],
            unit="s",
            description="Age of the last successful operational database snapshot.",
        )
        self._deletion_snapshot_lock = Lock()
        self._deletion_snapshots: dict[
            tuple[DeletionTaskType, DeletionTaskState], DeletionQueueSnapshot
        ] = {
            (task_type, state): DeletionQueueSnapshot(task_type, state, 0, 0)
            for task_type in _QUEUE_TASK_TYPES
            for state in _QUEUE_STATES
        }

        def queue_count_callback(_: metrics.CallbackOptions) -> Iterator[Observation]:
            with self._deletion_snapshot_lock:
                snapshots = tuple(self._deletion_snapshots.values())
            for snapshot in snapshots:
                yield Observation(
                    snapshot.count,
                    {"task.type": snapshot.task_type, "state": snapshot.state},
                )

        def queue_age_callback(_: metrics.CallbackOptions) -> Iterator[Observation]:
            with self._deletion_snapshot_lock:
                snapshots = tuple(self._deletion_snapshots.values())
            for snapshot in snapshots:
                yield Observation(
                    snapshot.oldest_age_seconds,
                    {"task.type": snapshot.task_type, "state": snapshot.state},
                )

        self._deletion_queue_count = meter.create_observable_gauge(
            "ai_interviewer.deletion.queue.tasks",
            callbacks=[queue_count_callback],
            unit="{task}",
            description="Current durable deletion task count.",
        )
        self._deletion_queue_age = meter.create_observable_gauge(
            "ai_interviewer.deletion.queue.oldest_age",
            callbacks=[queue_age_callback],
            unit="s",
            description="Age of the oldest durable deletion task.",
        )
        self._meter = meter
        self._database_pool_registered = False

    @contextmanager
    def http_server(
        self,
        *,
        method: str,
        scheme: str,
        trace_headers: Mapping[str, str],
    ) -> Iterator[HttpObservation]:
        safe_method = normalize_http_method(method)
        safe_scheme = scheme if scheme in {"http", "https"} else "_OTHER"
        active_attributes = {
            "http.request.method": safe_method,
            "url.scheme": safe_scheme,
        }
        self._http_active.add(1, active_attributes)
        parent_context = TraceContextTextMapPropagator().extract(carrier=trace_headers)
        with self._tracer.start_as_current_span(
            f"HTTP {safe_method}",
            context=parent_context,
            kind=SpanKind.SERVER,
            attributes=active_attributes,
            record_exception=False,
            set_status_on_exception=False,
        ) as span:
            observation = _HttpObservation(
                span=span,
                duration=self._http_duration,
                active=self._http_active,
                active_attributes=active_attributes,
                method=safe_method,
                scheme=safe_scheme,
            )
            try:
                yield observation
            except Exception:
                observation.finish(route="_unmatched", status_code=500)
                raise
            finally:
                observation.finish(route="_unmatched", status_code=500)

    @contextmanager
    def dependency_operation(
        self, *, dependency: str, operation: str
    ) -> Iterator[DependencyObservation]:
        safe_dependency = dependency if dependency in _DEPENDENCY_OPERATIONS else "other"
        allowed_operations = _DEPENDENCY_OPERATIONS.get(safe_dependency, frozenset())
        safe_operation = operation if operation in allowed_operations else "other"
        attributes = {
            "ai_interviewer.dependency.name": safe_dependency,
            "ai_interviewer.dependency.operation": safe_operation,
        }
        with self._tracer.start_as_current_span(
            f"{safe_dependency} {safe_operation}",
            kind=SpanKind.CLIENT,
            attributes=attributes,
            record_exception=False,
            set_status_on_exception=False,
        ) as span:
            observation = _DependencyObservation(
                span=span,
                duration=self._dependency_duration,
                attributes=attributes,
            )
            try:
                yield observation
            except Exception:
                observation.set_outcome("error")
                raise
            finally:
                observation.finish()

    def register_database_pool(self, callback: Callable[[], DatabasePoolSnapshot]) -> None:
        if self._database_pool_registered:
            raise RuntimeError("database pool telemetry is already registered")
        self._database_pool_registered = True

        def connection_callback(_: metrics.CallbackOptions) -> Iterator[Observation]:
            try:
                snapshot = callback()
            except Exception:
                logger.warning("Database pool telemetry collection failed")
                return
            yield Observation(snapshot.idle, {"state": "idle"})
            yield Observation(snapshot.used, {"state": "used"})

        def limit_callback(_: metrics.CallbackOptions) -> Iterator[Observation]:
            try:
                snapshot = callback()
            except Exception:
                return
            yield Observation(snapshot.base_limit, {"type": "base"})
            yield Observation(snapshot.overflow_limit, {"type": "overflow"})

        self._meter.create_observable_gauge(
            "ai_interviewer.database.pool.connections",
            callbacks=[connection_callback],
            unit="{connection}",
            description="Current application database pool connections.",
        )
        self._meter.create_observable_gauge(
            "ai_interviewer.database.pool.limit",
            callbacks=[limit_callback],
            unit="{connection}",
            description="Configured application database pool limits.",
        )

    def record_scan(self, outcome: ScanOutcome) -> None:
        safe_outcome = outcome if outcome in {"clean", "infected", "error"} else "error"
        self._scan_count.add(1, {"outcome": safe_outcome})

    def record_deletion_transition(
        self, task_type: DeletionTaskType, state: DeletionTaskState, count: int = 1
    ) -> None:
        if count < 1:
            return
        safe_type = task_type if task_type in {"file", "processor"} else "file"
        safe_state = (
            state
            if state in {"pending", "processing", "retry", "escalated", "completed"}
            else "escalated"
        )
        self._deletion_transitions.add(
            count,
            {"task.type": safe_type, "state": safe_state},
        )

    def record_deletion_snapshot(self, snapshots: Sequence[DeletionQueueSnapshot]) -> None:
        with self._deletion_snapshot_lock:
            for snapshot in snapshots:
                self._deletion_snapshots[(snapshot.task_type, snapshot.state)] = (
                    DeletionQueueSnapshot(
                        task_type=snapshot.task_type,
                        state=snapshot.state,
                        count=max(snapshot.count, 0),
                        oldest_age_seconds=max(snapshot.oldest_age_seconds, 0),
                    )
                )

    def record_operational_snapshot(self, outcome: OperationalSnapshotOutcome) -> None:
        safe_outcome = outcome if outcome in {"success", "error"} else "error"
        self._operational_snapshot_attempts.add(
            1,
            {"monitor.name": "deletion_queues", "outcome": safe_outcome},
        )
        if safe_outcome == "success":
            with self._operational_snapshot_lock:
                self._operational_snapshot_last_success = monotonic()

    def force_flush(self, timeout_millis: int = 5_000) -> bool:
        metrics_flushed = self._meter_provider.force_flush(timeout_millis)
        traces_flushed = self._tracer_provider.force_flush(timeout_millis)
        return metrics_flushed and traces_flushed

    def shutdown(self) -> None:
        try:
            self._meter_provider.shutdown()
        except Exception:
            logger.warning("Telemetry meter provider shutdown failed")
        try:
            self._tracer_provider.shutdown()
        except Exception:
            logger.warning("Telemetry tracer provider shutdown failed")


def _views() -> list[View]:
    return [
        View(
            instrument_name="http.server.request.duration",
            aggregation=ExplicitBucketHistogramAggregation(
                boundaries=HTTP_DURATION_BUCKETS_SECONDS
            ),
        ),
        View(
            instrument_name="ai_interviewer.dependency.operation.duration",
            aggregation=ExplicitBucketHistogramAggregation(boundaries=_DEPENDENCY_BUCKETS),
        ),
    ]


def build_telemetry(
    settings: Settings,
    *,
    span_exporter: SpanExporter | None = None,
    metric_reader: MetricReader | None = None,
) -> TelemetryRuntime:
    """Build isolated providers or a no-op runtime when explicitly disabled."""
    if not settings.telemetry_enabled:
        return DisabledTelemetry()
    endpoint = settings.telemetry_otlp_endpoint
    if endpoint is None:
        raise RuntimeError("telemetry enabled without an OTLP endpoint")
    timeout = float(settings.telemetry_export_timeout_seconds)
    resolved_span_exporter = span_exporter or OTLPSpanExporter(
        endpoint=f"{endpoint}/v1/traces",
        timeout=timeout,
    )
    resolved_metric_reader = metric_reader or PeriodicExportingMetricReader(
        FailureIsolatedMetricExporter(
            OTLPMetricExporter(endpoint=f"{endpoint}/v1/metrics", timeout=timeout)
        ),
        export_interval_millis=settings.telemetry_export_interval_seconds * 1_000,
        export_timeout_millis=settings.telemetry_export_timeout_seconds * 1_000,
    )
    resource = Resource.create(
        {
            "service.name": "ai-interviewer-api",
            "service.version": settings.release_id,
            "service.instance.id": str(uuid4()),
            "deployment.environment.name": settings.environment,
            "ai_interviewer.release.revision": settings.release_revision,
        }
    )
    meter_provider = MeterProvider(
        metric_readers=[resolved_metric_reader],
        resource=resource,
        shutdown_on_exit=False,
        views=_views(),
    )
    tracer_provider = TracerProvider(
        sampler=ParentBased(TraceIdRatioBased(settings.telemetry_trace_sample_ratio)),
        resource=resource,
        shutdown_on_exit=False,
        span_limits=SpanLimits(
            max_span_attributes=16,
            max_events=0,
            max_links=4,
            max_attribute_length=200,
        ),
        meter_provider=meter_provider,
    )
    tracer_provider.add_span_processor(
        BatchSpanProcessor(
            FailureIsolatedSpanExporter(resolved_span_exporter),
            max_queue_size=settings.telemetry_span_queue_size,
            schedule_delay_millis=settings.telemetry_span_schedule_delay_ms,
            max_export_batch_size=settings.telemetry_span_batch_size,
            export_timeout_millis=settings.telemetry_export_timeout_seconds * 1_000,
            meter_provider=meter_provider,
        )
    )
    return OpenTelemetryRuntime(tracer_provider, meter_provider)
