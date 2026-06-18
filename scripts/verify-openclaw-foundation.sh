#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$PROJECT_ROOT"

ENV_FILE="${ENV_FILE:-.env.server}"
COMPOSE_FILE="${COMPOSE_FILE:-docker-compose.server.yml}"
OPENCLAW_URL="${OPENCLAW_URL:-http://127.0.0.1:${OPENCLAW_PORT:-8080}}"
REQUIRE_OPENAI_AUTH="${REQUIRE_OPENAI_AUTH:-false}"

log() {
  printf '[openclaw-verify] %s\n' "$*"
}

fail() {
  printf '[openclaw-verify][ERROR] %s\n' "$*" >&2
  exit 1
}

compose() {
  docker compose --env-file "$ENV_FILE" -f "$COMPOSE_FILE" "$@"
}

env_value() {
  local key="$1"
  awk -F= -v key="$key" '$1 == key {print substr($0, length(key) + 2)}' "$ENV_FILE" | tail -1
}

[[ -f "$ENV_FILE" ]] || fail "missing env file: $ENV_FILE"
[[ -f "$COMPOSE_FILE" ]] || fail "missing compose file: $COMPOSE_FILE"

log "checking OpenClaw internal skill key"
[[ -n "$(env_value OPENCLAW_SKILL_KEY)" ]] || fail "OPENCLAW_SKILL_KEY is missing"

DB_CONTAINER="$(compose ps -q postgres)"
[[ -n "$DB_CONTAINER" ]] || fail "postgres service is not running"

log "checking plan limits and user quota rows"
docker exec -i "$DB_CONTAINER" psql -U "${POSTGRES_USER:-postgres}" -d "${POSTGRES_DB:-ai_holdings}" -v ON_ERROR_STOP=1 -At <<'SQL' >/tmp/openclaw-foundation-db-check.txt
WITH required(action) AS (
  VALUES ('ai_analysis'), ('trade_write'), ('data_read'), ('max_positions'), ('daily_model_tokens'), ('deep_research')
),
missing AS (
  SELECT action
  FROM required
  WHERE NOT EXISTS (
    SELECT 1 FROM public.plan_limits pl WHERE pl.plan = 'basic' AND pl.action = required.action
  )
)
SELECT 'missing_basic_plan_actions=' || COALESCE(string_agg(action, ','), '') FROM missing;

SELECT 'users=' || count(*) FROM public.users;
SELECT 'quota_tracking=' || count(*) FROM public.quota_tracking;
SELECT 'subscriptions=' || count(*) FROM public.subscriptions WHERE status = 'active';
SQL

cat /tmp/openclaw-foundation-db-check.txt
if grep -q '^missing_basic_plan_actions=.' /tmp/openclaw-foundation-db-check.txt; then
  fail "basic plan limits are incomplete"
fi

users="$(awk -F= '$1 == "users" {print $2}' /tmp/openclaw-foundation-db-check.txt)"
quotas="$(awk -F= '$1 == "quota_tracking" {print $2}' /tmp/openclaw-foundation-db-check.txt)"
subs="$(awk -F= '$1 == "subscriptions" {print $2}' /tmp/openclaw-foundation-db-check.txt)"
[[ "${users:-0}" -le "${quotas:-0}" ]] || fail "not all users have quota_tracking rows"
[[ "${users:-0}" -le "${subs:-0}" ]] || fail "not all users have active subscriptions"

log "checking OpenClaw runtime status"
python3 - "$OPENCLAW_URL/health" "$OPENCLAW_URL/api/hermes/domain-tools" "$REQUIRE_OPENAI_AUTH" "$(env_value OPENCLAW_SKILL_KEY)" <<'PY'
import json
import sys
import urllib.request

url, tools_url, require_openai, skill_key = sys.argv[1:5]
with urllib.request.urlopen(url, timeout=10) as response:
    payload = json.load(response)

runtime = payload.get("runtime", {})
auth = runtime.get("authorization", {})
token_plan = runtime.get("token_plan", {})
gateway = payload.get("gateway", {})
active_skills = set(gateway.get("active_skills") or [])
required_skills = {
    "trade-input",
    "broker-parse",
    "position-aggregate",
    "daily-analysis",
    "quant-options-strategy",
    "profit-taking",
    "ftshare-market-data",
    "ima-skill",
    "gbrain-sync",
}
missing_skills = sorted(required_skills - active_skills)
data_sources = payload.get("data_sources") or []

assert payload.get("status") == "ok", payload
assert auth.get("openclaw_skill_key_configured") is True, payload
assert token_plan.get("default_plan"), payload
assert token_plan.get("context_pack_max_tokens", 0) >= 16000, payload
assert not missing_skills, {"missing_openclaw_skills": missing_skills, "active_skills": sorted(active_skills)}
assert data_sources, payload
if require_openai.lower() == "true":
    assert auth.get("system_model_auth_ready") is True, payload
    assert auth.get("live_model_authorization") == "ready", payload

tools_request = urllib.request.Request(
    tools_url,
    headers={"X-OpenClaw-Skill-Key": skill_key} if skill_key else {},
)
with urllib.request.urlopen(tools_request, timeout=10) as response:
    tools_payload = json.load(response)
tools = {item.get("name") for item in tools_payload.get("tools", [])}
required_domain_tools = {
    "market.quote",
    "market.batch_quote",
    "options.sell_put_rank",
    "broker.positions_read",
    "reference.ima.search",
    "reference.ima.read",
}
missing_domain_tools = sorted(required_domain_tools - tools)
assert not missing_domain_tools, {
    "missing_domain_tools": missing_domain_tools,
    "tools": sorted(tools),
}

print(
    "runtime_authorization="
    + json.dumps(
        {
            "openclaw_skill_key_configured": auth.get("openclaw_skill_key_configured"),
            "model_auth_mode": runtime.get("modes", {}).get("model_auth_mode"),
            "deep_provider": runtime.get("models", {}).get("deep_provider"),
            "openai_configured": auth.get("openai_configured"),
            "openai_codex_configured": auth.get("openai_codex_configured"),
            "system_model_auth_ready": auth.get("system_model_auth_ready"),
            "live_model_authorization": auth.get("live_model_authorization"),
            "default_plan": token_plan.get("default_plan"),
            "context_pack_max_tokens": token_plan.get("context_pack_max_tokens"),
            "active_skills": sorted(active_skills),
            "data_sources": [
                {
                    "id": item.get("id"),
                    "status": item.get("status"),
                    "kind": item.get("kind"),
                }
                for item in data_sources
            ],
            "domain_tools": sorted(tools),
        },
        ensure_ascii=False,
    )
)
PY

log "OpenClaw foundation verification complete"
