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

export FUTU_SIDECAR_MODE="${FUTU_SIDECAR_MODE:-real}"
export FUTU_SIDECAR_HOST="${FUTU_SIDECAR_HOST:-127.0.0.1}"
export FUTU_SIDECAR_PORT="${FUTU_SIDECAR_PORT:-8765}"
export FUTU_OPEND_HOST="${FUTU_OPEND_HOST:-127.0.0.1}"
export FUTU_OPEND_PORT="${FUTU_OPEND_PORT:-11111}"
export FUTU_CONNECTOR_READ_ONLY="${FUTU_CONNECTOR_READ_ONLY:-true}"
export PYTHONPATH="$ROOT${PYTHONPATH:+:$PYTHONPATH}"

if ! "$PYTHON_BIN" -c "import futu" >/dev/null 2>&1; then
  echo "[ERROR] futu-api is not installed in $PYTHON_BIN" >&2
  echo "Install it with:" >&2
  echo "  uv pip install --python \"$PYTHON_BIN\" -r \"$ROOT/local_connectors/requirements.txt\"" >&2
  exit 1
fi

exec "$PYTHON_BIN" -m local_connectors.futu_opend.server
