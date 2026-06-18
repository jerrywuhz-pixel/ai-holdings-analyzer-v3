#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

OPENCLAW_VERSION="${OPENCLAW_VERSION:-2026.5.27}"
WEIXIN_CLI_VERSION="${WEIXIN_CLI_VERSION:-2.1.4}"
WEIXIN_PLUGIN_VERSION="${WEIXIN_PLUGIN_VERSION:-2.4.4}"
MIN_NODE_VERSION="${MIN_NODE_VERSION:-22.19.0}"
USE_DOCKER="${USE_DOCKER:-auto}"
RUN_INSTALL="${RUN_INSTALL:-false}"

log() {
  printf '[openclaw-weixin-sidecar] %s\n' "$*"
}

fail() {
  printf '[openclaw-weixin-sidecar][ERROR] %s\n' "$*" >&2
  exit 1
}

node_satisfies() {
  node - "$MIN_NODE_VERSION" <<'JS'
const required = process.argv[2].split('.').map(Number);
const current = process.versions.node.split('.').map(Number);
for (let i = 0; i < 3; i += 1) {
  if ((current[i] || 0) > (required[i] || 0)) process.exit(0);
  if ((current[i] || 0) < (required[i] || 0)) process.exit(1);
}
process.exit(0);
JS
}

if [[ "${RUN_INSIDE_OPENCLAW_WEIXIN_SIDECAR:-false}" != "true" ]]; then
  needs_docker=false
  if [[ "$USE_DOCKER" == "true" ]]; then
    needs_docker=true
  elif [[ "$USE_DOCKER" == "auto" ]]; then
    if ! command -v node >/dev/null 2>&1 || ! node_satisfies; then
      needs_docker=true
    fi
  fi

  if [[ "$needs_docker" == "true" ]]; then
    command -v docker >/dev/null 2>&1 || fail "Node >= $MIN_NODE_VERSION is unavailable and docker is not installed"
    log "using node:22-alpine sidecar because host Node is below $MIN_NODE_VERSION or USE_DOCKER=true"
    exec docker run --rm \
      -e RUN_INSIDE_OPENCLAW_WEIXIN_SIDECAR=true \
      -e OPENCLAW_VERSION="$OPENCLAW_VERSION" \
      -e WEIXIN_CLI_VERSION="$WEIXIN_CLI_VERSION" \
      -e WEIXIN_PLUGIN_VERSION="$WEIXIN_PLUGIN_VERSION" \
      -e MIN_NODE_VERSION="$MIN_NODE_VERSION" \
      -e RUN_INSTALL="$RUN_INSTALL" \
      -v "$PROJECT_ROOT:/workspace" \
      -w /workspace \
      node:22-bookworm-slim \
      bash ./scripts/verify-openclaw-weixin-sidecar.sh
  fi
fi

command -v node >/dev/null 2>&1 || fail "node is required"
command -v npm >/dev/null 2>&1 || fail "npm is required"
node_satisfies || fail "Node $(node -v) does not satisfy required >= $MIN_NODE_VERSION"

log "node=$(node -v) npm=$(npm -v)"
log "checking official package metadata"
npm view "openclaw@$OPENCLAW_VERSION" version engines --json
npm view "@tencent-weixin/openclaw-weixin@$WEIXIN_PLUGIN_VERSION" version engines --json
npm view "@tencent-weixin/openclaw-weixin-cli@$WEIXIN_CLI_VERSION" version engines --json

log "checking official weixin CLI entrypoint"
npx -y "@tencent-weixin/openclaw-weixin-cli@$WEIXIN_CLI_VERSION" --help

log "checking OpenClaw host package can be resolved"
timeout 20 npm view "openclaw@$OPENCLAW_VERSION" dist.tarball --json >/tmp/openclaw-sidecar-host-package.txt
cat /tmp/openclaw-sidecar-host-package.txt

if [[ "$RUN_INSTALL" == "true" ]]; then
  log "running official installer in interactive mode; this may require QR login"
  npx -y "@tencent-weixin/openclaw-weixin-cli@$WEIXIN_CLI_VERSION" install
else
  log "RUN_INSTALL=false, so no login or channel cutover was attempted"
fi

log "sidecar preflight complete"
