from __future__ import annotations

"""Broker snapshot persistence for P0 read-only account sync."""

import os
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Literal, Optional, Protocol

from pydantic import BaseModel

from adapters.futu import (
    ConnectorModeRequest,
    FutuAccountSnapshot,
    FutuReadOnlyConnector,
    FutuSnapshotReadRequest,
)


class FutuBrokerSyncRequest(BaseModel):
    tenant_id: str
    broker_connection_id: Optional[str] = None
    connector_instance_id: Optional[str] = None
    channel_binding_id: Optional[str] = None
    connection_label: str = "富途本地 OpenD"
    snapshot_label: str = "default"
    include_positions: bool = True
    include_cash: bool = True
    connector_mode: ConnectorModeRequest = "auto"
    connector_runtime_mode: Literal["user_local_polling", "relay_websocket", "local_dev_direct"] = "local_dev_direct"
    allow_mock_fallback: bool = False
    trigger: Literal["webapp_action", "cron", "system_replay"] = "webapp_action"
    sync_window_key: Optional[str] = None
    persist: bool = True


@dataclass
class BrokerPersistenceResult:
    broker_connection_id: str
    asset_source_id: str
    broker_sync_snapshot_id: str
    positions_written: int
    cash_balances_written: int
    margin_balances_written: int


class BrokerSyncRepository(Protocol):
    async def persist_futu_snapshot(
        self,
        *,
        request: FutuBrokerSyncRequest,
        snapshot: FutuAccountSnapshot,
        broker_connection_id: str,
        sync_window_key: str,
    ) -> BrokerPersistenceResult:
        ...


class FutuBrokerSyncService:
    def __init__(
        self,
        *,
        connector: FutuReadOnlyConnector,
        repository: BrokerSyncRepository | None = None,
    ) -> None:
        self._connector = connector
        self._repository = repository

    async def sync(self, request: FutuBrokerSyncRequest) -> dict[str, Any]:
        broker_connection_id = request.broker_connection_id or str(uuid.uuid4())
        if request.persist:
            _ensure_uuid("broker_connection_id", broker_connection_id)
            if request.connector_instance_id:
                _ensure_uuid("connector_instance_id", request.connector_instance_id)

        account_snapshot = await self._connector.read_account_snapshot(
            FutuSnapshotReadRequest(
                tenant_id=request.tenant_id,
                broker_connection_id=broker_connection_id,
                snapshot_label=request.snapshot_label,
                include_positions=request.include_positions,
                include_cash=request.include_cash,
                connector_mode=request.connector_mode,
                allow_mock_fallback=request.allow_mock_fallback,
            )
        )
        normalized = _summarize_account_snapshot(account_snapshot)
        sync_window_key = request.sync_window_key or _default_sync_window_key(request.snapshot_label)

        persistence: BrokerPersistenceResult | None = None
        if request.persist:
            repository = self._repository or create_supabase_broker_sync_repository_from_env()
            persistence = await repository.persist_futu_snapshot(
                request=request,
                snapshot=account_snapshot,
                broker_connection_id=broker_connection_id,
                sync_window_key=sync_window_key,
            )

        return {
            "persisted": persistence is not None,
            "broker_connection_id": persistence.broker_connection_id if persistence else broker_connection_id,
            "asset_source_id": persistence.asset_source_id if persistence else None,
            "broker_sync_snapshot_id": persistence.broker_sync_snapshot_id if persistence else None,
            "sync_window_key": sync_window_key,
            "source_quality": _source_quality_for_snapshot(account_snapshot),
            "positions_written": persistence.positions_written if persistence else 0,
            "cash_balances_written": persistence.cash_balances_written if persistence else 0,
            "margin_balances_written": persistence.margin_balances_written if persistence else 0,
            "snapshot_summary": normalized,
            "account_snapshot": account_snapshot.model_dump(mode="json"),
        }


