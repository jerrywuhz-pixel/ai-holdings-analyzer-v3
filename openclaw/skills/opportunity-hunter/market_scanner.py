"""
Market Scanner — 市场扫描模块

扫描指定市场的整体行情概览，包括指数行情和涨跌分布统计。
通过 data-service 批量获取行情数据。
"""

from __future__ import annotations

import logging
import os
from typing import Any

import httpx

logger = logging.getLogger(__name__)

# ---------- 市场指数配置 ----------

MARKET_INDICES: dict[str, list[dict[str, str]]] = {
    "CN": [
        {"symbol": "SH000001", "name": "上证指数"},
        {"symbol": "SZ399001", "name": "深证成指"},
        {"symbol": "SZ399006", "name": "创业板指"},
    ],
    "US": [
        {"symbol": "SPY", "name": "S&P 500 ETF"},
        {"symbol": "QQQ", "name": "纳斯达克100 ETF"},
        {"symbol": "DIA", "name": "道琼斯 ETF"},
        {"symbol": "IWM", "name": "罗素2000 ETF"},
    ],
    "HK": [
        {"symbol": "HKHSI", "name": "恒生指数"},
        {"symbol": "HKHSCEI", "name": "恒生中国企业指数"},
    ],
}

# 用于涨跌分布统计的宽基成分股（采样代表）
BREADTH_SYMBOLS: dict[str, list[str]] = {
    "CN": [
        "SH600519", "SH601318", "SH600036", "SH601012", "SH600276",
        "SH601166", "SH600030", "SH601888", "SH600900", "SH601398",
        "SZ000858", "SZ000333", "SZ002714", "SZ000651", "SZ002475",
        "SZ300750", "SZ002594", "SZ000001", "SZ002230", "SZ300059",
        "SH600887", "SH601899", "SH600585", "SH601688", "SH600048",
        "SZ002415", "SZ000568", "SZ300015", "SZ002352", "SZ000725",
    ],
    "US": [
        "AAPL", "MSFT", "GOOGL", "AMZN", "NVDA", "META", "TSLA",
        "BRK-B", "JPM", "V", "UNH", "JNJ", "WMT", "XOM", "PG",
        "MA", "HD", "CVX", "MRK", "ABBV", "KO", "PEP", "COST",
        "AVGO", "MCD", "ADBE", "CRM", "NFLX", "AMD", "INTC",
    ],
    "HK": [
        "HK00700", "HK09988", "HK03690", "HK09618", "HK01810",
        "HK02318", "HK01299", "HK00941", "HK03988", "HK01398",
        "HK00939", "HK02388", "HK00005", "HK00016", "HK00027",
        "HK01766", "HK02628", "HK02007", "HK00669", "HK02382",
    ],
}


async def scan_market(
    market: str,
    data_service_url: str | None = None,
) -> dict[str, Any]:
    """
    扫描指定市场的整体行情概览。

    获取主要指数行情和涨跌分布统计。

    Args:
        market: 市场标识，"CN" / "US" / "HK"。
        data_service_url: data-service 基础 URL，
            默认从环境变量 DATA_SERVICE_URL 读取，
            回退到 "http://localhost:8000"。

    Returns:
        市场概览字典，包含：
        - advance_count: 上涨数量
        - decline_count: 下跌数量
        - flat_count: 平盘数量
        - total_volume: 总成交额（各股成交额之和，仅作统计参考）
        - index_quotes: 指数行情列表
    """
    if market not in MARKET_INDICES:
        logger.warning("Unknown market '%s', returning empty overview", market)
        return {
            "advance_count": 0,
            "decline_count": 0,
            "flat_count": 0,
            "total_volume": 0,
            "index_quotes": [],
        }

    base_url = data_service_url or os.getenv(
        "DATA_SERVICE_URL", "http://localhost:8000"
    )

    # 1. 获取指数行情
    index_symbols = [idx["symbol"] for idx in MARKET_INDICES[market]]
    index_name_map = {idx["symbol"]: idx["name"] for idx in MARKET_INDICES[market]}

    index_quotes = await _fetch_batch_quotes(base_url, index_symbols)
    index_results = []
    for sym in index_symbols:
        q = index_quotes.get(sym, {})
        index_results.append({
            "symbol": sym,
            "name": index_name_map.get(sym, ""),
            "price": q.get("price"),
            "change": q.get("change"),
            "change_rate": q.get("change_rate"),
        })

    # 2. 获取宽基成分股用于涨跌分布统计
    breadth_syms = BREADTH_SYMBOLS.get(market, [])
    breadth_quotes = await _fetch_batch_quotes(base_url, breadth_syms)

    advance_count = 0
    decline_count = 0
    flat_count = 0
    total_volume = 0.0

    for _sym, q in breadth_quotes.items():
        cr = q.get("change_rate")
        if cr is None:
            continue
        if cr > 0:
            advance_count += 1
        elif cr < 0:
            decline_count += 1
        else:
            flat_count += 1

        # 如果有 volume 字段则累加
        vol = q.get("volume")
        if vol and isinstance(vol, (int, float)):
            total_volume += vol

    # 用采样比例估算全市场涨跌分布
    # 采样数量与全市场总量的比例（粗略估算）
    scale_factors = {"CN": 50, "US": 10, "HK": 8}
    scale = scale_factors.get(market, 1)

    return {
        "advance_count": advance_count * scale,
        "decline_count": decline_count * scale,
        "flat_count": flat_count * scale,
        "total_volume": total_volume,
        "index_quotes": index_results,
    }


async def _fetch_batch_quotes(
    base_url: str,
    symbols: list[str],
) -> dict[str, dict[str, Any]]:
    """
    调用 data-service 批量行情接口。

    Args:
        base_url: data-service 基础 URL。
        symbols: 股票代码列表。

    Returns:
        {symbol: quote_dict} 映射，失败的 symbol 不包含在结果中。
    """
    if not symbols:
        return {}

    url = f"{base_url.rstrip('/')}/api/quote/batch"
    payload = {"symbols": symbols}

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(url, json=payload)
            resp.raise_for_status()
            body = resp.json()

        if body.get("ok") and isinstance(body.get("data"), dict):
            return body["data"]

        logger.warning(
            "data-service batch quote returned non-ok: %s",
            body.get("message", "unknown"),
        )
        return {}
    except httpx.HTTPStatusError as exc:
        logger.error(
            "data-service batch quote HTTP error: %s %s",
            exc.response.status_code,
            exc.response.text[:200],
        )
        return {}
    except httpx.RequestError as exc:
        logger.error("data-service batch quote request error: %s", exc)
        return {}
    except Exception as exc:
        logger.error("Unexpected error in _fetch_batch_quotes: %s", exc)
        return {}
