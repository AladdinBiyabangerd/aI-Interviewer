#!/bin/sh
# Materialize Railway/env secrets into files so hosted Settings validators can
# require *_FILE mounts (ADR-0006 / ADR-0007) without a Kubernetes secret volume.
set -eu

SECRETS_DIR="${AI_INTERVIEWER_SECRETS_DIR:-/tmp/ai-interviewer-secrets}"
mkdir -p "$SECRETS_DIR"
chmod 700 "$SECRETS_DIR"

write_secret() {
  target="$1"
  value="$2"
  # Avoid trailing newline so URLs / JSON stay exact.
  printf '%s' "$value" >"$target"
  chmod 600 "$target"
}

if [ -z "${AI_INTERVIEWER_DATABASE_URL_FILE:-}" ]; then
  if [ -n "${AI_INTERVIEWER_DATABASE_URL:-}" ]; then
    write_secret "$SECRETS_DIR/database-url" "$AI_INTERVIEWER_DATABASE_URL"
    export AI_INTERVIEWER_DATABASE_URL_FILE="$SECRETS_DIR/database-url"
    unset AI_INTERVIEWER_DATABASE_URL
  elif [ -n "${DATABASE_URL:-}" ]; then
    write_secret "$SECRETS_DIR/database-url" "$DATABASE_URL"
    export AI_INTERVIEWER_DATABASE_URL_FILE="$SECRETS_DIR/database-url"
  fi
fi

if [ -z "${AI_INTERVIEWER_PRIVACY_KEYRING_FILE:-}" ] && [ -n "${AI_INTERVIEWER_PRIVACY_KEYRING:-}" ]; then
  write_secret "$SECRETS_DIR/privacy-keyring.json" "$AI_INTERVIEWER_PRIVACY_KEYRING"
  export AI_INTERVIEWER_PRIVACY_KEYRING_FILE="$SECRETS_DIR/privacy-keyring.json"
  unset AI_INTERVIEWER_PRIVACY_KEYRING
fi

export PORT="${PORT:-8000}"

if [ "$#" -gt 0 ]; then
  exec "$@"
fi
exec ai-interviewer-api
