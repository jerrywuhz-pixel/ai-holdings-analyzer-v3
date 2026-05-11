"""
Profit-taking action plan orchestrator.

Runs before market open, evaluates all active holdings, stores daily action
plans, and creates delivery_runs for actionable suggestions.
"""
from __future__ import annotations

import asyncio
import hashlib
import logging
import os
from datetime import date, datetime, timezone
from typing import Any

from .strategy import build_profit_taking_plan

logger = logging.getLogger(__name__)


class ProfitTakingOrchestrator:
    """Generate stop-profit action plans for active holdings."""

    def __init__(
        self,
        supabase_url: str | None = None,
        supabase_key: str | None = None,
    ) -> None:
        self.supabase_url = supabase_url or os.getenv("SUPABASE_URL", "")
        self.supabase_key = supabase_key or os.getenv("SUPABASE_SERVICE_ROLE_KEY", "")

    async def generate_daily_plans(
        self,
        plan_date: str | None = None,
        job_run_id: str | None = None,
    ) -> dict[str, Any]:
        """Generate plans for all active positions across tenants."""
        plan_date = plan_date or date.today().isoformat()
        if not self.supabase_url or not self.supabase_key:
            return {
                "ok": False,
                "message": "Supabase not configured",
                "plans_created": 0,
                "deliveries_created": 0,
            }

        client = self._create_client()
        positions = await self._fetch_active_positions(client)
        sessions = await self._fetch_latest_sessions(client)

        plans_created = 0
        deliveries_created = 0
        actionable = 0
        errors: list[dict[str, str]] = []

        market_history_cache: dict[str, list[dict[str, Any]]] = {}
        for position in positions:
            symbol = position.get("symbol", "")
            tenant_id = position.get("tenant_id", "")
            try:
                quote, price_bars = await self._fetch_symbol_data(symbol)
                market = position.get("market") or quote.get("market") or ""
                if market not in market_history_cache:
                    market_history_cache[market] = await self._fetch_market_history(market)

                plan = build_profit_taking_plan(
                    position=position,
                    quote=quote,
                    price_bars=price_bars,
                    market_bars=market_history_cache[market],
                    today=plan_date,
                )
                plan_id = await self._save_plan(client, plan, job_run_id)
                plans_created += 1
                if plan["should_push"]:
                    actionable += 1
                    session = sessions.get(tenant_id)
                    if session:
                        await self._create_delivery(
                            client=client,
                            plan=plan,
                            plan_id=plan_id,
                            job_run_id=job_run_id,
                            session=session,
                        )
                        deliveries_created += 1
                    else:
                        await self._mark_plan_delivery_status(
                            client, plan_id, "SKIPPED_NO_SESSION"
                        )
            except Exception as exc:
                logger.exception("Profit-taking plan failed for %s/%s", tenant_id, symbol)
                errors.append({"tenant_id": str(tenant_id), "symbol": str(symbol), "error": str(exc)})

        return {
            "ok": not errors,
            "plan_date": plan_date,
            "positions_scanned": len(positions),
            "plans_created": plans_created,
            "actionable": actionable,
            "deliveries_created": deliveries_created,
            "errors": errors,
        }

    def _create_client(self):
        from openclaw.gateway.supabase_client import create_skill_client

        return create_skill_client(
            "profit-taking",
            self.supabase_key,
            self.supabase_url,
        )

    async def _fetch_active_positions(self, client) -> list[dict[str, Any]]:
        resp = (
            await client.table("position_snapshots")
            .select("tenant_id, symbol, provider_symbol, market, exchange, stock_name, total_quantity, average_cost, total_cost, snapshot_date")
            .gt("total_quantity", 0)
            .order("snapshot_date", desc=True)
            .execute()
        )
        latest: dict[tuple[str, str], dict[str, Any]] = {}
        for row in resp.data or []:
            key = (str(row.get("tenant_id")), str(row.get("symbol")))
            if key not in latest:
                latest[key] = row
        return list(latest.values())

    async def _fetch_latest_sessions(self, client) -> dict[str, dict[str, Any]]:
        resp = (
            await client.table("user_sessions")
            .select("tenant_id, context_token, conversation_id, last_active_at")
            .eq("is_active", True)
            .eq("session_type", "wechat_claw")
            .order("last_active_at", desc=True)
            .execute()
        )
        sessions: dict[str, dict[str, Any]] = {}
        for row in resp.data or []:
            tenant_id = str(row.get("tenant_id"))
            if tenant_id and tenant_id not in sessions:
                sessions[tenant_id] = row
        return sessions

    async def _save_plan(
        self,
        client,
        plan: dict[str, Any],
        job_run_id: str | None,
    ) -> str:
        payload = {
            "tenant_id": plan["tenant_id"],
            "symbol": plan["symbol"],
            "market": plan["market"],
            "stock_name": plan["stock_name"],
            "plan_date": plan["plan_date"],
            "action": plan["action"],
            "target_price": plan["target_price"],
            "stop_price": plan["stop_price"],
            "reduce_ratio": plan["reduce_ratio"],
            "today_reach_probability": plan["today_reach_probability"],
            "strategy_name": "market-adaptive-atr-rsi-v1",
            "backtest_summary": plan["backtest"],
            "metrics": plan["metrics"],
            "reason": plan["reason"],
            "instruction": plan["instruction"],
            "delivery_status": "PENDING" if plan["should_push"] else "NOT_REQUIRED",
            "job_run_id": job_run_id,
        }

        try:
            resp = await client.table("profit_taking_plans").insert(payload).execute()
            if resp.data:
                return str(resp.data[0]["id"])
            return await self._find_plan_id(client, plan)
        except Exception as exc:
            message = str(exc).lower()
            if "duplicate" not in message and "unique" not in message and "23505" not in message:
                raise
            update_payload = dict(payload)
            update_payload.pop("tenant_id", None)
            update_payload.pop("symbol", None)
            update_payload.pop("plan_date", None)
            resp = (
                await client.table("profit_taking_plans")
                .update(update_payload)
                .eq("tenant_id", plan["tenant_id"])
                .eq("symbol", plan["symbol"])
                .eq("plan_date", plan["plan_date"])
                .execute()
            )
            if resp.data:
                return str(resp.data[0]["id"])
            return await self._find_plan_id(client, plan)

    async def _find_plan_id(self, client, plan: dict[str, Any]) -> str:
        resp = (
            await client.table("profit_taking_plans")
            .select("id")
            .eq("tenant_id", plan["tenant_id"])
            .eq("symbol", plan["symbol"])
            .eq("plan_date", plan["plan_date"])
            .limit(1)
            .execute()
        )
        return str(resp.data[0]["id"]) if resp.data else ""

    async def _mark_plan_delivery_status(self, client, plan_id: str, status: str) -> None:
        if not plan_id:
            return
        await (
            client.table("profit_taking_plans")
            .update({"delivery_status": status})
            .eq("id", plan_id)
            .execute()
        )

    async def _create_delivery(
        self,
        client,
        plan: dict[str, Any],
        plan_id: str,
        job_run_id: str | None,
        session: dict[str, Any],
    ) -> None:
        if not job_run_id:
            job_run_id = await self._create_fallback_job(client, plan["tenant_id"])

        delivery_key = f"profit-taking:{plan['plan_date']}:{plan['symbol']}"
        idempotency_key = hashlib.sha256(
            f"{plan['tenant_id']}:{delivery_key}".encode("utf-8")
        ).hexdigest()
        payload = {
            "job_run_id": job_run_id,
            "tenant_id": plan["tenant_id"],
            "channel": "wechat_claw",
            "status": "PENDING",
            "content": {
                "delivery_key": delivery_key,
                "plan_id": plan_id,
                "text": plan["instruction"],
                "action": plan["action"],
                "symbol": plan["symbol"],
                "target_price": plan["target_price"],
            },
            "context_token": session.get("context_token"),
            "target_conversation": session.get("conversation_id"),
            "delivery_key": delivery_key,
            "idempotency_key": idempotency_key,
        }
        if not payload["context_token"] or not payload["target_conversation"]:
            await self._mark_plan_delivery_status(client, plan_id, "SKIPPED_NO_SESSION")
            return

        try:
            await client.table("delivery_runs").insert(payload).execute()
            await self._mark_plan_delivery_status(client, plan_id, "QUEUED")
        except Exception as exc:
            message = str(exc).lower()
            if "duplicate" in message or "unique" in message or "23505" in message:
                await self._mark_plan_delivery_status(client, plan_id, "QUEUED")
                return
            raise

    async def _create_fallback_job(self, client, tenant_id: str) -> str:
        now = datetime.now(timezone.utc).isoformat()
        resp = (
            await client.table("job_runs")
            .insert({
                "tenant_id": tenant_id,
                "job_type": "profit_taking",
                "status": "RUNNING",
                "started_at": now,
                "timeout_seconds": 180,
                "config": {"trigger_type": "cron"},
            })
            .execute()
        )
        return str(resp.data[0]["id"])

    async def _fetch_symbol_data(
        self,
        symbol: str,
    ) -> tuple[dict[str, Any], list[dict[str, Any]]]:
        bars = await asyncio.to_thread(_download_history, _to_yahoo_symbol(symbol), "1y")
        if not bars:
            raise RuntimeError(f"No historical bars for {symbol}")
        last = bars[-1]
        prev = bars[-2] if len(bars) > 1 else last
        price = last["close"]
        prev_close = prev["close"] or price
        quote = {
            "symbol": symbol,
            "market": _infer_market(symbol),
            "price": price,
            "change": price - prev_close,
            "change_rate": ((price - prev_close) / prev_close) * 100 if prev_close else 0,
        }
        return quote, bars

    async def _fetch_market_history(self, market: str) -> list[dict[str, Any]]:
        market_symbol = {
            "CN": "000001.SS",
            "HK": "^HSI",
            "US": "^GSPC",
        }.get(market, "^GSPC")
        return await asyncio.to_thread(_download_history, market_symbol, "1y")


