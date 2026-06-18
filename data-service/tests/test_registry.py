import pytest
from datetime import datetime, timezone
from unittest.mock import patch, AsyncMock

from services.registry import DataSourceRegistry, QuoteFreshnessError


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


def test_us_priority_prefers_longbridge_when_mcp_token_is_configured(monkeypatch, registry):
    monkeypatch.setenv("LONGBRIDGE_MCP_ACCESS_TOKEN", "token")

    assert registry._get_priority("NVDA")[:2] == ["longbridge", "yahoo"]


def test_us_priority_keeps_yahoo_first_without_longbridge_env(monkeypatch, registry):
    monkeypatch.delenv("LONGBRIDGE_MCP_ACCESS_TOKEN", raising=False)
    monkeypatch.delenv("LONGBRIDGE_APP_KEY", raising=False)
    monkeypatch.delenv("LONGBRIDGE_APP_SECRET", raising=False)
    monkeypatch.delenv("LONGBRIDGE_ACCESS_TOKEN", raising=False)

    assert registry._get_priority("NVDA")[:2] == ["yahoo", "longbridge"]


def test_akshare_is_not_in_default_fallback_priority(monkeypatch, registry):
    monkeypatch.delenv("AKSHARE_ENABLED", raising=False)

    assert "akshare" not in registry._get_priority("SH600519")
    assert "akshare" not in registry._get_priority("HK00700")
    assert "akshare" not in registry._get_priority("NVDA")


def test_akshare_can_be_enabled_as_optional_fallback(monkeypatch, registry):
    monkeypatch.setenv("AKSHARE_ENABLED", "true")

    assert registry._get_priority("SH600519")[-1] == "akshare"
    assert registry._get_priority("HK00700")[-1] == "akshare"
    assert registry._get_priority("NVDA")[-1] == "akshare"


@pytest.mark.asyncio
async def test_get_quote_respects_explicit_futu_source(registry):
    """source=futu 强制走 Futu quote adapter，并使用独立缓存键。"""
    mock_quote = {"symbol": "AAPL", "price": 191.2, "market": "US", "source": "futu"}

    with patch.object(registry._cache, "get", new_callable=AsyncMock, return_value=None) as mock_cache_get:
        with patch.object(registry._adapters["futu"], "fetch_quote", new_callable=AsyncMock, return_value=mock_quote) as mock_futu:
            with patch.object(registry._adapters["yahoo"], "fetch_quote", new_callable=AsyncMock) as mock_yahoo:
                with patch.object(registry._cache, "set", new_callable=AsyncMock) as mock_cache_set:
                    result = await registry.get_quote("AAPL", prefer="futu")

    assert result["source"] == "futu"
    assert result["source_fallback"] is False
    mock_futu.assert_awaited_once_with("AAPL")
    mock_yahoo.assert_not_awaited()
    mock_cache_get.assert_awaited_once_with("quote:futu:AAPL")
    mock_cache_set.assert_awaited_once()


@pytest.mark.asyncio
async def test_get_quote_recomputes_freshness_and_skips_stale_cache_when_required(registry):
    """require_fresh=true 时不使用已过期缓存，会重新请求首选实时源。"""
    old_quote = {
        "symbol": "AAPL",
        "price": 190.0,
        "market": "US",
        "source": "futu",
        "source_tier": "L1_trading",
        "timestamp": 1,
    }
    live_quote = {
        "symbol": "AAPL",
        "price": 191.2,
        "market": "US",
        "source": "futu",
        "source_tier": "L1_trading",
        "timestamp": int(datetime.now(timezone.utc).timestamp()),
    }

    with patch.object(registry._cache, "get", new_callable=AsyncMock, return_value=old_quote):
        with patch.object(registry._adapters["futu"], "fetch_quote", new_callable=AsyncMock, return_value=live_quote) as mock_futu:
            with patch.object(registry._cache, "set", new_callable=AsyncMock):
                result = await registry.get_quote("AAPL", prefer="futu", require_fresh=True, max_age_seconds=60)

    assert result["price"] == 191.2
    assert result["quote_actionability"] == "trade_draft"
    assert result["freshness_status"] == "fresh"
    assert result["cached"] is False
    mock_futu.assert_awaited_once_with("AAPL")


