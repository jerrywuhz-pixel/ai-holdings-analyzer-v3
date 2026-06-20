#!/usr/bin/env bash
set -euo pipefail

HERMES_HOME="${HERMES_HOME:-/root/.hermes}"
HOOK_DIR="${HERMES_IMA_GATEWAY_HOOK_DIR:-$HERMES_HOME/hooks/ima-archive}"
DATA_SERVICE_URL="${HERMES_IMA_ARCHIVE_HOOK_DATA_SERVICE_URL:-${DATA_SERVICE_URL:-http://172.17.0.1:8000}}"
RESTART_GATEWAYS=1

usage() {
  cat <<'EOF'
Usage: install-hermes-ima-gateway-hook.sh [options]

Install a Hermes gateway agent:end hook that archives real WeChat gateway
responses through data-service /api/hermes/ima/archive.

Options:
  --no-restart      Install files but do not restart active hermes-gateway-wx-* units.
  -h, --help        Show this help.
EOF
}

while [ "$#" -gt 0 ]; do
  case "$1" in
    --no-restart)
      RESTART_GATEWAYS=0
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "Unknown option: $1" >&2
      usage >&2
      exit 2
      ;;
  esac
done

log() {
  printf '[hermes-ima-gateway-hook] %s\n' "$*"
}

mkdir -p "$HOOK_DIR"
chmod 0755 "$HOOK_DIR"

cat > "$HOOK_DIR/HOOK.yaml" <<'YAML'
name: ima-archive
description: Archive real Hermes gateway replies into the data-service IMA archive pipeline.
events:
  - agent:end
YAML

cat > "$HOOK_DIR/handler.py" <<'PY'
from __future__ import annotations

import json
import os
import urllib.request
from pathlib import Path
from typing import Any


def handle(event_type: str, context: dict[str, Any]) -> None:
    if event_type != "agent:end":
        return
    response = str(context.get("response") or "").strip()
    if not response:
        return
    data_service = _env("HERMES_IMA_ARCHIVE_HOOK_DATA_SERVICE_URL") or "http://172.17.0.1:8000"
    token = _env("HERMES_INTERNAL_TOKEN") or _env("HERMES_DOMAIN_TOOLS_KEY")

    prompt = str(context.get("message") or "").strip()
    session_id = str(context.get("session_id") or "").strip()
    platform = str(context.get("platform") or "").strip()
    user_id = str(context.get("user_id") or "").strip()
    chat_id = str(context.get("chat_id") or "").strip()
    title = "Hermes WeChat reply"
    if platform:
        title = f"{title} - {platform}"
    body = {
        "source": "wechat_gateway_reply",
        "title": title,
        "content_markdown": response,
        "prompt": prompt or None,
        "result_type": "gateway_agent_reply",
        "payload": {
            "ok": True,
            "result_type": "gateway_agent_reply",
            "reply_text": response,
            "session_id": session_id,
            "platform": platform,
        },
        "metadata": {
            "hook": "ima-archive",
            "event_type": event_type,
            "session_id": session_id,
            "platform": platform,
            "chat_id": chat_id,
            "user_id": user_id,
            "response_from_gateway_hook": True,
            "response_may_be_truncated_by_hermes_hook": len(response) >= 500,
        },
    }
    headers = {"Content-Type": "application/json"}
    if token:
        headers["X-Hermes-Internal-Token"] = token
    request = urllib.request.Request(
        data_service.rstrip("/") + "/api/hermes/ima/archive",
        data=json.dumps(body, ensure_ascii=False, separators=(",", ":")).encode("utf-8"),
        headers=headers,
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=45) as resp:
            raw = resp.read(2000).decode("utf-8", "replace")
        parsed = json.loads(raw or "{}")
        archive = parsed.get("archive") if isinstance(parsed, dict) else {}
        _log({
            "status": archive.get("status") or ("ok" if 200 <= resp.status < 300 else "failed"),
            "ima": archive.get("ima") if isinstance(archive, dict) else None,
            "session_id": session_id,
            "auth_header": bool(token),
        })
    except Exception as exc:  # noqa: BLE001 - hooks must not break message delivery.
        _log({"status": "failed", "reason": str(exc)[:300], "session_id": session_id})


def _env(name: str) -> str:
    value = os.getenv(name, "").strip()
    if value:
        return value
    for env_path in _env_paths():
        try:
            for line in env_path.read_text(encoding="utf-8").splitlines():
                if not line or line.lstrip().startswith("#") or "=" not in line:
                    continue
                key, raw = line.split("=", 1)
                if key == name:
                    return raw.strip().strip("'\"")
        except OSError:
            continue
    return ""


def _env_paths() -> list[Path]:
    paths: list[Path] = []
    for value in (
        os.getenv("HERMES_IMA_ARCHIVE_HOOK_ENV"),
        str(Path(os.getenv("HERMES_HOME", "/root/.hermes")) / ".env"),
        "/opt/ai-holdings-analyzer-v3/.env.server",
    ):
        if not value:
            continue
        path = Path(value)
        if path not in paths:
            paths.append(path)
    return paths


def _log(record: dict[str, Any]) -> None:
    log_path = Path(os.getenv("HERMES_IMA_ARCHIVE_HOOK_LOG", "/root/.hermes/logs/ima-archive-hook.jsonl"))
    try:
        log_path.parent.mkdir(parents=True, exist_ok=True)
        with log_path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")
    except OSError:
        pass
PY

python3 - "$HOOK_DIR/handler.py" <<'PY'
from pathlib import Path
import sys

path = Path(sys.argv[1])
compile(path.read_text(encoding="utf-8"), str(path), "exec")
PY
log "installed hook in $HOOK_DIR"

if command -v systemctl >/dev/null 2>&1; then
  systemctl daemon-reload || true
fi

if [ "$RESTART_GATEWAYS" -eq 1 ] && command -v systemctl >/dev/null 2>&1; then
  mapfile -t units < <(systemctl list-units --type=service --state=active --no-legend 'hermes-gateway-wx-*.service' | awk '{print $1}')
  if [ "${#units[@]}" -gt 0 ]; then
    systemctl restart "${units[@]}"
    log "restarted ${#units[@]} active Hermes WeChat gateway unit(s)"
  else
    log "no active Hermes WeChat gateway units found"
  fi
else
  log "restart skipped"
fi
