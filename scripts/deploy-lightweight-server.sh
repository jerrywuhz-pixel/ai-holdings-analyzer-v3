#!/usr/bin/env bash
set -euo pipefail

SERVER_HOST="${SERVER_HOST:-149.129.240.111}"
SERVER_USER="${SERVER_USER:-root}"
SERVER_PORT="${SERVER_PORT:-22222}"
SSH_KEY="${SSH_KEY:-$HOME/.ssh/ai_holdings_aliyun_deploy_20260521}"
REMOTE_DIR="${REMOTE_DIR:-/opt/ai-holdings-analyzer-v3}"
WEBAPP_HTTP_PORT="${WEBAPP_HTTP_PORT:-3000}"
DATA_SERVICE_PORT="${DATA_SERVICE_PORT:-8000}"

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SSH_TARGET="${SERVER_USER}@${SERVER_HOST}"
SSH_OPTS=(-i "$SSH_KEY" -p "$SERVER_PORT" -o StrictHostKeyChecking=accept-new)

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
  -e "ssh -i '$SSH_KEY' -p '$SERVER_PORT' -o StrictHostKeyChecking=accept-new" \
  --exclude '.git/' \
  --exclude '._*' \
  --exclude '.DS_Store' \
  --exclude '.next/' \
  --exclude 'node_modules/' \
  --exclude '.venv/' \
  --exclude 'venv/' \
  --exclude '.runtime/' \
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
  docker compose --env-file .env.server -f docker-compose.server.yml up -d --force-recreate data-service gbrain openclaw webapp
"

log "waiting for services"
ssh "${SSH_OPTS[@]}" "$SSH_TARGET" "
  set -e
  cd '$REMOTE_DIR'
  host_bind=\"\$(grep -E '^INTERNAL_HOST_BIND=' .env.server | tail -n 1 | cut -d= -f2- || true)\"
  host_bind=\"\${host_bind:-127.0.0.1}\"
  sleep 20
  docker compose --env-file .env.server -f docker-compose.server.yml ps
  curl -fsS \"http://\${host_bind}:8000/health\"
  curl -fsS \"http://\${host_bind}:8080/health\"
  docker exec ai-holdings-server-postgres-1 psql -U postgres -d ai_holdings -Atc 'select count(*) from public.schema_migrations;'
  curl -fsSI http://127.0.0.1:$WEBAPP_HTTP_PORT >/dev/null
"

log "done: http://${SERVER_HOST}:${WEBAPP_HTTP_PORT}"
