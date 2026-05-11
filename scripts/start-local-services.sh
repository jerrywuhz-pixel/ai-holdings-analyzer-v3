#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
ENV_FILE="$PROJECT_ROOT/.env"
RUN_DIR="$PROJECT_ROOT/.run"
LOG_DIR="$PROJECT_ROOT/.logs"

mkdir -p "$RUN_DIR" "$LOG_DIR"

load_env_defaults() {
  local file="$1"
  local raw_line line key value
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

if [[ -f "$ENV_FILE" ]]; then
  load_env_defaults "$ENV_FILE"
fi

DATA_SERVICE_PORT="${DATA_SERVICE_PORT:-8000}"
OPENCLAW_PORT="${OPENCLAW_PORT:-8080}"
WEBAPP_PORT="${WEBAPP_PORT:-3000}"
FUTU_SIDECAR_PORT="${FUTU_SIDECAR_PORT:-8765}"
START_WORKERS="${START_WORKERS:-true}"
START_FUTU_SIDECAR="${START_FUTU_SIDECAR:-false}"
POST_CONFIRMATION_WORKER_POLL_INTERVAL_SECONDS="${POST_CONFIRMATION_WORKER_POLL_INTERVAL_SECONDS:-2}"
OPENCLAW_OUTBOX_WORKER_POLL_INTERVAL_SECONDS="${OPENCLAW_OUTBOX_WORKER_POLL_INTERVAL_SECONDS:-2}"
OPENCLAW_DELIVERY_MODE="${OPENCLAW_DELIVERY_MODE:-log}"

if [[ "${DEPLOYMENT_MODE:-local}" == "local" && "$OPENCLAW_DELIVERY_MODE" == "disabled" ]]; then
  OPENCLAW_DELIVERY_MODE="log"
fi

is_port_listening() {
  local port="$1"
  lsof -nP -iTCP:"$port" -sTCP:LISTEN >/dev/null 2>&1
}

is_placeholder() {
  local value="${1:-}"
  [[ -z "$value" || "$value" == your-* || "$value" == *your-project* || "$value" == replace-with-* || "$value" == placeholder* ]]
}

disable_placeholder_supabase() {
  if is_placeholder "${SUPABASE_SERVICE_ROLE_KEY:-}" || is_placeholder "${SUPABASE_ANON_KEY:-}"; then
    export SUPABASE_URL=""
    export SUPABASE_SERVICE_ROLE_KEY=""
    export SUPABASE_ANON_KEY=""
    export OPENCLAW_SKILL_KEY=""
  fi
}

start_data_service() {
  if is_port_listening "$DATA_SERVICE_PORT"; then
    echo "[INFO] data-service already listening on :$DATA_SERVICE_PORT"
    return
  fi

  echo "[INFO] Starting data-service on :$DATA_SERVICE_PORT"
  (
    cd "$PROJECT_ROOT/data-service/src"
    PYTHONPATH="$PROJECT_ROOT/data-service/src:$PROJECT_ROOT" nohup python3 -m uvicorn main:app --host 127.0.0.1 --port "$DATA_SERVICE_PORT" \
      > "$LOG_DIR/data-service.log" 2>&1 </dev/null &
    echo $! > "$RUN_DIR/data-service.pid"
  )
}

start_openclaw() {
  if is_port_listening "$OPENCLAW_PORT"; then
    echo "[INFO] openclaw already listening on :$OPENCLAW_PORT"
    return
  fi

  echo "[INFO] Starting openclaw on :$OPENCLAW_PORT"
  (
    cd "$PROJECT_ROOT"
    PORT="$OPENCLAW_PORT" PYTHONPATH="$PROJECT_ROOT" nohup python3 -m uvicorn openclaw.gateway_app:app --host 127.0.0.1 --port "$OPENCLAW_PORT" \
      > "$LOG_DIR/openclaw.log" 2>&1 </dev/null &
    echo $! > "$RUN_DIR/openclaw.pid"
  )
}

start_webapp() {
  if is_port_listening "$WEBAPP_PORT"; then
    echo "[INFO] webapp already listening on :$WEBAPP_PORT"
    return
  fi

  echo "[INFO] Starting webapp on :$WEBAPP_PORT"
  (
    cd "$PROJECT_ROOT/webapp"
    nohup npm run dev -- --hostname 127.0.0.1 --port "$WEBAPP_PORT" \
      > "$LOG_DIR/webapp.log" 2>&1 </dev/null &
    echo $! > "$RUN_DIR/webapp.pid"
  )
}

start_futu_sidecar() {
  if is_port_listening "$FUTU_SIDECAR_PORT"; then
    echo "[INFO] futu sidecar already listening on :$FUTU_SIDECAR_PORT"
    return
  fi

  echo "[INFO] Starting futu sidecar on :$FUTU_SIDECAR_PORT (mode=${FUTU_SIDECAR_MODE:-mock})"
  (
    cd "$PROJECT_ROOT"
    FUTU_SIDECAR_PORT="$FUTU_SIDECAR_PORT" PYTHONPATH="$PROJECT_ROOT" nohup python3 -m local_connectors.futu_opend.server \
      > "$LOG_DIR/futu-sidecar.log" 2>&1 </dev/null &
    echo $! > "$RUN_DIR/futu-sidecar.pid"
  )
}

is_pid_file_running() {
  local pid_file="$1"
  if [[ ! -f "$pid_file" ]]; then
    return 1
  fi
  local pid
  pid="$(cat "$pid_file")"
  [[ -n "$pid" ]] && kill -0 "$pid" >/dev/null 2>&1
}

start_post_confirmation_worker() {
  local pid_file="$RUN_DIR/post-confirmation-worker.pid"
  if is_pid_file_running "$pid_file"; then
    echo "[INFO] post-confirmation worker already running ($(cat "$pid_file"))"
    return
  fi

  if [[ -z "${SUPABASE_URL:-}" || -z "${SUPABASE_SERVICE_ROLE_KEY:-}" ]]; then
    echo "[WARN] Skipping post-confirmation worker because Supabase env is not configured"
    return
  fi

  echo "[INFO] Starting post-confirmation worker"
  (
    cd "$PROJECT_ROOT"
    PYTHONPATH="$PROJECT_ROOT" nohup python3 -m openclaw.gateway.post_confirmation_worker \
      --poll-interval "$POST_CONFIRMATION_WORKER_POLL_INTERVAL_SECONDS" \
      > "$LOG_DIR/post-confirmation-worker.log" 2>&1 </dev/null &
    echo $! > "$pid_file"
  )
}

start_outbox_worker() {
  local pid_file="$RUN_DIR/outbox-worker.pid"
  if is_pid_file_running "$pid_file"; then
    echo "[INFO] outbox worker already running ($(cat "$pid_file"))"
    return
  fi

  if [[ -z "${SUPABASE_URL:-}" || -z "${SUPABASE_SERVICE_ROLE_KEY:-}" ]]; then
    echo "[WARN] Skipping outbox worker because Supabase env is not configured"
    return
  fi

  echo "[INFO] Starting outbox worker (mode=$OPENCLAW_DELIVERY_MODE)"
  (
    cd "$PROJECT_ROOT"
    OPENCLAW_DELIVERY_MODE="$OPENCLAW_DELIVERY_MODE" PYTHONPATH="$PROJECT_ROOT" nohup python3 -m openclaw.gateway.outbox_worker \
      --poll-interval "$OPENCLAW_OUTBOX_WORKER_POLL_INTERVAL_SECONDS" \
      > "$LOG_DIR/outbox-worker.log" 2>&1 </dev/null &
    echo $! > "$pid_file"
  )
}

wait_for_http() {
  local name="$1"
  local url="$2"
  local attempts=40
  local i
  for ((i = 1; i <= attempts; i++)); do
    if curl -fsS "$url" >/dev/null 2>&1; then
      echo "[INFO] $name is healthy: $url"
      return
    fi
    sleep 0.5
  done
  echo "[WARN] $name did not pass health check: $url"
}

disable_placeholder_supabase
start_data_service
start_openclaw
start_webapp
if [[ "$START_FUTU_SIDECAR" == "true" || "$START_FUTU_SIDECAR" == "1" || "$START_FUTU_SIDECAR" == "yes" ]]; then
  start_futu_sidecar
else
  echo "[INFO] Futu sidecar disabled (START_FUTU_SIDECAR=$START_FUTU_SIDECAR)"
fi
if [[ "$START_WORKERS" == "true" || "$START_WORKERS" == "1" || "$START_WORKERS" == "yes" ]]; then
  start_post_confirmation_worker
  start_outbox_worker
else
  echo "[INFO] Background workers disabled (START_WORKERS=$START_WORKERS)"
fi

wait_for_http "data-service" "http://127.0.0.1:$DATA_SERVICE_PORT/health"
wait_for_http "openclaw" "http://127.0.0.1:$OPENCLAW_PORT/health"
wait_for_http "webapp" "http://127.0.0.1:$WEBAPP_PORT"
if [[ "$START_FUTU_SIDECAR" == "true" || "$START_FUTU_SIDECAR" == "1" || "$START_FUTU_SIDECAR" == "yes" ]]; then
  wait_for_http "futu-sidecar" "http://127.0.0.1:$FUTU_SIDECAR_PORT/health"
fi

echo "[INFO] Local services started"
echo "  Data Service: http://127.0.0.1:$DATA_SERVICE_PORT"
echo "  OpenClaw:     http://127.0.0.1:$OPENCLAW_PORT"
echo "  WebApp:       http://127.0.0.1:$WEBAPP_PORT"
echo "  Futu Sidecar: START_FUTU_SIDECAR=$START_FUTU_SIDECAR, http://127.0.0.1:$FUTU_SIDECAR_PORT"
echo "  Workers:      START_WORKERS=$START_WORKERS, OPENCLAW_DELIVERY_MODE=$OPENCLAW_DELIVERY_MODE"
echo "  Logs:         $LOG_DIR"
echo "  Verify note:  stop the webapp dev server before ./scripts/verify-p0.sh if you need a clean npm run build (.next is shared)"
