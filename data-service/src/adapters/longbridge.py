"""
Longbridge 数据源适配器（港股实时行情）

通过 Longbridge OpenAPI 获取港股/美股实时行情，
并提供业务层 symbol 与 Longbridge 格式的自动映射。

优先通过 Longbridge OpenAPI SDK 获取行情；若 SDK 或 OpenAPI 三元组
未配置，则使用系统级 Longbridge MCP bearer token 调用只读 quote 工具。
"""

import asyncio
import json
import os
import time
import urllib.request
from typing import Any, Dict, List, Optional

from adapters.base import DataSourceAdapter

try:
    from longbridge.openapi import Config, QuoteContext
    _HAS_LONGBRIDGE = True
except ImportError:
    _HAS_LONGBRIDGE = False


def to_longbridge_symbol(symbol: str) -> str:
    """
    将业务层 symbol 转换为 Longbridge 格式。

    规则：
        - HK00700 -> 700.HK（去掉 HK 前缀，追加 .HK）
        - NVDA -> NVDA.US（业务层美股 symbol 默认追加 .US）
        - 已带市场后缀的 symbol 保持原样
    """
    s = symbol.strip().upper()
    if s.startswith("HK"):
        return f"{s[2:]}.HK"
    if "." in s:
        return s
    if s.startswith(("SH", "SZ")) and len(s) > 2 and s[2:].isdigit():
        return f"{s[2:]}.{s[:2]}"
    if s.isalpha() and 1 <= len(s) <= 6:
        return f"{s}.US"
    return s


def to_business_symbol(lb_symbol: str) -> str:
    """
    将 Longbridge symbol 反向映射为业务层统一格式。

    规则：
        - 700.HK -> HK00700（补齐前导零至 5 位）
        - NVDA.US -> NVDA
        - SH/SZ 后缀转回业务层前缀
    """
    lb = lb_symbol.strip().upper()
    if lb.endswith(".HK"):
        code = lb[:-3]
        return f"HK{code.zfill(5)}"
    if lb.endswith(".US"):
        return lb[:-3]
    if lb.endswith(".SH"):
        return f"SH{lb[:-3]}"
    if lb.endswith(".SZ"):
        return f"SZ{lb[:-3]}"
    return lb


def _normalize_quote(lb_symbol: str, quote: Any) -> Dict[str, Any]:
    """
    将 Longbridge QuoteContext 返回的 Quote 对象转换为标准化行情字典。
    """
    # Longbridge SDK 返回的对象通常包含以下属性：
    # symbol, name, last_done, change, change_rate, timestamp 等
    # 由于 SDK 类型可能变化，使用 getattr 安全访问
    price = getattr(quote, "last_done", None)
    change = getattr(quote, "change", None)
    change_rate = getattr(quote, "change_rate", None)
    name = getattr(quote, "name", "") or ""
    timestamp = getattr(quote, "timestamp", None)

    # 处理时间戳
    ts = int(time.time())
    if isinstance(timestamp, (int, float)):
        ts = int(timestamp) if timestamp < 1e11 else int(timestamp / 1000)

    return {
        "symbol": to_business_symbol(lb_symbol),
        "name": name,
        "market": "HK",
        "exchange": "HKEX",
        "price": round(float(price), 4) if price is not None else None,
        "change": round(float(change), 4) if change is not None else None,
        "change_rate": round(float(change_rate), 2) if change_rate is not None else None,
        "currency": "HKD",
        "timestamp": ts,
    }


def _market_from_symbol(symbol: str) -> str:
    s = symbol.strip().upper()
    if s.endswith(".US"):
        return "US"
    if s.endswith(".HK") or s.startswith("HK"):
        return "HK"
    if s.endswith(".SH"):
        return "SH"
    if s.endswith(".SZ"):
        return "SZ"
    return ""


def _currency_from_market(market: str) -> str:
    return {"US": "USD", "HK": "HKD", "SH": "CNY", "SZ": "CNY"}.get(market, "")


def _parse_longbridge_timestamp(value: Any) -> int:
    if isinstance(value, (int, float)):
        return int(value) if value < 1e11 else int(value / 1000)
    if isinstance(value, str) and value:
        try:
            from datetime import datetime

            return int(datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp())
        except Exception:
            return int(time.time())
    return int(time.time())


def _normalize_mcp_quote(item: Dict[str, Any]) -> Dict[str, Any]:
    symbol = str(item.get("symbol") or "").upper()
    market = _market_from_symbol(symbol)
    last_done = item.get("last_done")
    prev_close = item.get("prev_close")
    change = None
    change_rate = None
    try:
        if last_done is not None and prev_close is not None:
            change = float(last_done) - float(prev_close)
            if float(prev_close) != 0:
                change_rate = change / float(prev_close) * 100
    except Exception:
        change = None
        change_rate = None

    return {
        "symbol": to_business_symbol(symbol),
        "name": item.get("name", "") or "",
        "market": market,
        "exchange": {"US": "NASDAQ", "HK": "HKEX", "SH": "SSE", "SZ": "SZSE"}.get(market, market),
        "price": round(float(last_done), 4) if last_done is not None else None,
        "change": round(float(change), 4) if change is not None else None,
        "change_rate": round(float(change_rate), 2) if change_rate is not None else None,
        "currency": _currency_from_market(market),
        "timestamp": _parse_longbridge_timestamp(item.get("timestamp")),
        "volume": item.get("volume"),
        "turnover": item.get("turnover"),
        "trade_status": item.get("trade_status"),
        "source": "longbridge_mcp",
    }


