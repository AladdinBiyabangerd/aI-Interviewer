# Staging baseline evidence format

## Purpose and boundary

`ai-interviewer-baseline` validates and summarizes an already aggregated monitoring-backend export. It does not query a provider, change telemetry, select an SLO, approve an error budget, or send evidence anywhere. Input must contain synthetic staging operational counts only—never request-level records, logs, traces, identifiers, URLs, SQL, object keys, exception text, CV/JD content, or credentials.

The strict input schema is generated from the installed release:

```powershell
uv run ai-interviewer-baseline schema
```

No sample evidence file is committed because a realistic-looking fixture could be mistaken for observed staging evidence. Automated tests construct synthetic values in test-only temporary files.

## Evidence fields

- Fixed identity: schema version 1, SLI contract `0d-c-a-v1`, service `ai-interviewer-api`, environment `staging`, and `synthetic_only=true`.
- Window: exactly 28 ordered, unique, contiguous UTC dates using an exclusive end date.
- Route population: SHA-256 of the exact code-owned product route-template set.
- Provenance: bounded backend/collector names and versions, temporality, export/monitor intervals, SHA-256 of the reviewed query definition, and SHA-256 of the preserved raw backend export. Digests refer to external source artifacts and never contain a path or URL.
- Release cohorts: one or more unique immutable release IDs plus full lowercase 40-character source revisions.
- Daily API counts: eligible, 5xx, and 4xx requests; per-bucket counts for all and non-5xx latency using the release's exact OpenTelemetry histogram boundaries plus the final `+Inf` bucket.
- Daily integrity counts: telemetry-gap seconds, sensitive-canary matches, unexpected metric attributes, snapshot successes/errors and maximum last-success age, process restarts, counter resets, and deployments.

Every object rejects unknown fields. The input file is read with a hard 2 MiB ceiling. The CLI never echoes validation details, input content, or the input path on failure.

## Deterministic result

The result contains aggregate total/good/5xx/4xx counts, availability ratio, traffic distribution, upper-bucket p50/p95/p99 estimates for all and non-5xx requests, telemetry and operational-snapshot integrity, restarts/resets/deployments, and fixed eligibility reasons.

Exit codes are:

- `0`: structurally valid and eligible for human SLO review; this is not approval.
- `2`: invalid/unreadable/oversized evidence.
- `3`: valid but incomplete evidence, including no traffic, a telemetry gap, missing daily snapshot success, route-contract drift, canary match, or unexpected metric attribute.

An overflow quantile reports `upper_bound_seconds=null` and `overflow=true`; the tool never invents a latency beyond the largest observed bucket.

## Evaluation procedure

1. Preserve the backend query definition and raw export in the approved evidence store; compute their SHA-256 digests.
2. Transform only aggregate daily values into the generated schema through the future reviewed provider adapter.
3. Run `uv run ai-interviewer-baseline evaluate <evidence.json>` in an isolated CI/review job.
4. Retain the exact release-image digest, JSON schema, input artifact digest, safe summary, CLI exit code, and reviewer identities together.
5. If the result is incomplete, repair measurement coverage and collect a new qualifying window. Do not edit observed counts or suppress a reason.
6. If eligible, 0D-C-B reviewers may use the counts/distributions as evidence when proposing objectives; their product/engineering/operations approval remains a separate signed decision.

