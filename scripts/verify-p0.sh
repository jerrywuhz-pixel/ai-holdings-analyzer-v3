#!/usr/bin/env bash
set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
ENV_FILE="$PROJECT_ROOT/.env"
MIGRATIONS_DIR="$PROJECT_ROOT/supabase/migrations"
SEED_DIR="$PROJECT_ROOT/supabase/seed"
RUN_DIR="$PROJECT_ROOT/.run"

GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

RUN_DB_MIGRATION=true
RUN_FUTU_REAL=false
RUN_LIVE_E2E=false
RUN_STRICT_LIVE_E2E=false
RUN_LIVE_CONFIRMATION=false
PYTHON_BIN="${PYTHON_BIN:-}"

declare -a STAGE_NAMES=()
declare -a STAGE_CLASSES=()
declare -a STAGE_RESULTS=()
declare -a STAGE_DETAILS=()

log_info()  { echo -e "${GREEN}[INFO]${NC} $*"; }
log_warn()  { echo -e "${YELLOW}[WARN]${NC} $*"; }
log_error() { echo -e "${RED}[ERROR]${NC} $*"; }

usage() {
  cat <<'EOF'
Usage: ./scripts/verify-p0.sh [options]

Options:
  --python <path>       Use a specific Python interpreter
  --skip-db-migration   Skip the DB migration stage
  --with-futu-real      Run the optional real Futu smoke after mock smoke
  --with-live-e2e       Run optional live E2E smoke against configured local hooks/services
  --with-live-confirmation
                        Run optional real OpenClaw confirmation/delivery smoke
  --strict-live-e2e     Fail optional live E2E when any step is skipped
  --help                Show this help text
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
  elif command -v python3.11 >/dev/null 2>&1; then
    PYTHON_BIN="python3.11"
  else
    PYTHON_BIN="python"
  fi
}

record_stage() {
  STAGE_NAMES+=("$1")
  STAGE_CLASSES+=("$2")
  STAGE_RESULTS+=("$3")
  STAGE_DETAILS+=("$4")
}

run_stage() {
  local stage_class="$1"
  local stage="$2"
  local detail="$3"
  local exit_code=0
  shift 3

  log_info "Running ${stage}: ${detail}"
  "$@"
  exit_code=$?
  if [[ "$exit_code" -eq 0 ]]; then
    record_stage "$stage" "$stage_class" "PASS" "$detail"
    return 0
  fi

  record_stage "$stage" "$stage_class" "FAIL" "${detail} (exit ${exit_code})"
  log_error "${stage} failed with exit ${exit_code}"
  return 1
}

skip_stage() {
  local stage_class="$1"
  local stage="$2"
  local detail="$3"
  record_stage "$stage" "$stage_class" "SKIP" "$detail"
  log_warn "Skipping ${stage}: ${detail}"
}

print_summary() {
  local required_pass=0
  local required_fail=0
  local required_skip=0
  local optional_pass=0
  local optional_fail=0
  local optional_skip=0
  local idx
  local stage_class
  local status

  echo
  echo "P0 verify summary"
  echo "-----------------"

  for idx in "${!STAGE_NAMES[@]}"; do
    stage_class="${STAGE_CLASSES[$idx]}"
    status="${STAGE_RESULTS[$idx]}"
    case "${stage_class}:${status}" in
      required:PASS) required_pass=$((required_pass + 1)) ;;
      required:FAIL) required_fail=$((required_fail + 1)) ;;
      required:SKIP) required_skip=$((required_skip + 1)) ;;
      optional:PASS) optional_pass=$((optional_pass + 1)) ;;
      optional:FAIL) optional_fail=$((optional_fail + 1)) ;;
      optional:SKIP) optional_skip=$((optional_skip + 1)) ;;
    esac
  done

  echo "Required"
  for idx in "${!STAGE_NAMES[@]}"; do
    [[ "${STAGE_CLASSES[$idx]}" == "required" ]] || continue
    status="${STAGE_RESULTS[$idx]}"
    case "$status" in
      PASS) printf "${GREEN}PASS${NC} %-20s %s\n" "${STAGE_NAMES[$idx]}" "${STAGE_DETAILS[$idx]}" ;;
      FAIL) printf "${RED}FAIL${NC} %-20s %s\n" "${STAGE_NAMES[$idx]}" "${STAGE_DETAILS[$idx]}" ;;
      SKIP) printf "${YELLOW}SKIP${NC} %-20s %s\n" "${STAGE_NAMES[$idx]}" "${STAGE_DETAILS[$idx]}" ;;
    esac
  done

  echo
  echo "Optional"
  for idx in "${!STAGE_NAMES[@]}"; do
    [[ "${STAGE_CLASSES[$idx]}" == "optional" ]] || continue
    status="${STAGE_RESULTS[$idx]}"
    case "$status" in
      PASS) printf "${GREEN}PASS${NC} %-20s %s\n" "${STAGE_NAMES[$idx]}" "${STAGE_DETAILS[$idx]}" ;;
      FAIL) printf "${RED}FAIL${NC} %-20s %s\n" "${STAGE_NAMES[$idx]}" "${STAGE_DETAILS[$idx]}" ;;
      SKIP) printf "${YELLOW}SKIP${NC} %-20s %s\n" "${STAGE_NAMES[$idx]}" "${STAGE_DETAILS[$idx]}" ;;
    esac
  done

  echo "-----------------"
  echo "required: passed=${required_pass} failed=${required_fail} skipped=${required_skip}"
  echo "optional: passed=${optional_pass} failed=${optional_fail} skipped=${optional_skip}"

  if [[ "$required_fail" -eq 0 && "$required_skip" -eq 0 ]]; then
    echo "gate: READY_FOR_NEXT_STAGE"
    return 0
  fi

  if [[ "$required_fail" -gt 0 ]]; then
    echo "gate: BLOCKED_REQUIRED_FAILURES"
  else
    echo "gate: INCOMPLETE_REQUIRED_CHECKS"
  fi

  return 1
}

