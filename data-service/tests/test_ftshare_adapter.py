import pytest
from unittest.mock import AsyncMock, patch

from adapters.ftshare import FtShareMarketDataAdapter, to_ftshare_symbol


def test_to_ftshare_symbol_converts_business_symbols():
    assert to_ftshare_symbol("SH600519") == "600519.SH"
    assert to_ftshare_symbol("SZ000001") == "000001.SZ"
    assert to_ftshare_symbol("600519.SH") == "600519.SH"


@pytest.mark.asyncio
async def test_fetch_quote_normalizes_stock_security_info_payload():
    adapter = FtShareMarketDataAdapter(skill_dir="/tmp/ftshare-market-data")
    payload = {
        "symbol": "600519.SH",
        "symbol_name": "贵州茅台",
        "close": "1297.64",
        "change": "-13.36",
        "change_rate": -0.0101906941266209,
        "ts_nanos": 1779416363000000000,
        "high": "1311.91",
        "low": "1296.6",
        "open": "1310.95",
        "pe_ttm": 19.6457,
        "pb": 5.9986,
        "market_cap": "1624995921792.6",
    }

    with patch.object(adapter, "_run_skill", new_callable=AsyncMock, return_value=payload) as run_skill:
        result = await adapter.fetch_quote("SH600519")

    run_skill.assert_awaited_once_with("stock-security-info", ["--symbol", "600519.SH"])
    assert result["symbol"] == "SH600519"
    assert result["name"] == "贵州茅台"
    assert result["market"] == "CN"
    assert result["exchange"] == "SSE"
    assert result["price"] == 1297.64
    assert result["change"] == -13.36
    assert result["change_rate"] == -1.02
    assert result["currency"] == "CNY"
    assert result["timestamp"] == 1779416363
    assert result["source"] == "ftshare"
    assert result["fundamentals"]["pe_ttm"] == 19.6457
    assert result["fundamentals"]["pb"] == 5.9986


@pytest.mark.asyncio
async def test_fetch_quote_rejects_non_cn_symbols():
    adapter = FtShareMarketDataAdapter(skill_dir="/tmp/ftshare-market-data")

    with pytest.raises(RuntimeError, match="only supports CN symbols"):
        await adapter.fetch_quote("AAPL")
