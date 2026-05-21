#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ACTION="${1:-status}"

CODEX_BRIDGE_HOST="${CODEX_BRIDGE_HOST:-127.0.0.1}"
CODEX_BRIDGE_PORT="${CODEX_BRIDGE_PORT:-8091}"
LOCAL_BRIDGE_BASE_URL="${LOCAL_BRIDGE_BASE_URL:-http://$CODEX_BRIDGE_HOST:$CODEX_BRIDGE_PORT}"

ALIYUN_HOST="${ALIYUN_HOST:-149.129.240.111}"
ALIYUN_SSH_PORT="${ALIYUN_SSH_PORT:-22222}"
ALIYUN_SSH_USER="${ALIYUN_SSH_USER:-root}"
ALIYUN_SSH_KEY="${ALIYUN_SSH_KEY:-$HOME/.ssh/ai_holdings_aliyun_deploy_20260521}"
REMOTE_BRIDGE_BASE_URL="${REMOTE_BRIDGE_BASE_URL:-http://127.0.0.1:8091}"
REMOTE_OPENCLAW_HEALTH_URL="${REMOTE_OPENCLAW_HEALTH_URL:-http://127.0.0.1:8080/health}"
REMOTE_DEPLOY_DIR="${REMOTE_DEPLOY_DIR:-/opt/ai-holdings-analyzer-v3}"

ssh_remote() {
  ssh \
    -i "$ALIYUN_SSH_KEY" \
    -p "$ALIYUN_SSH_PORT" \
    -o BatchMode=yes \
    -o ServerAliveInterval=15 \
    -o ServerAliveCountMax=4 \
    "$ALIYUN_SSH_USER@$ALIYUN_HOST" \
    "$@"
}

print_section() {
  printf '\n[codex-deep-auth] %s\n' "$1"
}

local_health() {
  print_section "local bridge health"
  curl -fsS "$LOCAL_BRIDGE_BASE_URL/health"
  printf '\n'
}

remote_bridge_health() {
  print_section "remote bridge health through reverse tunnel"
  ssh_remote "curl -fsS '$REMOTE_BRIDGE_BASE_URL/health'"
  printf '\n'
}

remote_openclaw_health() {
  print_section "remote OpenClaw runtime health"
  ssh_remote "curl -fsS '$REMOTE_OPENCLAW_HEALTH_URL'"
  printf '\n'
}

remote_bridge_smoke() {
  print_section "remote bridge GPT-5.5 smoke"
  ssh_remote "curl -fsS -H 'Content-Type: application/json' -d '{\"model\":\"openai-codex/gpt-5.5\",\"messages\":[{\"role\":\"user\",\"content\":\"Respond exactly with CODEX_AUTH_OK.\"}]}' '$REMOTE_BRIDGE_BASE_URL/v1/chat/completions'"
  printf '\n'
}

remote_gbrain_smoke() {
  print_section "remote gbrain model-adapter smoke"
  ssh_remote "cd '$REMOTE_DEPLOY_DIR' && docker compose --env-file .env.server -f docker-compose.server.yml -f docker-compose.lightweight-host.yml exec -T gbrain bun --eval 'import { buildDefaultModelAdapter, createDefaultHermesModelPolicy } from \"./src/model-adapter.ts\"; const adapter = buildDefaultModelAdapter(); const policy = createDefaultHermesModelPolicy(30 * 60 * 1000, \"deep\"); const result = await adapter.generate(policy, { objective: \"deep auth smoke\", prompt: \"Respond exactly with CODEX_AUTH_OK.\", messages: [{ role: \"user\", content: \"Respond exactly with CODEX_AUTH_OK.\" }] }); console.log(JSON.stringify({ provider: result.provider, model: result.model, stub: result.stub, finishReason: result.finishReason, attemptedRoutes: result.attemptedRoutes, text: result.text }, null, 2));'"
}

case "$ACTION" in
  status)
    local_health
    remote_bridge_health
    remote_openclaw_health
    ;;
  smoke)
    local_health
    remote_bridge_health
    remote_openclaw_health
    remote_bridge_smoke
    remote_gbrain_smoke
    ;;
  -h|--help|help)
    cat <<USAGE
Usage: scripts/check-codex-deep-auth.sh <status|smoke>

status  Check local bridge, remote tunnel, and OpenClaw runtime health.
smoke   Also run GPT-5.5 bridge and gbrain model-adapter smoke tests.
USAGE
    ;;
  *)
    echo "unknown action: $ACTION" >&2
    exit 2
    ;;
esac
