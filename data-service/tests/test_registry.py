import pytest
from unittest.mock import patch, AsyncMock

from services.registry import DataSourceRegistry


@pytest.fixture
def registry():
    return DataSourceRegistry()


@pytest.mark.asyncio
async def test_get_quote_selects_tushare_for_sh_prefix(registry):
    """SH 前缀 symbol 自动路由到 TushareAdapter。"""
    mock_quote = {"symbol": "SH600519", "price": 1705.0, "market": "CN"}

    with patch.object(registry._cache, "get", new_callable=AsyncMock, return_value=None):
        with patch.object(registry._adapters["tushare"], "fetch_quote", new_callable=AsyncMock, return_value=mock_quote):
            with patch.object(registry._cache, "set", new_callable=AsyncMock) as mock_cache_set:
                result = await registry.get_quote("SH600519")

    assert result["symbol"] == "SH600519"
    assert result["price"] == 1705.0
    assert result["source_fallback"] is False
    assert result["cached"] is False
    assert result["stale"] is False
    mock_cache_set.assert_awaited_once()


@pytest.mark.asyncio
async def test_get_quote_falls_back_to_ftshare_for_cn_symbol(registry):
    """Tushare 失败后，CN symbol 回退到 ClawHub ftshare-market-data 数据源。"""
    mock_quote = {"symbol": "SH600519", "price": 1297.64, "market": "CN"}

    with patch.object(registry._cache, "get", new_callable=AsyncMock, return_value=None):
        with patch.object(registry._adapters["tushare"], "fetch_quote", new_callable=AsyncMock, side_effect=RuntimeError("fail")):
            with patch.object(registry._adapters["ftshare"], "fetch_quote", new_callable=AsyncMock, return_value=mock_quote) as mock_ftshare:
                with patch.object(registry._cache, "set", new_callable=AsyncMock) as mock_cache_set:
                    result = await registry.get_quote("SH600519")

    assert result["symbol"] == "SH600519"
    assert result["price"] == 1297.64
    assert result["source_fallback"] is True
    assert result["cached"] is False
    assert result["stale"] is False
    mock_ftshare.assert_awaited_once_with("SH600519")
    mock_cache_set.assert_awaited_once()


@pytest.mark.asyncio
async def test_get_quote_selects_tushare_for_sz_prefix(registry):
    """SZ 前缀 symbol 自动路由到 TushareAdapter。"""
    mock_quote = {"symbol": "SZ000001", "price": 10.5, "market": "CN"}

    with patch.object(registry._cache, "get", new_callable=AsyncMock, return_value=None):
        with patch.object(registry._adapters["tushare"], "fetch_quote", new_callable=AsyncMock, return_value=mock_quote):
            with patch.object(registry._cache, "set", new_callable=AsyncMock) as mock_cache_set:
                result = await registry.get_quote("SZ000001")

    assert result["symbol"] == "SZ000001"
    assert result["price"] == 10.5
    assert result["source_fallback"] is False
    assert result["cached"] is False
    assert result["stale"] is False
    mock_cache_set.assert_awaited_once()


@pytest.mark.asyncio
async def test_get_quote_selects_yahoo_for_us_symbol(registry):
    """美股 symbol 自动路由到 YahooFinanceAdapter。"""
    mock_quote = {"symbol": "AAPL", "price": 191.24, "market": "US"}

    with patch.object(registry._cache, "get", new_callable=AsyncMock, return_value=None):
        with patch.object(registry._adapters["yahoo"], "fetch_quote", new_callable=AsyncMock, return_value=mock_quote):
            with patch.object(registry._cache, "set", new_callable=AsyncMock) as mock_cache_set:
                result = await registry.get_quote("AAPL")

    assert result["symbol"] == "AAPL"
    assert result["price"] == 191.24
    assert result["source_fallback"] is False
    assert result["cached"] is False
    assert result["stale"] is False
    mock_cache_set.assert_awaited_once()


@pytest.mark.asyncio
async def test_get_quote_cache_hit_returns_directly(registry):
    """缓存命中时直接返回缓存值（带 enriched metadata），不请求数据源，也不写入缓存。"""
    mock_quote = {"symbol": "AAPL", "price": 191.24}

    with patch.object(registry._cache, "get", new_callable=AsyncMock, return_value=mock_quote):
        with patch.object(registry._adapters["yahoo"], "fetch_quote", new_callable=AsyncMock) as mock_yahoo:
            with patch.object(registry._cache, "set", new_callable=AsyncMock) as mock_cache_set:
                result = await registry.get_quote("AAPL")

    assert result["symbol"] == "AAPL"
    assert result["price"] == 191.24
    assert result["cached"] is True
    assert result["stale"] is False
    mock_yahoo.assert_not_awaited()
    mock_cache_set.assert_not_awaited()


@pytest.mark.asyncio
async def test_get_quote_cache_miss_fetches_and_writes_cache(registry):
    """缓存未命中时请求数据源并回写缓存。"""
    mock_quote = {"symbol": "SH600519", "price": 1705.0}

    with patch.object(registry._cache, "get", new_callable=AsyncMock, return_value=None):
        with patch.object(registry._adapters["tushare"], "fetch_quote", new_callable=AsyncMock, return_value=mock_quote):
            with patch.object(registry._cache, "set", new_callable=AsyncMock) as mock_cache_set:
                result = await registry.get_quote("SH600519")

    assert result["symbol"] == "SH600519"
    assert result["price"] == 1705.0
    assert result["source_fallback"] is False
    assert result["cached"] is False
    assert result["stale"] is False
    mock_cache_set.assert_awaited_once()


@pytest.mark.asyncio
async def test_health_check_returns_status_dict(registry):
    """health_check 返回各数据源布尔状态（含 ftshare / longbridge）。"""
    with patch.object(registry._adapters["yahoo"], "fetch_quote", new_callable=AsyncMock, return_value={"price": 1}) as mock_yahoo:
        with patch.object(registry._adapters["tushare"], "fetch_quote", new_callable=AsyncMock, side_effect=RuntimeError("fail")) as mock_tushare:
            with patch.object(registry._adapters["akshare"], "fetch_quote", new_callable=AsyncMock, side_effect=RuntimeError("fail")) as mock_akshare:
                with patch.object(registry._adapters["longbridge"], "fetch_quote", new_callable=AsyncMock, side_effect=RuntimeError("fail")) as mock_longbridge:
                    with patch.object(registry._adapters["ftshare"], "fetch_quote", new_callable=AsyncMock, return_value={"price": 1}) as mock_ftshare:
                        result = await registry.health_check()

    assert isinstance(result, dict)
    assert result["yahoo"] is True
    assert result["tushare"] is False
    assert result["ftshare"] is True
    assert result["akshare"] is False
    assert result["longbridge"] is False
    mock_yahoo.assert_awaited_once_with("AAPL")
    mock_tushare.assert_awaited_once_with("SH600519")
    mock_ftshare.assert_awaited_once_with("SH600519")
    mock_akshare.assert_awaited_once_with("SH600519")
    mock_longbridge.assert_awaited_once_with("HK00700")
