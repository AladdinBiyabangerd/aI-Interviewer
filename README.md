# AI Interviewer Platform

The public frontend now implements a **general Java Q&A assessment MVP**: reusable
versioned questions, single/multiple choice, adaptive difficulty, server-side scores,
study references and student ratings/flags. Company context is optional. Open-ended
interviews are no longer public. See the [assessment setup and review guide](docs/java-assessment-mvp.md)
and [ADR 0030](docs/adr/0030-general-java-question-assessment.md). The historical Python
platform scope below remains separate from this public-product change.

## Quick start (Start All)

Same pattern as ingress-academy: one block, everything local.

**Requires:** Docker Desktop, [uv](https://docs.astral.sh/uv/), Node.js 22+.

```bash
cd "/Users/mac/My Workspace/My projects/ingress_interview_platform"
./scripts/dev-up.sh
```

If Docker was closed, the script opens **Docker Desktop** and waits, then starts:

1. Postgres (`docker compose`)
2. Migrations
3. API on http://127.0.0.1:8001
4. Next.js on http://localhost:3000

Open:

- http://localhost:3000 — home  
- http://localhost:3000/java — Java assessment  
- http://127.0.0.1:8001/api/v1/health/live — API  

First time (empty question bank):

```bash
SEED_QUESTION_BANK=1 ./scripts/dev-up.sh
```

Stop with `Ctrl+C`.

The admin question editor uses a separate login at `/admin/login`. Run
`npm run admin:setup` in `frontend/` to create local credentials; see
[the frontend README](frontend/README.md) for the deployment settings.

In Cursor: **Terminal → Run Task → Start All** (`.vscode/tasks.json`).

## Hosted deploy (Vercel + Railway)

Both targets are supported:

- **Vercel** — Next.js UI (`frontend/`) — [docs/deployment/vercel.md](docs/deployment/vercel.md)
- **Railway** — Postgres + FastAPI API (and optionally the same Next.js app) —
  [docs/deployment/railway.md](docs/deployment/railway.md)

Recommended: Vercel for the UI, Railway for Postgres + API. Overview:
[docs/deployment/README.md](docs/deployment/README.md).

## Current scope

Phases 0A, 0B, 0C-A, 0C-B, 0C-C, 0D-A, 0D-B, 0D-C-A, the bounded 0D-C-B1 baseline evidence tooling, and Phase 1A-A through 1A-D4 are implemented and locally release-verified. Phase 1B is in progress: 1B-A adds the disabled-by-default provider-neutral model gateway, 1B-B1 adds strict evidence-linked CV/JD schemas, 1B-B2 adds encrypted immutable profiles and durable fenced jobs, 1B-C1 adds a policy-gated profiling worker, and 1B-C2 adds authenticated owner profile status/inspection plus immutable correction. Phase 1B-D1 adds an offline, payload-safe labeled quality evaluator with fixed field/slice/span/review thresholds, a separate digest-bound four-role approval contract, and a deliberately non-qualifying synthetic AZ/EN CV/JD seed. Phase 1B-D2.1 adds a concrete, disabled-by-default OpenAI Responses adapter; D2.2a adds an explicit-confirmation offline runner bound to an exact private corpus, approval window, prompt digest, and OpenAI release, plus a deliberately unadjudicated review-draft step and a provider-free authorization preflight. D2.2b1 adds exact, create-only finalization that permits human adjudication/owner outcomes while rejecting corpus, prediction, provenance, release, and fixture-order drift. Generated history is never overwritten: every correction is a new encrypted, evidence-revalidated version protected by strong `If-Match` concurrency and exact-retry idempotency. The profiling worker binds code-owned prompts, an approved immutable processor activity, encrypted processor-usage registration, one provider request ID, independent evidence validation, encrypted persistence, and the live job lease. Source text, extraction/profiling-job metadata, and decrypted owned profile histories participate in account privacy export and owner/document cascades erase them. A bounded payload-blind worker process can now supervise explicitly enabled extraction and profiling workers, but both workers and their operational deployment remain disabled by default. No API credential or real corpus is bundled and no live OpenAI request was made during verification. Real prediction evidence, human adjudication, error analysis, threshold success, named quality approval, production worker activation, interview, evaluation, report, RAG, voice, and video remain pending. Live staging measurement and the remaining 0D reliability/production gates are deferred until the text flow is feature-stable under [ADR 0010](docs/adr/0010-feature-stable-mvp-before-hosted-reliability-baseline.md); they remain mandatory before production.

An O*NET-derived 40-fixture synthetic AZ/EN development corpus now meets every
pre-run structural minimum without pretending to replace the pending real-corpus and
human-approval gate. See its [preparation record](docs/status/phase-1b-d2-development-corpus.md).

A dormant [question-intelligence foundation](docs/status/question-intelligence-foundation.md)
now models rights-cleared evidence, deep JD/CV competency activation, explicit cold-start
industry provenance, multi-signal ranking, coverage/diversity, company fingerprints, and
versioned question concepts in PostgreSQL. It makes no model/network call and does not
mark the pending Phase 1B approval, Phase 1C, or Phase 2 gates complete. The architectural
decision is recorded in [ADR 0029](docs/adr/0029-evidence-ranked-question-intelligence-foundation.md).

See [the development roadmap](docs/development-roadmap.md), [worker supervision record](docs/status/worker-supervision-runtime.md), [worker supervision ADR](docs/adr/0028-disabled-by-default-worker-supervision.md), [review-finalization record](docs/status/phase-1b-d2-2b1-review-finalization.md), [review-finalization ADR](docs/adr/0027-exact-human-review-finalization.md), [authorized quality-runner record](docs/status/phase-1b-d2-2a-authorized-quality-runner.md), [authorized quality-runner ADR](docs/adr/0026-authorized-offline-quality-prediction-run.md), [OpenAI adapter record](docs/status/phase-1b-d2-1-openai-responses-adapter.md), [OpenAI adapter ADR](docs/adr/0025-openai-responses-provider-adapter.md), [profile quality contract](docs/quality/profile-quality-gate.md), [Phase 1B-D1 completion record](docs/status/phase-1b-d1-profile-quality-contract.md), [profile quality ADR](docs/adr/0024-deterministic-profile-quality-gate.md), [Phase 1B-C2 completion record](docs/status/phase-1b-c2-owner-profile-inspection-and-correction.md), [owner profile correction ADR](docs/adr/0023-owner-profile-inspection-and-correction.md), [Phase 1B-C1 completion record](docs/status/phase-1b-c1-policy-gated-profiling-worker.md), [profiling execution ADR](docs/adr/0022-policy-gated-profiling-execution.md), [Phase 1B-B2.2 completion record](docs/status/phase-1b-b2-2-durable-profiling-jobs.md), [profiling-job ADR](docs/adr/0021-durable-fenced-profiling-jobs.md), [Phase 1B-B2.1 completion record](docs/status/phase-1b-b2-1-encrypted-profile-persistence.md), [profile persistence ADR](docs/adr/0020-encrypted-candidate-profile-persistence.md), [Phase 1B-B1 completion record](docs/status/phase-1b-b1-evidence-profile-contracts.md), [evidence profile ADR](docs/adr/0019-evidence-linked-profile-contracts.md), [Phase 1B-A completion record](docs/status/phase-1b-a-model-gateway.md), [model gateway ADR](docs/adr/0018-provider-neutral-model-gateway.md), [Phase 1A-D4 completion record](docs/status/phase-1a-d4-lifecycle-and-phase-gate.md), [lifecycle and phase gate ADR](docs/adr/0017-phase-1a-lifecycle-and-phase-gate.md), [owner correction ADR](docs/adr/0016-owner-source-text-inspection-and-correction.md), [isolated parser worker ADR](docs/adr/0015-isolated-parser-worker.md), [source-text ADR](docs/adr/0013-encrypted-immutable-candidate-source-text.md), [sequencing ADR](docs/adr/0010-feature-stable-mvp-before-hosted-reliability-baseline.md), [SLI measurement contract](docs/reliability/sli-measurement-contract.md), and [baseline evidence format](docs/reliability/baseline-evidence-format.md).

For a single detailed account of everything implemented from the beginning, see the
[implementation history](docs/implementation-history.md).

## Prerequisites

- Python 3.12
- [uv](https://docs.astral.sh/uv/)
- Docker, for PostgreSQL integration and container verification
- Node.js 22.13 or newer, for the interactive frontend demo

## Local full stack

See **[Quick start (Start All)](#quick-start-start-all)** above. Manual equivalent:

```bash
# Start Docker Desktop first if needed, then:
docker compose up --detach --wait --build postgres
uv sync --frozen
uv run ai-interviewer-migrate upgrade
uv run uvicorn ai_interviewer.main:app --host 127.0.0.1 --port 8001
# other terminal:
cd frontend && npm install && npm run dev
```

## Public Java assessment application

The responsive [`frontend`](frontend/README.md) provides an English Java assessment
with Junior, Mid and Senior scope. PostgreSQL stores the question bank, saved answers
and feedback. Assessment requests need no OpenAI or Blob service. Apply migration
`20260910_0016`, load and review the seed question bank using the
[assessment guide](docs/java-assessment-mvp.md), then start the Next.js application.
Uploaded question PDFs use the deterministic, private
[source-ingestion workflow](docs/java-question-source-ingestion.md); staged source text
never becomes a public question without separate rights and editorial review.
The former bilingual interview implementation is retained outside public routes.

```powershell
cd frontend
npm install
npm run dev
```

Open `http://localhost:3000`.

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

Protected extracted-text and profile endpoints:

- `GET`/`PUT /api/v1/preparations/{id}/document-versions/{document_version_id}/source-text` (`preparation:read`/`preparation:write`; correction requires strong `If-Match`)
- `GET /api/v1/preparations/{id}/document-versions/{document_version_id}/profiles/{source_text_version_id}` (`preparation:read`; safe job status plus completed encrypted profile history)
- `PUT /api/v1/preparations/{id}/document-versions/{document_version_id}/profiles/{source_text_version_id}` (`preparation:write`; strict evidence-linked correction plus strong `If-Match`)

Authentication, privacy, file security, model execution, and both background workers are deliberately disabled in the local example. Staging and production refuse to start with mandatory identity/privacy/file boundaries disabled or without release identity. Model execution additionally fails closed without exact provider/model/version coordinates; `provider=openai` requires a server-side API secret and any other provider still requires an explicitly injected adapter. Hosted OpenAI credentials must come from an absolute secret file. See [.env.example](.env.example), [ADR 0004](docs/adr/0004-oidc-resource-server-and-local-identity.md), [ADR 0005](docs/adr/0005-jurisdiction-aware-privacy-lifecycle.md), [ADR 0006](docs/adr/0006-file-secret-security.md), [ADR 0018](docs/adr/0018-provider-neutral-model-gateway.md), and [ADR 0025](docs/adr/0025-openai-responses-provider-adapter.md). The API never accepts an ID token in place of an access token.

Phase 0C-C owns file bytes and their quarantine/release/deletion lifecycle. Phase 1A-A adds preparation context, Phase 1A-B adds immutable document-version metadata, Phase 1A-C durably coordinates authenticated raw upload/paste, Phase 1A-D1 adds internal encrypted immutable source-text lineage, Phase 1A-D2.1 adds the durable fenced extraction-job contract, Phase 1A-D2.2 adds the isolated, no-network PDF/DOCX/TXT parser worker, Phase 1A-D3 adds the authenticated owner read/correction HTTP contract, and Phase 1A-D4 closes the phase by wiring source-text and extraction-job data into privacy export and proving the full pipeline against real PDF/DOCX/text fixtures. Phase 1B-A adds the provider-neutral model execution boundary, 1B-B1 adds strict in-memory evidence contracts, 1B-B2 adds encrypted exact-source profiles and fenced jobs, 1B-C1 adds disabled-by-default policy-gated worker execution, 1B-C2 exposes owner-only status/inspection/correction without mutating generated history, 1B-D1 freezes the deterministic labeled quality and separate approval contract, 1B-D2.1 adds the reviewed OpenAI Responses transport, D2.2a adds its private authorized offline prediction/review-artifact workflow, and D2.2b1 adds exact review finalization. The next gate is D2.2b2: an approved rights-cleared full-corpus run, exhaustive human adjudication, error analysis, threshold success, and named approval. A disabled-by-default supervisor runtime now exists; production worker activation remains a separate reviewed decision.

## Background workers (disabled by default)

The API process never starts background jobs. A separate process supervises only workers
that are explicitly enabled in configuration. Extraction also requires the secure file
boundary. Profiling additionally requires the approved model, privacy, file, processor,
and exact durable-job controls described above.

Run one bounded operator sweep:

```powershell
uv run ai-interviewer-workers --once
```

Run continuous polling with graceful termination:

```powershell
uv run ai-interviewer-workers
```

The command exits with code `2` when neither worker is enabled and code `1` when a sweep
encounters a runtime failure. Logs contain only bounded outcome counts and exception type
names; they exclude candidate content, identifiers, paths, provider bodies, and exception
messages. Enabling a worker and deploying this process remain explicit operational actions.

## OpenAI provider (disabled by default)

The concrete adapter calls only `https://api.openai.com/v1/responses`, requests strict JSON Schema output, sends `store=false`, disables automatic input truncation, and propagates the durable job UUID as `X-Client-Request-Id`. It does not enable tools, web search, file search, or background responses. The application still validates the returned JSON and exact reported model release.

Never paste an API key into source code, documentation, commits, tickets, or chat. For development, place a newly created key only in the ignored local `.env` as `AI_INTERVIEWER_OPENAI_API_KEY`, or point `AI_INTERVIEWER_OPENAI_API_KEY_FILE` to a protected secret file containing only the key. Hosted environments accept only the absolute secret-file form. A key exposed anywhere must be revoked before use.

Enabling the gateway alone does not send data: the profiling worker remains a separate gate and every real job still requires an approved processor activity. No live request is part of the test suite.

## Profile quality evaluation

The quality CLI exposes strict private-artifact schemas, an explicitly authorized
prediction action, a deliberately unadjudicated human-review draft, payload-safe metric
summaries, and a separate approval gate:

```powershell
uv run ai-interviewer-profile-quality prompt-digest
uv run ai-interviewer-profile-quality build-development-corpus <output.json>
uv run ai-interviewer-profile-quality validate-corpus <corpus.json>
uv run ai-interviewer-profile-quality schema corpus
uv run ai-interviewer-profile-quality schema authorization
uv run ai-interviewer-profile-quality schema predictions
uv run ai-interviewer-profile-quality schema review-draft
uv run ai-interviewer-profile-quality schema evidence
uv run ai-interviewer-profile-quality schema approval
uv run ai-interviewer-profile-quality preflight <corpus.json> <authorization.json>
uv run ai-interviewer-profile-quality generate <corpus.json> <authorization.json> <predictions.json> --confirm-external-processing
uv run ai-interviewer-profile-quality prepare-review <corpus.json> <predictions.json> <review-draft.json>
uv run ai-interviewer-profile-quality finalize-review <corpus.json> <predictions.json> <completed-review.json> <quality-evidence.json>
uv run ai-interviewer-profile-quality evaluate <quality-evidence.json>
uv run ai-interviewer-profile-quality gate <quality-evidence.json> <approval.json>
```

`build-development-corpus` reproducibly creates the repository-safe O*NET-derived
benchmark, while `validate-corpus` reports structural counts without granting rights,
provider, quality, or product approval. `preflight` validates the exact corpus digest, current prompt contract, approval window,
and authorized OpenAI release without loading a provider credential or making a network
call. `generate` can send every private fixture to OpenAI and therefore must be used only with
a newly rotated server key, exact digest-bound authorization, and approved corpus/data
controls. It creates but never overwrites a private output file. `evaluate`, `gate`,
`preflight`, `validate-corpus`, `build-development-corpus`, `prepare-review`, and
`finalize-review` make no provider call. The checked-in four-fixture seed intentionally
returns `blocked`; the 40-fixture development corpus is structurally ready but remains
synthetic, so neither validates production quality on real documents. See the
[quality contract](docs/quality/profile-quality-gate.md).

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
