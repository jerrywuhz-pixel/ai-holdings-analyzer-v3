#!/usr/bin/env bash
set -euo pipefail

SERVER_HOST="${SERVER_HOST:-149.129.240.111}"
SERVER_USER="${SERVER_USER:-root}"
SERVER_PORT="${SERVER_PORT:-22}"
SSH_KEY="${SSH_KEY:-$HOME/.ssh/ai_holdings_aliyun_deploy_20260519}"
SSH_KNOWN_HOSTS_FILE="${SSH_KNOWN_HOSTS_FILE:-}"
REMOTE_DIR="${REMOTE_DIR:-/opt/ai-holdings-analyzer-v3}"
WEBAPP_HTTP_PORT="${WEBAPP_HTTP_PORT:-3000}"
DATA_SERVICE_PORT="${DATA_SERVICE_PORT:-8000}"

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SSH_TARGET="${SERVER_USER}@${SERVER_HOST}"
SSH_OPTS=(-i "$SSH_KEY" -p "$SERVER_PORT" -o StrictHostKeyChecking=accept-new)
if [ -n "$SSH_KNOWN_HOSTS_FILE" ]; then
  SSH_OPTS+=(-o "UserKnownHostsFile=$SSH_KNOWN_HOSTS_FILE")
fi
RSYNC_SSH="ssh -i '$SSH_KEY' -p '$SERVER_PORT' -o StrictHostKeyChecking=accept-new"
if [ -n "$SSH_KNOWN_HOSTS_FILE" ]; then
  RSYNC_SSH="$RSYNC_SSH -o UserKnownHostsFile='$SSH_KNOWN_HOSTS_FILE'"
fi

log() {
  printf '[deploy-lightweight] %s\n' "$*"
}

require_command() {
  if ! command -v "$1" >/dev/null 2>&1; then
    printf 'Missing required local command: %s\n' "$1" >&2
    exit 1
  fi
}

require_command ssh
require_command rsync

if [ ! -f "$SSH_KEY" ]; then
  printf 'SSH key not found: %s\n' "$SSH_KEY" >&2
  exit 1
fi

log "checking ssh access to ${SSH_TARGET}"
ssh "${SSH_OPTS[@]}" "$SSH_TARGET" "echo ssh_ok >/dev/null"

log "preparing remote directory ${REMOTE_DIR}"
ssh "${SSH_OPTS[@]}" "$SSH_TARGET" "mkdir -p '$REMOTE_DIR'"

log "checking/installing remote rsync"
ssh "${SSH_OPTS[@]}" "$SSH_TARGET" "
  set -e
  if ! command -v rsync >/dev/null 2>&1; then
    if command -v dnf >/dev/null 2>&1; then
      dnf install -y rsync
    elif command -v yum >/dev/null 2>&1; then
      yum install -y rsync
    elif command -v apt-get >/dev/null 2>&1; then
      apt-get update && apt-get install -y rsync
    else
      echo 'rsync is required on the remote server' >&2
      exit 1
    fi
  fi
"

log "syncing project files"
rsync -az --delete \
  -e "$RSYNC_SSH" \
  --exclude '.git/' \
  --exclude '._*' \
  --exclude '.DS_Store' \
  --exclude '.next/' \
  --exclude 'node_modules/' \
  --exclude '.pytest_cache/' \
  --exclude '__pycache__/' \
  --exclude '.env' \
  --include '.env.server.example' \
  --exclude '.env.server' \
  --exclude '.env.*.local' \
  --exclude '.env.local' \
  --exclude '.env.development' \
  --exclude '.env.production' \
  --exclude '*.log' \
  "$ROOT_DIR/" "$SSH_TARGET:$REMOTE_DIR/"

log "writing lightweight-server env"
ssh "${SSH_OPTS[@]}" "$SSH_TARGET" "
  set -e
  cd '$REMOTE_DIR'
  if [ ! -f .env.server ]; then
    cp .env.server.example .env.server
  fi
  sed -i 's|YOUR_SERVER_IP|$SERVER_HOST|g' .env.server
  sed -i 's|^WEBAPP_HTTP_PORT=.*|WEBAPP_HTTP_PORT=$WEBAPP_HTTP_PORT|' .env.server
  sed -i 's|^DATA_SERVICE_URL=.*|DATA_SERVICE_URL=http://data-service:8000|' .env.server
  sed -i 's|^NEXT_PUBLIC_DATA_SERVICE_URL=.*|NEXT_PUBLIC_DATA_SERVICE_URL=http://data-service:8000|' .env.server
  if ! grep -q '^SUPABASE_URL=.\+' .env.server || ! grep -q '^SUPABASE_SERVICE_ROLE_KEY=.\+' .env.server; then
    if grep -q '^HISTORICAL_STORAGE_BACKEND=' .env.server; then
      sed -i 's|^HISTORICAL_STORAGE_BACKEND=.*|HISTORICAL_STORAGE_BACKEND=file|' .env.server
    else
      printf '%s\n' 'HISTORICAL_STORAGE_BACKEND=file' >> .env.server
    fi
    if grep -q '^HISTORICAL_MANIFEST_BACKEND=' .env.server; then
      sed -i 's|^HISTORICAL_MANIFEST_BACKEND=.*|HISTORICAL_MANIFEST_BACKEND=file|' .env.server
    else
      printf '%s\n' 'HISTORICAL_MANIFEST_BACKEND=file' >> .env.server
    fi
  fi
  if ! grep -q '^LONGBRIDGE_MCP_ACCESS_TOKEN=.\+' .env.server && [ -f /root/.hermes/secrets/longbridge_mcp_auth_response.json ]; then
    python3 - <<'PY'
