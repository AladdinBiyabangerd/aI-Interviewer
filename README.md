# AI Interviewer Platform

Production-oriented implementation of the candidate-preparation platform described in the supplied technical plan. Development is intentionally incremental: a phase must satisfy its exit gate before work starts on dependent product capabilities.

## Current scope

Phases 0A, 0B, 0C-A, 0C-B, 0C-C, 0D-A, 0D-B, 0D-C-A, the bounded 0D-C-B1 baseline evidence tooling, and Phase 1A-A through 1A-C are implemented. The application persists owner-bound preparation context and immutable CV/JD lineage, and now exposes durable authenticated upload/paste through validation, quarantine, malware scanning, clean release, and idempotent attachment. It does not yet expose parsing/extracted text, interview, evaluation, report, RAG, voice, or video capability. Live staging measurement and the remaining 0D reliability/production gates are deferred until the text flow is feature-stable under [ADR 0010](docs/adr/0010-feature-stable-mvp-before-hosted-reliability-baseline.md); they remain mandatory before production.

See [the development roadmap](docs/development-roadmap.md), [Phase 1A-C completion record](docs/status/phase-1a-c-authenticated-document-intake.md), [document-intake ADR](docs/adr/0012-durable-authenticated-document-intake.md), [sequencing ADR](docs/adr/0010-feature-stable-mvp-before-hosted-reliability-baseline.md), [SLI measurement contract](docs/reliability/sli-measurement-contract.md), and [baseline evidence format](docs/reliability/baseline-evidence-format.md).

For a single detailed account of everything implemented from the beginning, see the
[implementation history](docs/implementation-history.md).

## Prerequisites

- Python 3.12
- [uv](https://docs.astral.sh/uv/)
- Docker, for PostgreSQL integration and container verification

## Local verification

```powershell
uv sync --frozen
./scripts/verify.ps1
```

The verification script starts the project PostgreSQL service when needed, creates a unique disposable test database, runs migration and integration checks, drops that database, and restores the prior environment. It never runs destructive migration tests against the development database.

## Run the API

Copy `.env.example` to `.env` for local-only settings, then run:

```powershell
uv run ai-interviewer-api
```

Operational endpoints:

- `GET /api/v1/health/live`
- `GET /api/v1/health/ready`

Protected identity endpoint:

- `GET /api/v1/identity/me` requires a validated JWT access token and the `profile:read` scope.

Protected privacy endpoints:

- `PUT /api/v1/privacy/profile` (`privacy:write`)
- `GET /api/v1/privacy/consents` (`privacy:read`)
- `POST`/`DELETE /api/v1/privacy/consents/{id}` (`privacy:write`)
- `POST /api/v1/privacy/requests` with per-request `privacy:read`, `privacy:export`, or `privacy:delete` scope and an `Idempotency-Key`
- `GET /api/v1/privacy/requests/{id}` (`privacy:read`)

Protected preparation-target endpoints:

- `POST /api/v1/preparations` (`preparation:write`, `Idempotency-Key`)
- `GET /api/v1/preparations` and `GET /api/v1/preparations/{id}` (`preparation:read`)
- `PUT /api/v1/preparations/{id}` (`preparation:write`, strong `If-Match` version)
- `POST /api/v1/preparations/{id}/archive` (`preparation:write`, strong `If-Match` version)

Protected candidate-document metadata endpoints:

- `GET /api/v1/preparations/{id}/documents` (`preparation:read`)
- `GET /api/v1/preparations/{id}/documents/{document_id}` (`preparation:read`, immutable version lineage and aggregate ETag)

Protected candidate-document intake endpoints:

- `POST /api/v1/preparations/{id}/documents/{cv|job_description}/upload` (`preparation:write`, `Idempotency-Key`, bounded raw PDF/DOCX/UTF-8 text body)
- `POST /api/v1/preparations/{id}/documents/{cv|job_description}/paste` (`preparation:write`, `Idempotency-Key`, bounded UTF-8 `text/plain` body)
- `GET /api/v1/preparations/{id}/document-intakes/{intake_id}` (`preparation:read`, durable owner-scoped status)

Authentication, privacy, and file security are deliberately disabled in the local example until an OIDC issuer, approved policy records, a mounted privacy keyring, a reviewed SSE-KMS bucket, and a local malware-scanner socket are configured. Staging and production both refuse to start with any boundary disabled or without release identity. See [.env.example](.env.example), [ADR 0004](docs/adr/0004-oidc-resource-server-and-local-identity.md), [ADR 0005](docs/adr/0005-jurisdiction-aware-privacy-lifecycle.md), and [ADR 0006](docs/adr/0006-file-secret-security.md). The API never accepts an ID token in place of an access token.

Phase 0C-C owns file bytes and their quarantine/release/deletion lifecycle. Phase 1A-A adds preparation context, Phase 1A-B adds immutable document-version metadata, and Phase 1A-C durably coordinates authenticated raw upload/paste into those boundaries. Parser workers, extracted text, and correction remain Phase 1A-D.

Interactive API documentation is disabled by default and can be explicitly enabled in a development environment.

## Telemetry

Telemetry is disabled for local development unless explicitly configured. Staging and production require an OTLP collector origin. The application emits OTLP/HTTP protobuf metrics and traces to `/v1/metrics` and `/v1/traces`; structured logs remain JSON on stdout for the platform log pipeline.

Only route templates and bounded operational enums are recorded. Raw URL paths, query strings, headers, authorization material, account/file/task identifiers, SQL, object keys, exception messages, and request/response bodies are excluded. Remote non-loopback collectors must use HTTPS in hosted environments; collector credentials belong in the collector or workload-identity boundary, not application telemetry headers.

Product API, health/operations, and unknown routes have separate bounded populations. Queue dashboards also expose operational snapshot failures and last-success age so stale observations are not presented as current. Numeric objectives and alerts require the documented 28-day staging evidence and named approvals.

The release-owned offline evaluator exposes its strict input schema and summarizes a reviewed aggregate export without contacting a backend:

```powershell
uv run ai-interviewer-baseline schema
uv run ai-interviewer-baseline evaluate <evidence.json>
```

An eligible result permits human review only; it does not create or approve an SLO.

## Database migrations

Start the local database and apply the release-owned, forward-only migration:

```powershell
docker compose up --detach --wait postgres
uv run ai-interviewer-migrate check-artifact
uv run ai-interviewer-migrate upgrade
```

The API readiness endpoint reports down unless `alembic_version` exactly matches the schema revision compiled into that release. Direct Alembic downgrade is limited to disposable test databases. See the [release and rollback runbook](docs/runbooks/release-and-rollback.md) and [database backup and restore runbook](docs/runbooks/database-backup-restore.md) before any hosted schema or recovery operation.

Build metadata and migration contents can be verified without database access:

```powershell
docker build --tag ai-interviewer-platform:local .
./scripts/verify-release-image.ps1
```
