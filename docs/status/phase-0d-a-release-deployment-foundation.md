# Phase 0D-A completion record

- **Status:** Complete within the bounded release/deployment-foundation scope
- **Completed:** 2026-08-24
- **Current stop:** Before Phase 0D-B telemetry baseline

## Delivered

- Staging and production now share the same fail-closed hosted configuration rules and require immutable release ID/source revision values.
- Release identity is frozen in settings, attached to safe lifecycle logs, and represented by OCI version/revision/creation labels.
- The runtime image includes the exact Alembic configuration and migration graph used by the application release.
- `ai-interviewer-migrate` has a narrow database/release configuration, artifact-only verification, and one forward-only upgrade operation. It exposes no release downgrade command.
- A stable PostgreSQL session advisory lock serializes migration jobs with bounded acquisition time. Alembic uses the lock-owning connection, and the command verifies the resulting database revision before success.
- API readiness requires `alembic_version` to equal the schema revision compiled into the release. A connected but incompatible database remains out of traffic.
- Migration events are bounded JSON. Failure reports disclose only an exception type, not exception text, SQL, or credentials.
- CI third-party actions are pinned by full SHA; the release image contract and non-root identity are checked; API/PostgreSQL images remain subject to HIGH/CRITICAL vulnerability gates; and a CycloneDX SBOM is retained per source revision.
- ADR 0007 and the release/rollback runbook define build-once promotion, least-privilege identities, staging-first ordering, forward-fix policy, compatibility rollback, and evidence requirements without prematurely selecting a cloud/orchestrator.

## Verification evidence

- Ruff, format checks, and strict mypy pass for `43` source files.
- `228` tests pass on Python 3.12, including `27` real-PostgreSQL integration tests; branch-aware coverage is `95.15%` and passes the enforced 95% gate.
- Integration coverage proves sole-head/model parity, repeatable upgrade, real advisory-lock exclusion/timeout, exact post-migration verification, readiness rejection for a mismatched schema, rollback behavior, and the existing identity/privacy/file-security database contracts.
- Dependency lock/compatibility checks pass and `pip-audit` reports no known vulnerable Python package.
- The release image built successfully and its contract check confirmed OCI release labels, embedded schema head `20260824_0004`, and runtime identity `10001:10001`. A real image-owned migration job completed against PostgreSQL, after which the API reached readiness under a read-only root filesystem, all capabilities dropped, and `no-new-privileges`.
- Trivy's database refreshed on 2026-08-24 and reported `0` HIGH/CRITICAL vulnerabilities in both `ai-interviewer-platform:phase0d-a` and `ai-interviewer-postgres:17.11-secure`.
- CycloneDX generation produced a populated `80`-component local rehearsal SBOM; CI YAML parsing and the retained-SBOM workflow contract were verified. The local rehearsal SBOM was intentionally removed after validation rather than committed.
- The isolated logical restore rehearsal passed at revision `20260824_0004`: all `13` tracked table counts matched, both audit immutability triggers remained active, the backup checksum was `32b2c6ecef29ca7bcd9b930a96fe9eab4dee7de1d486e865d97fa0c643a88e89`, and temporary recovery artifacts were removed. The runbook script now starts/stops PostgreSQL when needed.

## Deliberately deferred

- No Kubernetes, ECS, cloud network, registry, secret-manager, IAM, bucket, KMS, scanner-sidecar, worker, or database provisioning manifest was invented before provider selection.
- No metrics exporter, tracing SDK, dashboard, alert, or SLO is implemented; those are the bounded 0D-B and 0D-C units.
- No rate limiter, quota backend, overload policy, or load test is implemented; those belong to 0D-D after topology and measurable budgets exist.
- No claim of a rehearsed staging rollout, zero-downtime schema change, PITR, failover, or public production readiness is made. Provider wiring and exercises are 0D-E.
- No user-facing upload, parser, CV/JD processing, LLM, interview engine, Knowledge Base/RAG, source ingestion, voice, or video was introduced.

## Next gate

Phase 0D-B will define and implement the telemetry baseline: bounded low-cardinality metrics, trace/correlation propagation, release attribution, strict sensitive-field exclusion, exporter failure isolation, retention/access rules, and initial dashboards. Work stops here pending explicit authorization.
