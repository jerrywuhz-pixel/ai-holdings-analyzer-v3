import pytest
from unittest.mock import MagicMock

from services.symbol_resolver import (
    resolve_symbol,
    search_symbols,
    SymbolInfo,
    _infer_symbol_info,
)


def test_infer_a_share_sh():
    """input '600519' -> symbol 'SH600519', market 'CN', exchange 'SH'"""
    result = _infer_symbol_info("600519")
    assert result is not None
    assert result.symbol == "SH600519"
    assert result.market == "CN"
    assert result.exchange == "SH"


def test_infer_a_share_sz():
    """input '000858' -> symbol 'SZ000858', market 'CN', exchange 'SZ'"""
    result = _infer_symbol_info("000858")
    assert result is not None
    assert result.symbol == "SZ000858"
    assert result.market == "CN"
    assert result.exchange == "SZ"


def test_infer_hk_stock():
    """input '00700' -> symbol 'HK00700', market 'HK', exchange 'HKEX'"""
    result = _infer_symbol_info("00700")
    assert result is not None
    assert result.symbol == "HK00700"
    assert result.market == "HK"
    assert result.exchange == "HKEX"


def test_infer_us_stock():
    """input 'AAPL' -> symbol 'AAPL', market 'US', exchange 'NASDAQ'"""
    result = _infer_symbol_info("AAPL")
    assert result is not None
    assert result.symbol == "AAPL"
    assert result.market == "US"
    assert result.exchange == "NASDAQ"


def test_infer_invalid():
    """input 'abc123' -> returns None"""
    result = _infer_symbol_info("abc123")
    assert result is None


@pytest.mark.asyncio
async def test_resolve_symbol_exact_match():
    """Mock supabase client returning a row, verify exact match path works."""
    mock_row = {
        "symbol": "SH600519",
        "name_zh": "贵州茅台",
        "name_en": "Kweichow Moutai Co.,Ltd.",
        "market": "CN",
        "exchange": "SH",
        "provider_symbols": {"tushare": "600519.SH", "yahoo": "600519.SS"},
        "aliases": ["茅台", "moutai"],
    }
    mock_table_chain = MagicMock()
    mock_client = MagicMock()
    mock_client.table.return_value = mock_table_chain
    mock_table_chain.select.return_value = mock_table_chain
    mock_table_chain.eq.return_value = mock_table_chain
    mock_table_chain.contains.return_value = mock_table_chain
    mock_table_chain.execute.return_value = MagicMock(data=[mock_row])

    result = await resolve_symbol("SH600519", supabase_client=mock_client)

    assert result is not None
    assert result.symbol == "SH600519"
    assert result.name_zh == "贵州茅台"
    assert result.market == "CN"
    assert result.exchange == "SH"
    mock_table_chain.eq.assert_called_once_with("symbol", "SH600519")


@pytest.mark.asyncio
async def test_resolve_symbol_alias_match():
    """Mock supabase client with alias match."""
    mock_row = {
        "symbol": "SH600519",
        "name_zh": "贵州茅台",
        "name_en": None,
        "market": "CN",
        "exchange": "SH",
        "provider_symbols": {},
        "aliases": ["茅台", "moutai"],
    }
    mock_table_chain = MagicMock()
    mock_client = MagicMock()
    mock_client.table.return_value = mock_table_chain
    mock_table_chain.select.return_value = mock_table_chain
    mock_table_chain.eq.return_value = mock_table_chain
    mock_table_chain.contains.return_value = mock_table_chain
    # First call (exact match) returns empty, second call (alias) returns row
    mock_table_chain.execute.side_effect = [
        MagicMock(data=[]),
        MagicMock(data=[mock_row]),
    ]

    result = await resolve_symbol("茅台", supabase_client=mock_client)

    assert result is not None
    assert result.symbol == "SH600519"
    assert result.name_zh == "贵州茅台"
    mock_table_chain.contains.assert_called_once_with("aliases", ["茅台"])


@pytest.mark.asyncio
async def test_resolve_symbol_fallback_to_inference():
    """Mock supabase client returning empty, verify falls back to rule inference."""
    mock_table_chain = MagicMock()
    mock_client = MagicMock()
    mock_client.table.return_value = mock_table_chain
    mock_table_chain.select.return_value = mock_table_chain
    mock_table_chain.eq.return_value = mock_table_chain
    mock_table_chain.contains.return_value = mock_table_chain
    mock_table_chain.execute.return_value = MagicMock(data=[])

    result = await resolve_symbol("600519", supabase_client=mock_client)

    assert result is not None
    assert result.symbol == "SH600519"
    assert result.market == "CN"
    assert result.exchange == "SH"


@pytest.mark.asyncio
async def test_search_symbols_empty_keyword():
    """Empty keyword returns empty list."""
    result = await search_symbols("")
    assert result == []

    result = await search_symbols("   ")
    assert result == []