def _download_history(yahoo_symbol: str, period: str) -> list[dict[str, Any]]:
    try:
        import yfinance as yf
    except ImportError as exc:
        raise RuntimeError("yfinance is required for profit-taking history") from exc

    frame = yf.download(
        yahoo_symbol,
        period=period,
        interval="1d",
        auto_adjust=False,
        progress=False,
        threads=False,
    )
    if frame is None or frame.empty:
        return []

    rows: list[dict[str, Any]] = []
    for idx, row in frame.iterrows():
        rows.append({
            "date": idx.date().isoformat() if hasattr(idx, "date") else str(idx),
            "open": _series_value(row, "Open"),
            "high": _series_value(row, "High"),
            "low": _series_value(row, "Low"),
            "close": _series_value(row, "Close"),
            "volume": _series_value(row, "Volume"),
        })
    return [row for row in rows if row["close"]]


def _series_value(row: Any, key: str) -> float | None:
    value = row.get(key)
    if hasattr(value, "iloc"):
        value = value.iloc[0]
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _to_yahoo_symbol(symbol: str) -> str:
    value = symbol.strip().upper()
    if value.startswith("SH"):
        return f"{value[2:]}.SS"
    if value.startswith("SZ"):
        return f"{value[2:]}.SZ"
    if value.startswith("HK"):
        return f"{value[2:].lstrip('0') or '0'}.HK"
    return value


def _infer_market(symbol: str) -> str:
    value = symbol.strip().upper()
    if value.startswith(("SH", "SZ")):
        return "CN"
    if value.startswith("HK"):
        return "HK"
    return "US"
