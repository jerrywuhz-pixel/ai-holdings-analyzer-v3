from __future__ import annotations

import asyncio
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable, Optional, Protocol

from pydantic import BaseModel, Field

from services.fx import (
    FALLBACK_FX_SOURCE,
    FxRateProvider,
    FxRateSnapshot,
    create_fx_rate_provider_from_env,
    fallback_fx_rate,
    normalize_currency,
)

DEFAULT_BASE_CURRENCY = "USD"
DEFAULT_BASE_CURRENCY_ENV = "PORTFOLIO_BASE_CURRENCY"
SOURCE_QUALITY_PRIORITY = {
    "broker_verified": 5,
    "user_confirmed": 4,
    "estimated": 3,
    "public_fallback": 2,
    "conflicted": 1,
}


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


class PortfolioReadModelError(RuntimeError):
    """Base error for the portfolio read model."""


class PortfolioReadModelConfigurationError(PortfolioReadModelError):
    """Raised when the read model cannot create a repository."""


class PortfolioSnapshotNotFoundError(PortfolioReadModelError):
    """Raised when no succeeded/partial snapshot exists for a tenant."""


@dataclass
class BrokerSnapshotBundle:
    snapshot: dict[str, Any]
    positions: list[dict[str, Any]]
    cash_balances: list[dict[str, Any]]
    margin_balances: list[dict[str, Any]]


class PortfolioSnapshotRepository(Protocol):
    async def get_latest_snapshot_bundle(self, tenant_id: str) -> Optional[BrokerSnapshotBundle]:
        ...


class PortfolioFreshnessDTO(BaseModel):
    snapshot_id: str
    broker_connection_id: Optional[str] = None
    status: str
    as_of: datetime
    received_at: datetime
    as_of_age_seconds: int
    received_age_seconds: int
    is_partial: bool
    missing_fields: list[str] = Field(default_factory=list)
    partial_components: list[str] = Field(default_factory=list)


class CashBalanceDTO(BaseModel):
    currency: str
    total_cash: Optional[float] = None
    available_cash: Optional[float] = None
    buying_power: Optional[float] = None
    source_quality: str
    as_of: datetime
    base_currency: str = DEFAULT_BASE_CURRENCY
    fx_rate: float = 1.0
    fx_source: str = FALLBACK_FX_SOURCE
    base_total_cash: Optional[float] = None
    base_available_cash: Optional[float] = None
    base_buying_power: Optional[float] = None


class PortfolioOverviewDTO(BaseModel):
    gross_market_value: float
    cash: float
    buying_power: float
    cash_secured_requirement: float
    base_currency: str = DEFAULT_BASE_CURRENCY
    base_fx_source: str = FALLBACK_FX_SOURCE
    base_total_value: float = 0.0
    base_gross_market_value: float = 0.0
    base_cash: float = 0.0
    base_buying_power: float = 0.0
    base_cash_secured_requirement: float = 0.0
    positions_count: int
    equity_count: int
    option_count: int
    markets: list[str] = Field(default_factory=list)
    currencies: list[str] = Field(default_factory=list)
    cash_balances: list[CashBalanceDTO] = Field(default_factory=list)
    freshness: PortfolioFreshnessDTO
    source_quality: str


class EquityPositionDTO(BaseModel):
    symbol: str
    name: Optional[str] = None
    instrument_type: str
    market: str
    exchange: Optional[str] = None
    position_side: str
    quantity: float
    average_cost: Optional[float] = None
    cost_basis: Optional[float] = None
    market_price: Optional[float] = None
    market_value: Optional[float] = None
    currency: str
    base_market_value: Optional[float] = None
    base_currency: str = DEFAULT_BASE_CURRENCY
    fx_rate: float = 1.0
    fx_source: str = FALLBACK_FX_SOURCE
    source_quality: str
    as_of: datetime


class OptionPositionDTO(EquityPositionDTO):
    option_type: Optional[str] = None
    strike: Optional[float] = None
    expiry: Optional[str] = None


class PortfolioPositionsDTO(BaseModel):
    equity_positions: list[EquityPositionDTO] = Field(default_factory=list)
    option_positions: list[OptionPositionDTO] = Field(default_factory=list)
    freshness: PortfolioFreshnessDTO
    source_quality: str


