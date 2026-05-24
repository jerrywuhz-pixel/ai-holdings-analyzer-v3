from unittest.mock import AsyncMock, Mock, patch

import pytest

from adapters.stooq import StooqAdapter, to_business_symbol, to_stooq_symbol


def test_stooq_symbol_mapping_supports_us_and_cn():
    assert to_stooq_symbol("AAPL") == "aapl.us"
    assert to_stooq_symbol("SH600519") == "600519.cn"
    assert to_stooq_symbol("SZ000001") == "000001.cn"
    assert to_business_symbol("AAPL.US") == "AAPL"
    assert to_business_symbol("600519.CN") == "SH600519"
    assert to_business_symbol("000001.CN") == "SZ000001"


def test_stooq_symbol_mapping_rejects_hk():
    with pytest.raises(RuntimeError, match="does not support HK"):
        to_stooq_symbol("HK00700")


@pytest.mark.asyncio
async def test_fetch_quote_aapl_parses_csv_response():
    adapter = StooqAdapter()
    csv_text = "\n".join(
        [
            "Symbol,Date,Time,Open,High,Low,Close,Volume",
            "AAPL.US,2026-05-22,22:00:19,306.12,311.4,305.84,308.82,43670223",
        ]
    )

    with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get:
        response = Mock()
        response.text = csv_text
        response.raise_for_status.return_value = None
        mock_get.return_value = response

        result = await adapter.fetch_quote("AAPL")

    assert result["symbol"] == "AAPL"
    assert result["market"] == "US"
    assert result["exchange"] == "US"
    assert result["price"] == 308.82
    assert result["change"] == 2.7
    assert result["change_rate"] == 0.88
    assert result["currency"] == "USD"
    assert result["source"] == "stooq"
    mock_get.assert_awaited_once()


@pytest.mark.asyncio
async def test_fetch_quote_rejects_nd_rows():
    adapter = StooqAdapter()
    csv_text = "\n".join(
        [
            "Symbol,Date,Time,Open,High,Low,Close,Volume",
            "0700.HK,N/D,N/D,N/D,N/D,N/D,N/D,N/D",
        ]
    )

    with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get:
        response = Mock()
        response.text = csv_text
        response.raise_for_status.return_value = None
        mock_get.return_value = response

        with pytest.raises(RuntimeError, match="no quote"):
            await adapter.fetch_quote("AAPL")
