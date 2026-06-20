#!/usr/bin/env bash
set -euo pipefail

HERMES_HOME="${HERMES_HOME:-/root/.hermes}"
HERMES_PROFILES_DIR="${HERMES_PROFILES_DIR:-$HERMES_HOME/profiles}"
HERMES_BIN="${HERMES_BIN:-/usr/local/lib/hermes-agent/venv/bin/hermes}"
HERMES_SHARED_AUTH_DIR="${HERMES_SHARED_AUTH_DIR:-$HERMES_HOME/shared-auth}"
HERMES_GATEWAY_TIMEOUT_STOP_SEC="${HERMES_GATEWAY_TIMEOUT_STOP_SEC:-240}"
SYNC_SOURCE="${SYNC_SOURCE:-$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/hermes_sync_preset_cron.py}"
SYNC_TARGET="${SYNC_TARGET:-/usr/local/bin/hermes-sync-preset-cron}"
SYSTEMD_DIR="${SYSTEMD_DIR:-/etc/systemd/system}"
PROFILE_FILTER=()
SYNC_EXISTING=0
INSTALL_UNITS=1
START_UNITS=1
RESTART_EXISTING_UNITS=0
SHARE_AUTH=1

usage() {
  cat <<'EOF'
Usage: scripts/install-hermes-profile-gateways.sh [options]

Install the Hermes preset-cron sync helper and create one systemd gateway unit
per profile. P0 preset cron jobs are global scheduler work and are not copied
into WeChat profiles unless explicitly requested.

Options:
  --profile NAME             Only process one profile. May be repeated.
  --sync-preset-cron         Copy global P0 preset cron into profile jobs.json.
  --no-sync                  Do not sync preset cron into profile jobs.json.
  --no-units                 Do not write systemd unit files.
  --no-start                 Write units but do not enable/start them.
  --no-shared-auth           Do not link profile auth.json files to shared auth.
  --restart-existing-units   Restart already-active profile units.
  -h, --help                 Show this help.
EOF
}

while [ "$#" -gt 0 ]; do
  case "$1" in
    --profile)
      PROFILE_FILTER+=("${2:?missing profile name}")
      shift 2
      ;;
    --no-sync)
      SYNC_EXISTING=0
      shift
      ;;
    --sync-preset-cron)
      SYNC_EXISTING=1
      shift
      ;;
    --no-units)
      INSTALL_UNITS=0
      shift
      ;;
    --no-start)
      START_UNITS=0
      shift
      ;;
    --no-shared-auth)
      SHARE_AUTH=0
      shift
      ;;
    --restart-existing-units)
      RESTART_EXISTING_UNITS=1
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
  printf '[hermes-profile-gateways] %s\n' "$*"
}

find_codex_auth_source() {
  python3 - "$HERMES_HOME" "$HERMES_PROFILES_DIR" "$HERMES_SHARED_AUTH_DIR/auth.json" <<'PY'
import json
import sys
from pathlib import Path

home = Path(sys.argv[1])
profiles_dir = Path(sys.argv[2])
shared_auth = Path(sys.argv[3])

paths = []
if shared_auth.exists():
    paths.append(shared_auth)
paths.append(home / "auth.json")
if profiles_dir.exists():
    paths.extend(sorted(profiles_dir.glob("*/auth.json")))

seen = set()
for path in paths:
    try:
        resolved = path.resolve()
    except OSError:
        resolved = path
    if resolved in seen or not path.exists():
        continue
    seen.add(resolved)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        continue
    providers = data.get("providers") if isinstance(data, dict) else None
    codex = providers.get("openai-codex") if isinstance(providers, dict) else None
    if isinstance(codex, dict) and codex.get("access_token"):
        print(path)
        raise SystemExit(0)
    pool = data.get("credential_pool") if isinstance(data, dict) else None
    codex_pool = pool.get("openai-codex") if isinstance(pool, dict) else None
    if isinstance(codex_pool, list) and any(isinstance(item, dict) and item.get("access_token") for item in codex_pool):
        print(path)
        raise SystemExit(0)
raise SystemExit(1)
PY
}