class PortfolioReadModelService:
    def __init__(
        self,
        *,
        repository: PortfolioSnapshotRepository,
        now_provider: Callable[[], datetime] = _utc_now,
        base_currency: str | None = None,
        fx_rate_provider: FxRateProvider | None = None,
    ) -> None:
        self._repository = repository
        self._now_provider = now_provider
        self._default_base_currency = _resolve_base_currency_code(base_currency)
        self._fx_rate_provider = fx_rate_provider or create_fx_rate_provider_from_env()

    async def get_overview(
        self,
        tenant_id: str,
        base_currency: str | None = None,
    ) -> PortfolioOverviewDTO:
        bundle = await self._require_bundle(tenant_id)
        resolved_base_currency = self._resolve_base_currency(base_currency)
        freshness = _build_freshness(bundle.snapshot, now=self._now_provider())
        equities, options = _split_positions(bundle.positions)
        currencies = _extract_currencies(bundle)
        fx_snapshot = await self._fx_rate_provider.get_rates(currencies, resolved_base_currency)
        cash_balances = [
            _to_cash_balance(row, base_currency=resolved_base_currency, fx_snapshot=fx_snapshot)
            for row in bundle.cash_balances
        ]

        cash = _round_money(
            sum(
                _convert_amount(_cash_amount(row), row.get("currency"), resolved_base_currency, fx_snapshot=fx_snapshot)
                for row in bundle.cash_balances
            )
        )
        buying_power = _round_money(
            _resolve_buying_power(
                bundle.cash_balances,
                bundle.margin_balances,
                base_currency=resolved_base_currency,
                fx_snapshot=fx_snapshot,
            )
        )
        cash_secured_requirement = _round_money(
            sum(
                _convert_amount(
                    _to_float(row.get("cash_secured_requirement")),
                    row.get("currency"),
                    resolved_base_currency,
                    fx_snapshot=fx_snapshot,
                )
                for row in bundle.margin_balances
            )
        )
        position_values = [
            _convert_amount(_to_float(row.get("market_value")), row.get("currency"), resolved_base_currency, fx_snapshot=fx_snapshot)
            for row in bundle.positions
        ]
        gross_market_value = _round_money(
            sum(abs(value) for value in position_values)
        )
        total_value = _round_money(cash + sum(position_values))

        markets = sorted(
            {
                str(row.get("market")).upper()
                for row in bundle.positions
                if row.get("market")
            }
        )
        return PortfolioOverviewDTO(
            gross_market_value=gross_market_value,
            cash=cash,
            buying_power=buying_power,
            cash_secured_requirement=cash_secured_requirement,
            base_currency=resolved_base_currency,
            base_fx_source=fx_snapshot.source,
            base_total_value=total_value,
            base_gross_market_value=gross_market_value,
            base_cash=cash,
            base_buying_power=buying_power,
            base_cash_secured_requirement=cash_secured_requirement,
            positions_count=len(bundle.positions),
            equity_count=len(equities),
            option_count=len(options),
            markets=markets,
            currencies=currencies,
            cash_balances=cash_balances,
            freshness=freshness,
            source_quality=str(bundle.snapshot.get("source_quality") or "unknown"),
        )

    async def get_positions(
        self,
        tenant_id: str,
        base_currency: str | None = None,
    ) -> PortfolioPositionsDTO:
        bundle = await self._require_bundle(tenant_id)
        resolved_base_currency = self._resolve_base_currency(base_currency)
        freshness = _build_freshness(bundle.snapshot, now=self._now_provider())
        equities, options = _split_positions(bundle.positions)
        fx_snapshot = await self._fx_rate_provider.get_rates(_extract_currencies(bundle), resolved_base_currency)

        return PortfolioPositionsDTO(
            equity_positions=[
                _to_equity_position(row, base_currency=resolved_base_currency, fx_snapshot=fx_snapshot)
                for row in equities
            ],
            option_positions=[
                _to_option_position(row, base_currency=resolved_base_currency, fx_snapshot=fx_snapshot)
                for row in options
            ],
            freshness=freshness,
            source_quality=str(bundle.snapshot.get("source_quality") or "unknown"),
        )

    async def _require_bundle(self, tenant_id: str) -> BrokerSnapshotBundle:
        bundle = await self._repository.get_latest_snapshot_bundle(tenant_id)
        if bundle is None:
            raise PortfolioSnapshotNotFoundError(
                f"No succeeded or partial broker snapshot found for tenant_id={tenant_id}"
            )
        return bundle

    def _resolve_base_currency(self, base_currency: str | None) -> str:
        if base_currency:
            return _resolve_base_currency_code(base_currency)
        return self._default_base_currency


