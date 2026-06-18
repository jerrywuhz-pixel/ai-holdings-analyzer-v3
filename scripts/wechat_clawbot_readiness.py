#!/usr/bin/env python3
"""
Read-only Hermes WeChat ClawBot readiness probe.

The reference.web first-stage path can pass internally while real WeChat remains
unusable if ClawBot credentials are missing. This probe makes that boundary
explicit from environment, database, and optional bridge poll evidence.
"""
from __future__ import annotations

import argparse
import json
import os
import shlex
import subprocess
import sys
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
ENV_FILE = PROJECT_ROOT / ".env"
SERVER_ENV_FILE = PROJECT_ROOT / ".env.server"
DEFAULT_WEBAPP_BASE_URL = "http://127.0.0.1:3000"


@dataclass
class Check:
    name: str
    status: str
    detail: str
    payload: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "status": self.status,
            "detail": self.detail,
            "payload": self.payload,
        }


def load_env_file(path: Path) -> None:
    if not path.exists():
        return
    for raw_line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


def env_present(*names: str) -> bool:
    return any(bool(os.getenv(name, "").strip()) for name in names)


def env_check(database_url: str = "") -> Check:
    payload = {
        "database_url": bool(database_url.strip()) or env_present("DATABASE_URL", "WEBAPP_DATABASE_URL", "SUPABASE_DB_URL"),
        "credential_encryption_key": env_present("ONBOARDING_CREDENTIAL_ENCRYPTION_KEY"),
        "clawbot_api_base_url": env_present("WECHAT_CLAWBOT_API_BASE_URL"),
        "bridge_secret": env_present("HERMES_CRON_SECRET", "OPENCLAW_CRON_SECRET", "WECHAT_CLAWBOT_BRIDGE_SECRET"),
        "delivery_mode": os.getenv("HERMES_DELIVERY_MODE") or os.getenv("OPENCLAW_DELIVERY_MODE") or "",
        "delivery_webhook": env_present("HERMES_DELIVERY_WEBHOOK_URL", "OPENCLAW_DELIVERY_WEBHOOK_URL"),
    }
    missing = [key for key in ("database_url", "credential_encryption_key", "bridge_secret") if not payload[key]]
    if missing:
        return Check("environment", "failed", f"missing required env group(s): {', '.join(missing)}", payload)
    if not payload["clawbot_api_base_url"]:
        return Check("environment", "gap", "WECHAT_CLAWBOT_API_BASE_URL is not configured; binding QR may not work", payload)
    return Check("environment", "passed", "required WeChat bridge env groups are present", payload)


def db_url_from_env(explicit: str = "") -> str:
    return explicit or os.getenv("DATABASE_URL") or os.getenv("WEBAPP_DATABASE_URL") or os.getenv("SUPABASE_DB_URL") or ""


def db_check(database_url: str, *, psql_command: str = "psql") -> Check:
    if not database_url:
        return Check("database", "failed", "DATABASE_URL/WEBAPP_DATABASE_URL/SUPABASE_DB_URL is not configured")
    try:
        rows = db_counts_psycopg(database_url)
    except Exception as psycopg_exc:  # noqa: BLE001
        try:
            rows = db_counts_psql(database_url, psql_command=psql_command)
        except Exception as psql_exc:  # noqa: BLE001
            return Check(
                "database",
                "failed",
                f"DB readiness query failed: psycopg={psycopg_exc}; psql={psql_exc}",
            )

    active_credentials = int(rows.get("active_wechat_credentials") or 0)
    active_bindings = int(rows.get("active_primary_wechat_bindings") or 0)
    pollable = int(rows.get("pollable_bridge_credentials") or 0)
    auth_sessions = int(rows.get("wechat_clawbot_auth_sessions") or 0)
    recent_pending = int(rows.get("recent_pending_auth_sessions") or 0)
    expired_pending = int(rows.get("expired_pending_auth_sessions") or 0)

    detail = (
        f"active_credentials={active_credentials}; active_primary_bindings={active_bindings}; "
        f"pollable_bridge_credentials={pollable}; auth_sessions={auth_sessions}"
    )
    if pollable > 0:
        return Check("database", "passed", detail, rows)
    if active_bindings > 0 and active_credentials == 0:
        return Check("database", "failed", f"{detail}; active binding exists but no active ClawBot credential", rows)
    if recent_pending > 0:
        return Check("database", "gap", f"{detail}; binding authorization appears pending", rows)
    if expired_pending > 0:
        return Check("database", "failed", f"{detail}; pending auth sessions are expired", rows)
    return Check("database", "gap", f"{detail}; no pollable WeChat credential", rows)


def db_counts_psycopg(database_url: str) -> dict[str, int]:
    import psycopg
    from psycopg.rows import dict_row

    with psycopg.connect(database_url, row_factory=dict_row) as conn:
        with conn.cursor() as cur:
            cur.execute(DB_COUNTS_SQL)
            return {str(row["metric"]): int(row["value"]) for row in cur.fetchall()}


def db_counts_psql(database_url: str, *, psql_command: str) -> dict[str, int]:
    command = shlex.split(psql_command)
    if not command:
        raise RuntimeError("psql command is empty")
    completed = subprocess.run(
        [*command, database_url, "-At", "-c", DB_COUNTS_SQL],
        text=True,
        capture_output=True,
        timeout=30,
        check=False,
    )
    if completed.returncode != 0:
        raise RuntimeError(completed.stderr.strip() or completed.stdout.strip() or f"psql exited {completed.returncode}")
    rows: dict[str, int] = {}
    for line in completed.stdout.splitlines():
        if "|" not in line:
            continue
        key, value = line.split("|", 1)
        rows[key] = int(value)
    return rows


