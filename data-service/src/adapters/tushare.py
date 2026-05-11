"""
Tushare 数据源适配器

通过 Tushare Pro API 获取 A 股 / 港股日线行情，
提供业务层 symbol 与 Tushare ts_code 的自动映射。
"""

import os
import time
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

import httpx

from adapters.base import DataSourceAdapter

TUSHARE_API_URL = "https://api.tushare.pro"


def to_tushare_symbol(symbol: str) -> str:
    """
    将业务层 symbol 转换为 Tushare ts_code 格式。

    规则：
        - SH600519 -> 600519.SH
        - SZ000001 -> 000001.SZ
        - HK00700  -> 00700.HK
        - AAPL     -> AAPL (美股保持原样)
    """
    s = symbol.strip().upper()
    if s.startswith("SH"):
        return f"{s[2:]}.SH"
    if s.startswith("SZ"):
        return f"{s[2:]}.SZ"
    if s.startswith("HK"):
        return f"{s[2:]}.HK"
    return s


def _to_business_symbol(ts_code: str) -> str:
    """
    将 Tushare ts_code 反向映射为业务层统一格式。

    规则：
        - 600519.SH -> SH600519
        - 000001.SZ -> SZ000001
        - 00700.HK  -> HK00700
    """
    tc = ts_code.strip().upper()
    if tc.endswith(".SH"):
        return f"SH{tc[:-3]}"
    if tc.endswith(".SZ"):
        return f"SZ{tc[:-3]}"
    if tc.endswith(".HK"):
        return f"HK{tc[:-3]}"
    return tc


def _infer_market(symbol: str) -> str:
    """根据业务层 symbol 前缀推断市场。"""
    s = symbol.strip().upper()
    if s.startswith(("SH", "SZ")):
        return "CN"
    if s.startswith("HK"):
        return "HK"
    return "US"


def _normalize_daily_item(fields: List[str], item: List[Any]) -> Dict[str, Any]:
    """
    将 Tushare daily 接口返回的 item（与 fields 对齐）转换为标准化行情字典。
    """
    record: Dict[str, Any] = dict(zip(fields, item))

    ts_code = str(record.get("ts_code", ""))
    close = record.get("close")
    pre_close = record.get("pre_close")
    change = record.get("change")
    pct_chg = record.get("pct_chg")
    trade_date = str(record.get("trade_date", ""))

    price = float(close) if close is not None else None
    change_val = float(change) if change is not None else None
    change_rate = float(pct_chg) if pct_chg is not None else None

    # 若接口未返回涨跌幅，手动计算
    if change_rate is None and price is not None and pre_close:
        change_rate = round(((price - float(pre_close)) / float(pre_close)) * 100, 4)
    if change_val is None and price is not None and pre_close:
        change_val = round(price - float(pre_close), 4)

    # 时间戳：取交易日期当日 15:00:00（北京时间）
    timestamp = int(time.time())
    if len(trade_date) == 8:
        try:
            dt = datetime.strptime(trade_date, "%Y%m%d").replace(hour=15, minute=0, second=0)
            timestamp = int(dt.timestamp())
        except ValueError:
            pass

    return {
        "symbol": _to_business_symbol(ts_code),
        "name": "",
        "market": _infer_market(_to_business_symbol(ts_code)),
        "exchange": "SSE" if ts_code.endswith(".SH") else ("SZSE" if ts_code.endswith(".SZ") else ""),
        "price": round(price, 4) if price is not None else None,
        "change": round(change_val, 4) if change_val is not None else None,
        "change_rate": round(change_rate, 2) if change_rate is not None else None,
        "currency": "CNY" if _infer_market(_to_business_symbol(ts_code)) == "CN" else "HKD",
        "timestamp": timestamp,
    }


class TushareAdapter(DataSourceAdapter):
    """Tushare Pro 数据源适配器实现。"""

    def __init__(self, token: Optional[str] = None, timeout: float = 15.0):
        self.token = token or os.getenv("TUSHARE_TOKEN")
        self.timeout = timeout
        self._client: Optional[httpx.AsyncClient] = None

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(timeout=self.timeout)
        return self._client

    async def _post(self, api_name: str, params: Dict[str, Any]) -> Dict[str, Any]:
        """发送 Tushare API 请求并解析响应。"""
        if not self.token:
            raise RuntimeError("TUSHARE_TOKEN not configured")

        client = await self._get_client()
        payload = {
            "api_name": api_name,
            "token": self.token,
            "params": params,
            "fields": "",
        }
        resp = await client.post(TUSHARE_API_URL, json=payload, headers={"Accept": "application/json"})
        resp.raise_for_status()

        data = resp.json()
        if data.get("code") != 0:
            msg = data.get("msg", "unknown error")
            raise RuntimeError(f"Tushare API error [{api_name}]: {msg}")

        return data.get("data", {})

    async def fetch_quote(self, symbol: str) -> Dict[str, Any]:
        """
        获取单只股票行情（通过 daily 接口取最近交易日数据）。

        Args:
            symbol: 业务层代码，如 "SH600519"

        Returns:
            标准化行情字典

        Raises:
            RuntimeError: token 未配置或请求失败
        """
        ts_code = to_tushare_symbol(symbol)

        # 取最近 10 个交易日的数据，防止周末/节假日无数据
        end_date = datetime.now().strftime("%Y%m%d")
        start_date = (datetime.now() - timedelta(days=10)).strftime("%Y%m%d")

        data = await self._post(
            "daily",
            {"ts_code": ts_code, "start_date": start_date, "end_date": end_date},
        )

        fields = data.get("fields", [])
        items = data.get("items", [])
        if not items:
            raise RuntimeError(f"No daily data returned for {symbol} ({ts_code})")

        # 按 trade_date 排序取最新（取最后一条，默认升序）
        try:
            date_idx = fields.index("trade_date")
            items_sorted = sorted(items, key=lambda x: x[date_idx], reverse=True)
            latest_item = items_sorted[0]
        except ValueError:
            latest_item = items[-1]

        return _normalize_daily_item(fields, latest_item)

    async def fetch_batch_quotes(self, symbols: List[str]) -> Dict[str, Dict[str, Any]]:
        """
        批量获取行情，失败项自动跳过。

        通过 asyncio.gather 并发调用 fetch_quote。
        """
        import asyncio

        results: Dict[str, Dict[str, Any]] = {}

        async def _fetch_one(sym: str):
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

    async def search_symbols(self, keyword: str, market: Optional[str] = None) -> List[Dict[str, Any]]:
        """
        Tushare 搜索 API 较复杂，暂返回空列表。
        """
        return []