class SupabasePortfolioSnapshotRepository:
    def __init__(self, client: Any) -> None:
        self._client = client

    async def get_latest_snapshot_bundle(self, tenant_id: str) -> Optional[BrokerSnapshotBundle]:
        def _load_bundle() -> Optional[BrokerSnapshotBundle]:
            snapshot_response = (
                self._client.table("broker_sync_snapshots")
                .select(
                    "id, tenant_id, broker_connection_id, status, as_of, received_at, "
                    "source_quality, missing_fields, partial_components"
                )
                .eq("tenant_id", tenant_id)
                .in_("status", ["succeeded", "partial"])
                .order("as_of", desc=True)
                .order("received_at", desc=True)
                .order("created_at", desc=True)
                .limit(20)
                .execute()
            )
            if not snapshot_response.data:
                return None

            snapshot = _select_best_snapshot(snapshot_response.data)
            snapshot_id = snapshot["id"]
            positions = (
                self._client.table("broker_position_snapshots")
                .select(
                    "provider_symbol, instrument_type, market, exchange, position_side, quantity, "
                    "average_cost, cost_basis, market_price, market_value, currency, source_quality, "
                    "position_payload, as_of"
                )
                .eq("tenant_id", tenant_id)
                .eq("broker_sync_snapshot_id", snapshot_id)
                .execute()
            ).data or []
            cash_balances = (
                self._client.table("cash_balance_snapshots")
                .select("currency, total_cash, available_cash, buying_power, source_quality, as_of")
                .eq("tenant_id", tenant_id)
                .eq("broker_sync_snapshot_id", snapshot_id)
                .execute()
            ).data or []
            margin_balances = (
                self._client.table("margin_balance_snapshots")
                .select(
                    "currency, margin_available, option_buying_power, cash_secured_requirement, "
                    "source_quality, as_of"
                )
                .eq("tenant_id", tenant_id)
                .eq("broker_sync_snapshot_id", snapshot_id)
                .execute()
            ).data or []
            return BrokerSnapshotBundle(
                snapshot=snapshot,
                positions=[dict(row) for row in positions],
                cash_balances=[dict(row) for row in cash_balances],
                margin_balances=[dict(row) for row in margin_balances],
            )

        return await asyncio.to_thread(_load_bundle)


class PostgresPortfolioSnapshotRepository:
    def __init__(self, database_url: str) -> None:
        if not database_url.strip():
            raise PortfolioReadModelConfigurationError(
                "DATABASE_URL is required for postgres portfolio read model queries"
            )
        self._database_url = database_url

    async def get_latest_snapshot_bundle(self, tenant_id: str) -> Optional[BrokerSnapshotBundle]:
        def _load_bundle() -> Optional[BrokerSnapshotBundle]:
            import psycopg
            from psycopg.rows import dict_row

            with psycopg.connect(self._database_url, row_factory=dict_row) as conn:
                with conn.cursor() as cursor:
                    cursor.execute(
                        """
                        SELECT
                          id, tenant_id, broker_connection_id, status, as_of, received_at,
                          source_quality, missing_fields, partial_components, created_at
                        FROM public.broker_sync_snapshots
                        WHERE tenant_id = %s
                          AND status IN ('succeeded', 'partial')
                        ORDER BY as_of DESC, received_at DESC, created_at DESC
                        LIMIT 20
                        """,
                        (tenant_id,),
                    )
                    snapshots = cursor.fetchall()
                    if not snapshots:
                        return None

                    snapshot = _select_best_snapshot([dict(row) for row in snapshots])
                    snapshot_id = snapshot["id"]
                    cursor.execute(
                        """
                        SELECT
                          provider_symbol, instrument_type, market, exchange, position_side, quantity,
                          average_cost, cost_basis, market_price, market_value, currency, source_quality,
                          position_payload, as_of
                        FROM public.broker_position_snapshots
                        WHERE tenant_id = %s
                          AND broker_sync_snapshot_id = %s
                        """,
                        (tenant_id, snapshot_id),
                    )
                    positions = [dict(row) for row in cursor.fetchall()]

                    cursor.execute(
                        """
                        SELECT currency, total_cash, available_cash, buying_power, source_quality, as_of
                        FROM public.cash_balance_snapshots
                        WHERE tenant_id = %s
                          AND broker_sync_snapshot_id = %s
                        """,
                        (tenant_id, snapshot_id),
                    )
                    cash_balances = [dict(row) for row in cursor.fetchall()]

                    cursor.execute(
                        """
                        SELECT
                          currency, margin_available, option_buying_power, cash_secured_requirement,
                          source_quality, as_of
                        FROM public.margin_balance_snapshots
                        WHERE tenant_id = %s
                          AND broker_sync_snapshot_id = %s
                        """,
                        (tenant_id, snapshot_id),
                    )
                    margin_balances = [dict(row) for row in cursor.fetchall()]

            return BrokerSnapshotBundle(
                snapshot=snapshot,
                positions=positions,
                cash_balances=cash_balances,
                margin_balances=margin_balances,
            )

        return await asyncio.to_thread(_load_bundle)