class SupabaseBrokerSyncRepository:
    def __init__(self, client: Any) -> None:
        self._client = client

    async def persist_futu_snapshot(
        self,
        *,
        request: FutuBrokerSyncRequest,
        snapshot: FutuAccountSnapshot,
        broker_connection_id: str,
        sync_window_key: str,
    ) -> BrokerPersistenceResult:
        import asyncio

        def _persist() -> BrokerPersistenceResult:
            broker_connection = self._ensure_broker_connection(
                request=request,
                broker_connection_id=broker_connection_id,
                snapshot=snapshot,
            )
            asset_source = self._ensure_asset_source(
                request=request,
                broker_connection_id=str(broker_connection["id"]),
                snapshot=snapshot,
            )
            sync_snapshot = self._insert_sync_snapshot(
                request=request,
                snapshot=snapshot,
                broker_connection_id=str(broker_connection["id"]),
                asset_source_id=str(asset_source["id"]),
                sync_window_key=sync_window_key,
            )
            positions_written = self._insert_position_snapshots(
                snapshot=snapshot,
                broker_sync_snapshot_id=str(sync_snapshot["id"]),
                asset_source_id=str(asset_source["id"]),
            )
            cash_written, margin_written = self._insert_balance_snapshots(
                snapshot=snapshot,
                broker_sync_snapshot_id=str(sync_snapshot["id"]),
                broker_connection_id=str(broker_connection["id"]),
                asset_source_id=str(asset_source["id"]),
            )
            return BrokerPersistenceResult(
                broker_connection_id=str(broker_connection["id"]),
                asset_source_id=str(asset_source["id"]),
                broker_sync_snapshot_id=str(sync_snapshot["id"]),
                positions_written=positions_written,
                cash_balances_written=cash_written,
                margin_balances_written=margin_written,
            )

        return await asyncio.to_thread(_persist)

    def _ensure_broker_connection(
        self,
        *,
        request: FutuBrokerSyncRequest,
        broker_connection_id: str,
        snapshot: FutuAccountSnapshot,
    ) -> dict[str, Any]:
        existing = (
            self._client.table("broker_connections")
            .select("*")
            .eq("id", broker_connection_id)
            .limit(1)
            .execute()
        )
        now = _iso_now()
        payload = {
            "tenant_id": request.tenant_id,
            "channel_binding_id": request.channel_binding_id,
            "broker": "futu",
            "connection_label": request.connection_label,
            "permission_scope": "read_only",
            "auth_status": "connected",
            "connection_mode": "local_connector",
            "connector_kind": "futu_opend",
            "connector_instance_id": request.connector_instance_id,
            "connector_runtime_mode": request.connector_runtime_mode,
            "token_storage_mode": "not_stored",
            "capabilities": ["positions", "cash_balances", "option_positions", "option_chain"],
            "status_detail": {
                "connector_mode": snapshot.connector_mode,
                "connector_instance_id": request.connector_instance_id,
                "connector_runtime_mode": request.connector_runtime_mode,
                "snapshot_status": snapshot.status,
                "permission_scope": snapshot.permission_scope,
                "missing_fields": snapshot.missing_fields,
            },
            "last_successful_sync_at": snapshot.received_at.isoformat(),
            "updated_at": now,
        }
        if existing.data:
            response = (
                self._client.table("broker_connections")
                .update(payload)
                .eq("id", broker_connection_id)
                .execute()
            )
            return response.data[0] if response.data else {**existing.data[0], **payload}

        same_label = (
            self._client.table("broker_connections")
            .select("*")
            .eq("tenant_id", request.tenant_id)
            .eq("connection_label", request.connection_label)
            .limit(1)
            .execute()
        )
        if same_label.data:
            response = (
                self._client.table("broker_connections")
                .update(payload)
                .eq("id", same_label.data[0]["id"])
                .execute()
            )
            return response.data[0] if response.data else {**same_label.data[0], **payload}

        response = (
            self._client.table("broker_connections")
            .insert({"id": broker_connection_id, **payload, "created_at": now})
            .execute()
        )
        if not response.data:
            raise RuntimeError("failed to persist broker connection")
        return response.data[0]

    def _ensure_asset_source(
        self,
        *,
        request: FutuBrokerSyncRequest,
        broker_connection_id: str,
        snapshot: FutuAccountSnapshot,
    ) -> dict[str, Any]:
        source_key = f"futu:{broker_connection_id}"
        payload = {
            "tenant_id": request.tenant_id,
            "source_key": source_key,
            "source_name": f"{request.connection_label} 持仓同步",
            "source_type": "broker_api",
            "provider": "futu",
            "provider_account_ref": broker_connection_id,
            "broker_connection_id": broker_connection_id,
            "channel_binding_id": request.channel_binding_id,
            "priority": 10,
            "source_quality": _source_quality_for_snapshot(snapshot),
            "lineage_policy": [
                "read_only_broker_snapshot",
                "no_order_execution",
                "raw_payload_not_persisted_in_cloud",
            ],
            "config": {
                "connector_kind": "futu_opend",
                "connector_mode": snapshot.connector_mode,
                "connector_instance_id": request.connector_instance_id,
                "connector_runtime_mode": request.connector_runtime_mode,
                "source_tier": snapshot.source_tier,
                "permission_scope": snapshot.permission_scope,
            },
            "is_active": True,
            "last_seen_at": snapshot.received_at.isoformat(),
            "updated_at": _iso_now(),
        }
        existing = (
            self._client.table("asset_sources")
            .select("*")
            .eq("tenant_id", request.tenant_id)
            .eq("source_key", source_key)
            .limit(1)
            .execute()
        )
        if existing.data:
            response = (
                self._client.table("asset_sources")
                .update(payload)
                .eq("id", existing.data[0]["id"])
                .execute()
            )
            return response.data[0] if response.data else {**existing.data[0], **payload}
        response = self._client.table("asset_sources").insert({**payload, "created_at": _iso_now()}).execute()
        if not response.data:
            raise RuntimeError("failed to persist asset source")
        return response.data[0]

    def _insert_sync_snapshot(
        self,
        *,
        request: FutuBrokerSyncRequest,
        snapshot: FutuAccountSnapshot,
        broker_connection_id: str,
        asset_source_id: str,
        sync_window_key: str,
    ) -> dict[str, Any]:
        summary = _summarize_account_snapshot(snapshot)
        response = (
            self._client.table("broker_sync_snapshots")
            .insert(
                {
                    "tenant_id": request.tenant_id,
                    "broker_connection_id": broker_connection_id,
                    "asset_source_id": asset_source_id,
                    "sync_window_key": sync_window_key,
                    "trigger": request.trigger,
                    "status": "succeeded" if snapshot.status == "complete" else "partial",
                    "as_of": snapshot.as_of.isoformat(),
                    "received_at": snapshot.received_at.isoformat(),
                    "coverage": {
                        "include_positions": request.include_positions,
                        "include_cash": request.include_cash,
                        "positions_count": len(snapshot.positions),
                        "cash_balance_count": len(snapshot.cash_balances),
                        "connector_mode": snapshot.connector_mode,
                        "connector_instance_id": request.connector_instance_id,
                        "connector_runtime_mode": request.connector_runtime_mode,
                        "permission_scope": snapshot.permission_scope,
                    },
                    "summary": summary,
                    "missing_fields": snapshot.missing_fields,
                    "partial_components": snapshot.missing_fields if snapshot.status == "partial" else [],
                    "source_quality": _source_quality_for_snapshot(snapshot),
                    "created_at": _iso_now(),
                }
            )
            .execute()
        )
        if not response.data:
            raise RuntimeError("failed to persist broker sync snapshot")
        return response.data[0]

    def _insert_position_snapshots(
        self,
        *,
        snapshot: FutuAccountSnapshot,
        broker_sync_snapshot_id: str,
        asset_source_id: str,
    ) -> int:
        rows = [
            _broker_position_row(
                snapshot=snapshot,
                position=position.model_dump(mode="json"),
                broker_sync_snapshot_id=broker_sync_snapshot_id,
                asset_source_id=asset_source_id,
            )
            for position in snapshot.positions
        ]
        if not rows:
            return 0
        response = self._client.table("broker_position_snapshots").insert(rows).execute()
        return len(response.data or rows)

    def _insert_balance_snapshots(
        self,
        *,
        snapshot: FutuAccountSnapshot,
        broker_sync_snapshot_id: str,
        broker_connection_id: str,
        asset_source_id: str,
    ) -> tuple[int, int]:
        cash_rows = []
        margin_rows = []
        for balance in snapshot.cash_balances:
            payload = balance.model_dump(mode="json")
            lineage = _source_lineage(snapshot)
            cash_rows.append(
                {
                    "tenant_id": snapshot.tenant_id,
                    "broker_sync_snapshot_id": broker_sync_snapshot_id,
                    "broker_connection_id": broker_connection_id,
                    "asset_source_id": asset_source_id,
                    "currency": balance.currency,
                    "total_cash": balance.available_cash,
                    "available_cash": balance.available_cash,
                    "buying_power": balance.buying_power,
                    "source_quality": _source_quality_for_snapshot(snapshot),
                    "balance_payload": payload,
                    "source_lineage": lineage,
                    "as_of": snapshot.as_of.isoformat(),
                    "created_at": _iso_now(),
                }
            )
            margin_rows.append(
                {
                    "tenant_id": snapshot.tenant_id,
                    "broker_sync_snapshot_id": broker_sync_snapshot_id,
                    "broker_connection_id": broker_connection_id,
                    "asset_source_id": asset_source_id,
                    "currency": balance.currency,
                    "margin_available": balance.buying_power,
                    "option_buying_power": balance.buying_power,
                    "cash_secured_requirement": balance.cash_secured_reserve,
                    "margin_required": balance.cash_secured_reserve,
                    "source_quality": _source_quality_for_snapshot(snapshot),
                    "balance_payload": payload,
                    "source_lineage": lineage,
                    "as_of": snapshot.as_of.isoformat(),
                    "created_at": _iso_now(),
                }
            )
        cash_count = 0
        margin_count = 0
        if cash_rows:
            response = self._client.table("cash_balance_snapshots").insert(cash_rows).execute()
            cash_count = len(response.data or cash_rows)
        if margin_rows:
            response = self._client.table("margin_balance_snapshots").insert(margin_rows).execute()
            margin_count = len(response.data or margin_rows)
        return cash_count, margin_count


