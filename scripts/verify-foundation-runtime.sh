#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$PROJECT_ROOT"

ENV_FILE="${ENV_FILE:-.env.server}"
COMPOSE_FILE="${COMPOSE_FILE:-docker-compose.server.yml}"
EXPECTED_HERMES="${HERMES_UPSTREAM_TARGET_VERSION:-v2026.5.29}"

env_value() {
  local name="$1"
  if [ ! -f "$ENV_FILE" ]; then
    return 0
  fi
  awk -F= -v key="$name" '$1 == key { value=$0; sub("^[^=]*=", "", value); print value }' "$ENV_FILE" | tail -1
}

SERVICE_BIND_HOST="${INTERNAL_HOST_BIND:-$(env_value INTERNAL_HOST_BIND)}"
SERVICE_BIND_HOST="${SERVICE_BIND_HOST:-127.0.0.1}"
WEBAPP_PORT="${WEBAPP_HTTP_PORT:-$(env_value WEBAPP_HTTP_PORT)}"
WEBAPP_PORT="${WEBAPP_PORT:-3000}"
DATA_SERVICE_PORT_RESOLVED="${DATA_SERVICE_PORT:-$(env_value DATA_SERVICE_PORT)}"
DATA_SERVICE_PORT_RESOLVED="${DATA_SERVICE_PORT_RESOLVED:-8000}"
WEBAPP_URL="${WEBAPP_URL:-http://127.0.0.1:${WEBAPP_PORT}}"
DATA_SERVICE_URL="${DATA_SERVICE_URL:-http://${SERVICE_BIND_HOST}:${DATA_SERVICE_PORT_RESOLVED}}"
HERMES_DOMAIN_TOOLS_KEY_RESOLVED="${HERMES_DOMAIN_TOOLS_KEY:-$(env_value HERMES_DOMAIN_TOOLS_KEY)}"
HERMES_DOMAIN_TOOLS_KEY_RESOLVED="${HERMES_DOMAIN_TOOLS_KEY_RESOLVED:-$(env_value HERMES_INTERNAL_TOKEN)}"

log() {
  printf '[foundation-verify] %s\n' "$*"
}

fail() {
  printf '[foundation-verify][ERROR] %s\n' "$*" >&2
  exit 1
}

json_check() {
  local label="$1"
  local url="$2"
  local expr="$3"
  local hermes_key="${4:-}"
  python3 - "$label" "$url" "$expr" "$hermes_key" <<'PY'
import json
import sys
import urllib.request

label, url, expr, hermes_key = sys.argv[1:5]
request = urllib.request.Request(url)
if hermes_key:
    request.add_header("X-Hermes-Domain-Tools-Key", hermes_key)
try:
    with urllib.request.urlopen(request, timeout=10) as response:
        payload = json.load(response)
except Exception as exc:
    raise SystemExit(f"{label}: failed to fetch {url}: {exc}")

scope = {"payload": payload}
if not eval(expr, {"__builtins__": {}}, scope):
    raise SystemExit(f"{label}: assertion failed: {expr}; payload={json.dumps(payload, ensure_ascii=False)[:1000]}")
print(f"{label}: ok")
PY
}

log "checking compose services"
docker compose --env-file "$ENV_FILE" -f "$COMPOSE_FILE" ps >/tmp/ai-holdings-foundation-ps.txt
cat /tmp/ai-holdings-foundation-ps.txt
if docker compose --env-file "$ENV_FILE" -f "$COMPOSE_FILE" ps --services | grep -qx 'openclaw'; then
  fail "Hermes-only deployment must not define or run an openclaw service"
fi

log "checking WebApp"
curl -fsSI "$WEBAPP_URL" >/dev/null || fail "WebApp is not reachable at $WEBAPP_URL"

log "checking data-service health"
json_check "data-service" "$DATA_SERVICE_URL/health" "payload.get('status') == 'ok' and payload.get('runtime') == 'hermes'"

log "checking Hermes domain tools"
json_check "hermes-domain-tools" "$DATA_SERVICE_URL/api/hermes/domain-tools" \
  "payload.get('ok') == True and payload.get('runtime') == 'hermes' and 'market.quote' in [tool.get('name') for tool in payload.get('tools', [])]" \
  "$HERMES_DOMAIN_TOOLS_KEY_RESOLVED"

log "checking GBrain adapter JSON health"
GBRAIN_HEALTH_JSON="$(
  docker compose --env-file "$ENV_FILE" -f "$COMPOSE_FILE" exec -T gbrain \
    bun /app/src/mcp-adapter.ts --health-json
)"
python3 - "$EXPECTED_HERMES" "$GBRAIN_HEALTH_JSON" <<'PY'
import json
import sys

expected_hermes, raw_payload = sys.argv[1:3]
payload = json.loads(raw_payload)
assert payload.get("ok") is True, payload
assert payload.get("adapter") == "gbrain-hermes", payload
assert payload.get("hermes_upstream_target") == expected_hermes, payload
print("gbrain: ok")
PY

log "foundation runtime verification complete"