def _select_best_snapshot(rows: list[dict[str, Any]]) -> dict[str, Any]:
    return dict(
        max(
            rows,
            key=lambda row: (
                _source_quality_priority(row.get("source_quality")),
                _status_priority(row.get("status")),
                _to_datetime(row.get("as_of")),
                _to_datetime(row.get("received_at")),
            ),
        )
    )


def _source_quality_priority(value: Any) -> int:
    return SOURCE_QUALITY_PRIORITY.get(str(value or "").lower(), 0)


def _status_priority(value: Any) -> int:
    return 2 if str(value or "").lower() == "succeeded" else 1


def create_portfolio_read_model_service_from_env() -> PortfolioReadModelService:
    mode = (
        os.getenv("PORTFOLIO_READ_REPOSITORY", "").strip().lower()
        or os.getenv("BROKER_SYNC_REPOSITORY", "").strip().lower()
    )
    if mode in {"postgres", "local_postgres", "database_url"}:
        return PortfolioReadModelService(
            repository=PostgresPortfolioSnapshotRepository(os.getenv("DATABASE_URL", "").strip())
        )
    if mode and mode not in {"supabase", "supabase_rest"}:
        raise PortfolioReadModelConfigurationError(f"unsupported PORTFOLIO_READ_REPOSITORY: {mode}")
    return PortfolioReadModelService(repository=create_supabase_portfolio_snapshot_repository_from_env())


def create_supabase_portfolio_snapshot_repository_from_env() -> SupabasePortfolioSnapshotRepository:
    url = os.getenv("SUPABASE_URL", "").strip()
    key = os.getenv("SUPABASE_SERVICE_ROLE_KEY", "").strip()
    if not url or not key:
        raise PortfolioReadModelConfigurationError(
            "SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY are required for portfolio read model queries"
        )

    try:
        from supabase import create_client
    except ImportError as exc:
        raise PortfolioReadModelConfigurationError("supabase client dependency is not installed") from exc

    return SupabasePortfolioSnapshotRepository(create_client(url, key))


def _build_freshness(snapshot: dict[str, Any], *, now: datetime) -> PortfolioFreshnessDTO:
    as_of = _to_datetime(snapshot.get("as_of"))
    received_at = _to_datetime(snapshot.get("received_at"))
    status = str(snapshot.get("status") or "unknown")
    return PortfolioFreshnessDTO(
        snapshot_id=str(snapshot.get("id")),
        broker_connection_id=_optional_str(snapshot.get("broker_connection_id")),
        status=status,
        as_of=as_of,
        received_at=received_at,
        as_of_age_seconds=max(0, int((now - as_of).total_seconds())),
        received_age_seconds=max(0, int((now - received_at).total_seconds())),
        is_partial=status == "partial",
        missing_fields=[str(item) for item in snapshot.get("missing_fields") or []],
        partial_components=[str(item) for item in snapshot.get("partial_components") or []],
    )


