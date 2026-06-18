#!/usr/bin/env bash
set -euo pipefail

HERMES_HOME="${HERMES_HOME:-/root/.hermes}"
HERMES_PROFILES_DIR="${HERMES_PROFILES_DIR:-$HERMES_HOME/profiles}"
HERMES_BIN="${HERMES_BIN:-/usr/local/lib/hermes-agent/venv/bin/hermes}"
SYNC_SOURCE="${SYNC_SOURCE:-$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/hermes_sync_preset_cron.py}"
SYNC_TARGET="${SYNC_TARGET:-/usr/local/bin/hermes-sync-preset-cron}"
SYSTEMD_DIR="${SYSTEMD_DIR:-/etc/systemd/system}"
PROFILE_FILTER=()
SYNC_EXISTING=1
INSTALL_UNITS=1
START_UNITS=1
RESTART_EXISTING_UNITS=0

usage() {
  cat <<'EOF'
Usage: scripts/install-hermes-profile-gateways.sh [options]

Install the Hermes preset-cron sync helper, sync P0 cron jobs into WeChat
profiles, and create one systemd gateway unit per profile.

Options:
  --profile NAME             Only process one profile. May be repeated.
  --no-sync                  Do not sync preset cron into profile jobs.json.
  --no-units                 Do not write systemd unit files.
  --no-start                 Write units but do not enable/start them.
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
    --no-units)
      INSTALL_UNITS=0
      shift
      ;;
    --no-start)
      START_UNITS=0
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
if [ ! -f "$SYNC_SOURCE" ]; then
  echo "Preset cron sync source not found: $SYNC_SOURCE" >&2
  exit 1
fi

install -m 0755 "$SYNC_SOURCE" "$SYNC_TARGET"
log "installed $SYNC_TARGET"

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
ExecStart=$HERMES_BIN --profile $profile gateway run --replace
Restart=always
RestartSec=5
KillSignal=SIGTERM

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