import json
from pathlib import Path

env_path = Path(".env.server")
token_path = Path("/root/.hermes/secrets/longbridge_mcp_auth_response.json")
token = json.loads(token_path.read_text()).get("structuredContent", {}).get("access_token", "")
if token:
    lines = env_path.read_text().splitlines()
    out = []
    updated = False
    for line in lines:
        if line.startswith("LONGBRIDGE_MCP_ACCESS_TOKEN="):
            out.append(f"LONGBRIDGE_MCP_ACCESS_TOKEN={token}")
            updated = True
        else:
            out.append(line)
    if not updated:
        out.append(f"LONGBRIDGE_MCP_ACCESS_TOKEN={token}")
    env_path.write_text("\n".join(out) + "\n")
PY
  fi
"

log "checking/installing docker"
ssh "${SSH_OPTS[@]}" "$SSH_TARGET" "
  set -e
  if ! command -v docker >/dev/null 2>&1; then
    if command -v dnf >/dev/null 2>&1; then
      cat > /etc/yum.repos.d/docker-ce.repo <<'EOF'
[docker-ce-stable]
name=Docker CE Stable - \$basearch
baseurl=https://mirrors.aliyun.com/docker-ce/linux/centos/8/\$basearch/stable
enabled=1
gpgcheck=1
gpgkey=https://mirrors.aliyun.com/docker-ce/linux/centos/gpg
EOF
      dnf makecache --repo docker-ce-stable
      dnf install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
    elif command -v yum >/dev/null 2>&1; then
      yum install -y yum-utils
      yum-config-manager --add-repo https://mirrors.aliyun.com/docker-ce/linux/centos/docker-ce.repo
      yum install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
    elif command -v apt-get >/dev/null 2>&1; then
      apt-get update
      apt-get install -y docker.io docker-compose-plugin
    else
      echo 'Docker is required and no supported package manager was found' >&2
      exit 1
    fi
  fi
  systemctl enable --now docker >/dev/null 2>&1 || service docker start
  docker compose version >/dev/null
"

log "running preflight"
ssh "${SSH_OPTS[@]}" "$SSH_TARGET" "cd '$REMOTE_DIR' && bash scripts/server-preflight.sh"

log "starting services"
ssh "${SSH_OPTS[@]}" "$SSH_TARGET" "
  set -e
  cd '$REMOTE_DIR'
  docker compose --env-file .env.server -f docker-compose.server.yml up -d --build
"

log "applying local Postgres migrations"
ssh "${SSH_OPTS[@]}" "$SSH_TARGET" "
  set -e
  cd '$REMOTE_DIR'
  bash scripts/apply-server-migrations.sh
  bash scripts/init-hermes-foundation.sh
  docker compose --env-file .env.server -f docker-compose.server.yml up -d data-service gbrain webapp
"

log "installing Hermes profile cron sync and gateway units"
ssh "${SSH_OPTS[@]}" "$SSH_TARGET" "
  set -e
  cd '$REMOTE_DIR'
  if [ -d /root/.hermes/profiles ]; then
    bash scripts/install-hermes-profile-gateways.sh
  else
    echo 'Hermes profiles dir not found; skipping profile gateway unit installation'
  fi
"

log "waiting for services"
ssh "${SSH_OPTS[@]}" "$SSH_TARGET" "
  set -e
  cd '$REMOTE_DIR'
  health_bind=\"\$(awk -F= '\$1 == \"INTERNAL_HOST_BIND\" {print \$2}' .env.server | tail -1)\"
  health_bind=\"\${health_bind:-127.0.0.1}\"
  sleep 20
  docker compose --env-file .env.server -f docker-compose.server.yml ps
  curl -fsS \"http://\$health_bind:8000/health\"
  hermes_key=\"\$(awk -F= '\$1 == \"HERMES_DOMAIN_TOOLS_KEY\" {print \$2}' .env.server | tail -1)\"
  curl -fsS -H \"X-Hermes-Domain-Tools-Key: \$hermes_key\" \"http://\$health_bind:8000/api/hermes/domain-tools\"
  docker exec ai-holdings-server-postgres-1 psql -U postgres -d ai_holdings -Atc 'select count(*) from public.schema_migrations;'
  curl -fsSI http://127.0.0.1:$WEBAPP_HTTP_PORT >/dev/null
"

log "done: http://${SERVER_HOST}:${WEBAPP_HTTP_PORT}"
