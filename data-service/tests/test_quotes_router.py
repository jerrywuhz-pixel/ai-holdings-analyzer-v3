from datetime import date, datetime, timezone
from fastapi.testclient import TestClient
from unittest.mock import patch, AsyncMock
from main import app
from services.historical_store import HistoricalManifestRecord, HistoricalQueryResponse, HistoricalRange
from services.symbol_resolver import SymbolInfo

client = TestClient(app)


def test_get_quote_success():
    mock_quote = {
        "symbol": "AAPL",
        "name": "Apple Inc.",
        "market": "US",
        "exchange": "NASDAQ",
        "price": 191.24,
        "change": 1.4,
        "change_rate": 0.74,
        "currency": "USD",
        "timestamp": 1713806400,
    }

    with patch(
        "routers.quotes._registry.get_quote", new_callable=AsyncMock, return_value=mock_quote
    ):
        response = client.get("/api/quote/AAPL")

    assert response.status_code == 200
    data = response.json()
    assert data["ok"] is True
    assert data["data"]["symbol"] == "AAPL"
    assert data["data"]["price"] == 191.24


def test_get_quote_history_returns_cached_bars():
    manifest = HistoricalManifestRecord(
        id="manifest-1",
        tenant_id="tenant-1",
        universe_id=None,
        job_id="job-1",
        source="futu_openapi",
        source_key="futu_openapi",
        market="US",
        symbol="AAPL",
        instrument_type="stock",
        data_kind="bar_1d",
        bar_interval="1d",
        interval="1d",
        adjustment="raw",
        range=HistoricalRange(start=date(2026, 5, 1), end=date(2026, 5, 9)),
        coverage_start=date(2026, 5, 1),
        coverage_end=date(2026, 5, 9),
        storage_backend="memory",
        storage_uri="memory://market-data/curated/tenant=tenant-1/source=futu_openapi/market=US/symbol=AAPL/bar_interval=1d/range=2026-05-01_2026-05-09.parquet",
        schema_version="v3_p0",
        freshness="fresh",
        status="ready",
        quality_status="validated",
        quality_report={},
        row_count=2,
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )
    query_result = HistoricalQueryResponse(
        found=True,
        cache_status="hit",
        manifest=manifest,
        bars=[
            {"date": "2026-05-01", "close": 101.0},
            {"date": "2026-05-02", "close": 102.0},
        ],
    )

    with patch(
        "routers.quotes._historical_store.read_bars",
        new_callable=AsyncMock,
        return_value=query_result,
    ):
        response = client.get(
            "/api/quote/AAPL/history",
            params={
                "tenant_id": "tenant-1",
                "market": "US",
                "interval": "1d",
                "start_date": "2026-05-01",
                "end_date": "2026-05-02",
            },
        )

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["found"] is True
    assert data["cache_status"] == "hit"
    assert len(data["bars"]) == 2
    assert data["manifest"]["storage_uri"].startswith("memory://")


def test_get_quote_history_returns_cache_miss_explicitly():
    query_result = HistoricalQueryResponse(
        found=False,
        cache_status="cache_miss",
        reason="manifest_not_found",
    )

    with patch(
        "routers.quotes._historical_store.read_bars",
        new_callable=AsyncMock,
        return_value=query_result,
    ):
        response = client.get(
            "/api/quote/NVDA/history",
            params={
                "market": "US",
                "interval": "1d",
                "start_date": "2026-05-01",
                "end_date": "2026-05-09",
            },
        )

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["found"] is False
    assert data["cache_status"] == "cache_miss"
    assert data["reason"] == "manifest_not_found"
    assert data["bars"] == []


def test_get_quote_error():
    with patch(
        "routers.quotes._registry.get_quote",
        new_callable=AsyncMock,
        side_effect=RuntimeError("Yahoo API error"),
    ):
        response = client.get("/api/quote/INVALID")

    assert response.status_code == 500
    data = response.json()
    assert data["detail"]["ok"] is False
    assert "Failed to fetch quote" in data["detail"]["message"]


def test_post_batch_quotes_success():
    mock_results = {
        "AAPL": {"symbol": "AAPL", "price": 191.24},
        "MSFT": {"symbol": "MSFT", "price": 418.97},
    }

    with patch(
        "routers.quotes._registry.fetch_batch_quotes",
        new_callable=AsyncMock,
        return_value=mock_results,
    ):
        response = client.post("/api/quote/batch", json={"symbols": ["AAPL", "MSFT", "INVALID"]})

    assert response.status_code == 200
    data = response.json()
    assert data["ok"] is True
    assert "AAPL" in data["data"]
    assert "MSFT" in data["data"]
    assert "INVALID" in data["failed"]


def test_post_batch_quotes_empty():
    response = client.post("/api/quote/batch", json={"symbols": []})
    assert response.status_code == 400
    data = response.json()
    assert data["detail"]["ok"] is False
    assert "empty" in data["detail"]["message"].lower()