DB_COUNTS_SQL = """
SELECT 'active_wechat_credentials' AS metric, count(*)::int AS value
FROM public.wechat_bot_credentials
WHERE credential_status = 'active'
UNION ALL
SELECT 'active_primary_wechat_bindings', count(*)::int
FROM public.channel_bindings
WHERE channel IN ('hermes_wechat', 'openclaw_wechat')
  AND binding_status = 'active'
  AND is_primary = true
UNION ALL
SELECT 'pollable_bridge_credentials', count(*)::int
FROM public.wechat_bot_credentials c
JOIN public.channel_bindings b
  ON b.tenant_id = c.tenant_id
  AND b.channel IN ('hermes_wechat', 'openclaw_wechat')
  AND b.binding_status = 'active'
  AND b.is_primary = true
WHERE c.credential_status = 'active'
UNION ALL
SELECT 'wechat_clawbot_auth_sessions', count(*)::int
FROM public.wechat_clawbot_auth_sessions
UNION ALL
SELECT 'recent_pending_auth_sessions', count(*)::int
FROM public.wechat_clawbot_auth_sessions
WHERE status IN ('qr_pending', 'authorized', 'conversation_pending')
  AND coalesce(expires_at, now() + interval '1 minute') >= now()
UNION ALL
SELECT 'expired_pending_auth_sessions', count(*)::int
FROM public.wechat_clawbot_auth_sessions
WHERE status IN ('qr_pending', 'authorized', 'conversation_pending')
  AND expires_at < now();
"""


def bridge_poll_check(webapp_base_url: str, secret: str) -> Check:
    if not secret:
        return Check("bridge_poll", "skipped", "bridge secret is not configured")
    status_code, response_json, raw = post_json(
        f"{webapp_base_url.rstrip('/')}/api/openclaw/wechat/poll",
        {},
        headers={"Authorization": f"Bearer {secret}", "Content-Type": "application/json"},
    )
    if not 200 <= status_code < 300:
        return Check("bridge_poll", "failed", f"{status_code or 'network'}: {raw}", response_json)
    credentials = int(response_json.get("credentials") or 0) if isinstance(response_json, dict) else 0
    if credentials <= 0:
        return Check("bridge_poll", "failed", "bridge reachable but credentials=0", compact(response_json))
    errors = response_json.get("errors") if isinstance(response_json, dict) else []
    if errors:
        return Check("bridge_poll", "gap", f"bridge reachable with credentials={credentials}, but errors present", compact(response_json))
    return Check("bridge_poll", "passed", f"bridge reachable with credentials={credentials}", compact(response_json))


def post_json(url: str, payload: dict[str, Any], *, headers: dict[str, str]) -> tuple[int, dict[str, Any] | None, str]:
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(url, data=body, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=30) as response:
            raw = response.read().decode("utf-8", errors="replace")
            return response.status, json.loads(raw) if raw else None, raw
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace")
        try:
            return exc.code, json.loads(raw), raw
        except json.JSONDecodeError:
            return exc.code, None, raw
    except urllib.error.URLError as exc:
        return 0, None, str(exc.reason)


def compact(value: Any, *, max_chars: int = 4000) -> dict[str, Any]:
    raw = json.dumps(value, ensure_ascii=False, default=str)
    if len(raw) <= max_chars:
        return value if isinstance(value, dict) else {"value": value}
    return {"truncated": True, "chars": len(raw), "preview": raw[:max_chars]}


def summarize(checks: list[Check]) -> dict[str, Any]:
    counts = {"passed": 0, "failed": 0, "gap": 0, "skipped": 0}
    for check in checks:
        counts[check.status] += 1
    if counts["failed"]:
        status = "fail"
    elif counts["gap"] or counts["skipped"]:
        status = "partial"
    else:
        status = "pass"
    return {
        "status": status,
        "counts": counts,
        "checks": [check.to_dict() for check in checks],
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Check real WeChat ClawBot readiness for Hermes.")
    parser.add_argument("--env-file", action="append", default=[], help="Additional env file(s) to load before checks.")
    parser.add_argument("--database-url", default="")
    parser.add_argument("--webapp-base-url", default=os.getenv("HERMES_WEBAPP_URL", DEFAULT_WEBAPP_BASE_URL))
    parser.add_argument(
        "--bridge-secret",
        default=os.getenv("HERMES_CRON_SECRET") or os.getenv("OPENCLAW_CRON_SECRET") or os.getenv("WECHAT_CLAWBOT_BRIDGE_SECRET") or "",
    )
    parser.add_argument("--psql-command", default=os.getenv("PSQL", "psql"))
    parser.add_argument("--skip-bridge", action="store_true")
    return parser.parse_args()


def main() -> int:
    load_env_file(SERVER_ENV_FILE)
    load_env_file(ENV_FILE)
    args = parse_args()
    for env_file in args.env_file:
        load_env_file(Path(env_file))
    bridge_secret = (
        args.bridge_secret
        or os.getenv("HERMES_CRON_SECRET")
        or os.getenv("OPENCLAW_CRON_SECRET")
        or os.getenv("WECHAT_CLAWBOT_BRIDGE_SECRET")
        or ""
    )
    checks = [
        env_check(db_url_from_env(args.database_url)),
        db_check(db_url_from_env(args.database_url), psql_command=args.psql_command),
    ]
    if not args.skip_bridge:
        checks.append(bridge_poll_check(args.webapp_base_url, bridge_secret))
    summary = summarize(checks)
    print(json.dumps(summary, ensure_ascii=False, indent=2, default=str))
    return 0 if summary["status"] == "pass" else 1


if __name__ == "__main__":
    sys.exit(main())