def create_supabase_broker_sync_repository_from_env() -> SupabaseBrokerSyncRepository:
    url = os.getenv("SUPABASE_URL", "").strip()
    key = os.getenv("SUPABASE_SERVICE_ROLE_KEY", "").strip()
    if not url or not key:
        raise RuntimeError("SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY are required for persisted broker sync")

    from supabase import create_client

    return SupabaseBrokerSyncRepository(create_client(url, key))


def _broker_position_row(
    *,
    snapshot: FutuAccountSnapshot,
    position: dict[str, Any],
    broker_sync_snapshot_id: str,
    asset_source_id: str,
) -> dict[str, Any]:
    raw_quantity = float(position.get("quantity") or 0)
    quantity = abs(raw_quantity)
    market_price = position.get("market_price")
    average_cost = position.get("average_cost")
    return {
        "tenant_id": snapshot.tenant_id,
        "broker_sync_snapshot_id": broker_sync_snapshot_id,
        "asset_source_id": asset_source_id,
        "instrument_id": None,
        "instrument_type": position.get("instrument_type"),
        "provider_symbol": position.get("symbol"),
        "market": position.get("market"),
        "exchange": _infer_exchange(str(position.get("symbol") or ""), str(position.get("market") or "")),
        "position_side": "short" if raw_quantity < 0 else "long",
        "quantity": quantity,
        "average_cost": average_cost,
        "cost_basis": _money(quantity * float(average_cost)) if average_cost is not None else None,
        "market_price": market_price,
        "market_value": _money(raw_quantity * float(market_price)) if market_price is not None else None,
        "currency": position.get("currency") or "USD",
        "source_quality": _source_quality_for_snapshot(snapshot),
        "reconciliation_status": "matched" if snapshot.connector_mode == "local_connector" else "unverified",
        "position_payload": position,
        "source_lineage": _source_lineage(snapshot),
        "as_of": snapshot.as_of.isoformat(),
        "created_at": _iso_now(),
    }


