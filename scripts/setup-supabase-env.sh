#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
ROOT_ENV="$PROJECT_ROOT/.env"
WEBAPP_ENV="$PROJECT_ROOT/webapp/.env.local"

MODE="local"
USE_STATUS=true

while [[ $# -gt 0 ]]; do
  case "$1" in
    --mode)
      MODE="${2:-local}"
      shift 2
      ;;
    --skip-status)
      USE_STATUS=false
      shift
      ;;
    *)
      echo "[ERROR] Unknown argument: $1" >&2
      exit 1
      ;;
  esac
done

if [[ "$MODE" != "local" && "$MODE" != "cloud" ]]; then
  echo "[ERROR] --mode must be local or cloud" >&2
  exit 1
fi

set_env_value() {
  local file="$1"
  local key="$2"
  local value="$3"
  local tmp

  mkdir -p "$(dirname "$file")"
  touch "$file"
  tmp="$(mktemp)"
  awk -v key="$key" -v value="$value" '
    BEGIN { replaced = 0 }
    $0 ~ "^" key "=" {
      print key "=" value
      replaced = 1
      next
    }
    { print }
    END {
      if (replaced == 0) {
        print key "=" value
      }
    }
  ' "$file" > "$tmp"
  mv "$tmp" "$file"
}

ensure_root_env() {
  if [[ ! -f "$ROOT_ENV" ]]; then
    if [[ -f "$PROJECT_ROOT/.env.example" ]]; then
      cp "$PROJECT_ROOT/.env.example" "$ROOT_ENV"
    else
      touch "$ROOT_ENV"
    fi
  fi
}

load_existing_env() {
  if [[ -f "$ROOT_ENV" ]]; then
    set -a
    # shellcheck disable=SC1090
    source "$ROOT_ENV"
    set +a
  fi
}

capture_supabase_status_env() {
  if [[ "$USE_STATUS" != "true" || "$MODE" != "local" ]]; then
    return
  fi
  local supabase_cmd=()
  if command -v supabase >/dev/null 2>&1; then
    supabase_cmd=(supabase)
  elif command -v npx >/dev/null 2>&1; then
    supabase_cmd=(npx supabase)
  else
    return
  fi

  local status_output
  if status_output="$("${supabase_cmd[@]}" status -o env 2>/dev/null)"; then
    while IFS='=' read -r key value; do
      value="${value%\"}"
      value="${value#\"}"
      case "$key" in
        SUPABASE_URL|SUPABASE_ANON_KEY|SUPABASE_SERVICE_ROLE_KEY|SUPABASE_DB_URL)
          if [[ -n "${value:-}" ]]; then
            export "$key=$value"
          fi
          ;;
        API_URL)
          if [[ -n "${value:-}" ]]; then
            export SUPABASE_URL="$value"
          fi
          ;;
        ANON_KEY)
          if [[ -n "${value:-}" ]]; then
            export SUPABASE_ANON_KEY="$value"
          fi
          ;;
        SERVICE_ROLE_KEY)
          if [[ -n "${value:-}" ]]; then
            export SUPABASE_SERVICE_ROLE_KEY="$value"
          fi
          ;;
        DB_URL)
          if [[ -n "${value:-}" ]]; then
            export SUPABASE_DB_URL="$value"
          fi
          ;;
      esac
    done <<< "$status_output"
  fi
}

env_or_default() {
  local value="$1"
  local fallback="$2"
  if [[ -z "$value" || "$value" == your-* || "$value" == *your-project* || "$value" == replace-with-* || "$value" == placeholder* ]]; then
    echo "$fallback"
  else
    echo "$value"
  fi
}

ensure_root_env
load_existing_env
capture_supabase_status_env

if [[ "$MODE" == "local" ]]; then
  SUPABASE_URL_VALUE="$(env_or_default "${SUPABASE_URL:-}" "http://127.0.0.1:54321")"
  SUPABASE_ANON_KEY_VALUE="$(env_or_default "${SUPABASE_ANON_KEY:-}" "replace-with-supabase-local-anon-key")"
  SUPABASE_SERVICE_ROLE_KEY_VALUE="$(env_or_default "${SUPABASE_SERVICE_ROLE_KEY:-}" "replace-with-supabase-local-service-role-key")"
  if [[ "${SUPABASE_DB_URL:-}" == *"localhost:5432/ai_holdings"* || "${SUPABASE_DB_URL:-}" == *"127.0.0.1:5432/ai_holdings"* ]]; then
    SUPABASE_DB_URL=""
  fi
  SUPABASE_DB_URL_VALUE="$(env_or_default "${SUPABASE_DB_URL:-}" "postgresql://postgres:postgres@127.0.0.1:54322/postgres")"
  DATABASE_URL_VALUE="$SUPABASE_DB_URL_VALUE"
  DEPLOYMENT_MODE_VALUE="local"
