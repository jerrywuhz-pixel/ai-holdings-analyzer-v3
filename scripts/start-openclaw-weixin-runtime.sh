#!/usr/bin/env bash
set -euo pipefail

OPENCLAW_VERSION="${OPENCLAW_VERSION:-2026.5.27}"
WEIXIN_CLI_VERSION="${WEIXIN_CLI_VERSION:-2.1.4}"
WEIXIN_PLUGIN_VERSION="${WEIXIN_PLUGIN_VERSION:-2.4.4}"
OPENCLAW_STATE_DIR="${OPENCLAW_STATE_DIR:-/state}"
OPENCLAW_GATEWAY_PORT="${OPENCLAW_GATEWAY_PORT:-18789}"
RUN_INSTALL="${RUN_INSTALL:-false}"
RUN_GATEWAY="${RUN_GATEWAY:-true}"

log() {
  printf '[openclaw-weixin-runtime] %s\n' "$*"
}

export OPENCLAW_STATE_DIR

log "installing official OpenClaw runtime packages"
npm install -g "openclaw@$OPENCLAW_VERSION" "@tencent-weixin/openclaw-weixin-cli@$WEIXIN_CLI_VERSION" >/tmp/openclaw-runtime-npm.log 2>&1

log "node=$(node -v) npm=$(npm -v) openclaw=$(openclaw --version)"

if ! openclaw plugins list 2>/dev/null | grep -q 'openclaw-weixin'; then
  log "installing @tencent-weixin/openclaw-weixin@$WEIXIN_PLUGIN_VERSION"
  openclaw plugins install "@tencent-weixin/openclaw-weixin@$WEIXIN_PLUGIN_VERSION"
else
  log "openclaw-weixin plugin already installed"
fi

if [[ "$RUN_INSTALL" == "true" ]]; then
  log "running official installer/login flow; scan QR if prompted"
  npx -y "@tencent-weixin/openclaw-weixin-cli@$WEIXIN_CLI_VERSION" install
fi

log "channel status before gateway start"
openclaw channels list --all | sed -n '/openclaw-weixin/p' || true

if [[ "$RUN_GATEWAY" != "true" ]]; then
  log "RUN_GATEWAY=false, exiting after preflight"
  exit 0
fi

log "starting official OpenClaw Gateway on port $OPENCLAW_GATEWAY_PORT"
exec openclaw gateway run \
  --allow-unconfigured \
  --auth none \
  --bind loopback \
  --port "$OPENCLAW_GATEWAY_PORT" \
  --ws-log compact
