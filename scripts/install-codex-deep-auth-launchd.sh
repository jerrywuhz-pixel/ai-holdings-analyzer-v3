#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ACTION="${1:-install}"

BRIDGE_LABEL="${BRIDGE_LABEL:-ai.holdings.codex-bridge}"
TUNNEL_LABEL="${TUNNEL_LABEL:-ai.holdings.codex-tunnel}"
LAUNCH_AGENTS_DIR="${LAUNCH_AGENTS_DIR:-$HOME/Library/LaunchAgents}"
RUNTIME_DIR="${CODEX_DEEP_AUTH_RUNTIME_DIR:-$HOME/.ai-holdings-analyzer-v3/codex-deep-auth}"
SOURCE_DIR="${CODEX_DEEP_AUTH_SOURCE_DIR:-$HOME/.ai-holdings-analyzer-v3/codex-bridge-src}"
BIN_DIR="$RUNTIME_DIR/bin"
LOG_DIR="${CODEX_DEEP_AUTH_LOG_DIR:-$RUNTIME_DIR/logs}"

PATH_VALUE="${CODEX_DEEP_AUTH_PATH:-/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/Users/ruifeng/npm-global/bin:$HOME/.local/bin:$HOME/.cargo/bin}"
CODEX_BIN="${CODEX_BIN:-$(command -v codex || true)}"
CODEX_BINARY="${CODEX_BINARY:-${CODEX_BIN:-codex}}"
PYTHON_BIN="${PYTHON_BIN:-$(command -v python3 || true)}"
PYTHON_BIN="${PYTHON_BIN:-python3}"
UV_BIN="${UV_BIN:-$(command -v uv || true)}"
UV_BIN="${UV_BIN:-uv}"

CODEX_BRIDGE_HOST="${CODEX_BRIDGE_HOST:-127.0.0.1}"
CODEX_BRIDGE_PORT="${CODEX_BRIDGE_PORT:-8091}"
OPENAI_CODEX_AUTH_PROFILE="${OPENAI_CODEX_AUTH_PROFILE:-system-pro}"
CODEX_BRIDGE_TIMEOUT_SECONDS="${CODEX_BRIDGE_TIMEOUT_SECONDS:-360}"
CODEX_CLI_TIMEOUT_SECONDS="${CODEX_CLI_TIMEOUT_SECONDS:-300}"
CODEX_BRIDGE_CODEX_WORKDIR="${CODEX_BRIDGE_CODEX_WORKDIR:-/tmp}"

ALIYUN_HOST="${ALIYUN_HOST:-149.129.240.111}"
ALIYUN_SSH_PORT="${ALIYUN_SSH_PORT:-22222}"
ALIYUN_SSH_USER="${ALIYUN_SSH_USER:-root}"
ALIYUN_SSH_KEY="${ALIYUN_SSH_KEY:-$HOME/.ssh/ai_holdings_aliyun_deploy_20260521}"
REMOTE_BRIDGE_HOST="${REMOTE_BRIDGE_HOST:-127.0.0.1}"
REMOTE_BRIDGE_PORT="${REMOTE_BRIDGE_PORT:-8091}"

BRIDGE_WRAPPER="$BIN_DIR/codex-bridge-launchd.sh"
TUNNEL_WRAPPER="$BIN_DIR/codex-tunnel-launchd.sh"
BRIDGE_PLIST="$LAUNCH_AGENTS_DIR/$BRIDGE_LABEL.plist"
TUNNEL_PLIST="$LAUNCH_AGENTS_DIR/$TUNNEL_LABEL.plist"

