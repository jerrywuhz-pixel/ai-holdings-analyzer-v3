#!/usr/bin/env python3
"""
Live local smoke for Futu read-only account sync persistence.

The default run uses the deterministic local mock connector and verifies that
the data-service writes the broker-scoped P0 tables. Set
SMOKE_FUTU_CONNECTOR_MODE=local_connector after starting the Futu sidecar to
exercise the real local OpenD boundary.
"""
from __future__ import annotations

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
        with urllib.request.urlopen(request, timeout=30) as response:
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


def row_by_id(client: Any, table: str, row_id: str) -> dict[str, Any]:
    response = client.table(table).select("*").eq("id", row_id).limit(1).execute()
    if not response.data:
        raise RuntimeError(f"{table} row not found: {row_id}")
    return response.data[0]


def rows_for_sync(client: Any, table: str, sync_snapshot_id: str) -> list[dict[str, Any]]:
    response = client.table(table).select("*").eq("broker_sync_snapshot_id", sync_snapshot_id).execute()
    return response.data or []


def main() -> int:
    load_env_file(ENV_FILE)
    client = create_supabase_client()

    tenant_id = os.getenv("SMOKE_TENANT_ID", DEFAULT_TENANT_ID)
    base_url = os.getenv("DATA_SERVICE_BASE_URL", "http://127.0.0.1:8000").rstrip("/")
    connector_mode = os.getenv("SMOKE_FUTU_CONNECTOR_MODE", "local_mock")
    connector_runtime_mode = os.getenv("SMOKE_FUTU_CONNECTOR_RUNTIME_MODE", "local_dev_direct")
    connector_instance_id = os.getenv("SMOKE_FUTU_CONNECTOR_INSTANCE_ID", "").strip() or None
    allow_mock_fallback = os.getenv("SMOKE_FUTU_ALLOW_MOCK_FALLBACK", "false").lower() in {"1", "true", "yes"}
    persist = os.getenv("SMOKE_FUTU_PERSIST", "true").lower() in {"1", "true", "yes"}
    nonce = str(int(time.time() * 1000))
    connection_label = os.getenv("SMOKE_FUTU_CONNECTION_LABEL", f"富途本地 OpenD 联调 {nonce}")

    payload = {
        "tenant_id": tenant_id,
        "connection_label": connection_label,
        "snapshot_label": os.getenv("SMOKE_FUTU_SNAPSHOT_LABEL", "default"),
        "connector_mode": connector_mode,
        "connector_runtime_mode": connector_runtime_mode,
        "connector_instance_id": connector_instance_id,
        "allow_mock_fallback": allow_mock_fallback,
        "include_positions": True,
        "include_cash": True,
        "trigger": "webapp_action",
        "persist": persist,
    }
    response = request_json(f"{base_url}/api/v3/broker/futu/sync", payload)
    if not response.get("ok"):
        raise RuntimeError(f"futu sync endpoint returned non-ok response: {response}")
    data = response["data"]
    snapshot_summary = data.get("snapshot_summary") or {}
    account_snapshot = data.get("account_snapshot") or {}
    expected_positions = int(snapshot_summary.get("positions_count") or 0)
    expected_cash_balances = int(snapshot_summary.get("cash_balance_count") or 0)

    if expected_positions < 1:
        raise RuntimeError("broker positions were not returned")
    if expected_cash_balances < 1:
        raise RuntimeError("cash balances were not returned")

    if not persist:
        summary = {
            "status": "pass",
            "tenant_id": tenant_id,
            "connector_mode": connector_mode,
            "source_quality": data.get("source_quality"),
            "persisted": False,
            "broker_connection": {
                "id": data.get("broker_connection_id"),
                "permission_scope": account_snapshot.get("permission_scope"),
                "auth_status": "not_persisted",
                "connector_runtime_mode": connector_runtime_mode,
                "connector_instance_id": connector_instance_id,
            },
            "asset_source": None,
            "broker_sync_snapshot": None,
            "rows": {
                "broker_position_snapshots": 0,
                "cash_balance_snapshots": 0,
                "margin_balance_snapshots": 0,
            },
            "snapshot_summary": snapshot_summary,
            "ran_at": datetime.now(timezone.utc).isoformat(),
        }
        print(json.dumps(summary, ensure_ascii=False, indent=2))
        return 0

    if not data.get("persisted"):
        raise RuntimeError("futu sync response was not persisted")

    sync_snapshot_id = str(data["broker_sync_snapshot_id"])
    broker_connection = row_by_id(client, "broker_connections", str(data["broker_connection_id"]))
    asset_source = row_by_id(client, "asset_sources", str(data["asset_source_id"]))
    sync_snapshot = row_by_id(client, "broker_sync_snapshots", sync_snapshot_id)
    position_rows = rows_for_sync(client, "broker_position_snapshots", sync_snapshot_id)
    cash_rows = rows_for_sync(client, "cash_balance_snapshots", sync_snapshot_id)
    margin_rows = rows_for_sync(client, "margin_balance_snapshots", sync_snapshot_id)

    if broker_connection.get("permission_scope") != "read_only":
        raise RuntimeError("broker connection is not read_only")
    if asset_source.get("source_type") != "broker_api":
        raise RuntimeError("asset source is not broker_api")
    if sync_snapshot.get("status") not in {"succeeded", "partial"}:
        raise RuntimeError(f"unexpected broker sync status: {sync_snapshot.get('status')}")
    if len(position_rows) != expected_positions:
        raise RuntimeError(
            f"broker positions persisted mismatch: expected {expected_positions}, got {len(position_rows)}"
        )
    if connector_mode != "local_connector" and expected_positions < 1:
        raise RuntimeError("mock broker positions were not persisted")
    if len(cash_rows) < 1:
        raise RuntimeError("cash balances were not persisted")
    if len(margin_rows) < 1:
        raise RuntimeError("margin balances were not persisted")

    summary = {
        "status": "pass",
        "tenant_id": tenant_id,
        "connector_mode": connector_mode,
        "source_quality": data.get("source_quality"),
        "broker_connection": {
            "id": broker_connection.get("id"),
            "permission_scope": broker_connection.get("permission_scope"),
            "auth_status": broker_connection.get("auth_status"),
            "connector_runtime_mode": broker_connection.get("connector_runtime_mode"),
            "connector_instance_id": broker_connection.get("connector_instance_id"),
        },
        "asset_source": {
            "id": asset_source.get("id"),
            "source_type": asset_source.get("source_type"),
            "source_quality": asset_source.get("source_quality"),
        },
        "broker_sync_snapshot": {
            "id": sync_snapshot_id,
            "status": sync_snapshot.get("status"),
            "sync_window_key": sync_snapshot.get("sync_window_key"),
        },
        "rows": {
            "broker_position_snapshots": len(position_rows),
            "cash_balance_snapshots": len(cash_rows),
            "margin_balance_snapshots": len(margin_rows),
        },
        "snapshot_summary": data.get("snapshot_summary"),
        "ran_at": datetime.now(timezone.utc).isoformat(),
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:
        print(json.dumps({"status": "fail", "error": str(exc)}, ensure_ascii=False, indent=2), file=sys.stderr)
        sys.exit(1)
