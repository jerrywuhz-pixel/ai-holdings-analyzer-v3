"""
Sector Hunter — 板块猎手模块

分析板块表现，按涨跌幅排序输出领涨/领跌板块 Top 10。
通过 data-service 批量获取板块 ETF/指数行情。
"""

from __future__ import annotations

import logging
import os
from typing import Any

import httpx

logger = logging.getLogger(__name__)

# ---------- 板块 ETF 配置 ----------

SECTOR_ETFS: dict[str, list[dict[str, str]]] = {
    "CN": [
        {"symbol": "SH512660", "name": "军工"},
        {"symbol": "SH512800", "name": "银行"},
        {"symbol": "SH512010", "name": "医药"},
        {"symbol": "SH512200", "name": "房地产"},
        {"symbol": "SH512880", "name": "券商"},
        {"symbol": "SH512690", "name": "白酒"},
        {"symbol": "SH515790", "name": "光伏"},
        {"symbol": "SH516160", "name": "新能源车"},
        {"symbol": "SH512400", "name": "有色金属"},
        {"symbol": "SH512670", "name": "国防军工"},
        {"symbol": "SH510050", "name": "上证50"},
        {"symbol": "SH510300", "name": "沪深300"},
        {"symbol": "SH510500", "name": "中证500"},
        {"symbol": "SH512980", "name": "传媒"},
        {"symbol": "SH515050", "name": "5GETF"},
        {"symbol": "SH512480", "name": "半导体"},
        {"symbol": "SH512760", "name": "芯片ETF"},
        {"symbol": "SH515880", "name": "通信ETF"},
    ],
    "US": [
        {"symbol": "XLF", "name": "金融"},
        {"symbol": "XLK", "name": "科技"},
        {"symbol": "XLE", "name": "能源"},
        {"symbol": "XLV", "name": "医疗"},
        {"symbol": "XLY", "name": "可选消费"},
        {"symbol": "XLP", "name": "必选消费"},
        {"symbol": "XLI", "name": "工业"},
        {"symbol": "XLB", "name": "材料"},
        {"symbol": "XLRE", "name": "房地产"},
        {"symbol": "XLU", "name": "公用事业"},
        {"symbol": "XLC", "name": "通信"},
    ],
    "HK": [
        {"symbol": "HK02800", "name": "盈富基金"},
        {"symbol": "HK02828", "name": "恒生中国企指数"},
        {"symbol": "HK03032", "name": "恒生科技ETF"},
        {"symbol": "HK03040", "name": "恒生金融ETF"},
        {"symbol": "HK03046", "name": "恒生医疗ETF"},
        {"symbol": "HK03036", "name": "恒生高股息ETF"},
        {"symbol": "HK03042", "name": "恒生地产ETF"},
        {"symbol": "HK03038", "name": "恒生消费ETF"},
        {"symbol": "HK03034", "name": "恒生新能源ETF"},
        {"symbol": "HK03044", "name": "恒生基建ETF"},
    ],
}


async def hunt_sectors(
    market: str,
    data_service_url: str | None = None,
) -> list[dict[str, Any]]:
    """
    分析板块表现，返回按涨跌幅排序的板块列表。

    Args:
        market: 市场标识，"CN" / "US" / "HK"。
        data_service_url: data-service 基础 URL，
            默认从环境变量 DATA_SERVICE_URL 读取，
            回退到 "http://localhost:8000"。

    Returns:
        板块列表，每个元素包含：
        - name: 板块名称
        - symbol: ETF 代码
        - change_rate: 涨跌幅（%）
        - volume: 成交额
        按 change_rate 降序排列，最多返回 10 个。
    """
    if market not in SECTOR_ETFS:
        logger.warning("Unknown market '%s' for sector hunting", market)
        return []

    base_url = data_service_url or os.getenv(
        "DATA_SERVICE_URL", "http://localhost:8000"
    )

    sector_list = SECTOR_ETFS[market]
    symbols = [s["symbol"] for s in sector_list]
    name_map = {s["symbol"]: s["name"] for s in sector_list}

    # 批量获取行情
    quotes = await _fetch_sector_quotes(base_url, symbols)

    # 组装板块表现数据
    results: list[dict[str, Any]] = []
    seen_symbols: set[str] = set()

    for sym in symbols:
        # 去重：同一 symbol 可能出现多次（不同名称）
        if sym in seen_symbols:
            continue
        seen_symbols.add(sym)

        q = quotes.get(sym, {})
        change_rate = q.get("change_rate")

        results.append({
            "name": name_map.get(sym, ""),
            "symbol": sym,
            "change_rate": change_rate,
            "volume": q.get("volume"),
            "price": q.get("price"),
        })

    # 按 change_rate 降序排列（None 排在末尾）
    results.sort(
        key=lambda x: x["change_rate"] if x["change_rate"] is not None else -9999,
        reverse=True,
    )

    # 返回 Top 10
    return results[:10]


async def _fetch_sector_quotes(
    base_url: str,
    symbols: list[str],
) -> dict[str, dict[str, Any]]:
    """
    调用 data-service 批量获取板块 ETF 行情。

    Args:
        base_url: data-service 基础 URL。
        symbols: ETF 代码列表。

    Returns:
        {symbol: quote_dict} 映射。
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
            "data-service sector quotes returned non-ok: %s",
            body.get("message", "unknown"),
        )
        return {}
    except httpx.HTTPStatusError as exc:
        logger.error(
            "data-service sector quotes HTTP error: %s %s",
            exc.response.status_code,
            exc.response.text[:200],
        )
        return {}
    except httpx.RequestError as exc:
        logger.error("data-service sector quotes request error: %s", exc)
        return {}
    except Exception as exc:
        logger.error("Unexpected error in _fetch_sector_quotes: %s", exc)
        return {}
