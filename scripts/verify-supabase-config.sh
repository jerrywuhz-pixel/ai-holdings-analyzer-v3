#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
ENV_FILE="$PROJECT_ROOT/.env"

if [[ -f "$ENV_FILE" ]]; then
  set -a
  # shellcheck disable=SC1090
  source "$ENV_FILE"
  set +a
fi

failures=0

check_var() {
  local key="$1"
  local value="${!key:-}"
  if [[ -z "$value" ]]; then
    echo "[FAIL] $key is missing"
    failures=$((failures + 1))
    return
  fi
  if [[ "$value" == your-* || "$value" == *your-project* || "$value" == replace-with-* || "$value" == placeholder* ]]; then
    echo "[WARN] $key is still a placeholder"
    return
  fi
  echo "[OK]   $key is set"
}

check_var "SUPABASE_URL"
check_var "SUPABASE_ANON_KEY"
check_var "SUPABASE_SERVICE_ROLE_KEY"
check_var "SUPABASE_DB_URL"
check_var "NEXT_PUBLIC_SUPABASE_URL"
check_var "NEXT_PUBLIC_SUPABASE_ANON_KEY"

if command -v supabase >/dev/null 2>&1; then
  echo "[OK]   supabase CLI: $(supabase --version)"
elif command -v npx >/dev/null 2>&1; then
  echo "[OK]   supabase CLI: $(npx supabase --version)"
else
  echo "[WARN] supabase CLI is not installed"
fi

if command -v psql >/dev/null 2>&1; then
  echo "[OK]   psql: $(psql --version)"
else
  echo "[WARN] psql is not installed"
fi

if command -v python3 >/dev/null 2>&1; then
  python3 - <<'PY'
import os
from urllib.parse import urlparse

url = os.getenv("SUPABASE_URL", "")
parsed = urlparse(url)
if parsed.scheme in {"http", "https"} and parsed.netloc:
    print("[OK]   SUPABASE_URL has a valid HTTP shape")
else:
    print("[FAIL] SUPABASE_URL is not a valid HTTP URL")
    raise SystemExit(1)

db_url = os.getenv("SUPABASE_DB_URL", "")
db = urlparse(db_url)
if db.scheme in {"postgres", "postgresql"} and db.hostname:
    print("[OK]   SUPABASE_DB_URL has a valid Postgres shape")
else:
    print("[FAIL] SUPABASE_DB_URL is not a valid Postgres URL")
    raise SystemExit(1)
PY
else
  echo "[WARN] python3 is not installed; skipping URL shape checks"
fi

TABLE_CHECK_SQL="
    SELECT table_name
    FROM information_schema.tables
    WHERE table_schema = 'public'
      AND table_name IN (
        'users',
        'tenant_accounts',
        'broker_sync_snapshots',
        'portfolio_positions',
        'pending_actions',
        'delivery_outbox'
      )
    ORDER BY table_name;
"

if command -v psql >/dev/null 2>&1 && [[ -n "${SUPABASE_DB_URL:-}" ]]; then
  echo "[INFO] Checking required tables through SUPABASE_DB_URL"
  psql "$SUPABASE_DB_URL" -v ON_ERROR_STOP=1 -Atc "$TABLE_CHECK_SQL"
elif command -v docker >/dev/null 2>&1 && docker ps --format '{{.Names}}' | grep -qE '^supabase_db_'; then
  db_container="$(docker ps --format '{{.Names}}' | grep -E '^supabase_db_' | head -n 1)"
  echo "[INFO] Checking required tables through Docker container $db_container"
  docker exec -i "$db_container" psql -U postgres -d postgres -v ON_ERROR_STOP=1 -Atc "$TABLE_CHECK_SQL"
else
  echo "[WARN] Skipping live table check because psql or SUPABASE_DB_URL is unavailable"
fi

if [[ "$failures" -gt 0 ]]; then
  echo "[FAIL] Supabase config has $failures missing required value(s)"
  exit 1
fi

echo "[INFO] Supabase config check completed"
