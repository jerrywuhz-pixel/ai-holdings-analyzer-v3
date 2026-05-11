import pytest
from unittest.mock import patch, AsyncMock, Mock

from adapters.tushare import TushareAdapter


@pytest.fixture
def adapter():
    return TushareAdapter(token="fake_token")


@pytest.mark.asyncio
async def test_fetch_quote_sh600519_returns_standardized_dict(adapter):
    """fetch_quote('SH600519') 返回含 price, change, change_rate 的标准化 dict."""
    mock_json = {
        "code": 0,
        "msg": "",
        "data": {
            "fields": [
                "ts_code",
                "trade_date",
                "open",
                "high",
                "low",
                "close",
                "pre_close",
                "change",
                "pct_chg",
            ],
            "items": [
                ["600519.SH", "20240423", 1695.0, 1710.0, 1690.0, 1705.0, 1690.0, 15.0, 0.89]
            ],
        },
    }

    with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
        mock_response = Mock()
        mock_response.json.return_value = mock_json
        mock_response.raise_for_status.return_value = None
        mock_post.return_value = mock_response

        result = await adapter.fetch_quote("SH600519")

        assert isinstance(result, dict)
        assert result["symbol"] == "SH600519"
        assert result["market"] == "CN"
        assert result["exchange"] == "SSE"
        assert result["price"] == 1705.0
        assert result["change"] == 15.0
        assert result["change_rate"] == 0.89
        assert result["currency"] == "CNY"
        assert "timestamp" in result
        mock_post.assert_awaited_once()


@pytest.mark.asyncio
async def test_fetch_quote_missing_token_raises_runtime_error():
    """token 缺失时抛出 RuntimeError。"""
    adapter = TushareAdapter(token=None)
    with pytest.raises(RuntimeError, match="TUSHARE_TOKEN not configured"):
        await adapter.fetch_quote("SH600519")


@pytest.mark.asyncio
async def test_fetch_quote_api_error_raises_runtime_error(adapter):
    """API 返回 code != 0 时抛出 RuntimeError。"""
    mock_json = {
        "code": -2001,
        "msg": "Invalid parameter",
        "data": None,
    }

    with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
        mock_response = Mock()
        mock_response.json.return_value = mock_json
        mock_response.raise_for_status.return_value = None
        mock_post.return_value = mock_response

        with pytest.raises(RuntimeError, match="Tushare API error"):
            await adapter.fetch_quote("SH600519")