link_shared_auth() {
  [ "$SHARE_AUTH" -eq 1 ] || return 0
  source_auth="$(find_codex_auth_source 2>/dev/null || true)"
  if [ -z "$source_auth" ]; then
    log "no openai-codex access token found; shared auth link skipped"
    return 0
  fi

  stamp="$(date +%Y%m%dT%H%M%S%z)"
  shared_auth="$HERMES_SHARED_AUTH_DIR/auth.json"
  shared_lock="$HERMES_SHARED_AUTH_DIR/auth.lock"
  mkdir -p "$HERMES_SHARED_AUTH_DIR"
  chmod 0700 "$HERMES_SHARED_AUTH_DIR"
  if [ ! -e "$shared_auth" ] || [ "$(readlink -f "$source_auth")" != "$(readlink -f "$shared_auth" 2>/dev/null || true)" ]; then
    [ -e "$shared_auth" ] && [ ! -L "$shared_auth" ] && cp -a "$shared_auth" "$shared_auth.bak-$stamp"
    install -m 0600 "$source_auth" "$shared_auth"
  fi
  : > "$shared_lock"
  chmod 0600 "$shared_lock"

  auth_homes=("$HERMES_HOME")
  for profile_dir in "${profiles[@]}"; do
    auth_homes+=("$profile_dir")
  done
  for auth_home in "${auth_homes[@]}"; do
    [ -d "$auth_home" ] || continue
    if [ -e "$auth_home/auth.json" ] && [ ! -L "$auth_home/auth.json" ]; then
      cp -a "$auth_home/auth.json" "$auth_home/auth.json.bak-shared-$stamp"
    fi
    rm -f "$auth_home/auth.json"
    ln -s "$shared_auth" "$auth_home/auth.json"
    if [ -e "$auth_home/auth.lock" ] && [ ! -L "$auth_home/auth.lock" ]; then
      cp -a "$auth_home/auth.lock" "$auth_home/auth.lock.bak-shared-$stamp"
    fi
    rm -f "$auth_home/auth.lock"
    ln -s "$shared_lock" "$auth_home/auth.lock"
  done
  log "linked Hermes auth for ${#auth_homes[@]} home(s) to $shared_auth"
}

if [ ! -d "$HERMES_HOME" ]; then
  echo "Hermes home not found: $HERMES_HOME" >&2
  exit 1
fi
if [ ! -d "$HERMES_PROFILES_DIR" ]; then
  echo "Hermes profiles dir not found: $HERMES_PROFILES_DIR" >&2
  exit 1
fi
if [ ! -x "$HERMES_BIN" ]; then
  echo "Hermes binary not executable: $HERMES_BIN" >&2
  exit 1
fi
if [ "$SYNC_EXISTING" -eq 1 ] && [ ! -f "$SYNC_SOURCE" ]; then
  echo "Preset cron sync source not found: $SYNC_SOURCE" >&2
  exit 1
fi

if [ -f "$SYNC_SOURCE" ]; then
  install -m 0755 "$SYNC_SOURCE" "$SYNC_TARGET"
  log "installed $SYNC_TARGET"
elif [ "$SYNC_EXISTING" -eq 0 ]; then
  log "preset cron sync helper not found; skipped because --sync-preset-cron was not requested"
fi

profiles=()
if [ "${#PROFILE_FILTER[@]}" -gt 0 ]; then
  for profile in "${PROFILE_FILTER[@]}"; do
    profiles+=("$HERMES_PROFILES_DIR/$profile")
  done
else
  while IFS= read -r -d '' profile_dir; do
    profiles+=("$profile_dir")
  done < <(find "$HERMES_PROFILES_DIR" -maxdepth 1 -mindepth 1 -type d -name 'wx-*' -print0 | sort -z)
fi

if [ "${#profiles[@]}" -eq 0 ]; then
  log "no wx-* profiles found"
  exit 0
fi

link_shared_auth

unit_names=()
for profile_dir in "${profiles[@]}"; do
  if [ ! -d "$profile_dir" ]; then
    echo "Profile dir not found: $profile_dir" >&2
    exit 1
  fi
  profile="$(basename "$profile_dir")"
  unit="hermes-gateway-${profile}.service"
  unit_path="$SYSTEMD_DIR/$unit"
  unit_names+=("$unit")

  if [ "$SYNC_EXISTING" -eq 1 ]; then
    HERMES_PRESET_CRON_HOME="$HERMES_HOME" "$SYNC_TARGET" "$profile_dir" >/tmp/hermes-sync-preset-cron-"$profile".json
    log "synced preset cron for $profile"
  fi

  if [ "$INSTALL_UNITS" -eq 1 ]; then
    cat > "$unit_path" <<EOF
[Unit]
Description=Hermes WeChat gateway for profile $profile
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=root
WorkingDirectory=$HERMES_HOME
Environment=HOME=/root
Environment=HERMES_HOME=$profile_dir
EnvironmentFile=-$HERMES_HOME/.env
ExecStart=$HERMES_BIN --profile $profile gateway run --replace
Restart=always
RestartSec=5
KillSignal=SIGTERM
TimeoutStopSec=$HERMES_GATEWAY_TIMEOUT_STOP_SEC

[Install]
WantedBy=multi-user.target
EOF
    chmod 0644 "$unit_path"
    log "wrote $unit_path"
  fi
done

if [ "$INSTALL_UNITS" -eq 1 ] && command -v systemctl >/dev/null 2>&1; then
  systemctl daemon-reload
  if [ "$START_UNITS" -eq 1 ]; then
    for unit in "${unit_names[@]}"; do
      if [ "$RESTART_EXISTING_UNITS" -eq 1 ] || ! systemctl is-active --quiet "$unit"; then
        systemctl enable --now "$unit"
      else
        systemctl enable "$unit" >/dev/null
      fi
      systemctl is-active --quiet "$unit"
      log "$unit active"
    done
  fi
fi
