import pytest
from unittest.mock import patch

from adapters.longbridge import (
    to_longbridge_symbol,
    to_business_symbol,
    LongbridgeAdapter,
)


def test_to_longbridge_symbol_hk():
    """'HK00700' -> '00700.HK'"""
    assert to_longbridge_symbol("HK00700") == "00700.HK"


def test_to_longbridge_symbol_us_defaults_to_us_suffix():
    assert to_longbridge_symbol("NVDA") == "NVDA.US"
    assert to_longbridge_symbol("NVDA.US") == "NVDA.US"


def test_to_business_symbol_hk():
    """'700.HK' -> 'HK00700'"""
    assert to_business_symbol("700.HK") == "HK00700"


def test_to_business_symbol_us_strips_provider_suffix():
    assert to_business_symbol("NVDA.US") == "NVDA"


@pytest.mark.asyncio
async def test_longbridge_unavailable_without_sdk():
    """When _HAS_LONGBRIDGE is False, fetch_quote raises RuntimeError"""
    with patch("adapters.longbridge._HAS_LONGBRIDGE", False), patch.dict("os.environ", {}, clear=True):
        adapter = LongbridgeAdapter()
        assert adapter._available is False
        with pytest.raises(RuntimeError, match="longbridge SDK/token or MCP token not configured"):
            await adapter.fetch_quote("HK00700")


@pytest.mark.asyncio
async def test_longbridge_unavailable_without_env():
    """When env vars missing, _available is False and fetch_quote raises RuntimeError"""
    with patch("adapters.longbridge._HAS_LONGBRIDGE", True):
        with patch.dict("os.environ", {}, clear=True):
            adapter = LongbridgeAdapter()
            assert adapter._available is False
            with pytest.raises(RuntimeError, match="longbridge SDK/token or MCP token not configured"):
                await adapter.fetch_quote("HK00700")


@pytest.mark.asyncio
async def test_longbridge_mcp_token_fetches_us_quote_without_sdk():
    with patch("adapters.longbridge._HAS_LONGBRIDGE", False), patch.dict(
        "os.environ", {"LONGBRIDGE_MCP_ACCESS_TOKEN": "token"}, clear=True
    ):
        adapter = LongbridgeAdapter()
        with patch.object(
            adapter,
            "_call_mcp_quote_sync",
            return_value=[
                {
                    "symbol": "NVDA.US",
                    "last_done": "208.190",
                    "prev_close": "208.640",
                    "timestamp": "2026-06-09T20:00:00Z",
                    "volume": 180962450,
                    "trade_status": "Normal",
                }
            ],
        ):
            quote = await adapter.fetch_quote("NVDA.US")

    assert quote["symbol"] == "NVDA"
    assert quote["market"] == "US"
    assert quote["currency"] == "USD"
    assert quote["price"] == 208.19
    assert quote["source"] == "longbridge_mcp"


@pytest.mark.asyncio
async def test_longbridge_mcp_token_maps_business_us_symbol_to_provider_symbol():
    with patch("adapters.longbridge._HAS_LONGBRIDGE", False), patch.dict(
        "os.environ", {"LONGBRIDGE_MCP_ACCESS_TOKEN": "token"}, clear=True
    ):
        adapter = LongbridgeAdapter()
        with patch.object(
            adapter,
            "_call_mcp_quote_sync",
            return_value=[
                {
                    "symbol": "NVDA.US",
                    "last_done": "208.190",
                    "prev_close": "208.640",
                    "timestamp": "2026-06-09T20:00:00Z",
                }
            ],
        ) as mock_call:
            quote = await adapter.fetch_quote("NVDA")

    mock_call.assert_called_once_with(["NVDA"])
    assert quote["symbol"] == "NVDA"
    assert quote["market"] == "US"