def test_search_success():
    mock_results = [
        {"symbol": "AAPL", "name": "Apple Inc.", "market": "US", "exchange": "NASDAQ"},
    ]

    with patch(
        "routers.quotes._registry.search_symbols",
        new_callable=AsyncMock,
        return_value=mock_results,
    ):
        response = client.get("/api/search?q=apple&market=US")

    assert response.status_code == 200
    data = response.json()
    assert data["ok"] is True
    assert len(data["results"]) == 1
    assert data["results"][0]["symbol"] == "AAPL"


def test_search_error():
    with patch(
        "routers.quotes._registry.search_symbols",
        new_callable=AsyncMock,
        side_effect=RuntimeError("search failed"),
    ):
        response = client.get("/api/search?q=test")

    assert response.status_code == 500
    data = response.json()
    assert data["detail"]["ok"] is False


def test_resolve_endpoint_success():
    """Mock services.symbol_resolver.resolve_symbol returning a SymbolInfo, verify 200 response."""
    mock_info = SymbolInfo(
        symbol="SH600519",
        name_zh="贵州茅台",
        name_en="Kweichow Moutai Co.,Ltd.",
        market="CN",
        exchange="SH",
        provider_symbols={"tushare": "600519.SH", "yahoo": "600519.SS"},
        aliases=["茅台"],
    )

    with patch(
        "routers.quotes.resolve_symbol", new_callable=AsyncMock, return_value=mock_info
    ):
        response = client.get("/api/resolve/600519")

    assert response.status_code == 200
    data = response.json()
    assert data["ok"] is True
    assert data["data"]["symbol"] == "SH600519"
    assert data["data"]["name_zh"] == "贵州茅台"
    assert data["data"]["name_en"] == "Kweichow Moutai Co.,Ltd."
    assert data["data"]["market"] == "CN"
    assert data["data"]["exchange"] == "SH"
    assert data["data"]["provider_symbols"] == {"tushare": "600519.SH", "yahoo": "600519.SS"}


def test_resolve_endpoint_not_found():
    """Mock returning None, verify 404 response."""
    with patch(
        "routers.quotes.resolve_symbol", new_callable=AsyncMock, return_value=None
    ):
        response = client.get("/api/resolve/invalid123")

    assert response.status_code == 404
    data = response.json()
    assert data["detail"]["ok"] is False
    assert "Could not resolve" in data["detail"]["message"]


def test_search_fallback_to_registry():
    """Mock _registry.search_symbols returning empty, mock resolver_search returning results."""
    mock_registry_results = []
    mock_resolver_results = [
        SymbolInfo(
            symbol="SH600519",
            name_zh="贵州茅台",
            market="CN",
            exchange="SH",
            provider_symbols={},
            aliases=["茅台"],
        ),
    ]

    with patch(
        "routers.quotes._registry.search_symbols",
        new_callable=AsyncMock,
        return_value=mock_registry_results,
    ):
        with patch(
            "routers.quotes.resolver_search",
            new_callable=AsyncMock,
            return_value=mock_resolver_results,
        ):
            response = client.get("/api/search?q=茅台")

    assert response.status_code == 200
    data = response.json()
    assert data["ok"] is True
    assert len(data["results"]) == 1
    assert data["results"][0]["symbol"] == "SH600519"
    assert data["results"][0]["name"] == "贵州茅台"
    assert data["results"][0]["market"] == "CN"
    assert data["results"][0]["exchange"] == "SH"
    assert data["results"][0]["type"] == "EQUITY"


def test_search_fallback_to_exact_resolver_when_provider_search_is_empty():
    """Yahoo search can be rate-limited; exact symbol search should still return resolver output."""
    mock_info = SymbolInfo(
        symbol="AAPL",
        name_en="Apple Inc.",
        market="US",
        exchange="NASDAQ",
        provider_symbols={"yahoo": "AAPL"},
        aliases=[],
    )

    with patch(
        "routers.quotes._registry.search_symbols",
        new_callable=AsyncMock,
        return_value=[],
    ):
        with patch("routers.quotes.resolver_search", new_callable=AsyncMock, return_value=[]):
            with patch("routers.quotes.resolve_symbol", new_callable=AsyncMock, return_value=mock_info):
                response = client.get("/api/search?q=AAPL&market=US")

    assert response.status_code == 200
    data = response.json()
    assert data["ok"] is True
    assert len(data["results"]) == 1
    assert data["results"][0]["symbol"] == "AAPL"
    assert data["results"][0]["name"] == "Apple Inc."
    assert data["results"][0]["market"] == "US"
    assert data["results"][0]["exchange"] == "NASDAQ"
    assert data["results"][0]["type"] == "EQUITY"
