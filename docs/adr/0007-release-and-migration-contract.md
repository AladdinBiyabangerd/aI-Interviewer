# ADR 0007: Release identity and forward-only migration contract

- **Status:** Accepted
- **Date:** 2026-08-24

## Context

The API now depends on persistent identity, privacy, and file-security schemas. A production release must not start against an unknown schema, run two schema writers concurrently, obtain application secrets merely to perform DDL, or depend on mutable migration files outside the image being deployed. Staging must exercise the same fail-closed configuration boundary as production. No cloud or orchestrator has yet been selected, so provider-specific deployment manifests would be premature.

## Decision

1. One immutable OCI image contains the installed application, `alembic.ini`, and the complete migration graph. The same digest is promoted between environments; it is not rebuilt per environment.
2. Hosted runtime and migration jobs require a bounded release label and the full source Git SHA. The image carries OCI version, revision, and creation labels, while startup logs contain only that non-sensitive release identity.
3. Staging and production use the same safety validator: TLS database access, mounted secret files, HTTPS identity/storage endpoints, OIDC, privacy, file security, and the local scanner socket all fail closed.
4. `ai-interviewer-migrate` is the only release-supported schema entrypoint. Its settings contain only release and database coordinates. It exposes `check-artifact` and `upgrade`; no downgrade operation is available.
5. Before Alembic runs, the command verifies that the artifact has exactly one head and that it equals the schema revision compiled into the API. A session-level PostgreSQL advisory lock with a stable application-owned key serializes release jobs. Lock acquisition is bounded; failure stops the deployment.
6. Alembic receives the same database connection that owns the advisory lock. After the forward upgrade, the command reads `alembic_version`, requires the exact compiled revision, releases the lock, and emits only bounded JSON metadata. Failure output contains the exception type, never the exception text or DSN.
7. Application readiness verifies both database connectivity and exact schema compatibility. Liveness remains independent so an operator can distinguish a running but unsafe-to-route release.
8. CI pins third-party actions by full commit SHA, runs the complete migration/integration/security gate, builds once with release labels, verifies non-root identity and embedded migration head, scans both images for HIGH/CRITICAL vulnerabilities, generates a CycloneDX SBOM, and retains that SBOM with the source revision.
9. The hosted migration identity and application identity must be separate when infrastructure is provisioned. The migration identity receives reviewed DDL privileges only for the one-off job; the long-lived API receives only its required DML/runtime privileges. Local development may use one disposable role.

## Release ordering

`build once -> test and scan -> identify immutable digest -> staging migration job -> staging API rollout/readiness -> production migration job -> production API rollout/readiness`

The deployment controller must serialize the overall release workflow as well; the database lock is the final safety boundary, not a substitute for release orchestration.

## Rollback and failure policy

- A migration failure leaves traffic on the previous healthy release and is fixed with a new forward migration or release.
- An application rollback is allowed only when the previous application is schema-compatible. Exact readiness deliberately rejects an incompatible old binary after a schema advance.
- Destructive or contract-breaking changes require an expand/migrate/contract sequence across releases. A database downgrade is not a normal rollback mechanism.
- Data restoration follows the backup/deletion-ledger runbook and requires an isolated target. It is not performed automatically by a failed deployment.

## Consequences

Provider-neutral code can now be wired into Kubernetes, ECS, or another reviewed platform without changing the release contract. Exact schema readiness is intentionally conservative: mixed application revisions cannot share one database after a schema revision changes unless a future ADR introduces an explicit compatibility window. Telemetry, alerts, rate controls, provider IaC, and staging/DR exercises remain 0D-B through 0D-E.
