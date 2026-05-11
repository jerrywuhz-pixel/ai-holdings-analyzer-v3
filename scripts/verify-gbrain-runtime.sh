#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
ENV_FILE="$PROJECT_ROOT/.env"

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

is_placeholder() {
  local value="${1:-}"
  [[ -z "$value" || "$value" == your-* || "$value" == *your-project* || "$value" == replace-with-* || "$value" == placeholder* ]]
}

if [[ -f "$ENV_FILE" ]]; then
  load_env_defaults "$ENV_FILE"
fi

echo "[gbrain] typecheck"
(
  cd "$PROJECT_ROOT/gbrain"
  npm run typecheck
)

if command -v bun >/dev/null 2>&1; then
  echo "[gbrain] unit tests"
  (
    cd "$PROJECT_ROOT/gbrain"
    bun run test
  )

  echo "[gbrain] Hermes runtime smoke"
  (
    cd "$PROJECT_ROOT/gbrain"
    bun run src/hermes-smoke.ts
  )
else
  echo "[gbrain][WARN] bun not found; skipped unit tests and Hermes smoke"
fi

GBRAIN_DB_URL="${GBRAIN_DATABASE_URL:-${DATABASE_URL:-}}"
if command -v bun >/dev/null 2>&1 && ! is_placeholder "$GBRAIN_DB_URL"; then
  echo "[gbrain] MCP adapter DB health-check"
  (
    cd "$PROJECT_ROOT/gbrain"
    DATABASE_URL="$GBRAIN_DB_URL" bun run src/mcp-adapter.ts --health-check
  )
else
  echo "[gbrain][WARN] skipped MCP DB health-check; set DATABASE_URL or GBRAIN_DATABASE_URL to a migrated Postgres database"
fi

echo "[gbrain] runtime verification complete"
