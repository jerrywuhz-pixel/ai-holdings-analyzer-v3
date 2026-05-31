from __future__ import annotations

from datetime import datetime, timezone

import pytest

from services.fx import EnvTrustedFxRateProvider, HttpFxRateProvider
from services.portfolio_read_model import (
    BrokerSnapshotBundle,
    PortfolioReadModelConfigurationError,
    PortfolioReadModelService,
    PortfolioSnapshotNotFoundError,
    PostgresPortfolioSnapshotRepository,
    create_portfolio_read_model_service_from_env,
    _select_best_snapshot,
    _to_datetime,
)


class FakePortfolioSnapshotRepository:
    def __init__(self, bundle: BrokerSnapshotBundle | None) -> None:
        self._bundle = bundle

    async def get_latest_snapshot_bundle(self, tenant_id: str) -> BrokerSnapshotBundle | None:
        return self._bundle


def _sample_snapshot(
    *,
    status: str = "succeeded",
    source_quality: str = "broker_verified",
    missing_fields: list[str] | None = None,
    partial_components: list[str] | None = None,
) -> dict:
    return {
        "id": "snapshot-1",
        "tenant_id": "tenant-1",
        "broker_connection_id": "broker-1",
        "status": status,
        "as_of": "2026-05-10T10:00:00+00:00",
        "received_at": "2026-05-10T10:01:00+00:00",
        "source_quality": source_quality,
        "missing_fields": missing_fields or [],
        "partial_components": partial_components or [],
    }


def test_read_model_prefers_broker_verified_snapshot_over_newer_mock_snapshot():
    selected = _select_best_snapshot(
        [
            {
                "id": "newer-mock",
                "status": "succeeded",
                "source_quality": "estimated",
                "as_of": "2026-05-10T10:10:00+00:00",
                "received_at": "2026-05-10T10:10:00+00:00",
            },
            {
                "id": "older-real",
                "status": "succeeded",
                "source_quality": "broker_verified",
                "as_of": "2026-05-10T10:00:00+00:00",
                "received_at": "2026-05-10T10:00:00+00:00",
            },
        ]
    )

    assert selected["id"] == "older-real"


def test_read_model_accepts_supabase_fractional_timestamp_widths():
    parsed = _to_datetime("2026-05-10T10:17:29.32119+00:00")

    assert parsed == datetime(2026, 5, 10, 10, 17, 29, 321190, tzinfo=timezone.utc)