ensure_node_modules() {
  local dir="$1"
  if ! command -v npm >/dev/null 2>&1; then
    log_error "npm is required in ${dir}"
    log_error "Next step: install Node.js with npm, then rerun ./scripts/verify-p0.sh"
    return 1
  fi
  (
    cd "$dir" || exit 1
    if [[ ! -d node_modules ]]; then
      log_info "Installing node_modules in ${dir}"
      npm ci
    fi
  )
}

resolve_supabase_cli() {
  if command -v supabase >/dev/null 2>&1; then
    SUPABASE_CMD=(supabase)
    return 0
  fi
  if command -v npx >/dev/null 2>&1; then
    SUPABASE_CMD=(npx supabase)
    return 0
  fi
  return 1
}

apply_seed_with_psql() {
  local db_url="${SUPABASE_DB_URL:-${DATABASE_URL:-}}"
  if ! command -v psql >/dev/null 2>&1 || [[ -z "$db_url" ]]; then
    return 1
  fi

  local seed_file
  for seed_file in "$SEED_DIR"/*.sql; do
    [[ -e "$seed_file" ]] || continue
    psql "$db_url" -v ON_ERROR_STOP=1 -f "$seed_file"
  done
}

apply_seed_with_docker_psql() {
  if ! command -v docker >/dev/null 2>&1; then
    return 1
  fi

  local db_container
  db_container="$(docker ps --format '{{.Names}}' | grep -E '^supabase_db_' | head -n 1 || true)"
  if [[ -z "$db_container" ]]; then
    return 1
  fi

  local seed_file
  for seed_file in "$SEED_DIR"/*.sql; do
    [[ -e "$seed_file" ]] || continue
    docker exec -i "$db_container" psql -U postgres -d postgres -v ON_ERROR_STOP=1 < "$seed_file"
  done
}

apply_seed() {
  local db_url="${SUPABASE_DB_URL:-${DATABASE_URL:-}}"

  if command -v psql >/dev/null 2>&1 && [[ -n "$db_url" ]]; then
    apply_seed_with_psql
    return 0
  fi

  if command -v docker >/dev/null 2>&1; then
    if docker ps --format '{{.Names}}' | grep -E '^supabase_db_' >/dev/null 2>&1; then
      apply_seed_with_docker_psql
      return 0
    fi
  fi

  log_warn "Seed files were not applied because neither psql nor a local Supabase DB container is available"
  return 0
}

run_db_migration() {
  if resolve_supabase_cli; then
    if [[ "${DEPLOYMENT_MODE:-local}" == "local" ]]; then
      (cd "$PROJECT_ROOT" && "${SUPABASE_CMD[@]}" db push --local)
    else
      (cd "$PROJECT_ROOT" && "${SUPABASE_CMD[@]}" db push)
    fi
    apply_seed
    return 0
  fi

  local db_url="${SUPABASE_DB_URL:-${DATABASE_URL:-}}"
  if ! command -v psql >/dev/null 2>&1; then
    log_error "DB migration requires Supabase CLI or psql"
    log_error "Next step: install Supabase CLI (https://supabase.com/docs/guides/cli) or PostgreSQL client tools, then rerun ./scripts/verify-p0.sh"
    return 1
  fi
  if [[ -z "$db_url" ]]; then
    log_error "DB migration requires SUPABASE_DB_URL or DATABASE_URL"
    log_error "Next step: export SUPABASE_DB_URL or DATABASE_URL for the target environment, or rerun with --skip-db-migration for a non-gating inner-loop check"
    return 1
  fi

  local migration_file
  for migration_file in "$MIGRATIONS_DIR"/*.sql; do
    [[ -e "$migration_file" ]] || continue
    psql "$db_url" -v ON_ERROR_STOP=1 -f "$migration_file"
  done
  apply_seed
}

run_data_service_tests() {
  (
    cd "$PROJECT_ROOT/data-service" || exit 1
    "$PYTHON_BIN" -m pytest -v --tb=short
  )
}

run_openclaw_tests() {
  (
    cd "$PROJECT_ROOT" || exit 1
    "$PYTHON_BIN" -m pytest -v --tb=short scripts/tests/test_openclaw_smoke.py &&
    "$PYTHON_BIN" -m pytest -v --tb=short openclaw/tests
  )
}

run_gbrain_typecheck() {
  ensure_node_modules "$PROJECT_ROOT/gbrain"
  (
    cd "$PROJECT_ROOT/gbrain" || exit 1
    npm run typecheck
  )
}

run_gbrain_tests() {
  if ! command -v bun >/dev/null 2>&1; then
    return 2
  fi

  (
    cd "$PROJECT_ROOT/gbrain" || exit 1
    bun run test
  )
}

run_webapp_lint() {
  ensure_node_modules "$PROJECT_ROOT/webapp"
  (
    cd "$PROJECT_ROOT/webapp" || exit 1
    npm run lint
  )
}

run_webapp_build() {
  ensure_node_modules "$PROJECT_ROOT/webapp"
  (
    cd "$PROJECT_ROOT/webapp" || exit 1
    npm run build
  )
}

run_futu_mock_smoke() {
  "$PROJECT_ROOT/scripts/verify-futu-local.sh" --mode mock --python "$PYTHON_BIN"
}

run_futu_real_smoke() {
  "$PROJECT_ROOT/scripts/verify-futu-local.sh" --mode real --python "$PYTHON_BIN"
}

run_live_e2e_smoke() {
  if [[ "$RUN_STRICT_LIVE_E2E" == "true" ]]; then
    "$PYTHON_BIN" "$PROJECT_ROOT/scripts/e2e_smoke.py" --mode live --strict-live
    return $?
  fi
  "$PYTHON_BIN" "$PROJECT_ROOT/scripts/e2e_smoke.py" --mode live
}

run_live_confirmation_smoke() {
  "$PYTHON_BIN" "$PROJECT_ROOT/scripts/live_confirmation_smoke.py"
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

is_pid_file_running() {
  local pid_file="$1"
  if [[ ! -f "$pid_file" ]]; then
    return 1
  fi

  local pid
  pid="$(cat "$pid_file")"
  [[ -n "$pid" ]] && kill -0 "$pid" >/dev/null 2>&1
}

warn_webapp_build_overlap() {
  local webapp_port="${WEBAPP_PORT:-3000}"
  local pid_file="$RUN_DIR/webapp.pid"

  if is_pid_file_running "$pid_file"; then
    log_warn "Detected a running webapp dev server from start-local-services (pid $(cat "$pid_file"))."
    log_warn "npm run build reuses webapp/.next, so dev/build can contaminate each other in the same worktree."
    log_warn "Recommendation: run ./scripts/stop-local-services.sh before the webapp build stage for a clean production build."
    return 0
  fi

  if is_port_open "127.0.0.1" "$webapp_port"; then
    log_warn "Detected something listening on WEBAPP_PORT=${webapp_port}."
    log_warn "If that process is webapp npm run dev, stop it before npm run build to avoid .next/dev-build overlap."
  fi
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --python)
      PYTHON_BIN="${2:-}"
      shift 2
      ;;
    --skip-db-migration)
      RUN_DB_MIGRATION=false
      shift
      ;;
    --with-futu-real)
      RUN_FUTU_REAL=true
      shift
      ;;
    --with-live-e2e)
      RUN_LIVE_E2E=true
      shift
      ;;
    --with-live-confirmation)
      RUN_LIVE_CONFIRMATION=true
      shift
      ;;
    --strict-live-e2e)
      RUN_LIVE_E2E=true
      RUN_STRICT_LIVE_E2E=true
      shift
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
export NEXT_PUBLIC_SUPABASE_URL="${NEXT_PUBLIC_SUPABASE_URL:-${SUPABASE_URL:-https://example.supabase.co}}"
export NEXT_PUBLIC_SUPABASE_ANON_KEY="${NEXT_PUBLIC_SUPABASE_ANON_KEY:-${SUPABASE_ANON_KEY:-dummy-anon-key}}"
export SUPABASE_SERVICE_ROLE_KEY="${SUPABASE_SERVICE_ROLE_KEY:-dummy-service-role}"

overall_ok=true

if [[ "$RUN_DB_MIGRATION" == "true" ]]; then
  run_stage "required" "db-migration" "apply Supabase migrations and seed" run_db_migration || overall_ok=false
else
  skip_stage "required" "db-migration" "disabled by --skip-db-migration; full gate remains incomplete"
fi

run_stage "required" "data-service-tests" "pytest data-service" run_data_service_tests || overall_ok=false
run_stage "required" "openclaw-tests" "pytest scripts/tests/test_openclaw_smoke.py + openclaw/tests" run_openclaw_tests || overall_ok=false
run_stage "required" "gbrain-typecheck" "npm run typecheck" run_gbrain_typecheck || overall_ok=false

gbrain_tests_rc=0
if run_gbrain_tests; then
  record_stage "gbrain-tests" "optional" "PASS" "bun run test"
else
  gbrain_tests_rc=$?
  if [[ "$gbrain_tests_rc" -eq 2 ]]; then
    skip_stage "optional" "gbrain-tests" "bun not installed; install via brew install oven-sh/bun/bun and rerun ./scripts/verify-p0.sh"
  else
    record_stage "gbrain-tests" "optional" "FAIL" "bun run test (exit ${gbrain_tests_rc})"
    log_error "gbrain-tests failed with exit ${gbrain_tests_rc}"
  fi
fi

run_stage "required" "webapp-lint" "npm run lint" run_webapp_lint || overall_ok=false
warn_webapp_build_overlap
run_stage "required" "webapp-build" "npm run build" run_webapp_build || overall_ok=false
run_stage "required" "futu-mock-smoke" "mock broker sync smoke" run_futu_mock_smoke || overall_ok=false

if [[ "$RUN_FUTU_REAL" == "true" ]]; then
  run_stage "optional" "futu-real-smoke" "real broker sync smoke" run_futu_real_smoke || true
else
  FUTU_OPEND_HOST="${FUTU_OPEND_HOST:-127.0.0.1}"
  FUTU_OPEND_PORT="${FUTU_OPEND_PORT:-11111}"
  if is_port_open "$FUTU_OPEND_HOST" "$FUTU_OPEND_PORT"; then
    skip_stage "optional" "futu-real-smoke" "opt-in; detected OpenD at ${FUTU_OPEND_HOST}:${FUTU_OPEND_PORT}. Re-run with --with-futu-real"
  else
    skip_stage "optional" "futu-real-smoke" "opt-in; OpenD not detected at ${FUTU_OPEND_HOST}:${FUTU_OPEND_PORT}. Start OpenD + real sidecar, then rerun with --with-futu-real"
  fi
fi

if [[ "$RUN_LIVE_E2E" == "true" ]]; then
  live_e2e_detail="live E2E smoke"
  if [[ "$RUN_STRICT_LIVE_E2E" == "true" ]]; then
    live_e2e_detail="${live_e2e_detail} (strict skips)"
  fi
  run_stage "optional" "live-e2e-smoke" "$live_e2e_detail" run_live_e2e_smoke || true
else
  skip_stage "optional" "live-e2e-smoke" "opt-in; rerun with --with-live-e2e after local services or hooks are configured"
fi

if [[ "$RUN_LIVE_CONFIRMATION" == "true" ]]; then
  run_stage "optional" "live-confirmation-smoke" "real OpenClaw confirmation and delivery smoke" run_live_confirmation_smoke || true
else
  skip_stage "optional" "live-confirmation-smoke" "opt-in; rerun with --with-live-confirmation when OpenClaw and Supabase are configured"
fi

if print_summary && [[ "$overall_ok" == "true" ]]; then
  exit 0
fi
exit 1
