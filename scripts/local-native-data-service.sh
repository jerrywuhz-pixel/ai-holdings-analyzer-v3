#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
ENV_FILE="${ENV_FILE:-$ROOT/.env.server}"
PYTHON_BIN="${PYTHON_BIN:-$ROOT/.runtime/native/venv-py/bin/python}"

if [[ ! -f "$ENV_FILE" ]]; then
  echo "[ERROR] env file not found: $ENV_FILE" >&2
  exit 1
fi

if [[ ! -x "$PYTHON_BIN" ]]; then
  echo "[ERROR] Python runtime not found: $PYTHON_BIN" >&2
  echo "Run the local native bootstrap before starting this service." >&2
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
export REDIS_HOST_PORT="${REDIS_HOST_PORT:-56379}"
export DATA_SERVICE_HTTP_PORT="${DATA_SERVICE_HTTP_PORT:-${DATA_SERVICE_PORT:-58000}}"
export DATA_SERVICE_PORT="$DATA_SERVICE_HTTP_PORT"
export DATABASE_URL="postgresql://${POSTGRES_USER}:${POSTGRES_PASSWORD}@127.0.0.1:${POSTGRES_HOST_PORT}/${POSTGRES_DB}"
export REDIS_URL="redis://127.0.0.1:${REDIS_HOST_PORT}/0"
export DATA_SERVICE_URL="http://127.0.0.1:${DATA_SERVICE_HTTP_PORT}"

# Mac native direct mode talks to the local sidecar. Cloud production still uses
# user_local_polling through the control-plane poll/upload endpoints.
if [[ "${FUTU_NATIVE_DIRECT_ENABLED:-true}" == "true" || "${FUTU_NATIVE_DIRECT_ENABLED:-true}" == "1" ]]; then
  export FUTU_CONNECTOR_MODE="${FUTU_NATIVE_CONNECTOR_MODE:-local_connector}"
  export FUTU_CONNECTOR_BASE_URL="${FUTU_NATIVE_CONNECTOR_BASE_URL:-http://127.0.0.1:${FUTU_SIDECAR_PORT:-8765}}"
fi
export FUTU_CONNECTOR_READ_ONLY="${FUTU_CONNECTOR_READ_ONLY:-true}"

export PYTHONPATH="$ROOT/data-service/src:$ROOT${PYTHONPATH:+:$PYTHONPATH}"
cd "$ROOT/data-service"
exec "$PYTHON_BIN" -m uvicorn src.main:app --host 127.0.0.1 --port "$DATA_SERVICE_HTTP_PORT" --workers "${DATA_SERVICE_WORKERS:-2}"
