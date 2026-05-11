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


def test_to_business_symbol_hk():
    """'700.HK' -> 'HK00700'"""
    assert to_business_symbol("700.HK") == "HK00700"


@pytest.mark.asyncio
async def test_longbridge_unavailable_without_sdk():
    """When _HAS_LONGBRIDGE is False, fetch_quote raises RuntimeError"""
    with patch("adapters.longbridge._HAS_LONGBRIDGE", False):
        adapter = LongbridgeAdapter()
        assert adapter._available is False
        with pytest.raises(RuntimeError, match="longbridge SDK not installed"):
            await adapter.fetch_quote("HK00700")


@pytest.mark.asyncio
async def test_longbridge_unavailable_without_env():
    """When env vars missing, _available is False and fetch_quote raises RuntimeError"""
    with patch("adapters.longbridge._HAS_LONGBRIDGE", True):
        with patch.dict("os.environ", {}, clear=True):
            adapter = LongbridgeAdapter()
            assert adapter._available is False
            with pytest.raises(RuntimeError, match="longbridge SDK not installed"):
                await adapter.fetch_quote("HK00700")
