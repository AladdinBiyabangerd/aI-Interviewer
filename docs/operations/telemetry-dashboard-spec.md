# Telemetry dashboard specification

## Global filters

Every view must filter by `deployment.environment.name`, `service.name`, and `service.version`. Production and staging are never combined by default. The source revision is available as `ai_interviewer.release.revision`. Dashboards must not add labels derived from logs, raw paths, request IDs, trace IDs, users, tasks, files, object keys, SQL, or exception text.

## Required panels

| Area | Panel | Source and grouping | Interpretation |
|---|---|---|---|
| HTTP | Request rate | count/rate of `http.server.request.duration`, grouped by `http.route` and `http.request.method` | Traffic volume by code-defined route template. |
| HTTP | Error share | duration count grouped by `http.response.status_code`; show 5xx share separately | Application/server failure proportion. 4xx is displayed but is not automatically a service failure. |
| HTTP | Latency | p50/p95/p99 of `http.server.request.duration`, grouped by route/method | Time to completed ASGI response in seconds. |
| HTTP | Saturation | max/current `http.server.active_requests`, grouped by method | Concurrent request pressure. |
| Dependencies | Outcome and latency | `ai_interviewer.dependency.operation.duration`, grouped by dependency/operation/outcome | Database, aggregate file-security, object-store, and scanner availability/latency. |
| PostgreSQL | Pool use | `ai_interviewer.database.pool.connections` (`state=used|idle`) over `ai_interviewer.database.pool.limit` (`type=base|overflow`) | Application-side connection saturation; no host, user, DSN, or SQL label. |
| File scanning | Scan outcomes | rate/increase of `ai_interviewer.file.scan.attempts`, grouped by `outcome=clean|infected|error` | Scanner workload and fail-closed scan errors. Infected is a security workflow result, not a platform outage by itself. |
| Deletion workers | State changes | rate/increase of `ai_interviewer.deletion.task.transitions`, grouped by `task.type` and `state` | File and processor worker throughput, retry, escalation, and completion. |
| Deletion queues | Backlog | `ai_interviewer.deletion.queue.tasks`, grouped by `task.type` and active `state` | Absolute durable work backlog sampled from PostgreSQL. |
| Deletion queues | Oldest age | `ai_interviewer.deletion.queue.oldest_age`, grouped by `task.type` and active `state` | Time since the oldest active task became available, based on database UTC time. |
| Measurement integrity | Operational snapshot attempts | rate/increase of `ai_interviewer.operational.snapshot.attempts`, grouped by `monitor.name` and `outcome` | Makes snapshot failures visible instead of silently reusing an old queue value. |
| Measurement integrity | Last successful snapshot age | `ai_interviewer.operational.snapshot.last_success_age`, grouped by `monitor.name` | Qualifies deletion queue panels; the series is absent until the first success. |
| Releases | Comparison | overlay request/dependency series by `service.version`; link traces by trace ID | Detect regressions introduced by a release without making release labels unbounded. |

Backend-specific rate, histogram-quantile, and exemplar syntax is selected with the monitoring provider. Panels must preserve the instrument/attribute contract above.

## Cardinality budget

| Attribute | Maximum source set |
|---|---|
| `http.request.method` | Nine standard methods plus `_OTHER` |
| `url.scheme` | `http`, `https`, `_OTHER` |
| `http.route` | Statically registered route templates plus `_unmatched` |
| `http.response.status_code` | Valid HTTP status integers |
| `ai_interviewer.request.population` | `product`, `operations`, `other` from an exact code-owned route set |
| dependency | `database`, `file_security`, `object_store`, `malware_scanner`, `other` |
| dependency operation | Fixed code allowlist plus `other` |
| outcome/state/type | Fixed enums defined by the telemetry module |
| `monitor.name` | `deletion_queues` |
| environment/release | One configured environment and release ID per running process |

Any proposed new attribute requires a privacy review, an explicit bounded value set, tests proving payload exclusion, and an update to ADR 0008. Trace IDs and request IDs are log/trace correlation fields, never metric attributes.

## SLI view

The API availability candidate view filters `ai_interviewer.request.population=product`; health and unknown routes are excluded. It displays total, non-5xx, 5xx, 4xx, and no-data state. The exact formulas, evidence requirements, and diagnostic/non-SLO boundary are defined in the [SLI measurement contract](../reliability/sli-measurement-contract.md).

## Gate boundary

This specification intentionally defines no availability target, latency target, error budget, alert threshold, pager route, or burn-rate window. Those require the 0D-C-B measured baseline and ownership approvals.
