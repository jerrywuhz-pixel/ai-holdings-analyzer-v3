from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from adapters.base import DataSourceAdapter
from adapters.futu import FutuConnectorError, FutuQuoteReadRequest, FutuReadOnlyConnector


class FutuQuoteAdapter(DataSourceAdapter):
    """Read-only real-time quote adapter backed by the admin-managed Futu OpenD connector."""

    def __init__(self, connector: FutuReadOnlyConnector | None = None) -> None:
        self._connector = connector or FutuReadOnlyConnector()

    async def fetch_quote(self, symbol: str) -> Dict[str, Any]:
        market = _infer_market(symbol)
        payload = await self._connector.read_quotes(
            FutuQuoteReadRequest(
                symbols=[_to_futu_symbol(symbol)],
                market=market,
                connector_mode="local_connector",
            )
        )
        quotes = payload.get("quotes") or []
        if not quotes:
            raise FutuConnectorError(f"Futu quote missing for {symbol}")
        quote = _normalize_quote(quotes[0], requested_symbol=symbol, source_payload=payload)
        if quote.get("price") is None:
            raise FutuConnectorError(f"Futu quote missing price for {symbol}")
        return quote

    async def fetch_batch_quotes(self, symbols: List[str]) -> Dict[str, Dict[str, Any]]:
        results: dict[str, dict[str, Any]] = {}

        async def _fetch_one(sym: str) -> tuple[str, dict[str, Any] | None]:
            try:
                return sym, await self.fetch_quote(sym)
            except Exception:
                return sym, None

        for item in await asyncio.gather(*[_fetch_one(sym) for sym in symbols], return_exceptions=True):
            if isinstance(item, Exception):
                continue
            symbol, quote = item
            if quote is not None:
                results[symbol] = quote
        return results

    async def search_symbols(self, keyword: str, market: Optional[str] = None) -> List[Dict[str, Any]]:
        return []


def _normalize_quote(quote: dict[str, Any], *, requested_symbol: str, source_payload: dict[str, Any]) -> dict[str, Any]:
    timestamp = _timestamp_value(quote.get("timestamp"), source_payload.get("as_of"))
    return {
        "symbol": requested_symbol.strip().upper(),
        "name": quote.get("name") or "",
        "market": quote.get("market") or _infer_market(requested_symbol),
        "exchange": quote.get("exchange") or quote.get("market") or _infer_market(requested_symbol),
        "price": _float_or_none(quote.get("price")),
        "change": _float_or_none(quote.get("change")),
        "change_rate": _float_or_none(quote.get("change_rate")),
        "currency": quote.get("currency") or _currency_for_market(_infer_market(requested_symbol)),
        "timestamp": timestamp,
        "source": "futu",
        "source_key": source_payload.get("source_key") or "futu_openapi",
        "source_tier": source_payload.get("source_tier") or "L1_trading",
        "source_owner": "admin_managed",
        "source_scope": "market_data",
        "tenant_owned": False,
        "quote_usage": "market_reference",
        "broker_account_scope": "system_admin",
        "connector_mode": source_payload.get("connector_mode"),
        "permission_scope": source_payload.get("permission_scope"),
        "freshness_seconds": max(0, int(datetime.now(timezone.utc).timestamp()) - timestamp),
        "lineage": source_payload.get("lineage") or {},
    }


def _to_futu_symbol(symbol: str) -> str:
    value = symbol.strip().upper()
    if value.startswith("HK"):
        return value[2:].lstrip("0") or "0"
    if value.startswith(("SH", "SZ")):
        return value[2:]
    return value


def _infer_market(symbol: str) -> str:
    value = symbol.strip().upper()
    if value.startswith(("SH", "SZ")):
        return "CN"
    if value.startswith("HK"):
        return "HK"
    return "US"


def _currency_for_market(market: str) -> str:
    return {"CN": "CNY", "HK": "HKD"}.get(market, "USD")


def _float_or_none(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _timestamp_value(value: Any, fallback: Any) -> int:
    if isinstance(value, (int, float)):
        return int(value if value < 1e11 else value / 1000)
    for candidate in (fallback,):
        if isinstance(candidate, datetime):
            return int(candidate.timestamp())
        if isinstance(candidate, str):
            try:
                return int(datetime.fromisoformat(candidate.replace("Z", "+00:00")).timestamp())
            except ValueError:
                pass
    return int(datetime.now(timezone.utc).timestamp())
