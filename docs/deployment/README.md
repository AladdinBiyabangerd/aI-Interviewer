# Deploy Intervia (interview platform)

Two hosts are supported side by side:

| Surface | Recommended host | Also works on |
|---------|------------------|---------------|
| Next.js UI + assessment APIs (`frontend/`) | **Vercel** | Railway (Docker) |
| FastAPI identity / OIDC resource server (repo root) | **Railway** | any Docker host |
| PostgreSQL | Railway Postgres, Neon, or Vercel Marketplace Postgres | — |

## Recommended topology (SSO + assessment)

1. **Postgres** — Railway Postgres (or Neon). Same logical DB for Next assessment tables and the FastAPI Alembic schema.
2. **API** — Railway service from repo root (`Dockerfile` + `railway.toml`). Needed for Portal SSO (`/api/v1/identity/me`).
3. **Frontend** — Vercel project with Root Directory `frontend` (see [vercel.md](vercel.md)).

Portal (ingress-academy) stays on its own host; wire HTTPS issuer / audience / redirect URIs per [portal-oidc-sso.md](../portal-oidc-sso.md).

## All-Railway topology

Create three Railway services from the same GitHub repo:

| Service | Root directory | Config |
|---------|----------------|--------|
| `postgres` | — | Railway Postgres plugin |
| `api` | `/` (repo root) | [railway.md](railway.md) |
| `web` | `frontend` | [railway.md](railway.md#frontend-service) |

Retention cron (`vercel.json`) only runs on Vercel. On Railway, call `GET /api/maintenance/retention` daily with `Authorization: Bearer $CRON_SECRET` from an external scheduler.

## Local parity

```bash
./scripts/dev-up.sh
```

See the root [README](../../README.md) Quick start section.
