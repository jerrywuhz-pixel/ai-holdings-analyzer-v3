#!/usr/bin/env python3
"""
Live local smoke for the WeChat confirmation -> holdings -> outbox path.

This script exercises the real OpenClaw HTTP ingress and Supabase-backed
workers. It is intentionally small and deterministic so it can be run before
coding sessions or after environment changes.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import time
import urllib.error
import urllib.request
import warnings
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
ENV_FILE = PROJECT_ROOT / ".env"
DEFAULT_TENANT_ID = "00000000-0000-0000-0000-000000000000"

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

warnings.filterwarnings("ignore", message="urllib3 v2 only supports OpenSSL.*")


def load_env_file(path: Path) -> None:
    if not path.exists():
        return
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


def request_json(url: str, payload: dict[str, Any]) -> dict[str, Any]:
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            raw = response.read().decode("utf-8")
            return json.loads(raw) if raw else {}
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"{url} returned HTTP {exc.code}: {raw}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"{url} request failed: {exc.reason}") from exc


def require_env(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise RuntimeError(f"{name} is required. Run scripts/setup-supabase-env.sh first.")
    return value


def create_supabase_client() -> Any:
    from supabase import create_client

    return create_client(require_env("SUPABASE_URL"), require_env("SUPABASE_SERVICE_ROLE_KEY"))


def first_row(client: Any, table: str, filters: dict[str, Any]) -> dict[str, Any] | None:
    query = client.table(table).select("*")
    for key, value in filters.items():
        query = query.eq(key, value)
    response = query.limit(1).execute()
    return response.data[0] if response.data else None


def ensure_channel_binding(
    client: Any,
    *,
    tenant_id: str,
    openclaw_account_id: str,
    session_space: str,
) -> str:
    tenant = first_row(client, "tenant_accounts", {"tenant_id": tenant_id})
    if tenant is None:
        raise RuntimeError(f"tenant_accounts row not found for tenant_id={tenant_id}")

    existing = first_row(
        client,
        "channel_bindings",
        {
            "tenant_id": tenant_id,
            "channel": "openclaw_wechat",
            "openclaw_account_id": openclaw_account_id,
        },
    )
    now = datetime.now(timezone.utc).isoformat()
    payload = {
        "tenant_id": tenant_id,
        "channel": "openclaw_wechat",
        "openclaw_account_id": openclaw_account_id,
        "channel_user_ref": "local-smoke-user",
        "account_label": "本地微信联调 Bot",
        "human_name": "Local Smoke",
        "session_space": session_space,
        "binding_status": "active",
        "is_primary": False,
        "bound_at": now,
        "last_seen_at": now,
        "binding_metadata": {"smoke": True, "managed_by": "scripts/live_confirmation_smoke.py"},
    }
    if existing:
        client.table("channel_bindings").update(payload).eq("id", existing["id"]).execute()
        return str(existing["id"])

    response = client.table("channel_bindings").insert(payload).execute()
    if not response.data:
        raise RuntimeError("failed to create local channel binding")
    return str(response.data[0]["id"])


def build_routing(
    *,
    tenant_id: str,
    channel_binding_id: str,
    openclaw_account_id: str,
    session_space: str,
    nonce: str,
) -> dict[str, Any]:
    return {
        "tenant_id": tenant_id,
        "channel_binding_id": channel_binding_id,
        "openclaw_account_id": openclaw_account_id,
        "channel": "openclaw_wechat",
        "session_space": session_space,
        "context_token": f"ctx-local-smoke-{nonce}",
        "target_conversation": f"conv-local-smoke-{nonce}",
        "timezone": "Asia/Shanghai",
    }


def post_wechat_text(openclaw_base_url: str, routing: dict[str, Any], text: str, nonce: str) -> dict[str, Any]:
    return request_json(
        f"{openclaw_base_url.rstrip('/')}/api/openclaw/wechat/messages",
        {
            "routing": routing,
            "message": {
                "id": f"msg-local-smoke-{nonce}",
                "type": "text",
                "text": text,
                "metadata": {"smoke": True, "nonce": nonce},
            },
        },
    )


async def run_workers_once(*, delivery_mode: str) -> dict[str, Any]:
    os.environ["OPENCLAW_DELIVERY_MODE"] = delivery_mode

    from openclaw.gateway.outbox_worker import create_outbox_worker_from_env
    from openclaw.gateway.post_confirmation_worker import create_post_confirmation_worker_from_env

    post_worker = create_post_confirmation_worker_from_env()
    post_stats = await post_worker.process_once(limit=100)

    outbox_worker = create_outbox_worker_from_env()
    outbox_stats = await outbox_worker.process_ready(limit=100)

    return {
        "post_confirmation": post_stats.__dict__,
        "outbox": outbox_stats.__dict__,
    }


def rows_created_since(client: Any, table: str, tenant_id: str, started_at: str, limit: int = 100) -> list[dict[str, Any]]:
    response = (
        client.table(table)
        .select("*")
        .eq("tenant_id", tenant_id)
        .gte("created_at", started_at)
        .order("created_at", desc=True)
        .limit(limit)
        .execute()
    )
    return response.data or []


def latest_position_snapshot(client: Any, tenant_id: str, symbol: str) -> dict[str, Any] | None:
    response = (
        client.table("position_snapshots")
        .select("*")
        .eq("tenant_id", tenant_id)
        .eq("symbol", symbol)
        .order("snapshot_date", desc=True)
        .order("created_at", desc=True)
        .limit(1)
        .execute()
    )
    return response.data[0] if response.data else None


def find_job_for_pending(client: Any, tenant_id: str, pending_action_id: str) -> dict[str, Any] | None:
    response = (
        client.table("job_runs")
        .select("*")
        .eq("tenant_id", tenant_id)
        .order("created_at", desc=True)
        .limit(100)
        .execute()
    )
    for row in response.data or []:
        config = row.get("config") or {}
        pending = config.get("pending_action") or {}
        if str(pending.get("id")) == pending_action_id:
            return row
    return None


def assert_live_result(
    client: Any,
    *,
    tenant_id: str,
    pending_action_id: str,
    confirmation_session_id: str,
    started_at: str,
) -> dict[str, Any]:
    pending_action = first_row(client, "pending_actions", {"id": pending_action_id})
    if not pending_action:
        raise RuntimeError("pending action was not persisted")
    if pending_action.get("status") != "committed":
        raise RuntimeError(f"pending action status is {pending_action.get('status')}, expected committed")

    confirmation_session = first_row(client, "confirmation_sessions", {"id": confirmation_session_id})
    if not confirmation_session:
        raise RuntimeError("confirmation session was not persisted")
    if confirmation_session.get("session_status") != "consumed":
        raise RuntimeError(
            f"confirmation session status is {confirmation_session.get('session_status')}, expected consumed"
        )

    job = find_job_for_pending(client, tenant_id, pending_action_id)
    if not job:
        raise RuntimeError("post-confirmation job was not created")
    if job.get("status") != "SUCCESS":
        raise RuntimeError(f"post-confirmation job status is {job.get('status')}, expected SUCCESS")

    trade_events = rows_created_since(client, "trade_events", tenant_id, started_at)
    matching_trades = [
        row
        for row in trade_events
        if row.get("symbol") == "AAPL"
        and row.get("side") == "BUY"
        and str(row.get("broker_message_fingerprint") or "").startswith("confirmation:")
    ]
    if not matching_trades:
        raise RuntimeError("confirmed AAPL BUY trade event was not written")

    position_snapshot = latest_position_snapshot(client, tenant_id, "AAPL")
    if not position_snapshot:
        raise RuntimeError("AAPL position snapshot was not refreshed")

    outbox_rows = rows_created_since(client, "delivery_outbox", tenant_id, started_at)
    task_updates = [row for row in outbox_rows if row.get("content_type") == "task_update"]
    confirmation_cards = [row for row in outbox_rows if row.get("content_type") == "confirmation_card"]
    if not confirmation_cards:
        raise RuntimeError("confirmation card was not queued")
    if not task_updates:
        raise RuntimeError("post-confirmation receipt was not queued")
    if not any(row.get("status") == "delivered" for row in task_updates):
        raise RuntimeError("post-confirmation receipt was not delivered in log mode")

    return {
        "pending_action": {
            "id": pending_action_id,
            "status": pending_action.get("status"),
        },
        "confirmation_session": {
            "id": confirmation_session_id,
            "status": confirmation_session.get("session_status"),
        },
        "job_run": {
            "id": job.get("id"),
            "status": job.get("status"),
            "job_type": job.get("job_type"),
        },
        "trade_event": {
            "id": matching_trades[0].get("id"),
            "symbol": matching_trades[0].get("symbol"),
            "quantity": matching_trades[0].get("quantity"),
            "price": matching_trades[0].get("price"),
        },
        "position_snapshot": {
            "id": position_snapshot.get("id"),
            "symbol": position_snapshot.get("symbol"),
            "total_quantity": position_snapshot.get("total_quantity"),
            "average_cost": position_snapshot.get("average_cost"),
        },
        "delivery_outbox": {
            "confirmation_cards": len(confirmation_cards),
            "task_updates": len(task_updates),
            "delivered_task_updates": len([row for row in task_updates if row.get("status") == "delivered"]),
        },
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run live local OpenClaw confirmation smoke.")
    parser.add_argument("--tenant-id", default=os.getenv("SMOKE_TENANT_ID", DEFAULT_TENANT_ID))
    parser.add_argument("--openclaw-base-url", default=os.getenv("OPENCLAW_BASE_URL", "http://127.0.0.1:8080"))
    parser.add_argument(
        "--openclaw-account-id",
        default=os.getenv("SMOKE_OPENCLAW_ACCOUNT_ID", "local-wechat-bot-001"),
    )
    parser.add_argument("--session-space", default=os.getenv("SMOKE_SESSION_SPACE", "local-smoke"))
    parser.add_argument("--delivery-mode", default=os.getenv("SMOKE_DELIVERY_MODE", "log"))
    parser.add_argument("--output", default="")
    return parser.parse_args()


def main() -> int:
    load_env_file(ENV_FILE)
    args = parse_args()

    started_at = datetime.now(timezone.utc).isoformat()
    nonce = str(int(time.time() * 1000))
    client = create_supabase_client()
    channel_binding_id = ensure_channel_binding(
        client,
        tenant_id=args.tenant_id,
        openclaw_account_id=args.openclaw_account_id,
        session_space=args.session_space,
    )
    routing = build_routing(
        tenant_id=args.tenant_id,
        channel_binding_id=channel_binding_id,
        openclaw_account_id=args.openclaw_account_id,
        session_space=args.session_space,
        nonce=nonce,
    )

    trade_text = f"今天买入 AAPL 1 股，价格 180 美元，记录一下，本地联调 {nonce}"
    create_response = post_wechat_text(args.openclaw_base_url, routing, trade_text, nonce)
    if create_response.get("result_type") != "confirmation_required":
        raise RuntimeError(f"expected confirmation_required, got {create_response}")

    session_token = str(create_response["session_token"])
    confirm_response = post_wechat_text(args.openclaw_base_url, routing, f"确认 {session_token}", f"{nonce}-confirm")
    if confirm_response.get("result_type") != "decision_received":
        raise RuntimeError(f"expected decision_received, got {confirm_response}")

    worker_stats = asyncio.run(run_workers_once(delivery_mode=args.delivery_mode))
    result = assert_live_result(
        client,
        tenant_id=args.tenant_id,
        pending_action_id=str(create_response["pending_action_id"]),
        confirmation_session_id=str(create_response["confirmation_session_id"]),
        started_at=started_at,
    )
    summary = {
        "status": "pass",
        "tenant_id": args.tenant_id,
        "channel_binding_id": channel_binding_id,
        "delivery_mode": args.delivery_mode,
        "session_token": session_token,
        "create_response": {
            "result_type": create_response.get("result_type"),
            "pending_action_id": create_response.get("pending_action_id"),
            "confirmation_session_id": create_response.get("confirmation_session_id"),
        },
        "confirm_response": {
            "result_type": confirm_response.get("result_type"),
            "status": confirm_response.get("status"),
            "decision": confirm_response.get("decision"),
        },
        "worker_stats": worker_stats,
        "result": result,
    }
    rendered = json.dumps(summary, ensure_ascii=False, indent=2)
    if args.output:
        Path(args.output).write_text(rendered + "\n", encoding="utf-8")
    print(rendered)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:
        print(json.dumps({"status": "fail", "error": str(exc)}, ensure_ascii=False, indent=2), file=sys.stderr)
        sys.exit(1)
