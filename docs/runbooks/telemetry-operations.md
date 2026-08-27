# Telemetry operations runbook

## Data boundary

Telemetry is operational metadata, not a copy of candidate data. It must never contain raw URL paths or query strings, headers, tokens, cookies, OIDC claims, account/file/task IDs, object keys, CV/JD bytes or text, interview content, SQL, DSNs, processor locators, request/response bodies, exception messages, or local variable values.

Allowed values are documented in the [dashboard specification](../operations/telemetry-dashboard-spec.md). A backend, collector processor, or agent may drop additional fields but must not enrich signals with client IP, geolocation, user identity, or payload data.

## Collector contract

1. The application sends OTLP/HTTP protobuf to the configured collector origin at `/v1/traces` and `/v1/metrics`.
2. Use a loopback collector/agent when practical. A non-loopback hosted endpoint must use HTTPS. The collector owns backend credentials and provider routing; do not configure authorization headers or credentials in the application.
3. Restrict application egress to the reviewed collector. Restrict collector ingestion to workload identities/network origins for this environment.
4. Configure collector memory/batch limits and backend retry/storage independently. Collector unavailability must not cause application restart or readiness failure.
5. Monitor collector dropped spans/metrics, queue saturation, export errors, certificate expiry, and backend rejection from the platform layer in 0D-C/0D-E.

## Measurement integrity

- The operational database snapshot emits an attempt outcome and, after its first success, a monotonic last-success age. A queue panel without a current successful snapshot is stale evidence and must not be interpreted as an empty or healthy queue.
- Product SLI calculations include only `ai_interviewer.request.population=product`. Health, unmatched, documentation, and unreviewed routes remain outside the denominator.
- A missing denominator is `no data`. Missing signals, collector gaps, restarts, and counter resets must be visible in baseline evidence and cannot be converted into successful events.
- Follow the [SLI measurement contract](../reliability/sli-measurement-contract.md) before exporting a baseline or proposing an objective.

## Baseline evidence evaluation

Use only a reviewed backend query/export adapter. Preserve the raw aggregate export and query definition in the approved evidence store and put only their SHA-256 digests in the bounded JSON evidence. Do not hand-edit observed counts.

```powershell
uv run ai-interviewer-baseline schema
uv run ai-interviewer-baseline evaluate <evidence.json>
```

Exit `0` permits human review but does not approve an objective. Exit `2` means the file is invalid; exit `3` means measurement is incomplete. Treat both as a failed 0D-C-B evidence gate. Follow the [baseline evidence format](../reliability/baseline-evidence-format.md) for retention, fields, and remediation.

## Initial retention and access policy

- Metrics: maximum 30 days online.
- Sampled traces: maximum 7 days online.
- Application operational logs: maximum 30 days online.
- An approved security incident hold may extend only the selected evidence, with owner, reason, expiry, and access review recorded.
- Production access is read-only for the on-call engineering group and security responders. Export, administrative mutation, and retention-policy changes require a separately audited privileged role.
- Candidate support, product analytics, model training, sales, and general staff receive no direct telemetry-backend access.
- Database `audit_events` and legal/privacy evidence follow their own stored retention rules and are not copied into telemetry.

Provider provisioning in 0D-E must encode these maximums, regional/storage requirements, encryption, access roles, audit logging, deletion, and backup behavior before production traffic.

## Verification

For each release:

1. Run the automated telemetry tests, including W3C parent propagation, route-template cardinality, redaction corpus, real OTLP protobuf export, exporter exceptions, database pool callbacks, and real PostgreSQL queue snapshots.
2. In staging, send only synthetic requests and confirm the required dashboard panels populate for the exact release ID/source revision.
3. Search the backend for the synthetic secret canaries placed in test query/header/path/exception inputs. The expected result is zero matches.
4. Stop or reject collector export and confirm API requests, file operations, readiness, and worker transactions continue; only bounded telemetry warnings may appear.
5. Confirm no public metrics route exists and that collector/backend endpoints are inaccessible from the public network.
6. Stop the operational snapshot dependency, confirm `outcome=error` increases while the last-success age grows, then recover it and confirm a new success refreshes the gauge.

## Incident handling

- Suspected telemetry data leak: stop downstream export at the collector, preserve minimal access evidence, revoke affected backend credentials, restrict access, identify the introducing release/instrument, and follow privacy/security incident handling. Do not erase evidence outside the approved incident process.
- Export outage: keep application traffic running, restore collector/backend service, inspect bounded queue/drop counters, and record the observability gap. Do not turn telemetry failure into application unavailability.
- Cardinality explosion: disable or drop the offending attribute at the collector, identify the code release, and issue a reviewed instrumentation fix. Never increase backend limits before verifying the field cannot contain identifiers or content.
- Trace/log correlation failure: verify release resources, W3C propagation, and JSON `trace_id`/`span_id`; do not add raw request metadata as a workaround.
