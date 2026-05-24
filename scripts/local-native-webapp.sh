#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
ENV_FILE="${ENV_FILE:-$ROOT/.env.server}"

if [[ ! -f "$ENV_FILE" ]]; then
  echo "[ERROR] env file not found: $ENV_FILE" >&2
  exit 1
fi

cd "$ROOT"
set -a
source "$ENV_FILE"
set +a

export POSTGRES_USER="${POSTGRES_USER:-postgres}"
export POSTGRES_PASSWORD="${POSTGRES_PASSWORD:-postgres}"
export POSTGRES_DB="${POSTGRES_DB:-ai_holdings}"
export POSTGRES_HOST_PORT="${POSTGRES_HOST_PORT:-55432}"
export DATA_SERVICE_HTTP_PORT="${DATA_SERVICE_HTTP_PORT:-${DATA_SERVICE_PORT:-58000}}"
export WEBAPP_HTTP_PORT="${WEBAPP_HTTP_PORT:-3000}"
export DATABASE_URL="postgresql://${POSTGRES_USER}:${POSTGRES_PASSWORD}@127.0.0.1:${POSTGRES_HOST_PORT}/${POSTGRES_DB}"
export WEBAPP_DATABASE_URL="$DATABASE_URL"
export DATA_SERVICE_URL="http://127.0.0.1:${DATA_SERVICE_HTTP_PORT}"
export NEXT_PUBLIC_DATA_SERVICE_URL="$DATA_SERVICE_URL"

cd "$ROOT/webapp"
if [[ -f "$ROOT/webapp/.next/standalone/server.js" ]]; then
  mkdir -p "$ROOT/webapp/.next/standalone/.next"
  if [[ -d "$ROOT/webapp/.next/static" ]]; then
    cp -R "$ROOT/webapp/.next/static" "$ROOT/webapp/.next/standalone/.next/"
  fi
  if [[ -d "$ROOT/webapp/public" ]]; then
    cp -R "$ROOT/webapp/public" "$ROOT/webapp/.next/standalone/"
  fi

  export HOSTNAME=127.0.0.1
  export PORT="$WEBAPP_HTTP_PORT"
  exec node "$ROOT/webapp/.next/standalone/server.js"
fi

exec npm run start -- -H 127.0.0.1 -p "$WEBAPP_HTTP_PORT"
