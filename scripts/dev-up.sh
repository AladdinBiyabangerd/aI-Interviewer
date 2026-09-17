#!/usr/bin/env bash
# Start local interview stack: Postgres + migrations + API (:8001) + Next.js (:3000).
# Same idea as ingress-academy README "Quick start" — one command, everything up.
#
#   ./scripts/dev-up.sh
#   SEED_QUESTION_BANK=1 ./scripts/dev-up.sh
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

API_PORT="${AI_INTERVIEWER_API_PORT:-8001}"
FE_PORT="${INTERVIEW_FRONTEND_PORT:-3000}"
DB_URL_FRONTEND="${DATABASE_URL:-postgresql://ai_interviewer:local-only@127.0.0.1:55432/ai_interviewer}"

echo "==> Repo: $ROOT"

ensure_docker() {
  if docker info >/dev/null 2>&1; then
    echo "==> Docker is running"
    return 0
  fi

  echo "==> Docker daemon is not running"
  if [[ "$(uname -s)" == "Darwin" ]] && [[ -d /Applications/Docker.app ]]; then
    echo "    Opening Docker Desktop…"
    open -a Docker
    echo "    Waiting for Docker (up to ~90s)…"
    for _ in $(seq 1 90); do
      if docker info >/dev/null 2>&1; then
        echo "==> Docker is ready"
        return 0
      fi
      sleep 1
    done
  fi

  echo ""
  echo "ERROR: Docker is not available."
  echo "  1. Open Docker Desktop and wait until it says Running"
  echo "  2. Re-run: ./scripts/dev-up.sh"
  echo ""
  exit 1
}

if [[ ! -f .env ]]; then
  cp .env.example .env
  echo "==> Created .env from .env.example"
fi

ensure_docker

echo "==> Postgres (docker compose)"
docker compose up --detach --wait --build postgres

echo "==> Python deps + migrations"
uv sync --frozen
uv run ai-interviewer-migrate check-artifact
uv run ai-interviewer-migrate upgrade

echo "==> Frontend .env.local"
mkdir -p frontend
if [[ ! -f frontend/.env.local ]]; then
  cat > frontend/.env.local <<EOF
NEXT_PUBLIC_APP_URL=http://localhost:${FE_PORT}
DATABASE_URL=${DB_URL_FRONTEND}
DATABASE_URL_UNPOOLED=${DB_URL_FRONTEND}
INTERVIEW_SESSION_SECRET=local-dev-interview-session-secret-min-32-bytes
CRON_SECRET=local-dev-cron-secret-at-least-32-bytes-xx
PORTAL_OIDC_ISSUER=http://127.0.0.1:8000/
PORTAL_OIDC_CLIENT_ID=interview-web
PORTAL_OIDC_REDIRECT_URI=http://localhost:${FE_PORT}/api/auth/callback
INTERVIEW_API_BASE_URL=http://127.0.0.1:${API_PORT}
EOF
  echo "    created frontend/.env.local"
else
  grep -q '^DATABASE_URL=' frontend/.env.local || echo "DATABASE_URL=${DB_URL_FRONTEND}" >> frontend/.env.local
  grep -q '^DATABASE_URL_UNPOOLED=' frontend/.env.local || echo "DATABASE_URL_UNPOOLED=${DB_URL_FRONTEND}" >> frontend/.env.local
  grep -q '^CRON_SECRET=' frontend/.env.local || echo "CRON_SECRET=local-dev-cron-secret-at-least-32-bytes-xx" >> frontend/.env.local
  grep -q '^INTERVIEW_SESSION_SECRET=' frontend/.env.local || echo "INTERVIEW_SESSION_SECRET=local-dev-interview-session-secret-min-32-bytes" >> frontend/.env.local
  grep -q '^INTERVIEW_API_BASE_URL=' frontend/.env.local || echo "INTERVIEW_API_BASE_URL=http://127.0.0.1:${API_PORT}" >> frontend/.env.local
  echo "    frontend/.env.local ready"
fi

echo "==> Frontend deps"
(cd frontend && npm install)

if [[ "${SEED_QUESTION_BANK:-0}" == "1" ]]; then
  echo "==> Seeding question bank"
  (cd frontend && npm run bank -- validate && npm run bank -- seed)
fi

cleanup() {
  echo ""
  echo "==> Stopping API (pid ${API_PID:-none})"
  if [[ -n "${API_PID:-}" ]]; then
    kill "${API_PID}" 2>/dev/null || true
  fi
}
trap cleanup EXIT INT TERM

echo "==> API  http://127.0.0.1:${API_PORT}"
uv run uvicorn ai_interviewer.main:app --host 127.0.0.1 --port "${API_PORT}" &
API_PID=$!
sleep 2

echo "==> App  http://localhost:${FE_PORT}"
echo "    Java http://localhost:${FE_PORT}/java"
echo "    SSO  needs ingress-academy on :8000 (optional)"
echo ""
(cd frontend && npm run dev -- --port "${FE_PORT}")
