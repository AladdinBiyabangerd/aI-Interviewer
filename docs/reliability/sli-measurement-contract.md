# Phase 0D-C-A SLI measurement contract

## Status and boundary

This contract is approved for collecting and reviewing staging measurements. It defines no SLO target, error budget, pager threshold, notification destination, SLA, or production promise. The product route population now includes the Phase 1A-A preparation-target API in addition to identity/privacy foundations, but it still lacks the document and interview journey. Under [ADR 0010](../adr/0010-feature-stable-mvp-before-hosted-reliability-baseline.md), live 28-day collection is deferred until the text MVP route/contract surface is feature-stable; it remains a mandatory pre-production gate.

## Required cohort

Every calculation must filter exactly one `service.name=ai-interviewer-api`, `deployment.environment.name=staging`, `service.version`, and `ai_interviewer.release.revision`. Releases may be compared side by side, but their counters and histograms must not be merged before resets and temporality are handled by the selected backend.

The reviewed HTTP population is emitted as `ai_interviewer.request.population`:

- `product`: the exact route templates in `core/reliability.py`; these are eligible for API SLIs.
- `operations`: liveness and readiness routes; diagnose the platform but never improve the product denominator.
- `other`: unmatched, documentation, test, or not-yet-reviewed routes; excluded fail-closed.

Methods, routes, status codes, resource identity, and metric temporality must be present. Raw paths, IDs, queries, headers, bodies, or log-derived dimensions remain forbidden.

## Indicator definitions

| ID | Source | Exact calculation | Interpretation and limitation |
|---|---|---|---|
| `api-request-availability` | count of `http.server.request.duration` with `population=product` | `good / total`, where `bad` is status 500-599 and `good = total - bad`; zero total is `no data` | Server-side proxy for whether an eligible API request completed without a server failure. 4xx remains good service behavior; it must be shown separately for product/auth diagnostics. |
| `api-request-latency-distribution` | buckets/count of the same histogram and population | report p50, p95, p99 and bucket counts for all eligible requests, plus the non-5xx subset; do not average percentiles | Baseline evidence only. It becomes a latency SLI only after 0D-C-B approves one or more user-relevant good-event thresholds that align with published buckets. |
| `dependency-operation-success` | count of `ai_interviewer.dependency.operation.duration` by dependency, operation, and outcome | `success / (success + unavailable + error)`; zero total is `no data` | Diagnostic by fixed operation. It cannot be combined across operations or substituted for user availability. |
| `scan-execution-success` | increase of `ai_interviewer.file.scan.attempts` | `(clean + infected) / (clean + infected + error)`; zero total is `no data` | Measures whether the scanner produced a conclusive verdict. `infected` is a correct fail-closed result, not platform failure. |
| `deletion-work-health` | deletion transitions, queue tasks, and oldest age | report counts/age by exact task type and state; separately report retry, escalation, and completion increases | Diagnostic until legal/vendor deletion deadlines and workload expectations are approved. No generic queue-age target is invented. |
| `operational-snapshot-integrity` | `ai_interviewer.operational.snapshot.attempts` and `.last_success_age` | report success/error attempts and last-success age; absence before first success is `no data`, not age zero | Qualifies deletion-queue evidence. A stale or failing snapshot invalidates claims based on the last exported queue values. |
| `database-pool-saturation` | used/idle connections and base/overflow limits | report peak used connections and used divided by total configured capacity | Diagnostic capacity evidence only; a protection threshold belongs to 0D-D load/capacity work. |

## Baseline evidence gate for 0D-C-B

A proposed objective may be reviewed only after all of the following exist:

1. One continuous 28-day staging window, plus daily and weekly summaries, using synthetic data only.
2. Start/end UTC timestamps, exact release IDs/revisions, collector/backend version, export interval, histogram temporality, and immutable query/export references.
3. Total/good/bad event counts rather than percentages alone; histogram bucket counts and bounds rather than screenshots alone.
4. Every deployment, process restart, counter reset, missing interval, collector rejection, clock issue, query change, and known test incident identified. A gap is never silently treated as a good event.
5. Per-route and aggregate product views. Low traffic is explicitly reported; it is not hidden by merging health probes into the denominator.
6. Confirmation that sensitive canaries are absent and only the Phase 0D-B allowlist/cardinality is present.
7. Product, engineering, and operations reviewers assess user relevance, defensibility, staffing, and response consequences. Their real identities, approval date, and review date are recorded in the approved 0D-C-B artifact.

No outage or event is excluded after observation merely to improve a result. A future scope exclusion must be prospective, written, reviewed, reproducible in queries, and tied to user impact.

The release-owned [baseline evidence format and evaluator](baseline-evidence-format.md) enforces the provider-neutral portion of this gate. Its `eligible_for_review` result means only that evidence is structurally complete enough for human review; it is never an SLO approval.

## Change control

- A route addition fails the route-population regression test until classified.
- An indicator/query change starts a new contract version and restarts the evidence window unless reviewers prove comparability.
- A metric attribute change requires the ADR 0008 privacy/cardinality review.
- Backend query syntax, recording rules, SLO targets, and alert rules are created only after the monitoring provider and 0D-C-B approvals exist.
