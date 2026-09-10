# Java assessment deployment update — September 10, 2026

The public product is now the Java Q&A assessment. Apply migration `20260910_0016`
and load/review/publish the bank as described in [the assessment guide](../java-assessment-mvp.md).
Uploaded question sources follow the separate [private ingestion and rights-review
workflow](../java-question-source-ingestion.md).
Assessment traffic requires PostgreSQL, the session signing secret and the retention
cron secret; it makes no OpenAI/Blob calls. The old interview generation, CV upload,
OpenAI webhook and practice endpoints return 410. The historical instructions below
describe retained interview infrastructure and cleanup obligations, not the current
student onboarding flow. Do not re-enable provider processing for the assessment.

# Vercel production deployment

The production text application is a standard Next.js application in `frontend/`.
Vercel serves the UI and same-origin Route Handlers. PostgreSQL is the durable source
of truth, a private Vercel Blob store holds CV uploads, and OpenAI Responses performs
company research, CV review, adaptive follow-ups, and final reports. Provider keys are
read only by Node.js server routes and are never exposed as `NEXT_PUBLIC_*` variables.

## Runtime topology

1. The browser uploads an optional PDF or DOCX directly to a private Blob store using
   a short-lived, owner-bound client token. The file does not pass through a Vercel
   request body.
2. `POST /api/interview-preparations/analyze` validates the input, persists a job, and
   starts separate background Responses for public web research and private CV review.
   CV content is never supplied to the web-search request.
3. The browser polls the owner-scoped status route. A signed OpenAI webhook also
   reconciles completed jobs when the browser is closed.
4. Questions, practice sessions, every answer, adaptive follow-up, and the final report
   are persisted in PostgreSQL. The report is based on the saved answers, not demo text.
5. A daily authenticated Vercel Cron removes records and private files after the
   configured retention period.

This production flow is intentionally separate from the repository's stricter dormant
FastAPI/OIDC/extraction pipeline. The latter remains available for a future account-based
enterprise deployment, but it is not falsely presented as the runtime behind this
anonymous text MVP.

## 1. Create and connect services

- Import the GitHub repository into Vercel and set **Root Directory** to `frontend`.
- Connect a managed PostgreSQL provider from the Vercel Marketplace (Neon is a suitable
  default) and ensure it injects `DATABASE_URL` into Production and Preview.
- Create a **Private** Vercel Blob store in the same project. Private/public access cannot
  be changed after creation.
- Create an OpenAI project key with an explicit spend limit. Create a webhook pointing to
  `https://YOUR_DOMAIN/api/webhooks/openai` and subscribe to response completion/failure
  events.

## 2. Vercel environment variables

Copy the names from `frontend/.env.example`:

- `NEXT_PUBLIC_APP_URL`
- `DATABASE_URL`
- `DATABASE_URL_UNPOOLED` (migration job only; normally injected by the provider)
- `BLOB_READ_WRITE_TOKEN`
- `OPENAI_API_KEY`
- `OPENAI_INTERVIEW_MODEL`
- `INTERVIEW_SESSION_SECRET`
- `OPENAI_WEBHOOK_SECRET`
- `CRON_SECRET`
- optional `INTERVIEW_RETENTION_DAYS`
- optional `INTERVIEW_ANALYSIS_LIMIT_PER_10_MINUTES`

Only `NEXT_PUBLIC_APP_URL` is browser-visible. Never create a `NEXT_PUBLIC_` variant of
any key, token, database URL, or signing secret. Use different databases, Blob stores,
OpenAI keys, signing secrets, and webhook endpoints for Preview and Production.

Generate a signing or cron secret in PowerShell:

```powershell
[Convert]::ToBase64String([Security.Cryptography.RandomNumberGenerator]::GetBytes(48))
```

## 3. Database and migrations

The shared Alembic chain owns the schema. Revision `20260902_0014` adds the Vercel
preparation, upload, practice-turn, and report tables. Do not run migrations from the
Vercel build: concurrent preview builds are not a safe migration boundary.

Run the forward-only migration once from a protected release job or trusted workstation
before promoting the Vercel deployment:

```powershell
$env:AI_INTERVIEWER_ENVIRONMENT = "production"
$env:AI_INTERVIEWER_DATABASE_URL = $env:DATABASE_URL_UNPOOLED
$env:AI_INTERVIEWER_HOSTED_ENVIRONMENT_SECRETS = "true"
$env:AI_INTERVIEWER_DATABASE_TLS_MODE = "require"
$env:AI_INTERVIEWER_RELEASE_ID = "vercel-production-20260902"
$env:AI_INTERVIEWER_RELEASE_REVISION = "<full-40-character-git-sha>"
uv run ai-interviewer-migrate check-artifact
uv run ai-interviewer-migrate upgrade
```

Use the provider's direct/unpooled connection string for the serialized migration job,
use the pooled `DATABASE_URL` in the serverless Next runtime, and verify that `alembic_version.version_num`
equals `20260902_0014`. PostgreSQL is required. `pgvector` is not required by the current
online path; the existing evidence-ranked question foundation remains relational until
an embedding retrieval implementation is approved.

## 4. CV storage and retention

Use a Private Vercel Blob store. Uploads are limited to 10 MiB and to PDF/DOCX at the
token, metadata, and file-signature boundaries. Files are not downloadable through a
public application route. Set `INTERVIEW_RETENTION_DAYS` to the approved value (default
7, maximum 30) and keep the daily cron enabled.

The Vercel runtime treats documents as opaque bytes and sends them to OpenAI's file
input. It never executes or locally extracts them. If the product later adds file
downloads, local archive extraction, or enterprise document retention, deploy the
repository's isolated parser plus ClamAV file-security worker on a container service
(for example Cloud Run, Fly.io, or Railway); ClamAV is not suitable for a Vercel Function.

## 5. OpenAI and asynchronous work

The company research and optional CV review run as OpenAI background Responses with
`store: false`. The status route polls the provider, and the signed webhook persists the
result even if the browser closes. Configure the webhook secret in Vercel after creating
the endpoint in the OpenAI project. Practice feedback and final reports are bounded
foreground calls with Vercel `maxDuration` declarations.

## 6. Vercel build settings

- Root Directory: `frontend`
- Framework Preset: Next.js
- Install Command: `npm ci`
- Build Command: `npm run build`
- Output Directory: leave empty (Next.js default)
- Node.js: 22.x or newer

No localhost API URL is used. Browser requests are same-origin. `vercel.json` registers
the daily retention cron.

## 7. Verification and promotion

Before deployment:

```powershell
cd frontend
npm ci
npm run lint
npm run typecheck
npm test
npm run build
cd ..
uv sync --frozen
uv run ai-interviewer-migrate check-artifact
./scripts/verify.ps1
```

After deployment, first confirm `GET /api/health` returns `200` and `status: ready`, then
check the homepage, a no-CV analysis, a CV analysis, source links,
question filters, Practice mode feedback, answer-dependent follow-up wording, Real
Interview mode, final report, webhook delivery, database rows, and retention endpoint
authorization. Confirm that browser bundles and network responses contain no provider,
database, Blob, webhook, cron, or signing secrets.