@pytest.mark.asyncio
async def test_get_quote_require_fresh_rejects_stale_source(registry):
    """实时调用在数据源只返回过期行情时失败，避免下游继续生成交易草稿。"""
    stale_quote = {
        "symbol": "AAPL",
        "price": 190.0,
        "market": "US",
        "source": "futu",
        "source_tier": "L1_trading",
        "timestamp": 1,
    }

    with patch.object(registry._cache, "get", new_callable=AsyncMock, return_value=None):
        with patch.object(registry._adapters["futu"], "fetch_quote", new_callable=AsyncMock, return_value=stale_quote):
            with patch.object(registry._cache, "get_with_stale", new_callable=AsyncMock, return_value=(None, False)):
                with pytest.raises(QuoteFreshnessError):
                    await registry.get_quote("AAPL", prefer="futu", require_fresh=True, max_age_seconds=60)


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
async def test_health_check_returns_status_dict(monkeypatch, registry):
    """health_check 返回各数据源布尔状态；AkShare 默认 optional 且不触发探测。"""
    monkeypatch.delenv("AKSHARE_ENABLED", raising=False)
    with patch.object(registry._adapters["yahoo"], "fetch_quote", new_callable=AsyncMock, return_value={"price": 1}) as mock_yahoo:
        with patch.object(registry._adapters["tushare"], "fetch_quote", new_callable=AsyncMock, side_effect=RuntimeError("fail")) as mock_tushare:
            with patch.object(registry._adapters["akshare"], "fetch_quote", new_callable=AsyncMock, side_effect=RuntimeError("fail")) as mock_akshare:
                with patch.object(registry._adapters["longbridge"], "fetch_quote", new_callable=AsyncMock, side_effect=RuntimeError("fail")) as mock_longbridge:
                    with patch.object(registry._adapters["ftshare"], "fetch_quote", new_callable=AsyncMock, return_value={"price": 1}) as mock_ftshare:
                        with patch.object(registry._adapters["futu"], "fetch_quote", new_callable=AsyncMock, return_value={"price": 1}) as mock_futu:
                            result = await registry.health_check()

    assert isinstance(result, dict)
    assert result["yahoo"] is True
    assert result["futu"] is True
    assert result["tushare"] is False
    assert result["ftshare"] is True
    assert result["akshare"] is False
    assert result["longbridge"] is False
    mock_yahoo.assert_awaited_once_with("AAPL")
    mock_futu.assert_awaited_once_with("AAPL")
    mock_tushare.assert_awaited_once_with("SH600519")
    mock_ftshare.assert_awaited_once_with("SH600519")
    mock_akshare.assert_not_awaited()
    mock_longbridge.assert_awaited_once_with("HK00700")


@pytest.mark.asyncio
async def test_health_check_probes_akshare_when_enabled(monkeypatch, registry):
    monkeypatch.setenv("AKSHARE_ENABLED", "true")
    with patch.object(registry._adapters["yahoo"], "fetch_quote", new_callable=AsyncMock, return_value={"price": 1}):
        with patch.object(registry._adapters["tushare"], "fetch_quote", new_callable=AsyncMock, return_value={"price": 1}):
            with patch.object(registry._adapters["ftshare"], "fetch_quote", new_callable=AsyncMock, return_value={"price": 1}):
                with patch.object(registry._adapters["futu"], "fetch_quote", new_callable=AsyncMock, return_value={"price": 1}):
                    with patch.object(registry._adapters["longbridge"], "fetch_quote", new_callable=AsyncMock, return_value={"price": 1}):
                        with patch.object(registry._adapters["akshare"], "fetch_quote", new_callable=AsyncMock, return_value={"price": 1}) as mock_akshare:
                            result = await registry.health_check()

    assert result["akshare"] is True
    mock_akshare.assert_awaited_once_with("SH600519")
