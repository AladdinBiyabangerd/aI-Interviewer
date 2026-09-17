# Vercel deployment for Intervia

> Also see the dual-host overview: [deployment README](README.md) and [Railway](railway.md).

Intervia has a field-neutral landing page at `/` and Java as its first available
interview track at `/java`. The Azerbaijani-first interface has an English option;
the Java track offers a general Q&A assessment and a separate Java 8 book-practice mode. Vercel serves the Next.js UI
and same-origin Route Handlers from `frontend/`; PostgreSQL stores the versioned
question bank, anonymous assessment sessions, answers and feedback. Assessment traffic
does not use OpenAI or Vercel Blob. The retained interview-generation, CV-upload,
OpenAI-webhook and open-ended-practice routes return HTTP 410 and must not be used as
deployment smoke tests.

Question PDFs follow the separate [private ingestion and rights-review workflow](../java-question-source-ingestion.md).
Staged source wording is never read by the public assessment runtime or published
automatically.

## 1. Vercel project and environment

- Import the GitHub repository and set **Root Directory** to `frontend`.
- Use the Next.js preset, Node.js 22.x or newer, `npm ci` as the install command and
  `npm run build` as the build command. Leave the output directory empty.
- Connect PostgreSQL and expose the pooled connection as `DATABASE_URL` to the runtime.
  Keep the direct/unpooled URL for the one-off migration job.
- Configure `NEXT_PUBLIC_APP_URL`, `INTERVIEW_SESSION_SECRET` and `CRON_SECRET`.
  The two secrets must be different; the session secret must contain at least 32 bytes.
- Optionally configure `INTERVIEW_RETENTION_DAYS` from 1 through 30. The default is 7.
- Use separate databases and secrets for Preview and Production.

### Portal SSO (optional, additive)

When the FastAPI API is hosted (typically on Railway), also set:

```env
INTERVIEW_API_BASE_URL=https://api.example.com
PORTAL_OIDC_ISSUER=https://ingress.academy/
PORTAL_OIDC_CLIENT_ID=interview-web
PORTAL_OIDC_REDIRECT_URI=https://your-vercel-domain/api/auth/callback
PORTAL_HOME_URL=https://ingress.academy/portal/welcome/
```

Allow that redirect URI on the portal OIDC client. Details:
[portal-oidc-sso.md](../portal-oidc-sso.md).

Only `NEXT_PUBLIC_APP_URL` is browser-visible. Never create a `NEXT_PUBLIC_` variant of
a database URL or secret. Existing OpenAI or Blob credentials are unnecessary for the
assessment and should remain configured only while approved cleanup of historical
artifacts requires them.

Generate a session or cron secret:

```bash
openssl rand -base64 48
```

PowerShell:

```powershell
[Convert]::ToBase64String([Security.Cryptography.RandomNumberGenerator]::GetBytes(48))
```

## 2. Apply the release migration

The shared forward-only Alembic chain owns the schema. The current release requires
exact revision `20260910_0016`. Do not run migrations from a Vercel build because
concurrent Preview builds are not a serialized migration boundary.

Run the migration from a protected release job or trusted workstation before promoting
the matching application release. The following form explicitly opts into the
short-lived environment secret supported by the migration CLI:

```powershell
$env:AI_INTERVIEWER_ENVIRONMENT = "production"
$env:AI_INTERVIEWER_DATABASE_URL = $env:DATABASE_URL_UNPOOLED
$env:AI_INTERVIEWER_HOSTED_ENVIRONMENT_SECRETS = "true"
$env:AI_INTERVIEWER_DATABASE_TLS_MODE = "require"
$env:AI_INTERVIEWER_RELEASE_ID = "vercel-production-20260910"
$env:AI_INTERVIEWER_RELEASE_REVISION = (git rev-parse HEAD)
uv run ai-interviewer-migrate check-artifact
uv run ai-interviewer-migrate upgrade
```

Use the provider's direct/unpooled connection for this serialized job and the pooled
`DATABASE_URL` in the Vercel runtime. The migration command normalizes standard
`postgres://` and `postgresql://` provider URLs to the required psycopg driver. Require
the `database_migration_completed` event and confirm its schema revision is
`20260910_0016`. Never run `alembic downgrade` against a data-bearing environment.

For a long-lived hosted migration worker, mount the database URL in a protected file
and use `AI_INTERVIEWER_DATABASE_URL_FILE` instead of the environment-secret opt-in.
See the [release and rollback runbook](../runbooks/release-and-rollback.md).

## 3. Seed, review and publish questions

Migration creates the tables but does not publish content. From `frontend/`, connect
the operator CLI to the intended database, validate and idempotently insert the 45
original seed questions as drafts:

```powershell
$env:DATABASE_URL = $env:DATABASE_URL_UNPOOLED
npm run bank -- validate
npm run bank -- seed
npm run bank -- list
```

Review each question's wording, choices, answer key, explanation, level and references.
Publish only the exact revisions that passed that review:

```powershell
npm run bank -- publish core-java-1 1
```

Repeat publishing for the reviewed revisions. Readiness requires at least the entry
question for every default topic; publish all three steps in a topic to enable its full
adaptive ladder. The CLI has no bulk-publish command so that loading drafts cannot
silently grant editorial approval.

## 4. Retention

`frontend/vercel.json` invokes `/api/maintenance/retention` daily at 03:00 UTC. Vercel
sends the configured `CRON_SECRET`; the route rejects missing or invalid authorization.
Expired anonymous sessions, answers and owner feedback are removed according to
`INTERVIEW_RETENTION_DAYS`. Versioned editorial question content is retained separately.

## 5. Verification and promotion

Before deployment:

```powershell
cd frontend
npm ci
npm run lint
npm run typecheck
npm test
npm run bank -- validate
npm audit --omit=dev --audit-level=high
npm run build
cd ..
uv sync --frozen
uv run ai-interviewer-migrate check-artifact
./scripts/verify.ps1
```

After the migration and reviewed question publication, require
`GET /api/health` to return HTTP 200 with `{"status":"ready"}`. Then verify the
homepage, an assessment at each level, book practice, Back/Skip navigation, refresh
restoration, scoring released only after completion, early completion, study references,
rating/flag submission and retention authorization.
Confirm that browser bundles and network responses contain no database URL, signing
secret, cron secret or answer key for unanswered questions.

Vercel reporting a successful deployment is not sufficient: it proves the application
artifact was deployed, while `/api/health` also verifies the exact database revision and
the minimum published question-bank coverage.
