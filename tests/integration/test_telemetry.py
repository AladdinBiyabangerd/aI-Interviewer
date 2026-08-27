from typing import cast

import pytest
from opentelemetry.sdk.metrics.export import InMemoryMetricReader
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from ai_interviewer.core.config import Settings
from ai_interviewer.core.operational_monitor import OperationalMonitor
from ai_interviewer.core.telemetry import OpenTelemetryRuntime, build_telemetry
from ai_interviewer.persistence.database import Database

pytestmark = pytest.mark.integration


@pytest.mark.asyncio
async def test_operational_monitor_reads_durable_queue_snapshots(database: Database) -> None:
    metric_reader = InMemoryMetricReader()
    runtime = cast(
        OpenTelemetryRuntime,
        build_telemetry(
            Settings(
                _env_file=None,
                environment="test",
                telemetry_enabled=True,
                telemetry_otlp_endpoint="http://127.0.0.1:4318",
                telemetry_trace_sample_ratio=1,
            ),
            span_exporter=InMemorySpanExporter(),
            metric_reader=metric_reader,
        ),
    )
    monitor = OperationalMonitor(database=database, telemetry=runtime, interval_seconds=5)

    await monitor.collect_once()
    assert runtime.force_flush()
    data = metric_reader.get_metrics_data()

    assert data is not None
    metrics = {
        metric.name: metric
        for resource_metrics in data.resource_metrics
        for scope_metrics in resource_metrics.scope_metrics
        for metric in scope_metrics.metrics
    }
    assert "ai_interviewer.deletion.queue.tasks" in metrics
    assert "ai_interviewer.deletion.queue.oldest_age" in metrics
    assert "ai_interviewer.operational.snapshot.attempts" in metrics
    assert "ai_interviewer.operational.snapshot.last_success_age" in metrics
    queue_points = metrics["ai_interviewer.deletion.queue.tasks"].data.data_points
    assert len(queue_points) == 8
    assert all(point.value == 0 for point in queue_points)
    snapshot_attempts = metrics["ai_interviewer.operational.snapshot.attempts"].data.data_points
    assert len(snapshot_attempts) == 1
    assert snapshot_attempts[0].value == 1
    assert snapshot_attempts[0].attributes == {
        "monitor.name": "deletion_queues",
        "outcome": "success",
    }
    runtime.shutdown()
