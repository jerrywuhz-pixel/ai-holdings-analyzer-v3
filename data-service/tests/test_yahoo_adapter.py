import pytest
from unittest.mock import patch, AsyncMock, Mock

from adapters.yahoo import YahooFinanceAdapter


@pytest.fixture
def adapter():
    return YahooFinanceAdapter()


@pytest.mark.asyncio
async def test_fetch_quote_aapl_returns_standardized_dict(adapter):
    """fetch_quote('AAPL') 返回含 price, change, change_rate 的标准化 dict."""
    mock_json = {
        "chart": {
            "result": [
                {
                    "meta": {
                        "shortName": "Apple Inc.",
                        "regularMarketPrice": 185.92,
                        "previousClose": 184.37,
                        "currency": "USD",
                        "exchangeName": "NMS",
                        "fullExchangeName": "NasdaqGS",
                        "regularMarketTime": 1713806404,
                    }
                }
            ],
            "error": None,
        }
    }

    with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get:
        mock_response = Mock()
        mock_response.json.return_value = mock_json
        mock_response.raise_for_status.return_value = None
        mock_get.return_value = mock_response

        result = await adapter.fetch_quote("AAPL")

        assert isinstance(result, dict)
        assert result["symbol"] == "AAPL"
        assert result["name"] == "Apple Inc."
        assert result["price"] == 185.92
        assert result["change"] == 1.55
        assert result["change_rate"] == 0.84
        assert result["currency"] == "USD"
        assert "timestamp" in result
        mock_get.assert_awaited_once()


@pytest.mark.asyncio
async def test_fetch_batch_quotes_aapl_msft_returns_two_results(adapter):
    """fetch_batch_quotes(['AAPL', 'MSFT']) 返回两个结果."""
    aapl_json = {
        "chart": {
            "result": [
                {
                    "meta": {
                        "shortName": "Apple Inc.",
                        "regularMarketPrice": 185.92,
                        "previousClose": 184.37,
                        "currency": "USD",
                        "exchangeName": "NMS",
                        "fullExchangeName": "NasdaqGS",
                        "regularMarketTime": 1713806404,
                    }
                }
            ],
            "error": None,
        }
    }
    msft_json = {
        "chart": {
            "result": [
                {
                    "meta": {
                        "shortName": "Microsoft Corporation",
                        "regularMarketPrice": 420.55,
                        "previousClose": 415.50,
                        "currency": "USD",
                        "exchangeName": "NMS",
                        "fullExchangeName": "NasdaqGS",
                        "regularMarketTime": 1713806405,
                    }
                }
            ],
            "error": None,
        }
    }

    with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get:
        def _side_effect(*args, **kwargs):
            url = args[0] if args else ""
            resp = Mock()
            if "AAPL" in url:
                resp.json.return_value = aapl_json
            elif "MSFT" in url:
                resp.json.return_value = msft_json
            else:
                raise ValueError(f"Unexpected URL: {url}")
            resp.raise_for_status.return_value = None
            return resp

        mock_get.side_effect = _side_effect

        results = await adapter.fetch_batch_quotes(["AAPL", "MSFT"])

        assert isinstance(results, dict)
        assert set(results.keys()) == {"AAPL", "MSFT"}
        assert results["AAPL"]["symbol"] == "AAPL"
        assert results["AAPL"]["price"] == 185.92
        assert results["MSFT"]["symbol"] == "MSFT"
        assert results["MSFT"]["price"] == 420.55
        assert mock_get.await_count == 2
