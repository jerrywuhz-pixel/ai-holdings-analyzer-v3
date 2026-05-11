"""
Yahoo Finance 数据源适配器

通过 Yahoo Finance v8 chart API 获取实时行情，
并提供 A 股 / 美股 / 港股的 symbol 后缀自动映射。
"""

import time
from typing import Any, Dict, List, Optional

import httpx

from adapters.base import DataSourceAdapter

# Yahoo Finance Chart API 基础 URL
YAHOO_CHART_URL = "https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"
YAHOO_SEARCH_URL = "https://query1.finance.yahoo.com/v1/finance/search"

# A 股 / 港股后缀映射规则
# 业务层传入的 symbol 可能带 SH/SZ/HK 前缀，需转换为 Yahoo 格式
SUFFIX_MAP = {
    "SH": ".SS",   # 上海证交所
    "SZ": ".SZ",  # 深圳证交所
    "HK": ".HK",  # 香港交易所
}


def to_yahoo_symbol(symbol: str) -> str:
    """
    将业务层 symbol 转换为 Yahoo Finance 格式。

    规则：
        - SH600519  -> 600519.SS
        - SZ000001  -> 000001.SZ
        - HK00700   -> 0700.HK (Yahoo 港股通常无 leading zero，但 chart API 兼容)
        - AAPL      -> AAPL (美股无后缀)
    """
    symbol = symbol.strip().upper()

    for prefix, suffix in SUFFIX_MAP.items():
        if symbol.startswith(prefix):
            # 去掉前缀，追加 Yahoo 后缀
            code = symbol[len(prefix):]
            return f"{code}{suffix}"

    # 默认当作美股或其他已含后缀的代码处理
    return symbol


def to_business_symbol(yahoo_symbol: str) -> str:
    """
    将 Yahoo symbol 反向映射为业务层统一格式。

    规则：
        - 600519.SS -> SH600519
        - 000001.SZ -> SZ000001
        - 0700.HK   -> HK00700 (补齐前导零)
        - AAPL      -> AAPL
    """
    yahoo_symbol = yahoo_symbol.strip().upper()

    if yahoo_symbol.endswith(".SS"):
        return f"SH{yahoo_symbol[:-3]}"
    if yahoo_symbol.endswith(".SZ"):
        return f"SZ{yahoo_symbol[:-3]}"
    if yahoo_symbol.endswith(".HK"):
        code = yahoo_symbol[:-3]
        # 港股在业务层通常补齐 5 位
        return f"HK{code.zfill(5)}"

    return yahoo_symbol


def _infer_market(yahoo_symbol: str) -> str:
    """根据 Yahoo symbol 后缀推断市场标识。"""
    if yahoo_symbol.endswith((".SS", ".SZ")):
        return "CN"
    if yahoo_symbol.endswith(".HK"):
        return "HK"
    return "US"


def _normalize_quote(yahoo_symbol: str, meta: Dict[str, Any]) -> Dict[str, Any]:
    """
    将 Yahoo Finance chart meta 转换为标准化行情字典。
    """
    price = meta.get("regularMarketPrice")
    prev_close = meta.get("previousClose") or meta.get("chartPreviousClose")
    currency = meta.get("currency", "USD")
    exchange = meta.get("exchangeName", "")
    full_exchange = meta.get("fullExchangeName", "")
    regular_time = meta.get("regularMarketTime")

    # 计算涨跌幅
    change = None
    change_rate = None
    if price is not None and prev_close:
        change = round(price - prev_close, 4)
        change_rate = round((change / prev_close) * 100, 2)

    # 处理时间戳：Yahoo 可能返回秒级或毫秒级，统一为秒级
    timestamp = None
    if isinstance(regular_time, (int, float)):
        timestamp = int(regular_time) if regular_time < 1e11 else int(regular_time / 1000)
    else:
        timestamp = int(time.time())

    return {
        "symbol": to_business_symbol(yahoo_symbol),
        "name": meta.get("shortName") or meta.get("longName") or "",
        "market": _infer_market(yahoo_symbol),
        "exchange": full_exchange or exchange,
        "price": round(price, 4) if price is not None else None,
        "change": change,
        "change_rate": change_rate,
        "currency": currency,
        "timestamp": timestamp,
    }


class YahooFinanceAdapter(DataSourceAdapter):
    """Yahoo Finance 数据源适配器实现。"""

    def __init__(self, timeout: float = 15.0):
        self.timeout = timeout
        self._client: Optional[httpx.AsyncClient] = None

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(timeout=self.timeout)
        return self._client

    async def fetch_quote(self, symbol: str) -> dict[str, Any]:
        """
        获取单只股票实时行情。

        Args:
            symbol: 业务层代码，如 "SH600519"、"AAPL"

        Returns:
            标准化行情字典

        Raises:
            RuntimeError: 请求失败或返回异常结构
        """
        yahoo_sym = to_yahoo_symbol(symbol)
        url = YAHOO_CHART_URL.format(symbol=yahoo_sym)

        client = await self._get_client()
        resp = await client.get(url, headers={"Accept": "application/json"})
        resp.raise_for_status()

        data = resp.json()
        chart = data.get("chart", {})

        if chart.get("error"):
            raise RuntimeError(f"Yahoo API error for {yahoo_sym}: {chart['error']}")

        results = chart.get("result")
        if not results:
            raise RuntimeError(f"No data returned for {yahoo_sym}")

        meta = results[0].get("meta", {})
        return _normalize_quote(yahoo_sym, meta)

    async def fetch_batch_quotes(self, symbols: List[str]) -> Dict[str, Dict[str, Any]]:
        """
        批量获取行情。

        由于 Yahoo chart API 不支持真正的批量请求，
        这里使用 asyncio.gather 并发获取，并对失败项进行优雅降级。

        Returns:
            {业务层 symbol: 标准化字典} 的映射，失败的 symbol 不包含在结果中。
        """
        import asyncio

        results: dict[str, dict[str, Any]] = {}

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
        通过 Yahoo Finance Search API 搜索股票。

        Args:
            keyword: 搜索关键词
            market:  市场过滤（如 "CN"、"US"、"HK"），目前仅做结果后过滤

        Returns:
            标准化搜索结果列表
        """
        client = await self._get_client()
        params = {
            "q": keyword,
            "quotesCount": 20,
            "newsCount": 0,
            "listsCount": 0,
        }
        resp = await client.get(YAHOO_SEARCH_URL, params=params, headers={"Accept": "application/json"})
        resp.raise_for_status()

        data = resp.json()
        quotes = data.get("quotes", [])

        results: List[Dict[str, Any]] = []
        for q in quotes:
            yahoo_sym = q.get("symbol", "")
            if not yahoo_sym:
                continue

            # 忽略期权、加密货币等非股票类型
            quote_type = q.get("quoteType", "EQUITY")
            if quote_type not in ("EQUITY", "INDEX", "ETF", "MUTUALFUND"):
                continue

            biz_sym = to_business_symbol(yahoo_sym)
            inferred_market = _infer_market(yahoo_sym)

            # 若指定 market 则过滤
            if market and inferred_market != market.upper():
                continue

            results.append({
                "symbol": biz_sym,
                "name": q.get("longname") or q.get("shortname") or "",
                "market": inferred_market,
                "exchange": q.get("exchDisp", ""),
                "type": quote_type,
            })

        return results