@pytest.mark.asyncio
async def test_read_model_splits_equity_and_option_positions():
    bundle = BrokerSnapshotBundle(
        snapshot=_sample_snapshot(),
        positions=[
            {
                "provider_symbol": "AAPL",
                "instrument_type": "stock",
                "market": "US",
                "exchange": "NASDAQ",
                "position_side": "long",
                "quantity": 100,
                "average_cost": 180.0,
                "cost_basis": 18000.0,
                "market_price": 195.0,
                "market_value": 19500.0,
                "currency": "USD",
                "source_quality": "broker_verified",
                "position_payload": {"name": "Apple"},
                "as_of": "2026-05-10T10:00:00+00:00",
            },
            {
                "provider_symbol": "AAPL260619P175",
                "instrument_type": "option_contract",
                "market": "US",
                "exchange": "OPRA",
                "position_side": "short",
                "quantity": 1,
                "average_cost": 4.5,
                "cost_basis": 450.0,
                "market_price": 3.2,
                "market_value": -320.0,
                "currency": "USD",
                "source_quality": "broker_verified",
                "position_payload": {
                    "option_type": "put",
                    "strike": 175.0,
                    "expiry": "2026-06-19",
                },
                "as_of": "2026-05-10T10:00:00+00:00",
            },
        ],
        cash_balances=[
            {
                "currency": "USD",
                "total_cash": 12000.0,
                "available_cash": 12000.0,
                "buying_power": 24000.0,
                "source_quality": "broker_verified",
                "as_of": "2026-05-10T10:00:00+00:00",
            }
        ],
        margin_balances=[
            {
                "currency": "USD",
                "margin_available": 24000.0,
                "option_buying_power": 24000.0,
                "cash_secured_requirement": 17500.0,
                "source_quality": "broker_verified",
                "as_of": "2026-05-10T10:00:00+00:00",
            }
        ],
    )
    service = PortfolioReadModelService(
        repository=FakePortfolioSnapshotRepository(bundle),
        now_provider=lambda: datetime(2026, 5, 10, 10, 6, 0, tzinfo=timezone.utc),
    )

    overview = await service.get_overview("tenant-1")
    positions = await service.get_positions("tenant-1")

    assert overview.positions_count == 2
    assert overview.equity_count == 1
    assert overview.option_count == 1
    assert overview.gross_market_value == 19820.0
    assert overview.cash == 12000.0
    assert overview.buying_power == 24000.0
    assert overview.cash_secured_requirement == 17500.0
    assert overview.base_currency == "USD"
    assert overview.base_fx_source == "fallback_estimate"
    assert overview.base_total_value == 31180.0
    assert overview.base_gross_market_value == 19820.0
    assert overview.base_cash == 12000.0
    assert overview.base_buying_power == 24000.0
    assert overview.base_cash_secured_requirement == 17500.0
    assert overview.markets == ["US"]
    assert overview.currencies == ["USD"]
    assert len(overview.cash_balances) == 1
    assert overview.cash_balances[0].currency == "USD"
    assert overview.cash_balances[0].fx_rate == 1.0
    assert overview.cash_balances[0].fx_source == "fallback_estimate"
    assert overview.cash_balances[0].base_available_cash == 12000.0
    assert positions.equity_positions[0].symbol == "AAPL"
    assert positions.equity_positions[0].name == "Apple"
    assert positions.equity_positions[0].market_value == 19500.0
    assert positions.equity_positions[0].base_market_value == 19500.0
    assert positions.equity_positions[0].base_currency == "USD"
    assert positions.equity_positions[0].fx_rate == 1.0
    assert positions.equity_positions[0].fx_source == "fallback_estimate"
    assert positions.option_positions[0].symbol == "AAPL260619P175"
    assert positions.option_positions[0].base_market_value == -320.0
    assert positions.option_positions[0].option_type == "put"
    assert positions.option_positions[0].strike == 175.0
    assert positions.option_positions[0].expiry == "2026-06-19"


