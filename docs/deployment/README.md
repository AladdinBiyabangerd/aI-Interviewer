# Deploy Intervia (interview platform)

Two hosts are supported side by side:

| Surface | Recommended host | Also works on |
|---------|------------------|---------------|
| Next.js UI + assessment APIs (`frontend/`) | **Vercel** | Railway (Docker) |
| FastAPI platform API (repo root) | **Railway** | any Docker host |
| PostgreSQL | Railway Postgres, Neon, or Vercel Marketplace Postgres | — |

## Recommended topology (assessment + admin editor)

1. **Postgres** — Railway Postgres (or Neon). Same logical DB for Next assessment tables and the FastAPI Alembic schema.
2. **API** — Railway service from repo root (`Dockerfile` + `railway.toml`) for the Python platform and migrations.
3. **Frontend** — Vercel project with Root Directory `frontend` (see [vercel.md](vercel.md)).

The current frontend admin login is standalone. Portal SSO integration is deferred.

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