def _split_positions(
    rows: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    equities: list[dict[str, Any]] = []
    options: list[dict[str, Any]] = []
    for row in rows:
        instrument_type = str(row.get("instrument_type") or "").lower()
        if instrument_type == "option_contract":
            options.append(row)
        else:
            equities.append(row)

    equities.sort(key=_position_sort_key)
    options.sort(key=_position_sort_key)
    return equities, options


def _extract_currencies(bundle: BrokerSnapshotBundle) -> list[str]:
    return sorted(
        {
            normalize_currency(value)
            for value in [
                *[row.get("currency") for row in bundle.positions],
                *[row.get("currency") for row in bundle.cash_balances],
                *[row.get("currency") for row in bundle.margin_balances],
            ]
            if value
        }
    )


def _position_sort_key(row: dict[str, Any]) -> tuple[float, str]:
    symbol = str(row.get("provider_symbol") or "")
    return (-abs(_to_float(row.get("market_value"))), symbol)


def _to_equity_position(
    row: dict[str, Any],
    *,
    base_currency: str,
    fx_snapshot: FxRateSnapshot,
) -> EquityPositionDTO:
    currency = normalize_currency(row.get("currency"))
    market_value = _optional_float(row.get("market_value"))
    payload = row.get("position_payload") or {}
    if not isinstance(payload, dict):
        payload = {}
    return EquityPositionDTO(
        symbol=str(row.get("provider_symbol") or ""),
        name=_optional_str(
            row.get("name")
            or payload.get("name")
            or payload.get("stock_name")
            or payload.get("security_name")
            or payload.get("short_name")
            or payload.get("stock_name_en")
            or payload.get("stock_name_cn")
            or payload.get("sec_name")
        ),
        instrument_type=str(row.get("instrument_type") or ""),
        market=str(row.get("market") or ""),
        exchange=_optional_str(row.get("exchange")),
        position_side=str(row.get("position_side") or "long"),
        quantity=_to_float(row.get("quantity")),
        average_cost=_optional_float(row.get("average_cost")),
        cost_basis=_optional_float(row.get("cost_basis")),
        market_price=_optional_float(row.get("market_price")),
        market_value=market_value,
        currency=currency,
        base_market_value=_convert_optional_amount(
            market_value,
            currency=currency,
            base_currency=base_currency,
            fx_snapshot=fx_snapshot,
        ),
        base_currency=base_currency,
        fx_rate=_resolve_fx_rate(currency, base_currency, fx_snapshot=fx_snapshot),
        fx_source=_resolve_fx_source(currency, base_currency, fx_snapshot=fx_snapshot),
        source_quality=str(row.get("source_quality") or "unknown"),
        as_of=_to_datetime(row.get("as_of")),
    )


def _to_option_position(
    row: dict[str, Any],
    *,
    base_currency: str,
    fx_snapshot: FxRateSnapshot,
) -> OptionPositionDTO:
    payload = row.get("position_payload") or {}
    if not isinstance(payload, dict):
        payload = {}

    return OptionPositionDTO(
        **_to_equity_position(row, base_currency=base_currency, fx_snapshot=fx_snapshot).model_dump(mode="python"),
        option_type=_optional_str(payload.get("option_type")),
        strike=_optional_float(payload.get("strike")),
        expiry=_optional_str(payload.get("expiry")),
    )


def _to_cash_balance(
    row: dict[str, Any],
    *,
    base_currency: str,
    fx_snapshot: FxRateSnapshot,
) -> CashBalanceDTO:
    currency = normalize_currency(row.get("currency"))
    total_cash = _optional_float(row.get("total_cash"))
    available_cash = _optional_float(row.get("available_cash"))
    buying_power = _optional_float(row.get("buying_power"))

    return CashBalanceDTO(
        currency=currency,
        total_cash=total_cash,
        available_cash=available_cash,
        buying_power=buying_power,
        source_quality=str(row.get("source_quality") or "unknown"),
        as_of=_to_datetime(row.get("as_of")),
        base_currency=base_currency,
        fx_rate=_resolve_fx_rate(currency, base_currency, fx_snapshot=fx_snapshot),
        fx_source=_resolve_fx_source(currency, base_currency, fx_snapshot=fx_snapshot),
        base_total_cash=_convert_optional_amount(
            total_cash,
            currency=currency,
            base_currency=base_currency,
            fx_snapshot=fx_snapshot,
        ),
        base_available_cash=_convert_optional_amount(
            available_cash,
            currency=currency,
            base_currency=base_currency,
            fx_snapshot=fx_snapshot,
        ),
        base_buying_power=_convert_optional_amount(
            buying_power,
            currency=currency,
            base_currency=base_currency,
            fx_snapshot=fx_snapshot,
        ),
    )


def _cash_amount(row: dict[str, Any]) -> float:
    available_cash = row.get("available_cash")
    if available_cash is not None:
        return _to_float(available_cash)
    return _to_float(row.get("total_cash"))


def _resolve_buying_power(
    cash_balances: list[dict[str, Any]],
    margin_balances: list[dict[str, Any]],
    *,
    base_currency: str,
    fx_snapshot: FxRateSnapshot,
) -> float:
    cash_buying_power = sum(
        _convert_amount(_to_float(row.get("buying_power")), row.get("currency"), base_currency, fx_snapshot=fx_snapshot)
        for row in cash_balances
    )
    if cash_buying_power > 0:
        return cash_buying_power

    margin_buying_power = 0.0
    for row in margin_balances:
        margin_buying_power += _convert_amount(
            _to_float(row.get("option_buying_power")),
            row.get("currency"),
            base_currency,
            fx_snapshot=fx_snapshot,
        )
        if row.get("option_buying_power") is None:
            margin_buying_power += _convert_amount(
                _to_float(row.get("margin_available")),
                row.get("currency"),
                base_currency,
                fx_snapshot=fx_snapshot,
            )
    return margin_buying_power


def _resolve_base_currency_code(value: str | None) -> str:
    if value:
        return normalize_currency(value)
    env_value = os.getenv(DEFAULT_BASE_CURRENCY_ENV)
    if env_value:
        return normalize_currency(env_value)
    return DEFAULT_BASE_CURRENCY


def _resolve_fx_rate(currency: Any, base_currency: str, *, fx_snapshot: FxRateSnapshot) -> float:
    source_currency = normalize_currency(currency)
    target_currency = normalize_currency(base_currency)
    if source_currency == target_currency:
        return 1.0
    return fx_snapshot.rates.get(source_currency, fallback_fx_rate(source_currency, target_currency))


def _resolve_fx_source(currency: Any, base_currency: str, *, fx_snapshot: FxRateSnapshot) -> str:
    source_currency = normalize_currency(currency)
    target_currency = normalize_currency(base_currency)
    if source_currency == target_currency:
        return fx_snapshot.source
    return fx_snapshot.source if source_currency in fx_snapshot.rates else FALLBACK_FX_SOURCE


def _convert_amount(amount: float, currency: Any, base_currency: str, *, fx_snapshot: FxRateSnapshot) -> float:
    return amount * _resolve_fx_rate(currency, base_currency, fx_snapshot=fx_snapshot)


def _convert_optional_amount(
    amount: Optional[float],
    *,
    currency: Any,
    base_currency: str,
    fx_snapshot: FxRateSnapshot,
) -> Optional[float]:
    if amount is None:
        return None
    return _round_money(_convert_amount(amount, currency, base_currency, fx_snapshot=fx_snapshot))


def _to_datetime(value: Any) -> datetime:
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if not value:
        return _utc_now()
    text = _normalize_iso_datetime_text(str(value).strip())
    if text.endswith("Z"):
        text = f"{text[:-1]}+00:00"
    parsed = datetime.fromisoformat(text)
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _normalize_iso_datetime_text(text: str) -> str:
    dot_index = text.find(".")
    if dot_index < 0:
        return text

    fraction_start = dot_index + 1
    fraction_end = fraction_start
    while fraction_end < len(text) and text[fraction_end].isdigit():
        fraction_end += 1

    fraction = text[fraction_start:fraction_end]
    if not fraction or len(fraction) in (3, 6):
        return text

    normalized_fraction = (fraction + "000000")[:6]
    return f"{text[:fraction_start]}{normalized_fraction}{text[fraction_end:]}"


def _optional_str(value: Any) -> Optional[str]:
    if value is None:
        return None
    return str(value)


def _optional_float(value: Any) -> Optional[float]:
    if value is None:
        return None
    return _to_float(value)


def _to_float(value: Any) -> float:
    if value is None:
        return 0.0
    return float(value)


def _round_money(value: float) -> float:
    return round(value, 2)