@pytest.mark.asyncio
async def test_read_model_converts_mixed_currency_overview_and_positions_to_base_currency():
    bundle = BrokerSnapshotBundle(
        snapshot=_sample_snapshot(),
        positions=[
            {
                "provider_symbol": "AAPL",
                "instrument_type": "stock",
                "market": "US",
                "exchange": "NASDAQ",
                "position_side": "long",
                "quantity": 5,
                "average_cost": 180.0,
                "cost_basis": 900.0,
                "market_price": 200.0,
                "market_value": 1000.0,
                "currency": "USD",
                "source_quality": "broker_verified",
                "position_payload": {},
                "as_of": "2026-05-10T10:00:00+00:00",
            },
            {
                "provider_symbol": "00700",
                "instrument_type": "stock",
                "market": "HK",
                "exchange": "HKEX",
                "position_side": "long",
                "quantity": 25,
                "average_cost": 380.0,
                "cost_basis": 9500.0,
                "market_price": 400.0,
                "market_value": 10000.0,
                "currency": "HKD",
                "source_quality": "broker_verified",
                "position_payload": {"stock_name": "腾讯控股"},
                "as_of": "2026-05-10T10:00:00+00:00",
            },
        ],
        cash_balances=[
            {
                "currency": "USD",
                "total_cash": 500.0,
                "available_cash": 500.0,
                "buying_power": 1000.0,
                "source_quality": "broker_verified",
                "as_of": "2026-05-10T10:00:00+00:00",
            },
            {
                "currency": "HKD",
                "total_cash": 20000.0,
                "available_cash": 20000.0,
                "buying_power": 30000.0,
                "source_quality": "broker_verified",
                "as_of": "2026-05-10T10:00:00+00:00",
            },
        ],
        margin_balances=[
            {
                "currency": "HKD",
                "margin_available": 30000.0,
                "option_buying_power": 30000.0,
                "cash_secured_requirement": 4000.0,
                "source_quality": "broker_verified",
                "as_of": "2026-05-10T10:00:00+00:00",
            }
        ],
    )
    service = PortfolioReadModelService(repository=FakePortfolioSnapshotRepository(bundle))

    overview = await service.get_overview("tenant-1")
    positions = await service.get_positions("tenant-1")

    assert overview.base_currency == "USD"
    assert overview.base_fx_source == "fallback_estimate"
    assert overview.cash == 3060.0
    assert overview.base_cash == 3060.0
    assert overview.gross_market_value == 2280.0
    assert overview.base_gross_market_value == 2280.0
    assert overview.buying_power == 4840.0
    assert overview.base_buying_power == 4840.0
    assert overview.cash_secured_requirement == 512.0
    assert overview.base_cash_secured_requirement == 512.0
    assert overview.base_total_value == 5340.0
    assert overview.cash != 20500.0
    assert overview.gross_market_value != 11000.0
    assert overview.currencies == ["HKD", "USD"]
    assert [balance.currency for balance in overview.cash_balances] == ["USD", "HKD"]
    assert overview.cash_balances[1].fx_rate == 0.128
    assert overview.cash_balances[1].fx_source == "fallback_estimate"
    assert overview.cash_balances[1].base_available_cash == 2560.0

    assert positions.equity_positions[0].symbol == "00700"
    assert positions.equity_positions[0].name == "腾讯控股"
    assert positions.equity_positions[0].market_value == 10000.0
    assert positions.equity_positions[0].base_market_value == 1280.0
    assert positions.equity_positions[0].base_currency == "USD"
    assert positions.equity_positions[0].fx_rate == 0.128
    assert positions.equity_positions[0].fx_source == "fallback_estimate"
    assert positions.equity_positions[1].symbol == "AAPL"
    assert positions.equity_positions[1].base_market_value == 1000.0


@pytest.mark.asyncio
async def test_read_model_uses_trusted_fx_provider_when_configured():
    bundle = BrokerSnapshotBundle(
        snapshot=_sample_snapshot(),
        positions=[
            {
                "provider_symbol": "00700",
                "instrument_type": "stock",
                "market": "HK",
                "exchange": "HKEX",
                "position_side": "long",
                "quantity": 25,
                "market_price": 400.0,
                "market_value": 10000.0,
                "currency": "HKD",
                "source_quality": "broker_verified",
                "position_payload": {"stock_name": "腾讯控股"},
                "as_of": "2026-05-10T10:00:00+00:00",
            },
        ],
        cash_balances=[
            {
                "currency": "HKD",
                "total_cash": 20000.0,
                "available_cash": 20000.0,
                "buying_power": 30000.0,
                "source_quality": "broker_verified",
                "as_of": "2026-05-10T10:00:00+00:00",
            },
        ],
        margin_balances=[],
    )
    service = PortfolioReadModelService(
        repository=FakePortfolioSnapshotRepository(bundle),
        fx_rate_provider=EnvTrustedFxRateProvider('{"HKD:USD": 0.13}', source="trusted_fx_fixture"),
    )

    overview = await service.get_overview("tenant-1")
    positions = await service.get_positions("tenant-1")

    assert overview.base_fx_source == "trusted_fx_fixture"
    assert overview.cash == 2600.0
    assert overview.gross_market_value == 1300.0
    assert overview.cash_balances[0].fx_source == "trusted_fx_fixture"
    assert overview.cash_balances[0].fx_rate == 0.13
    assert positions.equity_positions[0].fx_source == "trusted_fx_fixture"
    assert positions.equity_positions[0].base_market_value == 1300.0