class LongbridgeAdapter(DataSourceAdapter):
    """Longbridge OpenAPI 数据源适配器实现（港股为主）。"""

    def __init__(self):
        self._app_key = os.getenv("LONGBRIDGE_APP_KEY")
        self._app_secret = os.getenv("LONGBRIDGE_APP_SECRET")
        self._access_token = os.getenv("LONGBRIDGE_ACCESS_TOKEN")
        self._mcp_access_token = os.getenv("LONGBRIDGE_MCP_ACCESS_TOKEN")
        self._mcp_url = os.getenv("LONGBRIDGE_MCP_URL", "https://mcp.longbridge.com")

        self._sdk_available = _HAS_LONGBRIDGE and bool(self._app_key and self._app_secret and self._access_token)
        self._mcp_available = bool(self._mcp_access_token)
        self._available = self._sdk_available or self._mcp_available

        if not self._sdk_available:
            self._config = None
            self._ctx = None
            return

        self._config = Config(
            app_key=self._app_key,
            app_secret=self._app_secret,
            access_token=self._access_token,
        )
        self._ctx: Optional[Any] = None

    def _get_context(self) -> Any:
        """惰性初始化 QuoteContext。"""
        if self._ctx is None:
            self._ctx = QuoteContext(self._config)
        return self._ctx

    async def fetch_quote(self, symbol: str) -> Dict[str, Any]:
        """
        获取单只股票实时行情。

        Args:
            symbol: 业务层代码，如 "HK00700"

        Returns:
            标准化行情字典

        Raises:
            RuntimeError: SDK 未安装、未配置或请求失败
        """
        if not self._available:
            raise RuntimeError("longbridge SDK/token or MCP token not configured")

        if self._mcp_available and not self._sdk_available:
            quotes = await self._fetch_mcp_quotes([symbol])
            if symbol in quotes:
                return quotes[symbol]
            normalized = to_business_symbol(to_longbridge_symbol(symbol))
            if normalized in quotes:
                return quotes[normalized]
            raise RuntimeError(f"No quote returned for {symbol}")

        lb_sym = to_longbridge_symbol(symbol)

        # Longbridge SDK 是同步库，使用 asyncio.to_thread 包装
        ctx = self._get_context()
        quotes = await asyncio.to_thread(ctx.quote, lb_sym)

        if not quotes:
            raise RuntimeError(f"No quote returned for {lb_sym}")

        quote = quotes[0] if isinstance(quotes, list) else quotes
        return _normalize_quote(lb_sym, quote)

    async def fetch_batch_quotes(self, symbols: List[str]) -> Dict[str, Dict[str, Any]]:
        """
        批量获取行情。

        使用 asyncio.gather 并发获取，并对失败项进行优雅降级。

        Returns:
            {业务层 symbol: 标准化字典} 的映射，失败的 symbol 不包含在结果中。
        """
        if not self._available:
            raise RuntimeError("longbridge SDK/token or MCP token not configured")

        if self._mcp_available and not self._sdk_available:
            return await self._fetch_mcp_quotes(symbols)

        results: Dict[str, Dict[str, Any]] = {}
        semaphore = asyncio.Semaphore(5)

        async def _fetch_one(sym: str):
            async with semaphore:
                try:
                    quote = await self.fetch_quote(sym)
                    return sym, quote
                except Exception:
                    return sym, None

        tasks = [_fetch_one(sym) for sym in symbols]
        completed = await asyncio.gather(*tasks, return_exceptions=True)

        for item in completed:
            if isinstance(item, Exception):
                continue
            sym, quote = item
            if quote is not None:
                results[sym] = quote

        return results

    def _call_mcp_quote_sync(self, symbols: List[str]) -> List[Dict[str, Any]]:
        payload = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {"name": "quote", "arguments": {"symbols": [to_longbridge_symbol(s) for s in symbols]}},
        }
        req = urllib.request.Request(
            self._mcp_url,
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "Accept": "application/json, text/event-stream",
                "Authorization": f"Bearer {self._mcp_access_token}",
            },
        )
        with urllib.request.urlopen(req, timeout=30) as response:
            raw = response.read().decode("utf-8", errors="replace")
        if raw.startswith("data: "):
            raw = raw[6:].strip()
        envelope = json.loads(raw)
        if envelope.get("error"):
            raise RuntimeError(str(envelope["error"]))
        result = envelope.get("result") or {}
        if result.get("isError"):
            raise RuntimeError(str(result.get("content") or result))
        content = result.get("content") or []
        if not content:
            return []
        text = content[0].get("text") if isinstance(content[0], dict) else None
        if not text:
            return []
        parsed = json.loads(text)
        return parsed if isinstance(parsed, list) else [parsed]

    async def _fetch_mcp_quotes(self, symbols: List[str]) -> Dict[str, Dict[str, Any]]:
        items = await asyncio.to_thread(self._call_mcp_quote_sync, symbols)
        results: Dict[str, Dict[str, Any]] = {}
        for item in items:
            normalized = _normalize_mcp_quote(item)
            results[normalized["symbol"]] = normalized
            raw_symbol = str(item.get("symbol") or "").upper()
            if raw_symbol:
                results[raw_symbol] = normalized
        return results

    async def search_symbols(self, keyword: str, market: Optional[str] = None) -> List[Dict[str, Any]]:
        """
        根据关键词搜索股票代码。

        Longbridge OpenAPI 暂无标准搜索接口，暂返回空列表
        或根据 keyword 做简单的港股代码过滤。
        """
        return []
