#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
ENV_FILE="${ENV_FILE:-$PROJECT_ROOT/.env.server}"
COMPOSE_FILE="${COMPOSE_FILE:-$PROJECT_ROOT/docker-compose.server.yml}"
BOOTSTRAP_FILE="${BOOTSTRAP_FILE:-$PROJECT_ROOT/deployment/local-postgres/000000_supabase_compat.sql}"
MIGRATIONS_DIR="${MIGRATIONS_DIR:-$PROJECT_ROOT/supabase/migrations}"

if [[ ! -f "$ENV_FILE" ]]; then
  echo "[server-migrations][ERROR] Missing env file: $ENV_FILE" >&2
  exit 1
fi

if [[ ! -f "$COMPOSE_FILE" ]]; then
  echo "[server-migrations][ERROR] Missing compose file: $COMPOSE_FILE" >&2
  exit 1
fi

if [[ ! -f "$BOOTSTRAP_FILE" ]]; then
  echo "[server-migrations][ERROR] Missing local Postgres bootstrap file: $BOOTSTRAP_FILE" >&2
  exit 1
fi

if [[ ! -d "$MIGRATIONS_DIR" ]]; then
  echo "[server-migrations][ERROR] Missing migrations directory: $MIGRATIONS_DIR" >&2
  exit 1
fi

set -a
# shellcheck disable=SC1090
source "$ENV_FILE"
set +a

POSTGRES_USER="${POSTGRES_USER:-postgres}"
POSTGRES_DB="${POSTGRES_DB:-ai_holdings}"

compose() {
  docker compose --env-file "$ENV_FILE" -f "$COMPOSE_FILE" "$@"
}

DB_CONTAINER="$(compose ps -q postgres)"
if [[ -z "$DB_CONTAINER" ]]; then
  echo "[server-migrations][ERROR] Postgres container is not running." >&2
  exit 1
fi

psql_file() {
  local file="$1"
  docker exec -i "$DB_CONTAINER" psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -v ON_ERROR_STOP=1 < "$file"
}

psql_cmd() {
  local sql="$1"
  docker exec "$DB_CONTAINER" psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -v ON_ERROR_STOP=1 -Atc "$sql"
}

echo "[server-migrations] Applying local Postgres compatibility bootstrap"
psql_file "$BOOTSTRAP_FILE" >/dev/null

psql_cmd "CREATE TABLE IF NOT EXISTS public.schema_migrations (filename text PRIMARY KEY, applied_at timestamptz NOT NULL DEFAULT now());" >/dev/null

for migration_file in "$MIGRATIONS_DIR"/*.sql; do
  [[ -e "$migration_file" ]] || continue
  migration_name="$(basename "$migration_file")"
  escaped_name="${migration_name//\'/\'\'}"
  already_applied="$(psql_cmd "SELECT 1 FROM public.schema_migrations WHERE filename = '$escaped_name' LIMIT 1;" || true)"

  if [[ "$already_applied" == "1" ]]; then
    echo "[server-migrations] Skipping $migration_name"
    continue
  fi

  echo "[server-migrations] Applying $migration_name"
  psql_file "$migration_file" >/dev/null
  psql_cmd "INSERT INTO public.schema_migrations(filename) VALUES ('$escaped_name') ON CONFLICT DO NOTHING;" >/dev/null
done

echo "[server-migrations] Migrations complete"