else
  : "${SUPABASE_URL:?SUPABASE_URL is required for --mode cloud}"
  : "${SUPABASE_ANON_KEY:?SUPABASE_ANON_KEY is required for --mode cloud}"
  : "${SUPABASE_SERVICE_ROLE_KEY:?SUPABASE_SERVICE_ROLE_KEY is required for --mode cloud}"
  : "${SUPABASE_DB_URL:?SUPABASE_DB_URL is required for --mode cloud}"
  for cloud_value in "$SUPABASE_URL" "$SUPABASE_ANON_KEY" "$SUPABASE_SERVICE_ROLE_KEY" "$SUPABASE_DB_URL"; do
    if [[ "$cloud_value" == your-* || "$cloud_value" == *your-project* || "$cloud_value" == replace-with-* || "$cloud_value" == placeholder* ]]; then
      echo "[ERROR] Cloud mode received a placeholder value. Export real Supabase project values first." >&2
      exit 1
    fi
  done
  SUPABASE_URL_VALUE="$SUPABASE_URL"
  SUPABASE_ANON_KEY_VALUE="$SUPABASE_ANON_KEY"
  SUPABASE_SERVICE_ROLE_KEY_VALUE="$SUPABASE_SERVICE_ROLE_KEY"
  SUPABASE_DB_URL_VALUE="$SUPABASE_DB_URL"
  DATABASE_URL_VALUE="${DATABASE_URL:-$SUPABASE_DB_URL}"
  DEPLOYMENT_MODE_VALUE="cloud"
fi

set_env_value "$ROOT_ENV" "DEPLOYMENT_MODE" "$DEPLOYMENT_MODE_VALUE"
set_env_value "$ROOT_ENV" "SUPABASE_URL" "$SUPABASE_URL_VALUE"
set_env_value "$ROOT_ENV" "SUPABASE_ANON_KEY" "$SUPABASE_ANON_KEY_VALUE"
set_env_value "$ROOT_ENV" "SUPABASE_SERVICE_ROLE_KEY" "$SUPABASE_SERVICE_ROLE_KEY_VALUE"
set_env_value "$ROOT_ENV" "SUPABASE_DB_URL" "$SUPABASE_DB_URL_VALUE"
set_env_value "$ROOT_ENV" "DATABASE_URL" "$DATABASE_URL_VALUE"
set_env_value "$ROOT_ENV" "OPENCLAW_SKILL_KEY" "$SUPABASE_SERVICE_ROLE_KEY_VALUE"
set_env_value "$ROOT_ENV" "NEXT_PUBLIC_SUPABASE_URL" "$SUPABASE_URL_VALUE"
set_env_value "$ROOT_ENV" "NEXT_PUBLIC_SUPABASE_ANON_KEY" "$SUPABASE_ANON_KEY_VALUE"
set_env_value "$ROOT_ENV" "GBRAIN_DATABASE_URL" "$DATABASE_URL_VALUE"

set_env_value "$WEBAPP_ENV" "NEXT_PUBLIC_SUPABASE_URL" "$SUPABASE_URL_VALUE"
set_env_value "$WEBAPP_ENV" "NEXT_PUBLIC_SUPABASE_ANON_KEY" "$SUPABASE_ANON_KEY_VALUE"
set_env_value "$WEBAPP_ENV" "SUPABASE_SERVICE_ROLE_KEY" "$SUPABASE_SERVICE_ROLE_KEY_VALUE"

echo "[INFO] Supabase environment written:"
echo "  root:   $ROOT_ENV"
echo "  webapp: $WEBAPP_ENV"
echo "  mode:   $MODE"
echo "  url:    $SUPABASE_URL_VALUE"

if [[ "$SUPABASE_ANON_KEY_VALUE" == replace-with-* || "$SUPABASE_SERVICE_ROLE_KEY_VALUE" == replace-with-* ]]; then
  echo "[WARN] Supabase keys are placeholders. Run 'supabase start' and then this script again, or provide cloud keys."
fi