usage() {
  cat <<USAGE
Usage: scripts/install-codex-deep-auth-launchd.sh <install|uninstall|status>

Installs two macOS LaunchAgents:
  $BRIDGE_LABEL  - local OpenAI-compatible Codex auth bridge
  $TUNNEL_LABEL  - reverse SSH tunnel from Aliyun 127.0.0.1:$REMOTE_BRIDGE_PORT to this Mac

Useful environment overrides:
  ALIYUN_HOST=$ALIYUN_HOST
  ALIYUN_SSH_PORT=$ALIYUN_SSH_PORT
  ALIYUN_SSH_KEY=$ALIYUN_SSH_KEY
  CODEX_BRIDGE_PORT=$CODEX_BRIDGE_PORT
  OPENAI_CODEX_AUTH_PROFILE=$OPENAI_CODEX_AUTH_PROFILE
  CODEX_DEEP_AUTH_RUNTIME_DIR=$RUNTIME_DIR
  CODEX_DEEP_AUTH_SOURCE_DIR=$SOURCE_DIR
USAGE
}

require_file() {
  local path="$1"
  local label="$2"
  if [[ ! -f "$path" ]]; then
    echo "[codex-deep-auth][ERROR] missing $label: $path" >&2
    exit 1
  fi
}

sync_bridge_source() {
  mkdir -p \
    "$SOURCE_DIR/scripts" \
    "$SOURCE_DIR/data-service" \
    "$SOURCE_DIR/local_connectors/openai_codex_bridge"

  cp "$ROOT_DIR/scripts/openai-codex-auth-bridge.sh" "$SOURCE_DIR/scripts/openai-codex-auth-bridge.sh"
  cp "$ROOT_DIR/data-service/requirements.txt" "$SOURCE_DIR/data-service/requirements.txt"
  cp "$ROOT_DIR/local_connectors/requirements.txt" "$SOURCE_DIR/local_connectors/requirements.txt"
  cp "$ROOT_DIR/local_connectors/__init__.py" "$SOURCE_DIR/local_connectors/__init__.py"
  cp "$ROOT_DIR/local_connectors/openai_codex_bridge/"*.py "$SOURCE_DIR/local_connectors/openai_codex_bridge/"
  chmod 700 "$SOURCE_DIR/scripts/openai-codex-auth-bridge.sh"
}

write_wrappers() {
  mkdir -p "$BIN_DIR" "$LOG_DIR" "$LAUNCH_AGENTS_DIR"

  cat > "$BRIDGE_WRAPPER" <<EOF
#!/usr/bin/env bash
set -euo pipefail
export PATH="$PATH_VALUE"
export CODEX_BIN="$CODEX_BIN"
export CODEX_BINARY="$CODEX_BINARY"
export PYTHON_BIN="$PYTHON_BIN"
export UV_BIN="$UV_BIN"
export CODEX_BRIDGE_MODE="command"
export CODEX_BRIDGE_HOST="$CODEX_BRIDGE_HOST"
export CODEX_BRIDGE_PORT="$CODEX_BRIDGE_PORT"
export OPENAI_CODEX_AUTH_PROFILE="$OPENAI_CODEX_AUTH_PROFILE"
export CODEX_BRIDGE_AUTH_PROFILE="$OPENAI_CODEX_AUTH_PROFILE"
export CODEX_BRIDGE_TIMEOUT_SECONDS="$CODEX_BRIDGE_TIMEOUT_SECONDS"
export CODEX_CLI_TIMEOUT_SECONDS="$CODEX_CLI_TIMEOUT_SECONDS"
export CODEX_BRIDGE_CODEX_WORKDIR="$CODEX_BRIDGE_CODEX_WORKDIR"
cd "$SOURCE_DIR"
exec "$SOURCE_DIR/scripts/openai-codex-auth-bridge.sh" start
EOF

  cat > "$TUNNEL_WRAPPER" <<EOF
#!/usr/bin/env bash
set -euo pipefail
export PATH="$PATH_VALUE"
exec /usr/bin/ssh \\
  -N \\
  -o ControlMaster=no \\
  -o ExitOnForwardFailure=yes \\
  -o ServerAliveInterval=30 \\
  -o ServerAliveCountMax=3 \\
  -o StrictHostKeyChecking=accept-new \\
  -i "$ALIYUN_SSH_KEY" \\
  -p "$ALIYUN_SSH_PORT" \\
  -R "$REMOTE_BRIDGE_HOST:$REMOTE_BRIDGE_PORT:$CODEX_BRIDGE_HOST:$CODEX_BRIDGE_PORT" \\
  "$ALIYUN_SSH_USER@$ALIYUN_HOST"
EOF

  chmod 700 "$BRIDGE_WRAPPER" "$TUNNEL_WRAPPER"
}

