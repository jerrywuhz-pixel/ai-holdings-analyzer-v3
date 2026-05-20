#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PYTHON_BIN="${PYTHON_BIN:-python3}"
CODEX_BIN="${CODEX_BIN:-codex}"
BRIDGE_HOST="${CODEX_BRIDGE_HOST:-127.0.0.1}"
BRIDGE_PORT="${CODEX_BRIDGE_PORT:-8091}"
AUTH_PROFILE="${OPENAI_CODEX_AUTH_PROFILE:-${HERMES_AUTH_PROFILE_ID:-system-pro}}"
BRIDGE_API_KEY="${OPENAI_CODEX_BRIDGE_API_KEY:-${CODEX_BRIDGE_API_KEY:-}}"

export PYTHONPATH="$ROOT_DIR:${PYTHONPATH:-}"

usage() {
  cat <<'USAGE'
Usage: scripts/openai-codex-auth-bridge.sh <status|login|start|smoke>

Commands:
  status  Show Codex CLI version and ChatGPT login status.
  login   Generate a Codex device-auth URL/code and wait for authorization.
  start   Start the local OpenAI-compatible bridge on CODEX_BRIDGE_HOST/PORT.
  smoke   Call the running bridge with openai-codex/gpt-5.5.
USAGE
}

status() {
  "$CODEX_BIN" --version
  "$CODEX_BIN" login status
}

login() {
  "$CODEX_BIN" login --device-auth
}

start() {
  local server_cmd=("$PYTHON_BIN")
  if ! "$PYTHON_BIN" - <<'PY' >/dev/null 2>&1
import fastapi  # noqa: F401
import uvicorn  # noqa: F401
PY
  then
    if command -v uv >/dev/null 2>&1; then
      server_cmd=(
        uv run
        --with-requirements "$ROOT_DIR/data-service/requirements.txt"
        --with-requirements "$ROOT_DIR/local_connectors/requirements.txt"
        python
      )
    else
      echo "FastAPI/uvicorn are missing for $PYTHON_BIN and uv is not installed." >&2
      exit 1
    fi
  fi

  export CODEX_BRIDGE_MODE="${CODEX_BRIDGE_MODE:-command}"
  export CODEX_BRIDGE_AUTH_PROFILE="${CODEX_BRIDGE_AUTH_PROFILE:-$AUTH_PROFILE}"
  export CODEX_BRIDGE_HOST="$BRIDGE_HOST"
  export CODEX_BRIDGE_PORT="$BRIDGE_PORT"
  export CODEX_BRIDGE_TIMEOUT_SECONDS="${CODEX_BRIDGE_TIMEOUT_SECONDS:-360}"
  export CODEX_BRIDGE_COMMAND="${CODEX_BRIDGE_COMMAND:-$PYTHON_BIN -m local_connectors.openai_codex_bridge.codex_cli_adapter}"
  if [[ -n "$BRIDGE_API_KEY" ]]; then
    export CODEX_BRIDGE_API_KEY="$BRIDGE_API_KEY"
  fi
  exec "${server_cmd[@]}" -m local_connectors.openai_codex_bridge.server
}

smoke() {
  local base_url="http://${BRIDGE_HOST}:${BRIDGE_PORT}"

  curl -fsS "${base_url}/health"
  printf '\n'
  if [[ -n "$BRIDGE_API_KEY" ]]; then
    curl -fsS \
      -H "Content-Type: application/json" \
      -H "Authorization: Bearer ${BRIDGE_API_KEY}" \
      -d '{"model":"openai-codex/gpt-5.5","messages":[{"role":"user","content":"Respond exactly with CODEX_AUTH_OK."}]}' \
      "${base_url}/v1/chat/completions"
  else
    curl -fsS \
      -H "Content-Type: application/json" \
      -d '{"model":"openai-codex/gpt-5.5","messages":[{"role":"user","content":"Respond exactly with CODEX_AUTH_OK."}]}' \
      "${base_url}/v1/chat/completions"
  fi
  printf '\n'
}

command="${1:-status}"
case "$command" in
  status) status ;;
  login) login ;;
  start) start ;;
  smoke) smoke ;;
  -h|--help|help) usage ;;
  *)
    usage >&2
    exit 2
    ;;
esac
