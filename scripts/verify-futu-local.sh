#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
ENV_FILE="$PROJECT_ROOT/.env"

MODE="mock"
PYTHON_BIN="${PYTHON_BIN:-}"
TEMP_DATA_SERVICE_PID=""
TEMP_DATA_SERVICE_LOG="$PROJECT_ROOT/.tmp-verify-data-service.log"

GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

log_info()  { echo -e "${GREEN}[INFO]${NC} $*"; }
log_warn()  { echo -e "${YELLOW}[WARN]${NC} $*"; }
log_error() { echo -e "${RED}[ERROR]${NC} $*"; }

usage() {
  cat <<'EOF'
Usage: ./scripts/verify-futu-local.sh [options]

Options:
  --mode <mock|real|both>  Which Futu smoke to run (default: mock)
  --python <path>          Use a specific Python interpreter
  --help                   Show this help text

Environment:
  SMOKE_FUTU_MOCK_PERSIST=true  Persist mock snapshots. Defaults to false so mock smoke cannot
                                overwrite the latest real portfolio view for the default tenant.
  SMOKE_FUTU_MOCK_TENANT_ID     Optional tenant id for persisted mock smoke when a dedicated
                                smoke tenant exists in the target database.
EOF
}

load_env_defaults() {
  local file="$1"
  local raw_line line key value

  [[ -f "$file" ]] || return 0

  while IFS= read -r raw_line || [[ -n "$raw_line" ]]; do
    line="${raw_line#"${raw_line%%[![:space:]]*}"}"
    line="${line%"${line##*[![:space:]]}"}"
    [[ -z "$line" || "$line" == \#* || "$line" != *=* ]] && continue

    key="${line%%=*}"
    value="${line#*=}"
    key="${key//[[:space:]]/}"
    value="${value#"${value%%[![:space:]]*}"}"
    value="${value%"${value##*[![:space:]]}"}"
    value="${value%$'\r'}"

    if [[ "$value" == \"*\" && "$value" == *\" ]]; then
      value="${value:1:${#value}-2}"
    elif [[ "$value" == \'* && "$value" == *\' ]]; then
      value="${value:1:${#value}-2}"
    fi

    if [[ -n "$key" && -z "${!key+x}" ]]; then
      export "$key=$value"
    fi
  done < "$file"
}

resolve_python() {
  if [[ -n "$PYTHON_BIN" ]]; then
    return 0
  fi
  if [[ -x "$PROJECT_ROOT/.venv/bin/python" ]]; then
    PYTHON_BIN="$PROJECT_ROOT/.venv/bin/python"
  elif [[ -x "$PROJECT_ROOT/data-service/.venv/bin/python" ]]; then
    PYTHON_BIN="$PROJECT_ROOT/data-service/.venv/bin/python"
  elif command -v python3 >/dev/null 2>&1; then
    PYTHON_BIN="python3"
  else
    PYTHON_BIN="python"
  fi
}

is_port_open() {
  local host="$1"
  local port="$2"

  "$PYTHON_BIN" - "$host" "$port" <<'PY'
import socket
import sys

host = sys.argv[1]
port = int(sys.argv[2])

try:
    with socket.create_connection((host, port), timeout=1):
        pass
except OSError:
    raise SystemExit(1)
raise SystemExit(0)
PY
}

read_json_field() {
  local url="$1"
  local field="$2"

  "$PYTHON_BIN" - "$url" "$field" <<'PY'
import json
import sys
import urllib.request

url = sys.argv[1]
field = sys.argv[2]

with urllib.request.urlopen(url, timeout=5) as response:
    payload = json.loads(response.read().decode("utf-8"))

value = payload
for part in field.split("."):
    if not isinstance(value, dict):
        value = None
        break
    value = value.get(part)

if value is None:
    raise SystemExit(1)
print(value)
PY
}

parse_url_part() {
  local url="$1"
  local field="$2"

  "$PYTHON_BIN" - "$url" "$field" <<'PY'
from urllib.parse import urlparse
import sys

parsed = urlparse(sys.argv[1])
field = sys.argv[2]

if field == "hostname":
    print(parsed.hostname or "")
elif field == "port":
    print(parsed.port or (443 if parsed.scheme == "https" else 80))
else:
    raise SystemExit(1)
PY
}

cleanup_temp_data_service() {
  if [[ -n "$TEMP_DATA_SERVICE_PID" ]]; then
    kill "$TEMP_DATA_SERVICE_PID" >/dev/null 2>&1 || true
    wait "$TEMP_DATA_SERVICE_PID" >/dev/null 2>&1 || true
  fi
}

ensure_data_service() {
  local base_url="${DATA_SERVICE_BASE_URL:-http://127.0.0.1:8000}"
  local health_url="${base_url%/}/health"
  local host
  local port
  local attempt

  if read_json_field "$health_url" "status" >/dev/null 2>&1; then
    return 0
  fi

  host="$(parse_url_part "$base_url" "hostname")"
  port="$(parse_url_part "$base_url" "port")"

  case "$host" in
    127.0.0.1|localhost)
      ;;
    *)
      log_error "Data service is not reachable at ${health_url}"
      log_error "Set DATA_SERVICE_BASE_URL to a reachable service, or run this smoke against localhost."
      return 1
      ;;
  esac

  if is_port_open "$host" "$port"; then
    log_error "Port ${host}:${port} is open, but ${health_url} did not return a healthy response"
    return 1
  fi

  log_info "Starting temporary data-service at ${base_url}"
  (
    cd "$PROJECT_ROOT/data-service"
    PYTHONPATH="$PROJECT_ROOT/data-service/src:$PROJECT_ROOT${PYTHONPATH:+:$PYTHONPATH}" \
      "$PYTHON_BIN" -m uvicorn main:app --host "$host" --port "$port" --log-level warning \
      >"$TEMP_DATA_SERVICE_LOG" 2>&1
  ) &
  TEMP_DATA_SERVICE_PID="$!"
  trap cleanup_temp_data_service EXIT

  for attempt in {1..30}; do
    if read_json_field "$health_url" "status" >/dev/null 2>&1; then
      return 0
    fi
    sleep 0.5
  done

  log_error "Temporary data-service did not become ready. Recent log:"
  tail -n 40 "$TEMP_DATA_SERVICE_LOG" 2>/dev/null || true
  return 1
}

run_mock() {
  ensure_data_service
  log_info "Running mock Futu smoke"
  (
    cd "$PROJECT_ROOT"
    SMOKE_FUTU_CONNECTOR_MODE=local_mock \
    SMOKE_FUTU_PERSIST="${SMOKE_FUTU_MOCK_PERSIST:-false}" \
    SMOKE_TENANT_ID="${SMOKE_FUTU_MOCK_TENANT_ID:-${SMOKE_TENANT_ID:-00000000-0000-0000-0000-000000000000}}" \
    "$PYTHON_BIN" scripts/live_futu_sync_smoke.py
  )
}

run_real() {
  local opend_host="${FUTU_OPEND_HOST:-127.0.0.1}"
  local opend_port="${FUTU_OPEND_PORT:-11111}"
  local sidecar_port="${FUTU_SIDECAR_PORT:-8765}"
  local sidecar_base_url="${FUTU_CONNECTOR_BASE_URL:-http://127.0.0.1:${sidecar_port}}"
  local health_url="${sidecar_base_url%/}/health"

  if ! is_port_open "$opend_host" "$opend_port"; then
    log_error "OpenD not detected at ${opend_host}:${opend_port}"
    log_error "Real smoke is opt-in and requires local OpenD plus a sidecar running in real mode."
    log_error "Next step: start and log into Futu OpenD locally, confirm port ${opend_port} is listening, then rerun ./scripts/verify-futu-local.sh --mode real"
    return 1
  fi

  local sidecar_mode
  if ! sidecar_mode="$(read_json_field "$health_url" "mode" 2>/dev/null)"; then
    log_error "Futu sidecar health check failed at ${health_url}"
    log_error "Start it with: START_FUTU_SIDECAR=true FUTU_SIDECAR_MODE=real ./scripts/start-local-services.sh"
    log_error "Then rerun: ./scripts/verify-futu-local.sh --mode real"
    return 1
  fi

  if [[ "$sidecar_mode" != "real" ]]; then
    log_error "Futu sidecar is reachable but reports mode=${sidecar_mode}"
    log_error "Restart it in real mode before running real smoke."
    log_error "Next step: START_FUTU_SIDECAR=true FUTU_SIDECAR_MODE=real ./scripts/start-local-services.sh"
    return 1
  fi

  ensure_data_service
  log_info "Running real Futu smoke against OpenD at ${opend_host}:${opend_port}"
  (
    cd "$PROJECT_ROOT"
    SMOKE_FUTU_CONNECTOR_MODE=local_connector \
    FUTU_CONNECTOR_MODE=local_connector \
    FUTU_CONNECTOR_BASE_URL="${sidecar_base_url%/}" \
    "$PYTHON_BIN" scripts/live_futu_sync_smoke.py
  )
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --mode)
      MODE="${2:-mock}"
      shift 2
      ;;
    --python)
      PYTHON_BIN="${2:-}"
      shift 2
      ;;
    --help)
      usage
      exit 0
      ;;
    *)
      log_error "Unknown argument: $1"
      usage
      exit 1
      ;;
  esac
done

load_env_defaults "$ENV_FILE"
resolve_python
export PYTHONPATH="$PROJECT_ROOT${PYTHONPATH:+:$PYTHONPATH}"

case "$MODE" in
  mock)
    run_mock
    echo "PASS futu-local mock"
    ;;
  real)
    run_real
    echo "PASS futu-local real"
    ;;
  both)
    run_mock
    run_real
    echo "PASS futu-local mock+real"
    ;;
  *)
    log_error "--mode must be mock, real, or both"
    exit 1
    ;;
esac
