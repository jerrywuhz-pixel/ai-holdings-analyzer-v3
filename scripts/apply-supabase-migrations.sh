#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
ENV_FILE="$PROJECT_ROOT/.env"
MIGRATIONS_DIR="$PROJECT_ROOT/supabase/migrations"
SEED_DIR="$PROJECT_ROOT/supabase/seed"

VIA="auto"
RUN_SEED=false

while [[ $# -gt 0 ]]; do
  case "$1" in
    --via)
      VIA="${2:-auto}"
      shift 2
      ;;
    --seed)
      RUN_SEED=true
      shift
      ;;
    *)
      echo "[ERROR] Unknown argument: $1" >&2
      exit 1
      ;;
  esac
done

if [[ -f "$ENV_FILE" ]]; then
  set -a
  # shellcheck disable=SC1090
  source "$ENV_FILE"
  set +a
fi

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

  echo "[INFO] Applying seed SQL with local psql"
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

  echo "[INFO] Applying seed SQL through Docker container $db_container"
  for seed_file in "$SEED_DIR"/*.sql; do
    [[ -e "$seed_file" ]] || continue
    docker exec -i "$db_container" psql -U postgres -d postgres -v ON_ERROR_STOP=1 < "$seed_file"
  done
}

apply_seed() {
  if [[ "$RUN_SEED" != "true" ]]; then
    return 0
  fi

  if apply_seed_with_psql; then
    return 0
  fi
  if apply_seed_with_docker_psql; then
    return 0
  fi

  echo "[WARN] Seed requested, but neither local psql nor Supabase DB container is available. Skipping seed files."
}

apply_with_supabase_cli() {
  SUPABASE_CMD=()
  if ! resolve_supabase_cli; then
    return 1
  fi

  echo "[INFO] Applying migrations with Supabase CLI"
  if [[ "${DEPLOYMENT_MODE:-local}" == "local" ]]; then
    (cd "$PROJECT_ROOT" && "${SUPABASE_CMD[@]}" db push --local)
  else
    (cd "$PROJECT_ROOT" && "${SUPABASE_CMD[@]}" db push)
  fi
  apply_seed
}

apply_with_psql() {
  local db_url="${SUPABASE_DB_URL:-${DATABASE_URL:-}}"
  if ! command -v psql >/dev/null 2>&1; then
    echo "[ERROR] psql is required for --via psql" >&2
    return 1
  fi
  if [[ -z "$db_url" ]]; then
    echo "[ERROR] SUPABASE_DB_URL or DATABASE_URL is required for --via psql" >&2
    return 1
  fi

  echo "[INFO] Applying migrations with psql"
  for migration_file in "$MIGRATIONS_DIR"/*.sql; do
    [[ -e "$migration_file" ]] || continue
    echo "[INFO] Applying $(basename "$migration_file")"
    psql "$db_url" -v ON_ERROR_STOP=1 -f "$migration_file"
  done

  if [[ "$RUN_SEED" == "true" ]]; then
    apply_seed_with_psql
  fi
}

case "$VIA" in
  auto)
    if apply_with_supabase_cli; then
      exit 0
    fi
    apply_with_psql
    ;;
  supabase)
    apply_with_supabase_cli
    ;;
  psql)
    apply_with_psql
    ;;
  *)
    echo "[ERROR] --via must be auto, supabase, or psql" >&2
    exit 1
    ;;
esac

echo "[INFO] Supabase migrations completed"