def _summarize_account_snapshot(snapshot: FutuAccountSnapshot) -> dict[str, Any]:
    positions_by_type: dict[str, int] = {}
    markets: set[str] = set()
    currencies: set[str] = set()
    gross_market_value = 0.0
    for position in snapshot.positions:
        positions_by_type[position.instrument_type] = positions_by_type.get(position.instrument_type, 0) + 1
        markets.add(position.market)
        currencies.add(position.currency)
        if position.market_price is not None:
            gross_market_value += abs(float(position.quantity)) * float(position.market_price)
    for balance in snapshot.cash_balances:
        currencies.add(balance.currency)

    return {
        "broker": snapshot.broker,
        "source_key": snapshot.source_key,
        "source_tier": snapshot.source_tier,
        "connector_mode": snapshot.connector_mode,
        "permission_scope": snapshot.permission_scope,
        "status": snapshot.status,
        "positions_count": len(snapshot.positions),
        "cash_balance_count": len(snapshot.cash_balances),
        "positions_by_type": positions_by_type,
        "markets": sorted(markets),
        "currencies": sorted(currencies),
        "gross_market_value": _money(gross_market_value),
        "missing_fields": snapshot.missing_fields,
    }


def _source_quality_for_snapshot(snapshot: FutuAccountSnapshot) -> str:
    if snapshot.connector_mode == "local_connector" and not snapshot.lineage.get("fallback_used"):
        return "broker_verified"
    if snapshot.lineage.get("fallback_used"):
        return "public_fallback"
    return "estimated"


