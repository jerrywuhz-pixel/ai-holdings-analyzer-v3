#!/usr/bin/env sh
set -eu

BASE_URL="${HERMES_DOMAIN_TOOLS_URL:-${DATA_SERVICE_URL:-http://172.17.0.1:8000}}"
LIMIT="${HERMES_ALERT_CYCLE_LIMIT:-50}"
CYCLE="${HERMES_ALERT_CENTER_CYCLE:-intraday}"
DATA_SERVICE_CONTAINER="${HERMES_DATA_SERVICE_CONTAINER:-ai-holdings-server-data-service-1}"

KEY="${HERMES_DOMAIN_TOOLS_KEY:-${HERMES_INTERNAL_TOKEN:-}}"
if [ -z "$KEY" ] && command -v docker >/dev/null 2>&1; then
  KEY="$(docker exec "$DATA_SERVICE_CONTAINER" printenv HERMES_DOMAIN_TOOLS_KEY 2>/dev/null || true)"
fi
if [ -z "$KEY" ] && command -v docker >/dev/null 2>&1; then
  KEY="$(docker exec "$DATA_SERVICE_CONTAINER" printenv HERMES_INTERNAL_TOKEN 2>/dev/null || true)"
fi
if [ -z "$KEY" ]; then
  echo "missing HERMES_DOMAIN_TOOLS_KEY or HERMES_INTERNAL_TOKEN" >&2
  exit 2
fi

post_json() {
  path="$1"
  body="$2"
  curl -fsS \
    -H "Content-Type: application/json" \
    -H "X-Hermes-Domain-Tools-Key: $KEY" \
    -H "X-Hermes-Internal-Token: $KEY" \
    --data-binary "$body" \
    "$BASE_URL$path"
}

case "$CYCLE" in
  premarket|intraday|postmarket) ;;
  *)
    echo "invalid HERMES_ALERT_CENTER_CYCLE: $CYCLE" >&2
    exit 2
    ;;
esac

echo "[$(date -Is)] alert-center $CYCLE"
post_json "/api/hermes/alert-center/run" "{\"cycle\":\"$CYCLE\",\"limit\":$LIMIT,\"dry_run\":false}"
echo
echo "[$(date -Is)] delivery"
post_json "/api/hermes/delivery/process-ready" "{\"limit\":$LIMIT,\"dry_run\":false}"
echo
