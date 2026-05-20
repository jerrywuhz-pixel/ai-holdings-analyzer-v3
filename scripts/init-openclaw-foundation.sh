#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$PROJECT_ROOT"

ENV_FILE="${ENV_FILE:-.env.server}"
COMPOSE_FILE="${COMPOSE_FILE:-docker-compose.server.yml}"
DEFAULT_PLAN="${OPENCLAW_DEFAULT_PLAN:-basic}"

log() {
  printf '[openclaw-init] %s\n' "$*"
}

fail() {
  printf '[openclaw-init][ERROR] %s\n' "$*" >&2
  exit 1
}

require_file() {
  [[ -f "$1" ]] || fail "missing required file: $1"
}

require_file "$ENV_FILE"
require_file "$COMPOSE_FILE"

set_env_value() {
  local key="$1"
  local value="$2"
  python3 - "$ENV_FILE" "$key" "$value" <<'PY'
import sys
from pathlib import Path

path = Path(sys.argv[1])
key = sys.argv[2]
value = sys.argv[3]
lines = path.read_text().splitlines()
updated = False
out = []
for line in lines:
    if line.startswith(f"{key}="):
        out.append(f"{key}={value}")
        updated = True
    else:
        out.append(line)
if not updated:
    out.append(f"{key}={value}")
path.write_text("\n".join(out) + "\n")
PY
}

get_env_value() {
  local key="$1"
  awk -F= -v key="$key" '$1 == key {print substr($0, length(key) + 2)}' "$ENV_FILE" | tail -1
}

compose() {
  docker compose --env-file "$ENV_FILE" -f "$COMPOSE_FILE" "$@"
}

log "checking compose services"
compose ps postgres >/dev/null
DB_CONTAINER="$(compose ps -q postgres)"
[[ -n "$DB_CONTAINER" ]] || fail "postgres service is not running"

if [[ -z "$(get_env_value OPENCLAW_SKILL_KEY)" ]]; then
  log "generating OpenClaw internal skill key"
  generated_key="$(python3 - <<'PY'
import secrets
print("oc_sk_" + secrets.token_urlsafe(32))
PY
)"
  set_env_value OPENCLAW_SKILL_KEY "$generated_key"
else
  log "OpenClaw internal skill key already configured"
fi

set_env_value OPENCLAW_DEFAULT_PLAN "$DEFAULT_PLAN"
set_env_value OPENAI_BASE_URL "${OPENAI_BASE_URL:-https://api.openai.com/v1}"

codex_profile="${OPENAI_CODEX_AUTH_PROFILE:-${HERMES_AUTH_PROFILE_ID:-${OPENCLAW_AUTH_PROFILE:-}}}"
codex_bridge_base_url="${OPENAI_CODEX_BRIDGE_BASE_URL:-${HERMES_CODEX_GATEWAY_BASE_URL:-${OPENCLAW_CODEX_GATEWAY_BASE_URL:-}}}"

if [[ -n "${OPENAI_API_KEY:-}" ]]; then
  log "writing OpenAI authorization from OPENAI_API_KEY environment"
  set_env_value OPENAI_API_KEY "$OPENAI_API_KEY"
  set_env_value GBRAIN_OPENAI_API_KEY "$OPENAI_API_KEY"
  set_env_value GBRAIN_LIVE_MODELS_ENABLED true
  set_env_value MODEL_ADAPTER_MODE live
  set_env_value MODEL_AUTH_MODE api_key
  set_env_value HERMES_DEEP_PROVIDER "${HERMES_DEEP_PROVIDER:-openai}"
elif [[ -n "$codex_profile" && -n "$codex_bridge_base_url" ]]; then
  log "writing system-level OpenAI Codex auth bridge configuration"
  set_env_value OPENAI_CODEX_AUTH_PROFILE "$codex_profile"
  set_env_value HERMES_AUTH_PROFILE_ID "$codex_profile"
  set_env_value OPENAI_CODEX_BRIDGE_BASE_URL "$codex_bridge_base_url"
  if [[ -n "${OPENAI_CODEX_BRIDGE_API_KEY:-}" ]]; then
    set_env_value OPENAI_CODEX_BRIDGE_API_KEY "$OPENAI_CODEX_BRIDGE_API_KEY"
  fi
  set_env_value GBRAIN_LIVE_MODELS_ENABLED true
  set_env_value MODEL_ADAPTER_MODE live
  set_env_value MODEL_AUTH_MODE openai_codex
  set_env_value HERMES_DEEP_PROVIDER openai-codex
  if [[ -z "$(get_env_value HERMES_DEEP_MODEL)" || "$(get_env_value HERMES_DEEP_MODEL)" == "gpt-5.5" ]]; then
    set_env_value HERMES_DEEP_MODEL "${HERMES_DEEP_MODEL:-gpt-5.4}"
  fi
else
  log "no OpenAI API key or Codex auth bridge provided; keeping model runtime in stub mode"
  if [[ -z "$(get_env_value GBRAIN_LIVE_MODELS_ENABLED)" ]]; then
    set_env_value GBRAIN_LIVE_MODELS_ENABLED false
  fi
  if [[ -z "$(get_env_value MODEL_ADAPTER_MODE)" ]]; then
    set_env_value MODEL_ADAPTER_MODE stub
  fi
  if [[ -z "$(get_env_value MODEL_AUTH_MODE)" ]]; then
    set_env_value MODEL_AUTH_MODE api_key
  fi
fi

