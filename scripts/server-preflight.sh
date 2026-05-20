#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

COMPOSE_FILE="${COMPOSE_FILE:-docker-compose.server.yml}"
ENV_FILE="${ENV_FILE:-.env.server}"

info() {
  printf '[server-preflight] %s\n' "$*"
}

fail() {
  printf '[server-preflight][ERROR] %s\n' "$*" >&2
  exit 1
}

require_file() {
  [[ -f "$1" ]] || fail "missing required file: $1"
}

require_cmd() {
  command -v "$1" >/dev/null 2>&1 || fail "$1 is not installed or not in PATH"
}

info "checking files"
require_file "$COMPOSE_FILE"
require_file "$ENV_FILE"
require_file "webapp/Dockerfile"
require_file "data-service/Dockerfile"
require_file "openclaw/Dockerfile"
require_file "gbrain/Dockerfile"

info "checking Docker"
require_cmd docker
docker version >/dev/null || fail "Docker daemon is not reachable"
docker compose version >/dev/null || fail "Docker Compose plugin is not available"

info "checking compose config"
docker compose --env-file "$ENV_FILE" -f "$COMPOSE_FILE" config >/tmp/ai-holdings-compose-config.yml

info "checking free disk space"
available_kb="$(df -Pk . | awk 'NR==2 {print $4}')"
if [[ "${available_kb:-0}" -lt 5242880 ]]; then
  fail "less than 5GB free disk space; free space before building images"
fi

info "checking configured public URL"
if grep -q 'YOUR_SERVER_IP' "$ENV_FILE"; then
  fail "replace YOUR_SERVER_IP in $ENV_FILE with your server public IP or domain"
fi

info "checking foundation version anchors"
grep -q '^OPENCLAW_UPSTREAM_TARGET_VERSION=' "$ENV_FILE" || fail "missing OPENCLAW_UPSTREAM_TARGET_VERSION in $ENV_FILE"
grep -q '^HERMES_UPSTREAM_TARGET_VERSION=' "$ENV_FILE" || fail "missing HERMES_UPSTREAM_TARGET_VERSION in $ENV_FILE"
grep -q '^GBRAIN_ADAPTER_VERSION=' "$ENV_FILE" || fail "missing GBRAIN_ADAPTER_VERSION in $ENV_FILE"

info "preflight passed"
