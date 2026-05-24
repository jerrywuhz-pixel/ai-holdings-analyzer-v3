from __future__ import annotations

"""
Stooq CSV quote adapter.

Used as a no-key fallback for US and CN quote display when Yahoo is rate
limited and premium broker/vendor quote APIs are unavailable.
"""

import csv
import time
from datetime import datetime, timezone
from io import StringIO
from typing import Any, Dict, List, Optional

import httpx

from adapters.base import DataSourceAdapter


STOOQ_QUOTE_URL = "https://stooq.com/q/l/"


def to_stooq_symbol(symbol: str) -> str:
    business_symbol = symbol.strip().upper()
    if business_symbol.startswith(("SH", "SZ")):
        return f"{business_symbol[2:]}.cn".lower()
    if business_symbol.startswith("HK"):
        raise RuntimeError("Stooq quote adapter does not support HK symbols")
    return f"{business_symbol}.us".lower()


def to_business_symbol(stooq_symbol: str) -> str:
    symbol = stooq_symbol.strip().upper()
    if symbol.endswith(".US"):
        return symbol[:-3]
    if symbol.endswith(".CN"):
        code = symbol[:-3]
        if code.startswith("6"):
            return f"SH{code}"
        return f"SZ{code}"
    return symbol


def _infer_market(stooq_symbol: str) -> str:
    symbol = stooq_symbol.strip().upper()
    if symbol.endswith(".CN"):
        return "CN"
    if symbol.endswith(".HK"):
        return "HK"
    return "US"


def _exchange_for_symbol(stooq_symbol: str) -> str:
    symbol = stooq_symbol.strip().upper()
    if symbol.endswith(".CN"):
        return "SSE/SZSE"
    if symbol.endswith(".HK"):
        return "HKEX"
    return "US"


def _currency_for_market(market: str) -> str:
    if market == "CN":
        return "CNY"
    if market == "HK":
        return "HKD"
    return "USD"


def _timestamp(date_text: str, time_text: str) -> int:
    if date_text == "N/D":
        return int(time.time())
    if time_text and time_text != "N/D":
        try:
            parsed = datetime.fromisoformat(f"{date_text}T{time_text}+00:00")
            return int(parsed.timestamp())
        except ValueError:
            pass
    try:
        parsed = datetime.fromisoformat(f"{date_text}T00:00:00+00:00")
        return int(parsed.timestamp())
    except ValueError:
        return int(time.time())


def _number(value: str) -> float | None:
    if not value or value == "N/D":
        return None
    try:
        return float(value)
    except ValueError:
        return None


def _parse_quote(text: str, requested_symbol: str) -> dict[str, Any]:
    rows = list(csv.DictReader(StringIO(text)))
    if not rows:
        raise RuntimeError("Stooq returned empty CSV")

    row = rows[0]
    stooq_symbol = row.get("Symbol") or requested_symbol
    close = _number(row.get("Close", ""))
    if close is None:
        raise RuntimeError(f"Stooq returned no quote for {requested_symbol}")

    open_price = _number(row.get("Open", ""))
    change = round(close - open_price, 4) if open_price is not None else None
    change_rate = round((change / open_price) * 100, 2) if change is not None and open_price else None
    market = _infer_market(stooq_symbol)

    return {
        "symbol": to_business_symbol(stooq_symbol),
        "name": "",
        "market": market,
        "exchange": _exchange_for_symbol(stooq_symbol),
        "price": round(close, 4),
        "change": change,
        "change_rate": change_rate,
        "currency": _currency_for_market(market),
        "timestamp": _timestamp(row.get("Date", ""), row.get("Time", "")),
        "source": "stooq",
    }


class StooqAdapter(DataSourceAdapter):
    """No-key Stooq CSV quote adapter for fallback display quotes."""

    def __init__(self, timeout: float = 10.0):
        self.timeout = timeout
        self._client: Optional[httpx.AsyncClient] = None

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(timeout=self.timeout, follow_redirects=True)
        return self._client

    async def fetch_quote(self, symbol: str) -> Dict[str, Any]:
        stooq_symbol = to_stooq_symbol(symbol)
        client = await self._get_client()
        response = await client.get(
            STOOQ_QUOTE_URL,
            params={"s": stooq_symbol, "f": "sd2t2ohlcv", "h": "", "e": "csv"},
            headers={"Accept": "text/csv"},
        )
        response.raise_for_status()
        return _parse_quote(response.text, stooq_symbol)

    async def fetch_batch_quotes(self, symbols: List[str]) -> Dict[str, Dict[str, Any]]:
        import asyncio

        results: dict[str, dict[str, Any]] = {}

        async def _fetch_one(symbol: str):
            try:
                return symbol, await self.fetch_quote(symbol)
            except Exception:
                return symbol, None

        completed = await asyncio.gather(*[_fetch_one(symbol) for symbol in symbols])
        for symbol, quote in completed:
            if quote is not None:
                results[symbol] = quote
        return results

    async def search_symbols(self, keyword: str, market: Optional[str] = None) -> List[Dict[str, Any]]:
        return []