log "initializing plan limits, subscriptions, and quota rows"
docker exec -i "$DB_CONTAINER" psql -U "${POSTGRES_USER:-postgres}" -d "${POSTGRES_DB:-ai_holdings}" -v ON_ERROR_STOP=1 \
  -v default_plan="$DEFAULT_PLAN" <<'SQL'
CREATE TABLE IF NOT EXISTS public.plan_limits (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  plan TEXT NOT NULL,
  action TEXT NOT NULL,
  limit_value INTEGER NOT NULL,
  description TEXT,
  UNIQUE(plan, action)
);

CREATE TABLE IF NOT EXISTS public.subscriptions (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id UUID NOT NULL REFERENCES public.users(id),
  plan TEXT NOT NULL DEFAULT 'free',
  status TEXT NOT NULL DEFAULT 'active',
  current_period_start TIMESTAMPTZ NOT NULL DEFAULT now(),
  current_period_end TIMESTAMPTZ NOT NULL DEFAULT (now() + interval '1 month'),
  cancel_at_period_end BOOLEAN DEFAULT FALSE,
  stripe_customer_id TEXT,
  stripe_subscription_id TEXT,
  stripe_price_id TEXT,
  wechat_transaction_id TEXT,
  payment_method TEXT,
  created_at TIMESTAMPTZ DEFAULT now(),
  updated_at TIMESTAMPTZ DEFAULT now(),
  UNIQUE(tenant_id),
  CONSTRAINT chk_sub_plan CHECK (plan IN ('free', 'basic', 'pro', 'enterprise')),
  CONSTRAINT chk_sub_status CHECK (status IN ('active', 'past_due', 'canceled', 'trialing')),
  CONSTRAINT chk_sub_payment_method CHECK (payment_method IS NULL OR payment_method IN ('stripe', 'wechat'))
);

CREATE TABLE IF NOT EXISTS public.usage_records (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id UUID NOT NULL REFERENCES public.users(id),
  action TEXT NOT NULL,
  quantity INTEGER NOT NULL DEFAULT 1,
  metadata JSONB DEFAULT '{}',
  created_at TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE IF NOT EXISTS public.quota_tracking (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id UUID NOT NULL REFERENCES public.users(id) UNIQUE,
  daily_writes INTEGER NOT NULL DEFAULT 0,
  daily_reads INTEGER NOT NULL DEFAULT 0,
  daily_ai_calls INTEGER NOT NULL DEFAULT 0,
  quota_reset_at TIMESTAMPTZ DEFAULT now(),
  updated_at TIMESTAMPTZ DEFAULT now()
);

INSERT INTO public.plan_limits (plan, action, limit_value, description) VALUES
  ('free', 'ai_analysis', 10, 'OpenClaw/Hermes AI analysis calls per month'),
  ('free', 'trade_write', 5, 'Confirmed trade-record writes per month'),
  ('free', 'data_read', 50, 'Portfolio and market-data reads per month'),
  ('free', 'max_positions', 10, 'Maximum active positions'),
  ('free', 'daily_model_tokens', 80000, 'Daily model token budget'),
  ('free', 'deep_research', 2, 'Deep research jobs per month'),
  ('basic', 'ai_analysis', 200, 'OpenClaw/Hermes AI analysis calls per month'),
  ('basic', 'trade_write', 50, 'Confirmed trade-record writes per month'),
  ('basic', 'data_read', 500, 'Portfolio and market-data reads per month'),
  ('basic', 'max_positions', 100, 'Maximum active positions'),
  ('basic', 'daily_model_tokens', 1000000, 'Daily model token budget'),
  ('basic', 'deep_research', 30, 'Deep research jobs per month'),
  ('pro', 'ai_analysis', -1, 'Unlimited OpenClaw/Hermes AI analysis calls'),
  ('pro', 'trade_write', -1, 'Unlimited confirmed trade-record writes'),
  ('pro', 'data_read', -1, 'Unlimited portfolio and market-data reads'),
  ('pro', 'max_positions', -1, 'Unlimited active positions'),
  ('pro', 'daily_model_tokens', 5000000, 'Daily model token budget'),
  ('pro', 'deep_research', 200, 'Deep research jobs per month'),
  ('enterprise', 'ai_analysis', -1, 'Unlimited OpenClaw/Hermes AI analysis calls'),
  ('enterprise', 'trade_write', -1, 'Unlimited confirmed trade-record writes'),
  ('enterprise', 'data_read', -1, 'Unlimited portfolio and market-data reads'),
  ('enterprise', 'max_positions', -1, 'Unlimited active positions'),
  ('enterprise', 'daily_model_tokens', -1, 'Unlimited daily model token budget'),
  ('enterprise', 'deep_research', -1, 'Unlimited deep research jobs')
ON CONFLICT (plan, action) DO UPDATE SET
  limit_value = EXCLUDED.limit_value,
  description = EXCLUDED.description;

INSERT INTO public.quota_tracking (tenant_id)
SELECT id FROM public.users
ON CONFLICT (tenant_id) DO NOTHING;

INSERT INTO public.subscriptions (tenant_id, plan, status, current_period_start, current_period_end)
SELECT id, :'default_plan', 'active', now(), now() + interval '1 month'
FROM public.users
ON CONFLICT (tenant_id) DO UPDATE SET
  plan = EXCLUDED.plan,
  status = 'active',
  current_period_start = EXCLUDED.current_period_start,
  current_period_end = EXCLUDED.current_period_end,
  updated_at = now();
SQL

log "OpenClaw foundation init complete"