write_plist() {
  local label="$1"
  local program="$2"
  local stdout_log="$3"
  local stderr_log="$4"
  local plist_path="$5"

  "$PYTHON_BIN" - "$label" "$program" "$stdout_log" "$stderr_log" "$plist_path" <<'PY'
from __future__ import annotations

import plistlib
import sys
from pathlib import Path

label, program, stdout_log, stderr_log, plist_path = sys.argv[1:6]
payload = {
    "Label": label,
    "ProgramArguments": [program],
    "RunAtLoad": True,
    "KeepAlive": True,
    "ThrottleInterval": 10,
    "StandardOutPath": stdout_log,
    "StandardErrorPath": stderr_log,
    "WorkingDirectory": str(Path(program).resolve().parents[1]),
}
Path(plist_path).write_bytes(plistlib.dumps(payload, sort_keys=False))
PY
}

bootout_if_loaded() {
  local label="$1"
  local plist_path="$2"
  launchctl bootout "gui/$(id -u)" "$plist_path" >/dev/null 2>&1 || true
  launchctl bootout "gui/$(id -u)/$label" >/dev/null 2>&1 || true
}

bootstrap_agent() {
  local label="$1"
  local plist_path="$2"
  bootout_if_loaded "$label" "$plist_path"
  launchctl bootstrap "gui/$(id -u)" "$plist_path"
  launchctl enable "gui/$(id -u)/$label" >/dev/null 2>&1 || true
  launchctl kickstart -k "gui/$(id -u)/$label"
}

install_agents() {
  require_file "$ROOT_DIR/scripts/openai-codex-auth-bridge.sh" "bridge script"
  require_file "$ALIYUN_SSH_KEY" "Aliyun SSH key"
  if [[ -z "$CODEX_BIN" || ! -x "$CODEX_BIN" ]]; then
    echo "[codex-deep-auth][ERROR] codex binary not executable: ${CODEX_BIN:-<empty>}" >&2
    exit 1
  fi

  sync_bridge_source
  write_wrappers
  write_plist "$BRIDGE_LABEL" "$BRIDGE_WRAPPER" "$LOG_DIR/codex-bridge.out.log" "$LOG_DIR/codex-bridge.err.log" "$BRIDGE_PLIST"
  write_plist "$TUNNEL_LABEL" "$TUNNEL_WRAPPER" "$LOG_DIR/codex-tunnel.out.log" "$LOG_DIR/codex-tunnel.err.log" "$TUNNEL_PLIST"

  bootstrap_agent "$BRIDGE_LABEL" "$BRIDGE_PLIST"
  bootstrap_agent "$TUNNEL_LABEL" "$TUNNEL_PLIST"

  echo "[codex-deep-auth] installed launch agents:"
  echo "  $BRIDGE_PLIST"
  echo "  $TUNNEL_PLIST"
  echo "[codex-deep-auth] runtime source:"
  echo "  $SOURCE_DIR"
}

uninstall_agents() {
  bootout_if_loaded "$TUNNEL_LABEL" "$TUNNEL_PLIST"
  bootout_if_loaded "$BRIDGE_LABEL" "$BRIDGE_PLIST"
  rm -f "$TUNNEL_PLIST" "$BRIDGE_PLIST"
  echo "[codex-deep-auth] uninstalled launch agents"
}

status_agents() {
  launchctl print "gui/$(id -u)/$BRIDGE_LABEL" 2>/dev/null || true
  launchctl print "gui/$(id -u)/$TUNNEL_LABEL" 2>/dev/null || true
}

case "$ACTION" in
  install) install_agents ;;
  uninstall) uninstall_agents ;;
  status) status_agents ;;
  -h|--help|help) usage ;;
  *)
    usage >&2
    exit 2
    ;;
esac