@pytest.mark.asyncio
async def test_read_model_supports_cash_only_snapshot():
    bundle = BrokerSnapshotBundle(
        snapshot=_sample_snapshot(),
        positions=[],
        cash_balances=[
            {
                "currency": "USD",
                "total_cash": 8000.0,
                "available_cash": 7500.0,
                "buying_power": 16000.0,
                "source_quality": "broker_verified",
                "as_of": "2026-05-10T10:00:00+00:00",
            }
        ],
        margin_balances=[
            {
                "currency": "USD",
                "margin_available": 16000.0,
                "option_buying_power": 16000.0,
                "cash_secured_requirement": 0.0,
                "source_quality": "broker_verified",
                "as_of": "2026-05-10T10:00:00+00:00",
            }
        ],
    )
    service = PortfolioReadModelService(repository=FakePortfolioSnapshotRepository(bundle))

    overview = await service.get_overview("tenant-1")
    positions = await service.get_positions("tenant-1")

    assert overview.positions_count == 0
    assert overview.equity_count == 0
    assert overview.option_count == 0
    assert overview.cash == 7500.0
    assert overview.buying_power == 16000.0
    assert overview.base_currency == "USD"
    assert overview.base_cash == 7500.0
    assert overview.base_buying_power == 16000.0
    assert overview.currencies == ["USD"]
    assert overview.cash_balances[0].base_available_cash == 7500.0
    assert positions.equity_positions == []
    assert positions.option_positions == []


@pytest.mark.asyncio
async def test_read_model_raises_when_no_snapshot_exists():
    service = PortfolioReadModelService(repository=FakePortfolioSnapshotRepository(None))

    with pytest.raises(PortfolioSnapshotNotFoundError):
        await service.get_overview("tenant-1")

    with pytest.raises(PortfolioSnapshotNotFoundError):
        await service.get_positions("tenant-1")


@pytest.mark.asyncio
async def test_read_model_exposes_freshness_and_source_quality():
    bundle = BrokerSnapshotBundle(
        snapshot=_sample_snapshot(
            status="partial",
            source_quality="public_fallback",
            missing_fields=["cash_balances"],
            partial_components=["cash_balances"],
        ),
        positions=[],
        cash_balances=[],
        margin_balances=[],
    )
    service = PortfolioReadModelService(
        repository=FakePortfolioSnapshotRepository(bundle),
        now_provider=lambda: datetime(2026, 5, 10, 10, 3, 0, tzinfo=timezone.utc),
    )

    overview = await service.get_overview("tenant-1")

    assert overview.source_quality == "public_fallback"
    assert overview.freshness.snapshot_id == "snapshot-1"
    assert overview.freshness.status == "partial"
    assert overview.freshness.is_partial is True
    assert overview.freshness.as_of_age_seconds == 180
    assert overview.freshness.received_age_seconds == 120
    assert overview.freshness.missing_fields == ["cash_balances"]
    assert overview.freshness.partial_components == ["cash_balances"]


def test_read_model_env_uses_postgres_when_broker_sync_uses_postgres(monkeypatch):
    monkeypatch.setenv("BROKER_SYNC_REPOSITORY", "postgres")
    monkeypatch.setenv("DATABASE_URL", "postgresql://postgres:postgres@localhost:5432/ai_holdings")
    monkeypatch.delenv("PORTFOLIO_READ_REPOSITORY", raising=False)
    monkeypatch.delenv("SUPABASE_URL", raising=False)
    monkeypatch.delenv("SUPABASE_SERVICE_ROLE_KEY", raising=False)

    service = create_portfolio_read_model_service_from_env()

    assert isinstance(service._repository, PostgresPortfolioSnapshotRepository)


def test_read_model_env_requires_database_url_for_postgres(monkeypatch):
    monkeypatch.setenv("PORTFOLIO_READ_REPOSITORY", "postgres")
    monkeypatch.delenv("DATABASE_URL", raising=False)

    with pytest.raises(PortfolioReadModelConfigurationError, match="DATABASE_URL"):
        create_portfolio_read_model_service_from_env()


@pytest.mark.asyncio
async def test_http_fx_provider_skips_network_when_only_base_currency_needed():
    provider = HttpFxRateProvider("http://127.0.0.1:1/latest", source="trusted_http_fx")

    snapshot = await provider.get_rates(["USD"], "USD")

    assert snapshot.rates == {"USD": 1.0}
    assert snapshot.source == "trusted_http_fx"
    assert snapshot.trusted is True
