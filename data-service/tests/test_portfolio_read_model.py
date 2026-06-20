from __future__ import annotations

from datetime import datetime, timezone

import pytest

from services.fx import EnvTrustedFxRateProvider
from services.portfolio_read_model import (
    BrokerSnapshotBundle,
    PostgresPortfolioSnapshotRepository,
    PortfolioReadModelService,
    PortfolioSnapshotNotFoundError,
    SupabasePortfolioSnapshotRepository,
    create_portfolio_snapshot_repository_from_env,
    _select_best_snapshot,
    _to_datetime,
)


class FakePortfolioSnapshotRepository:
    def __init__(self, bundle: BrokerSnapshotBundle | None) -> None:
        self._bundle = bundle

    async def get_latest_snapshot_bundle(self, tenant_id: str) -> BrokerSnapshotBundle | None:
        return self._bundle


class FakeSupabaseClient:
    def __init__(self, table_rows: dict[str, list[dict]]) -> None:
        self.table_rows = table_rows

    def table(self, name: str):
        return FakeSupabaseQuery(self.table_rows.get(name, []))


class FakeSupabaseQuery:
    def __init__(self, rows: list[dict]) -> None:
        self._rows = list(rows)

    def select(self, *_args, **_kwargs):
        return self

    def eq(self, key: str, value):
        self._rows = [row for row in self._rows if row.get(key) == value]
        return self

    def in_(self, key: str, values: list):
        allowed = set(values)
        self._rows = [row for row in self._rows if row.get(key) in allowed]
        return self

    def order(self, key: str, desc: bool = False):
        self._rows = sorted(self._rows, key=lambda row: str(row.get(key) or ""), reverse=desc)
        return self

    def limit(self, count: int):
        self._rows = self._rows[:count]
        return self

    def execute(self):
        return type("FakeResponse", (), {"data": self._rows})()


class FakePostgresConnection:
    def __init__(self, table_rows: dict[str, list[dict]]) -> None:
        self.table_rows = table_rows

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def cursor(self, **_kwargs):
        return FakePostgresCursor(self.table_rows)


class FakePostgresCursor:
    def __init__(self, table_rows: dict[str, list[dict]]) -> None:
        self.table_rows = table_rows
        self._rows: list[dict] = []

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def execute(self, query: str, params):
        tenant_id = params[0]
        if "FROM public.broker_sync_snapshots" in query:
            self._rows = [
                row
                for row in self.table_rows.get("broker_sync_snapshots", [])
                if row.get("tenant_id") == tenant_id and row.get("status") in {"succeeded", "partial"}
            ]
        elif "FROM public.webapp_manual_positions" in query:
            self._rows = [
                row
                for row in self.table_rows.get("webapp_manual_positions", [])
                if row.get("tenant_id") == tenant_id and row.get("position_status") == "open"
            ]
        elif "FROM public.broker_position_snapshots" in query:
            snapshot_id = params[1]
            self._rows = [
                row
                for row in self.table_rows.get("broker_position_snapshots", [])
                if row.get("tenant_id") == tenant_id and row.get("broker_sync_snapshot_id") == snapshot_id
            ]
        elif "FROM public.cash_balance_snapshots" in query:
            snapshot_id = params[1]
            self._rows = [
                row
                for row in self.table_rows.get("cash_balance_snapshots", [])
                if row.get("tenant_id") == tenant_id and row.get("broker_sync_snapshot_id") == snapshot_id
            ]
        elif "FROM public.margin_balance_snapshots" in query:
            snapshot_id = params[1]
            self._rows = [
                row
                for row in self.table_rows.get("margin_balance_snapshots", [])
                if row.get("tenant_id") == tenant_id and row.get("broker_sync_snapshot_id") == snapshot_id
            ]
        else:
            self._rows = []

    def fetchall(self):
        return self._rows


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
async def test_supabase_repository_falls_back_to_webapp_manual_positions_without_broker_snapshot():
    client = FakeSupabaseClient(
        {
            "broker_sync_snapshots": [],
            "webapp_manual_positions": [
                {
                    "id": "manual-1",
                    "tenant_id": "tenant-1",
                    "instrument_type": "stock",
                    "symbol": "NVDA",
                    "name": "NVIDIA",
                    "market": "US",
                    "exchange": "NASDAQ",
                    "position_side": "long",
                    "quantity": 2,
                    "average_cost": 900,
                    "market_price": 1000,
                    "market_value": 2000,
                    "currency": "USD",
                    "source_quality": "user_confirmed",
                    "source_tier": "user_confirmed",
                    "source_actionability": "analysis_only",
                    "source_as_of": "2026-05-10T10:00:00+00:00",
                    "source_lineage": {"source": "test"},
                    "note": "manual",
                    "position_status": "open",
                    "updated_at": "2026-05-10T10:01:00+00:00",
                }
            ],
        }
    )
    repository = SupabasePortfolioSnapshotRepository(client)

    bundle = await repository.get_latest_snapshot_bundle("tenant-1")

    assert bundle is not None
    assert bundle.snapshot["id"] == "manual-webapp:tenant-1"
    assert bundle.snapshot["source_quality"] == "user_confirmed"
    assert bundle.snapshot["partial_components"] == ["manual_positions_fallback"]
    assert bundle.positions[0]["provider_symbol"] == "NVDA"
    assert bundle.positions[0]["cost_basis"] == 1800
    assert bundle.positions[0]["position_payload"]["name"] == "NVIDIA"


