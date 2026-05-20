#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$PROJECT_ROOT"

ENV_FILE="${ENV_FILE:-.env.server}"
COMPOSE_FILE="${COMPOSE_FILE:-docker-compose.server.yml}"
WEBAPP_URL="${WEBAPP_URL:-http://127.0.0.1:${WEBAPP_HTTP_PORT:-3000}}"
DATA_SERVICE_URL="${DATA_SERVICE_URL:-http://127.0.0.1:${DATA_SERVICE_PORT:-8000}}"
OPENCLAW_URL="${OPENCLAW_URL:-http://127.0.0.1:${OPENCLAW_PORT:-8080}}"
EXPECTED_OPENCLAW="${OPENCLAW_UPSTREAM_TARGET_VERSION:-v2026.5.18}"
EXPECTED_HERMES="${HERMES_UPSTREAM_TARGET_VERSION:-v2026.5.16}"

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
  python3 - "$label" "$url" "$expr" <<'PY'
import json
import sys
import urllib.request

label, url, expr = sys.argv[1:4]
try:
    with urllib.request.urlopen(url, timeout=10) as response:
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

log "checking WebApp"
curl -fsSI "$WEBAPP_URL" >/dev/null || fail "WebApp is not reachable at $WEBAPP_URL"

log "checking data-service health"
json_check "data-service" "$DATA_SERVICE_URL/health" "payload.get('status') == 'ok'"

log "checking OpenClaw/Hermes foundation health"
json_check "openclaw" "$OPENCLAW_URL/health" \
  "payload.get('status') == 'ok' and payload.get('runtime', {}).get('foundation', {}).get('openclaw_upstream_target') == '$EXPECTED_OPENCLAW' and payload.get('runtime', {}).get('foundation', {}).get('hermes_upstream_target') == '$EXPECTED_HERMES'"

log "checking GBrain adapter JSON health"
GBRAIN_HEALTH_JSON="$(
  docker compose --env-file "$ENV_FILE" -f "$COMPOSE_FILE" exec -T gbrain \
    bun /app/src/mcp-adapter.ts --health-json
)"
python3 - "$EXPECTED_OPENCLAW" "$EXPECTED_HERMES" "$GBRAIN_HEALTH_JSON" <<'PY'
import json
import sys

expected_openclaw, expected_hermes, raw_payload = sys.argv[1:4]
payload = json.loads(raw_payload)
assert payload.get("ok") is True, payload
assert payload.get("openclaw_upstream_target") == expected_openclaw, payload
assert payload.get("hermes_upstream_target") == expected_hermes, payload
print("gbrain: ok")
PY

log "foundation runtime verification complete"
