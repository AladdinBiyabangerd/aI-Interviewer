# ADR 0008: Payload-blind OpenTelemetry baseline

- **Status:** Accepted
- **Date:** 2026-08-24

## Context

The release foundation needs diagnosable HTTP, PostgreSQL, object-storage, malware-scanner, and deletion-worker failures before external traffic. Telemetry can itself become a privacy leak or availability dependency if it captures raw targets, headers, content, identifiers, SQL, exception messages, or performs synchronous network export in request paths. No monitoring vendor or deployment provider has been selected.

OpenTelemetry Python traces and metrics are stable while its log signal remains in development. The HTTP semantic conventions define stable server duration and active-request instruments, route-template attribution, and seconds as the duration unit. OTLP preserves the OpenTelemetry data model and permits a collector to route signals to a later approved backend.

## Decision

1. Use application-owned OpenTelemetry Python providers for metrics and traces. Do not replace process-global providers, which keeps application factories and tests isolated.
2. Export OTLP protobuf over HTTP to fixed `/v1/traces` and `/v1/metrics` endpoints. Hosted non-loopback export requires HTTPS; loopback permits an agent/sidecar. Exporter authentication, fan-out, retry storage, and vendor credentials belong at the collector boundary.
3. Use bounded batch span export and periodic metric export. Queue, batch, interval, timeout, sample ratio, span attribute/event/link limits, and string length are typed configuration. Transport exceptions are converted to bounded warnings and cannot fail request, readiness, file, or worker operations.
4. Use parent-based ratio sampling. Resource identity contains fixed service name, release ID, source revision, random process instance ID, and deployment environment.
5. Record the stable `http.server.request.duration` histogram with the published explicit buckets and `http.server.active_requests`. Attributes are limited to normalized HTTP method, scheme, route template, response status, and bounded error type. Raw path, URL, host, query, client address, headers, and body are forbidden.
6. Accept W3C `traceparent`/`tracestate` only for incoming trace continuity. No bearer, baggage, or arbitrary request metadata is copied into a span.
7. Emit custom low-cardinality instruments for dependency duration/outcome, database pool use/limits, malware-scan outcome, deletion-task transitions, and absolute file/processor deletion queue count/oldest age. Durable queue snapshots use database time and never expose task, owner, processor, or object identifiers.
8. Keep application logs as one JSON object per stdout line. Only application-owned constant messages are retained; parameterized application messages and third-party messages are suppressed. Known credential/URL/email/token patterns are redacted. Exceptions expose type and bounded frame basename/function/line only, never exception text, locals, or full paths. Valid trace/span IDs and canonical UUID request IDs provide correlation.
9. Client request IDs must be canonical UUIDs; other values are replaced. This prevents an untrusted correlation header from becoming a free-form log channel.
10. The provider-neutral dashboard specification defines panels and cardinality budgets, not alert thresholds. SLOs, error budgets, paging policy, and exercised response belong to 0D-C.

## Consequences

- Operators gain request rate/error/duration, concurrency, dependency outcome/latency, pool saturation, scan outcomes, and deletion backlog signals without candidate content.
- Logs remain available when OTLP is unavailable, and OTLP failure remains isolated from application work. Collector health still requires platform monitoring in 0D-C/0D-E.
- No public `/metrics` endpoint or vendor SDK is introduced.
- Auto-instrumentation of FastAPI, SQLAlchemy, boto, or HTTP clients is deliberately rejected because their default attributes can include raw URLs, SQL statements, headers, or provider coordinates. New dependency spans must pass the same explicit allowlist.
- Exact backend queries and dashboard provisioning are adapted at provider selection, but instrument names, units, labels, panel intent, and retention/access rules are fixed now.

## References

- [OpenTelemetry Python status and SDK](https://opentelemetry.io/docs/languages/python/)
- [OpenTelemetry Python exporters](https://opentelemetry.io/docs/languages/python/exporters/)
- [HTTP metric semantic conventions](https://opentelemetry.io/docs/specs/semconv/http/http-metrics/)
- [OpenTelemetry SDK environment-variable specification](https://opentelemetry.io/docs/specs/otel/configuration/sdk-environment-variables/)
