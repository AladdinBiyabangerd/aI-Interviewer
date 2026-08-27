# Phase 0D-B completion record

- **Status:** Complete within the bounded telemetry-baseline scope
- **Completed:** 2026-08-24
- **Current stop:** Before Phase 0D-C reliability objectives and response

## Delivered

- Vendor-neutral OpenTelemetry 1.44 metrics/traces with application-owned providers and OTLP/HTTP protobuf export.
- Typed hosted configuration requiring telemetry, a credential-free collector origin, HTTPS or loopback transport, nonzero trace sampling, bounded timeouts/intervals, and valid span batch/queue relationships.
- Stable HTTP duration and active-request instruments with published explicit duration buckets, W3C parent propagation, route-template-only names, bounded methods/schemes/status/error types, and no raw target/header/body capture.
- Release/environment/service/process resource correlation and JSON log correlation through valid trace/span IDs and canonical UUID request IDs.
- Strict structured-log policy: third-party and parameterized messages are suppressed, known credential/URL/email/token patterns are redacted, and exceptions expose only type plus bounded frame metadata.
- Dependency latency/outcome spans and metrics for database/file readiness, object storage, and malware scanning; database pool use/limit gauges; scan-result counters; file/processor deletion transition counters; and absolute durable deletion queue/oldest-age gauges sampled from PostgreSQL database time.
- Background exporter and operational-monitor failures are contained and cannot fail application requests or durable work. Export timeout, span queue/batch/attribute/event/link limits, and monitor intervals are bounded.
- Payload-blind decorators preserve the existing object-store/scanner interfaces and file/privacy state machines.
- ADR 0008, telemetry operations runbook, dashboard/panel contract, cardinality budget, and initial retention/access policy.

## Verification evidence

- `248` tests pass on Python 3.12, including the then-current real-PostgreSQL integration suite (`28` collected integration tests). Branch-aware coverage is `95.27%` and passes the enforced 95% gate.
- Ruff, format checks, and strict mypy pass for `46` source files.
- Dependency lock/compatibility checks pass and `pip-audit` reports no known vulnerable Python package.
- Tests prove remote W3C parent continuity; low-cardinality route/method normalization; absence of raw path/query/header/content/object-key/exception text; trace/log correlation; exporter exception isolation; persistent observable gauges; database pool callbacks; scan/deletion signals; and real PostgreSQL file/processor queue snapshots.
- A real local OTLP/HTTP collector stub receives non-empty protobuf requests on the fixed `/v1/traces` and `/v1/metrics` endpoints.
- The `ai-interviewer-platform:phase0d-b` runtime image passed the release-identity, embedded schema (`20260824_0004`), and non-root (`10001:10001`) contract checks. Its local Linux/amd64 manifest is `sha256:a23eea42c7d8731d6d82774ae83a72906958f6c322be93a39f25f253a30d5ab4`.
- The release-image smoke test passed with a read-only root filesystem, all Linux capabilities dropped, `no-new-privileges`, exact database readiness, and no appearance of a query-string canary in application logs.
- Trivy reports `0` HIGH/CRITICAL vulnerabilities in both `ai-interviewer-platform:phase0d-b` and `ai-interviewer-postgres:17.11-secure`. CycloneDX generation produced a valid `91`-component local rehearsal SBOM; the CI contract retains the release SBOM for each source revision.

## Deliberately deferred

- No monitoring vendor, OpenTelemetry Collector deployment, public metrics endpoint, cloud dashboard resource, or provider credential was invented before provider selection.
- No numeric SLO, error budget, availability/latency target, burn-rate alert, pager route, or on-call exercise is claimed. Those are Phase 0D-C and require measured staging baselines plus named owners.
- No rate limit, quota, cost ceiling, overload policy, or load test is implemented; those remain 0D-D.
- No staging or production rollout, telemetry-backend access provisioning, regional retention enforcement, PITR/failover exercise, or public-readiness claim is made; those remain 0D-E.
- No user-facing upload, parser, CV/JD processing, LLM, interview engine, Knowledge Base/RAG, source ingestion, voice, or video was introduced.

## Next gate

Phase 0D-C will establish measured SLIs, approved SLO/error budgets, actionable multi-window alerts, ownership/escalation, and exercised dependency/file-security incident procedures. Work stops here pending explicit authorization.
