# Railway deployment

Use this with the overview in [README.md](README.md). The repo root `railway.toml`
targets the **API** service. The Next.js app uses `frontend/railway.toml` when the
service Root Directory is `frontend`.

## 1. Postgres

Add a Railway **PostgreSQL** plugin to the project. Note:

- `DATABASE_URL` — pooled or standard URL for the Next.js runtime
- Direct / unpooled URL if Railway exposes one — prefer it for one-off migrations

Point both the API and the frontend at the **same** database if you run Portal SSO
and the Java assessment together.

## 2. API service (repo root)

1. New service → Deploy from GitHub → this repository.
2. Root Directory: empty / `/`.
3. Builder: Dockerfile (`railway.toml` already sets this).
4. Generate a public HTTPS domain (e.g. `https://api-xxxx.up.railway.app`).

### SSO-capable profile (recommended first deploy)

Full `staging`/`production` Settings also require object storage, malware scanner,
telemetry exporter, and immutable release IDs (see ADR-0006/0007). For Portal SSO
identity checks first, run a hosted **development** profile with auth enabled:

```env
AI_INTERVIEWER_ENVIRONMENT=development
AI_INTERVIEWER_DOCS_ENABLED=false
AI_INTERVIEWER_LOG_LEVEL=INFO
AI_INTERVIEWER_DATABASE_TLS_MODE=require
AI_INTERVIEWER_HOSTED_ENVIRONMENT_SECRETS=true
AI_INTERVIEWER_DATABASE_URL=${{Postgres.DATABASE_URL}}
AI_INTERVIEWER_ALLOWED_HOSTS=["api-xxxx.up.railway.app"]
AI_INTERVIEWER_AUTH_ENABLED=true
AI_INTERVIEWER_AUTH_OIDC_ISSUER=https://ingress.academy/
AI_INTERVIEWER_AUTH_OIDC_AUDIENCE=https://api-xxxx.up.railway.app
AI_INTERVIEWER_AUTH_OIDC_JWKS_URL=https://ingress.academy/portal/oauth/jwks.json
AI_INTERVIEWER_AUTH_OIDC_ALGORITHMS=["RS256"]
AI_INTERVIEWER_AUTH_REQUIRED_TOKEN_TYPE=at+jwt
```

Replace hosts with your real domains. Issuer trailing slash must match the portal
`OIDC_ISSUER` bit-for-bit. Set portal `OIDC_INTERVIEW_AUDIENCE` to the same audience.

The container entrypoint (`scripts/railway-api-entrypoint.sh`) writes
`AI_INTERVIEWER_DATABASE_URL` / `DATABASE_URL` into a secret file for processes that
require `*_FILE` mounts.

`PORT` is set by Railway; the API listens on it automatically.

### Migrations (one-off)

From a trusted machine or a Railway one-off run against the **direct** DB URL:

```bash
export AI_INTERVIEWER_ENVIRONMENT=production
export AI_INTERVIEWER_DATABASE_URL='postgresql://…'
export AI_INTERVIEWER_HOSTED_ENVIRONMENT_SECRETS=true
export AI_INTERVIEWER_DATABASE_TLS_MODE=require
export AI_INTERVIEWER_RELEASE_ID="railway-$(date -u +%Y%m%d)"
export AI_INTERVIEWER_RELEASE_REVISION="$(git rev-parse HEAD)"
uv run ai-interviewer-migrate check-artifact
uv run ai-interviewer-migrate upgrade
```

Never run `alembic downgrade` on a data-bearing database.

### Full production API gates

When you are ready for `AI_INTERVIEWER_ENVIRONMENT=production`, you also need
privacy + file-security + telemetry (S3/KMS, clamd, OTLP, release identity). Generate
a keyring once and store it only in Railway Variables:

```bash
python3 scripts/generate_privacy_keyring.py --compact
# → set AI_INTERVIEWER_PRIVACY_KEYRING=<json>
# entrypoint materializes AI_INTERVIEWER_PRIVACY_KEYRING_FILE
```

## 3. Frontend service {#frontend-service}

### Option A — Vercel (preferred for UI)

Follow [vercel.md](vercel.md). Set:

```env
INTERVIEW_API_BASE_URL=https://api-xxxx.up.railway.app
PORTAL_OIDC_ISSUER=https://ingress.academy/
PORTAL_OIDC_CLIENT_ID=interview-web
PORTAL_OIDC_REDIRECT_URI=https://your-frontend-domain/api/auth/callback
PORTAL_HOME_URL=https://ingress.academy/portal/welcome/
```

Plus the assessment vars (`DATABASE_URL`, `INTERVIEW_SESSION_SECRET`,
`NEXT_PUBLIC_APP_URL`, `CRON_SECRET`).

### Option B — Railway web service

1. New service from the same repo.
2. Root Directory: `frontend`.
3. Uses `frontend/Dockerfile` + `frontend/railway.toml`.
4. Build arg / variable: `NEXT_PUBLIC_APP_URL=https://your-web-domain` (must be present
   at **build** time for the client bundle).
5. Runtime variables: same as Vercel (no Vercel Cron — schedule retention yourself).

```env
DATABASE_URL=${{Postgres.DATABASE_URL}}
INTERVIEW_SESSION_SECRET=<openssl rand -base64 48>
CRON_SECRET=<openssl rand -base64 48>
NEXT_PUBLIC_APP_URL=https://web-xxxx.up.railway.app
INTERVIEW_API_BASE_URL=https://api-xxxx.up.railway.app
PORTAL_OIDC_ISSUER=https://ingress.academy/
PORTAL_OIDC_CLIENT_ID=interview-web
PORTAL_OIDC_REDIRECT_URI=https://web-xxxx.up.railway.app/api/auth/callback
PORTAL_HOME_URL=https://ingress.academy/portal/welcome/
```

## 4. Portal redirect allow-list

On ingress-academy, add the production callback to
`OIDC_INTERVIEW_REDIRECT_URIS` (and the `interview-web` admin row):

```text
https://your-frontend-domain/api/auth/callback
```

## 5. Smoke

1. `GET https://api…/api/v1/health/live` → 200
2. Frontend `/api/health` → ready (after migration + published questions)
3. Portal login → frontend **Portal** / SSO → `/api/auth/me` shows `authenticated`
4. **Çıxış** clears interview cookies
