"""
行情 API 路由

提供单股查询、批量查询、股票搜索、历史缓存读取和数据源健康检测端点，
通过 DataSourceRegistry 实现多数据源自动路由与缓存。
"""

from datetime import date
from typing import Any, Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from routers.data_broker import _historical_store
from services.registry import DataSourceRegistry
from services.symbol_resolver import resolve_symbol, search_symbols as resolver_search

router = APIRouter(tags=["quotes"])

# 全局注册表（自动初始化所有适配器与缓存）
_registry = DataSourceRegistry()


# ---------- Pydantic 模型 ----------

class BatchQuoteRequest(BaseModel):
    symbols: list[str] = Field(..., max_length=100)


class BatchQuoteResponse(BaseModel):
    data: dict[str, dict[str, Any]]
    failed: list[str]


class SearchResponse(BaseModel):
    results: list[dict[str, Any]]


class HealthResponse(BaseModel):
    yahoo: bool
    tushare: bool
    ftshare: bool
    akshare: bool
    longbridge: bool


class ResolveResponse(BaseModel):
    symbol: str
    name_zh: Optional[str] = None
    name_en: Optional[str] = None
    market: str
    exchange: str
    provider_symbols: dict[str, str]


# ---------- 路由 ----------

@router.get("/quote/{symbol}/history")
async def get_quote_history(
    symbol: str,
    market: str = Query(..., description="Market code, e.g. US / HK / CN"),
    interval: str = Query(..., description="Bar interval, e.g. 1d"),
    start_date: date = Query(..., description="Inclusive range start date"),
    end_date: date = Query(..., description="Inclusive range end date"),
    tenant_id: Optional[str] = Query(None, description="Tenant-scoped manifest lookup"),
) -> dict[str, Any]:
    """
    读取已持久化的历史行情缓存。

    P0 只查询本地/对象存储已保存数据：
    - hit: 返回已保存 bars
    - cache_miss: 没有 manifest 或 coverage 不足
    - degraded: manifest 存在但对象缺失或 freshness/status 降级
    """
    try:
        historical = await _historical_store.read_bars(
            tenant_id=tenant_id,
            symbol=symbol,
            market=market,
            bar_interval=interval,
            start_date=start_date,
            end_date=end_date,
        )
        return {"ok": True, "data": historical.model_dump(mode="json")}
    except ValueError as exc:
        raise HTTPException(
            status_code=422,
            detail={"ok": False, "message": f"Invalid historical query: {exc}"},
        )
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail={"ok": False, "message": f"Failed to fetch historical quotes for {symbol}: {exc}"},
        )

@router.get("/quote/{symbol}")
async def get_quote(
    symbol: str,
    source: Optional[str] = Query(None, description="Preferred data source: yahoo / tushare / ftshare / akshare / longbridge"),
) -> dict[str, Any]:
    """
    获取单只股票实时行情。

    Path:
        symbol: 业务层股票代码，如 "AAPL"、"SH600519"、"HK00700"
    Query:
        source: 可选，优先使用的数据源标识

    Returns:
        标准化行情字典
    """
    try:
        quote = await _registry.get_quote(symbol, prefer=source)
        return {"ok": True, "data": quote}
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail={"ok": False, "message": f"Failed to fetch quote for {symbol}: {exc}"},
        )


@router.post("/quote/batch")
async def post_batch_quotes(payload: BatchQuoteRequest) -> dict[str, Any]:
    """
    批量获取股票实时行情。

    Body:
        { "symbols": ["AAPL", "SH600519", "HK00700"] }

    Returns:
        { "ok": true, "data": { ... }, "failed": ["INVALID"] }
    """
    if not payload.symbols:
        raise HTTPException(status_code=400, detail={"ok": False, "message": "symbols list is empty"})

    try:
        results = await _registry.fetch_batch_quotes(payload.symbols)
        failed = [sym for sym in payload.symbols if sym not in results]
        return {"ok": True, "data": results, "failed": failed}
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail={"ok": False, "message": f"Failed to fetch batch quotes: {exc}"},
        )


@router.get("/search")
async def search_symbols(
    q: str = Query(..., min_length=1, description="Search keyword"),
    market: Optional[str] = Query(None, description="Market filter: CN / US / HK"),
) -> dict[str, Any]:
    """
    搜索股票代码。

    优先使用 Yahoo Finance 搜索，若无结果则回退到 symbol_registry 本地搜索。

    Query:
        q:      关键词（股票名称或代码）
        market: 可选市场过滤

    Returns:
        { "ok": true, "results": [ ... ] }
    """
    try:
        results = await _registry.search_symbols(q, market=market)
        if not results:
            registry_results = await resolver_search(q)
            results = [
                {
                    "symbol": r.symbol,
                    "name": r.name_zh or r.name_en or r.symbol,
                    "market": r.market,
                    "exchange": r.exchange,
                    "type": "EQUITY",
                }
                for r in registry_results
            ]
        return {"ok": True, "results": results}
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail={"ok": False, "message": f"Search failed: {exc}"},
        )


@router.get("/resolve/{user_input}")
async def resolve_stock(user_input: str) -> dict[str, Any]:
    """
    解析用户输入为标准化股票代码。

    支持：精确代码（SH600519）、数字代码（600519）、名称（茅台）、拼音等。

    Path:
        user_input: 用户输入，如 "600519"、"贵州茅台"、"AAPL"

    Returns:
        { "ok": true, "data": { symbol, name_zh, market, exchange, provider_symbols } }
    """
    try:
        info = await resolve_symbol(user_input)
        if info is None:
            raise HTTPException(
                status_code=404,
                detail={"ok": False, "message": f"Could not resolve '{user_input}'"},
            )
        return {
            "ok": True,
            "data": {
                "symbol": info.symbol,
                "name_zh": info.name_zh,
                "name_en": info.name_en,
                "market": info.market,
                "exchange": info.exchange,
                "provider_symbols": info.provider_symbols,
            },
        }
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail={"ok": False, "message": f"Resolve failed: {exc}"},
        )


@router.get("/health/sources")
async def get_sources_health() -> dict[str, Any]:
    """
    获取各数据源健康状态。

    Returns:
        { "ok": true, "data": {"yahoo": true, "tushare": false, "akshare": true, "longbridge": false} }
    """
    try:
        health = await _registry.health_check()
        return {"ok": True, "data": health}
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail={"ok": False, "message": f"Health check failed: {exc}"},
        )
