#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
RUN_DIR="$PROJECT_ROOT/.run"

stop_pid_file() {
  local name="$1"
  local pid_file="$RUN_DIR/$name.pid"
  if [[ ! -f "$pid_file" ]]; then
    echo "[INFO] $name pid file not found"
    return
  fi
  local pid
  pid="$(cat "$pid_file")"
  if [[ -n "$pid" ]] && kill -0 "$pid" >/dev/null 2>&1; then
    echo "[INFO] Stopping $name ($pid)"
    kill "$pid"
  else
    echo "[INFO] $name is not running"
  fi
  rm -f "$pid_file"
}

stop_pid_file "post-confirmation-worker"
stop_pid_file "outbox-worker"
stop_pid_file "futu-sidecar"
stop_pid_file "data-service"
stop_pid_file "openclaw"
stop_pid_file "webapp"
