from __future__ import annotations

from datetime import datetime, timezone

import httpx
import pytest
from fastapi import FastAPI

import routers.portfolio as portfolio_module
from routers.portfolio import router as portfolio_router
from services.portfolio_read_model import (
    PortfolioFreshnessDTO,
    PortfolioOverviewDTO,
    PortfolioPositionsDTO,
    PortfolioReadModelConfigurationError,
    PortfolioSnapshotNotFoundError,
)


class StubPortfolioService:
    def __init__(
        self,
        *,
        overview: PortfolioOverviewDTO | None = None,
        positions: PortfolioPositionsDTO | None = None,
        error: Exception | None = None,
    ) -> None:
        self._overview = overview
        self._positions = positions
        self._error = error

    async def get_overview(self, tenant_id: str) -> PortfolioOverviewDTO:
        if self._error is not None:
            raise self._error
        assert self._overview is not None
        return self._overview

    async def get_positions(self, tenant_id: str) -> PortfolioPositionsDTO:
        if self._error is not None:
            raise self._error
        assert self._positions is not None
        return self._positions


@pytest.fixture
def app():
    _app = FastAPI()
    _app.include_router(portfolio_router, prefix="/api")
    return _app


@pytest.fixture
def client(app):
    transport = httpx.ASGITransport(app=app)
    return httpx.AsyncClient(transport=transport, base_url="http://test")


@pytest.fixture(autouse=True)
def reset_portfolio_service():
    original = portfolio_module._portfolio_read_model_service
    portfolio_module._portfolio_read_model_service = None
    yield
    portfolio_module._portfolio_read_model_service = original


def _freshness() -> PortfolioFreshnessDTO:
    return PortfolioFreshnessDTO(
        snapshot_id="snapshot-1",
        broker_connection_id="broker-1",
        status="succeeded",
        as_of=datetime(2026, 5, 10, 10, 0, 0, tzinfo=timezone.utc),
        received_at=datetime(2026, 5, 10, 10, 1, 0, tzinfo=timezone.utc),
        as_of_age_seconds=120,
        received_age_seconds=60,
        is_partial=False,
    )


@pytest.mark.asyncio
async def test_overview_endpoint_returns_read_model_payload(client):
    portfolio_module._portfolio_read_model_service = StubPortfolioService(
        overview=PortfolioOverviewDTO(
            gross_market_value=19820.0,
            cash=12000.0,
            buying_power=24000.0,
            cash_secured_requirement=17500.0,
            positions_count=2,
            equity_count=1,
            option_count=1,
            markets=["US"],
            currencies=["USD"],
            freshness=_freshness(),
            source_quality="broker_verified",
        ),
        positions=PortfolioPositionsDTO(
            equity_positions=[],
            option_positions=[],
            freshness=_freshness(),
            source_quality="broker_verified",
        ),
    )

    response = await client.get("/api/v3/portfolio/overview", params={"tenant_id": "tenant-1"})

    assert response.status_code == 200
    payload = response.json()
    assert payload["ok"] is True
    assert payload["data"]["gross_market_value"] == 19820.0
    assert payload["data"]["base_currency"] == "USD"
    assert payload["data"]["base_fx_source"] == "fallback_estimate"
    assert payload["data"]["base_total_value"] == 0.0
    assert payload["data"]["cash_balances"] == []
    assert payload["data"]["positions_count"] == 2
    assert payload["data"]["freshness"]["snapshot_id"] == "snapshot-1"
    assert payload["data"]["source_quality"] == "broker_verified"


@pytest.mark.asyncio
async def test_positions_endpoint_returns_equity_and_option_lists(client):
    portfolio_module._portfolio_read_model_service = StubPortfolioService(
        overview=PortfolioOverviewDTO(
            gross_market_value=0.0,
            cash=0.0,
            buying_power=0.0,
            cash_secured_requirement=0.0,
            positions_count=0,
            equity_count=0,
            option_count=0,
            markets=[],
            currencies=[],
            freshness=_freshness(),
            source_quality="broker_verified",
        ),
        positions=PortfolioPositionsDTO(
            equity_positions=[
                {
                    "symbol": "AAPL",
                    "instrument_type": "stock",
                    "market": "US",
                    "exchange": "NASDAQ",
                    "position_side": "long",
                    "quantity": 100.0,
                    "average_cost": 180.0,
                    "cost_basis": 18000.0,
                    "market_price": 195.0,
                    "market_value": 19500.0,
                    "currency": "USD",
                    "source_quality": "broker_verified",
                    "as_of": datetime(2026, 5, 10, 10, 0, 0, tzinfo=timezone.utc),
                }
            ],
            option_positions=[
                {
                    "symbol": "AAPL260619P175",
                    "instrument_type": "option_contract",
                    "market": "US",
                    "exchange": "OPRA",
                    "position_side": "short",
                    "quantity": 1.0,
                    "average_cost": 4.5,
                    "cost_basis": 450.0,
                    "market_price": 3.2,
                    "market_value": -320.0,
                    "currency": "USD",
                    "source_quality": "broker_verified",
                    "as_of": datetime(2026, 5, 10, 10, 0, 0, tzinfo=timezone.utc),
                    "option_type": "put",
                    "strike": 175.0,
                    "expiry": "2026-06-19",
                }
            ],
            freshness=_freshness(),
            source_quality="broker_verified",
        ),
    )

    response = await client.get("/api/v3/portfolio/positions", params={"tenant_id": "tenant-1"})

    assert response.status_code == 200
    payload = response.json()["data"]
    assert len(payload["equity_positions"]) == 1
    assert len(payload["option_positions"]) == 1
    assert payload["equity_positions"][0]["symbol"] == "AAPL"
    assert payload["option_positions"][0]["symbol"] == "AAPL260619P175"
    assert payload["option_positions"][0]["option_type"] == "put"


@pytest.mark.asyncio
async def test_portfolio_endpoints_return_not_found_when_snapshot_missing(client):
    portfolio_module._portfolio_read_model_service = StubPortfolioService(
        error=PortfolioSnapshotNotFoundError("No succeeded or partial broker snapshot found for tenant_id=tenant-1")
    )

    overview = await client.get("/api/v3/portfolio/overview", params={"tenant_id": "tenant-1"})
    positions = await client.get("/api/v3/portfolio/positions", params={"tenant_id": "tenant-1"})

    assert overview.status_code == 404
    assert positions.status_code == 404
    assert "tenant_id=tenant-1" in overview.json()["detail"]["message"]


@pytest.mark.asyncio
async def test_portfolio_endpoints_return_clear_error_when_supabase_env_missing(client, monkeypatch):
    monkeypatch.setattr(
        portfolio_module,
        "create_portfolio_read_model_service_from_env",
        lambda: (_ for _ in ()).throw(
            PortfolioReadModelConfigurationError(
                "SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY are required for portfolio read model queries"
            )
        ),
    )

    response = await client.get("/api/v3/portfolio/overview", params={"tenant_id": "tenant-1"})

    assert response.status_code == 503
    assert response.json()["detail"]["message"].startswith("SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY")