@pytest.mark.asyncio
async def test_postgres_repository_falls_back_to_webapp_manual_positions_without_broker_snapshot():
    def connect_factory(_database_url: str):
        return FakePostgresConnection(
            {
                "broker_sync_snapshots": [],
                "webapp_manual_positions": [
                    {
                        "id": "manual-1",
                        "tenant_id": "tenant-1",
                        "instrument_type": "stock",
                        "symbol": "TSLA",
                        "name": "Tesla",
                        "market": "US",
                        "exchange": "NASDAQ",
                        "position_side": "long",
                        "quantity": 3,
                        "average_cost": 200,
                        "market_price": 250,
                        "market_value": 750,
                        "currency": "USD",
                        "source_quality": "user_confirmed",
                        "source_tier": "user_confirmed",
                        "source_actionability": "analysis_only",
                        "source_as_of": None,
                        "source_lineage": {"source": "test"},
                        "note": "manual",
                        "position_status": "open",
                        "updated_at": "2026-05-10T10:01:00+00:00",
                    }
                ],
            }
        )

    repository = PostgresPortfolioSnapshotRepository("postgresql://example", connect_factory=connect_factory)

    bundle = await repository.get_latest_snapshot_bundle("tenant-1")

    assert bundle is not None
    assert bundle.snapshot["id"] == "manual-webapp:tenant-1"
    assert bundle.positions[0]["provider_symbol"] == "TSLA"
    assert bundle.positions[0]["cost_basis"] == 600
    assert bundle.positions[0]["position_payload"]["source"] == "webapp_manual_positions"


@pytest.mark.asyncio
async def test_postgres_manual_position_fallback_estimates_value_from_cost_basis():
    def connect_factory(_database_url: str):
        return FakePostgresConnection(
            {
                "broker_sync_snapshots": [],
                "webapp_manual_positions": [
                    {
                        "id": "manual-1",
                        "tenant_id": "tenant-1",
                        "instrument_type": "stock",
                        "symbol": "TSLA",
                        "name": "Tesla",
                        "market": "US",
                        "exchange": "NASDAQ",
                        "position_side": "long",
                        "quantity": 3,
                        "average_cost": 200,
                        "market_price": None,
                        "market_value": None,
                        "currency": "USD",
                        "source_quality": "user_confirmed",
                        "source_tier": "user_confirmed",
                        "source_actionability": "analysis_only",
                        "source_as_of": None,
                        "source_lineage": {"source": "test"},
                        "note": "manual",
                        "position_status": "open",
                        "updated_at": "2026-05-10T10:01:00+00:00",
                    }
                ],
            }
        )

    repository = PostgresPortfolioSnapshotRepository("postgresql://example", connect_factory=connect_factory)

    bundle = await repository.get_latest_snapshot_bundle("tenant-1")

    assert bundle is not None
    assert bundle.positions[0]["market_price"] == 200
    assert bundle.positions[0]["market_value"] == 600
    assert bundle.positions[0]["position_payload"]["valuation_basis"] == "manual_cost_basis"


def test_repository_factory_uses_database_url_when_supabase_env_is_missing(monkeypatch):
    monkeypatch.delenv("SUPABASE_URL", raising=False)
    monkeypatch.delenv("SUPABASE_SERVICE_ROLE_KEY", raising=False)
    monkeypatch.setenv("DATABASE_URL", "postgresql://example")

    repository = create_portfolio_snapshot_repository_from_env()

    assert isinstance(repository, PostgresPortfolioSnapshotRepository)


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