def _source_lineage(snapshot: FutuAccountSnapshot) -> list[dict[str, Any]]:
    return [
        {
            "source_key": snapshot.source_key,
            "source_tier": snapshot.source_tier,
            "connector_mode": snapshot.connector_mode,
            "permission_scope": snapshot.permission_scope,
            "as_of": snapshot.as_of.isoformat(),
            "received_at": snapshot.received_at.isoformat(),
            "lineage": snapshot.lineage,
        }
    ]


def _default_sync_window_key(snapshot_label: str) -> str:
    now = datetime.now(timezone.utc)
    return f"futu:{snapshot_label}:{now.strftime('%Y%m%dT%H%M%S')}:{uuid.uuid4().hex[:8]}"


def _ensure_uuid(field_name: str, value: str) -> None:
    try:
        uuid.UUID(value)
    except ValueError as exc:
        raise ValueError(f"{field_name} must be a UUID when persist=true") from exc


def _infer_exchange(symbol: str, market: str) -> str | None:
    upper = symbol.upper()
    normalized_market = market.upper()
    if normalized_market == "HK" or upper.endswith(".HK"):
        return "HKEX"
    if normalized_market in {"CN", "SH"} or upper.endswith(".SH"):
        return "SSE"
    if normalized_market == "SZ" or upper.endswith(".SZ"):
        return "SZSE"
    if normalized_market == "US":
        return "NASDAQ"
    return None


def _iso_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _money(value: float) -> float:
    return round(value, 2)
