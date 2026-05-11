from __future__ import annotations

"""
Read-only local Futu OpenD sidecar.

This process runs on the user's machine, talks to the local OpenD process, and
exposes a narrow HTTP contract to the data-service. It intentionally has no
order endpoints and returns `permission_scope=read_only` on every data payload.
"""

import importlib
import math
import os
import re
from datetime import date, datetime, timedelta, timezone
from typing import Any, Literal, Optional

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel


READ_ONLY_SCOPE = "read_only"
SOURCE_KEY = "futu_openapi"
SOURCE_TIER = "L1_trading"


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


class FutuSidecarError(RuntimeError):
    """Raised when the local Futu sidecar cannot satisfy a read-only request."""


class SnapshotRequest(BaseModel):
    tenant_id: str
    broker_connection_id: str
    snapshot_label: str = "default"
    include_positions: bool = True
    include_cash: bool = True
    connector_mode: str = "local_connector"
    permission_scope: Literal["read_only"] = "read_only"


class OptionChainRequest(BaseModel):
    tenant_id: str
    broker_connection_id: str
    underlying_symbol: str
    snapshot_label: str = "default"
    option_type: Literal["put", "call", "all"] = "put"
    min_days_to_expiry: Optional[int] = None
    max_days_to_expiry: Optional[int] = None
    connector_mode: str = "local_connector"
    permission_scope: Literal["read_only"] = "read_only"


class FutuSidecarSettings(BaseModel):
    mode: Literal["mock", "real"] = "mock"
    opend_host: str = "127.0.0.1"
    opend_port: int = 11111
    trade_market: str = "US"
    security_firm: str = "FUTUINC"
    trade_env: str = "REAL"
    currency: str = "USD"
    account_id: int = 0
    account_index: int = 0
    sdk_module: str = "futu"
    max_snapshot_codes: int = 400


def load_settings() -> FutuSidecarSettings:
    return FutuSidecarSettings(
        mode=_normalize_sidecar_mode(os.getenv("FUTU_SIDECAR_MODE", "mock")),
        opend_host=os.getenv("FUTU_OPEND_HOST", "127.0.0.1"),
        opend_port=int(os.getenv("FUTU_OPEND_PORT", "11111")),
        trade_market=os.getenv("FUTU_TRD_MARKET", "US"),
        security_firm=os.getenv("FUTU_SECURITY_FIRM", "FUTUINC"),
        trade_env=os.getenv("FUTU_TRD_ENV", "REAL"),
        currency=os.getenv("FUTU_CURRENCY", "USD"),
        account_id=int(os.getenv("FUTU_ACC_ID", "0")),
        account_index=int(os.getenv("FUTU_ACC_INDEX", "0")),
        sdk_module=os.getenv("FUTU_SDK_MODULE", "futu"),
        max_snapshot_codes=int(os.getenv("FUTU_MAX_SNAPSHOT_CODES", "400")),
    )


def create_app() -> FastAPI:
    app = FastAPI(title="Futu OpenD Read-Only Sidecar", version="0.1.0")

    @app.get("/health")
    async def health() -> dict[str, Any]:
        return _health_payload(load_settings())

    @app.get("/api/v1/account-diagnostics")
    async def read_account_diagnostics() -> dict[str, Any]:
        try:
            settings = load_settings()
            data = _build_reader(settings).read_account_diagnostics()
            return {"ok": True, "data": data}
        except FutuSidecarError as exc:
            raise HTTPException(status_code=503, detail={"ok": False, "message": _sanitize_error_message(str(exc))})

    @app.post("/api/v1/snapshots")
    async def read_snapshot(payload: SnapshotRequest) -> dict[str, Any]:
        _enforce_request_read_only(payload.permission_scope)
        try:
            data = _build_reader(load_settings()).read_snapshot(payload)
            return {"ok": True, "data": data}
        except FutuSidecarError as exc:
            raise HTTPException(status_code=503, detail={"ok": False, "message": _sanitize_error_message(str(exc))})

    @app.post("/api/v1/option-chain")
    async def read_option_chain(payload: OptionChainRequest) -> dict[str, Any]:
        _enforce_request_read_only(payload.permission_scope)
        try:
            data = _build_reader(load_settings()).read_option_chain(payload)
            return {"ok": True, "data": data}
        except FutuSidecarError as exc:
            raise HTTPException(status_code=503, detail={"ok": False, "message": _sanitize_error_message(str(exc))})

    return app


class MockFutuSidecarReader:
    def __init__(self, settings: FutuSidecarSettings) -> None:
        self._settings = settings

    def read_account_diagnostics(self) -> dict[str, Any]:
        requested = _diagnostic_requested_payload(self._settings)
        candidates = [
            {
                "security_firm": self._settings.security_firm,
                "trd_market": self._settings.trade_market,
                "acc_id": requested["acc_id"],
                "account_count": 1,
                "position_count": None,
                "matches_requested": True,
                "status": "mock",
            }
        ]
        return {
            "connector": "futu-opend-sidecar",
            "mode": self._settings.mode,
            "permission_scope": READ_ONLY_SCOPE,
            "requested": requested,
            "candidate_entities": candidates,
            "summary": {
                "candidate_count": len(candidates),
                "non_zero_position_candidates": 0,
                "diagnostic_mode": "mock",
            },
            "recommendations": _build_diagnostic_recommendations(requested, candidates),
        }

    def read_snapshot(self, request: SnapshotRequest) -> dict[str, Any]:
        now = _utc_now()
        positions = [
            {
                "symbol": "AAPL",
                "market": "US",
                "instrument_type": "stock",
                "quantity": 100.0,
                "average_cost": 182.5,
                "market_price": 191.2,
                "currency": "USD",
            },
            {
                "symbol": "AAPL260619P175",
                "market": "US",
                "instrument_type": "option_contract",
                "quantity": -1.0,
                "average_cost": 2.55,
                "market_price": 2.45,
                "currency": "USD",
                "option_type": "put",
                "strike": 175.0,
                "expiry": "2026-06-19",
            },
        ]
        cash_balances = [
            {
                "currency": "USD",
                "available_cash": 25000.0,
                "buying_power": 48000.0,
                "cash_secured_reserve": 17500.0,
            }
        ]
        return _snapshot_payload(
            request=request,
            settings=self._settings,
            as_of=now - timedelta(seconds=12),
            received_at=now,
            positions=positions if request.include_positions else [],
            cash_balances=cash_balances if request.include_cash else [],
            missing_fields=[],
            status="complete",
            provider="futu_opend_sidecar_mock",
        )

    def read_option_chain(self, request: OptionChainRequest) -> dict[str, Any]:
        now = _utc_now()
        raw_contracts = [
            {
                "contract_symbol": "AAPL260619P175",
                "underlying_symbol": "AAPL",
                "option_type": "put",
                "strike": 175.0,
                "expiry": "2026-06-19",
                "days_to_expiry": 40,
                "bid": 2.4,
                "ask": 2.7,
                "delta": 0.21,
                "implied_volatility": 0.34,
                "open_interest": 1200,
                "volume": 180,
                "currency": "USD",
                "as_of": now - timedelta(seconds=10),
                "source_key": SOURCE_KEY,
                "source_tier": SOURCE_TIER,
            },
            {
                "contract_symbol": "AAPL260619P165",
                "underlying_symbol": "AAPL",
                "option_type": "put",
                "strike": 165.0,
                "expiry": "2026-06-19",
                "days_to_expiry": 40,
                "bid": 1.2,
                "ask": 1.35,
                "delta": 0.12,
                "implied_volatility": 0.36,
                "open_interest": 900,
                "volume": 95,
                "currency": "USD",
                "as_of": now - timedelta(seconds=10),
                "source_key": SOURCE_KEY,
                "source_tier": SOURCE_TIER,
            },
        ]
        contracts = [
            item
            for item in raw_contracts
            if item["underlying_symbol"] == request.underlying_symbol.upper() and _option_contract_matches(item, request)
        ]
        return _option_chain_payload(
            request=request,
            settings=self._settings,
            as_of=max((item["as_of"] for item in contracts), default=now - timedelta(seconds=10)),
            received_at=now,
            contracts=contracts,
            missing_fields=[] if contracts else ["option_chain"],
            status="complete" if contracts else "partial",
            provider="futu_opend_sidecar_mock",
        )


class FutuSdkSidecarReader:
    def __init__(self, settings: FutuSidecarSettings) -> None:
        self._settings = settings
        self._sdk = _import_futu_sdk(settings.sdk_module)

    def read_account_diagnostics(self) -> dict[str, Any]:
        candidates: list[dict[str, Any]] = []
        for security_firm in _diagnostic_security_firms(self._sdk, self._settings.security_firm):
            for trade_market in _diagnostic_trade_markets(self._sdk, self._settings.trade_market):
                candidates.append(self._diagnose_trade_context(security_firm=security_firm, trade_market=trade_market))
        requested = _diagnostic_requested_payload(self._settings)
        return {
            "connector": "futu-opend-sidecar",
            "mode": self._settings.mode,
            "permission_scope": READ_ONLY_SCOPE,
            "requested": requested,
            "candidate_entities": candidates,
            "summary": {
                "candidate_count": len(candidates),
                "non_zero_position_candidates": sum(1 for item in candidates if (item.get("position_count") or 0) > 0),
                "diagnostic_mode": "real",
            },
            "recommendations": _build_diagnostic_recommendations(requested, candidates),
        }

    def read_snapshot(self, request: SnapshotRequest) -> dict[str, Any]:
        now = _utc_now()
        ctx = self._open_trade_context()
        try:
            positions = self._read_positions(ctx) if request.include_positions else []
            cash_balances = self._read_cash_balances(ctx) if request.include_cash else []
        finally:
            _close_context(ctx)

        missing_fields: list[str] = []
        if request.include_cash and not cash_balances:
            missing_fields.append("cash_balances")
        self._enrich_position_names(positions)

        return _snapshot_payload(
            request=request,
            settings=self._settings,
            as_of=now,
            received_at=now,
            positions=positions,
            cash_balances=cash_balances,
            missing_fields=missing_fields,
            status="complete" if not missing_fields else "partial",
            provider="futu_opend_sidecar",
        )

    def read_option_chain(self, request: OptionChainRequest) -> dict[str, Any]:
        now = _utc_now()
        quote_ctx = self._open_quote_context()
        try:
            raw_chain = self._query_option_chain(quote_ctx, request)
            contract_codes = [_as_str(_pick(item, "code", "contract_code")) for item in raw_chain]
            snapshots = self._query_market_snapshots(quote_ctx, [code for code in contract_codes if code])
            contracts = [
                _map_option_contract(chain_item=item, snapshot=snapshots.get(_as_str(_pick(item, "code", "contract_code")), {}), request=request, as_of=now)
                for item in raw_chain
            ]
        finally:
            _close_context(quote_ctx)

        contracts = [item for item in contracts if _option_contract_matches(item, request)]
        missing_fields = [] if contracts else ["option_chain"]
        return _option_chain_payload(
            request=request,
            settings=self._settings,
            as_of=now,
            received_at=now,
            contracts=contracts,
            missing_fields=missing_fields,
            status="complete" if not missing_fields else "partial",
            provider="futu_opend_sidecar",
        )

    def _open_trade_context(self) -> Any:
        return self._open_trade_context_for(
            security_firm=self._settings.security_firm,
            trade_market=self._settings.trade_market,
        )

    def _open_trade_context_for(self, *, security_firm: str, trade_market: str) -> Any:
        try:
            return self._sdk.OpenSecTradeContext(
                filter_trdmarket=_sdk_constant(self._sdk.TrdMarket, trade_market),
                host=self._settings.opend_host,
                port=self._settings.opend_port,
                security_firm=_sdk_constant(self._sdk.SecurityFirm, security_firm),
            )
        except Exception as exc:
            raise FutuSidecarError(f"failed to open Futu trade context: {exc}") from exc

    def _open_quote_context(self) -> Any:
        try:
            return self._sdk.OpenQuoteContext(host=self._settings.opend_host, port=self._settings.opend_port)
        except Exception as exc:
            raise FutuSidecarError(f"failed to open Futu quote context: {exc}") from exc

    def _read_positions(self, ctx: Any) -> list[dict[str, Any]]:
        ret, data = ctx.position_list_query()
        _ensure_ret_ok(self._sdk, ret, data, "position_list_query")
        return [_map_position_record(item, self._settings.currency) for item in _records(data)]

    def _read_cash_balances(self, ctx: Any) -> list[dict[str, Any]]:
        currency = _sdk_constant(getattr(self._sdk, "Currency", object()), self._settings.currency, required=False)
        kwargs = {
            "trd_env": _sdk_constant(self._sdk.TrdEnv, self._settings.trade_env),
            "acc_id": self._settings.account_id,
            "acc_index": self._settings.account_index,
            "refresh_cache": False,
        }
        if currency is not None:
            kwargs["currency"] = currency
        ret, data = ctx.accinfo_query(**kwargs)
        _ensure_ret_ok(self._sdk, ret, data, "accinfo_query")
        return [_map_cash_record(item, self._settings.currency) for item in _records(data)]

    def _query_option_chain(self, quote_ctx: Any, request: OptionChainRequest) -> list[dict[str, Any]]:
        start, end = _expiry_window(request)
        option_type = _option_type_constant(self._sdk, request.option_type)
        code = _market_code(request.underlying_symbol, self._settings.trade_market)
        ret, data = quote_ctx.get_option_chain(code=code, start=start, end=end, option_type=option_type)
        _ensure_ret_ok(self._sdk, ret, data, "get_option_chain")
        return _records(data)

    def _query_market_snapshots(self, quote_ctx: Any, codes: list[str]) -> dict[str, dict[str, Any]]:
        if not codes:
            return {}
        snapshots: dict[str, dict[str, Any]] = {}
        for offset in range(0, len(codes), self._settings.max_snapshot_codes):
            chunk = codes[offset : offset + self._settings.max_snapshot_codes]
            ret, data = quote_ctx.get_market_snapshot(chunk)
            _ensure_ret_ok(self._sdk, ret, data, "get_market_snapshot")
            for item in _records(data):
                code = _as_str(_pick(item, "code"))
                if code:
                    snapshots[code] = item
        return snapshots

    def _enrich_position_names(self, positions: list[dict[str, Any]]) -> None:
        missing_name_positions = [
            item
            for item in positions
            if not item.get("name")
            and item.get("symbol")
            and item.get("instrument_type") in {"stock", "etf"}
        ]
        if not missing_name_positions:
            return

        codes = [
            _market_code(str(item.get("symbol") or ""), str(item.get("market") or self._settings.trade_market))
            for item in missing_name_positions
        ]
        quote_ctx = self._open_quote_context()
        try:
            snapshots = self._query_market_snapshots(quote_ctx, codes)
        except FutuSidecarError:
            return
        finally:
            _close_context(quote_ctx)

        for item in missing_name_positions:
            code = _market_code(str(item.get("symbol") or ""), str(item.get("market") or self._settings.trade_market))
            name = _position_name_from_record(snapshots.get(code, {}))
            if name:
                item["name"] = name

    def _diagnose_trade_context(self, *, security_firm: str, trade_market: str) -> dict[str, Any]:
        ctx = self._open_trade_context_for(security_firm=security_firm, trade_market=trade_market)
        try:
            ret, data = ctx.get_acc_list()
            _ensure_ret_ok(self._sdk, ret, data, "get_acc_list")
            accounts = _records(data)
            selected_acc_id, selected_acc_index = _resolve_candidate_account_selector(self._settings, accounts)
            position_count: Optional[int] = None
            position_error: Optional[str] = None
            if accounts:
                try:
                    ret, positions = ctx.position_list_query(
                        trd_env=_sdk_constant(self._sdk.TrdEnv, self._settings.trade_env),
                        acc_id=selected_acc_id,
                        acc_index=selected_acc_index,
                        refresh_cache=False,
                        position_market=_sdk_constant(self._sdk.TrdMarket, trade_market),
                    )
                    _ensure_ret_ok(self._sdk, ret, positions, "position_list_query")
                    position_count = len(_records(positions))
                except FutuSidecarError as exc:
                    position_error = _sanitize_error_message(str(exc))
            return {
                "security_firm": security_firm,
                "trd_market": trade_market,
                "acc_id": _mask_identifier(selected_acc_id),
                "matches_requested": security_firm == self._settings.security_firm and trade_market == self._settings.trade_market,
                "account_count": len(accounts),
                "position_count": position_count,
                "status": "ok" if position_error is None else "partial",
                "error": position_error,
            }
        finally:
            _close_context(ctx)


def _build_reader(settings: FutuSidecarSettings) -> MockFutuSidecarReader | FutuSdkSidecarReader:
    if settings.mode == "real":
        return FutuSdkSidecarReader(settings)
    return MockFutuSidecarReader(settings)


def _health_payload(settings: FutuSidecarSettings) -> dict[str, Any]:
    return {
        "ok": True,
        "connector": "futu-opend-sidecar",
        "mode": settings.mode,
        "permission_scope": READ_ONLY_SCOPE,
        "opend": {"host": settings.opend_host, "port": settings.opend_port},
        "supports": {
            "positions": True,
            "cash_balances": True,
            "option_chain": True,
            "account_diagnostics": True,
            "place_order": False,
            "modify_order": False,
            "cancel_order": False,
        },
        "account_context": _account_context_payload(settings),
        "diagnostics": {
            "account_context_path": "/api/v1/account-diagnostics",
            "candidate_entities_in_health": False,
        },
    }


def _account_context_payload(settings: FutuSidecarSettings) -> dict[str, Any]:
    return {
        "security_firm": settings.security_firm,
        "trd_market": settings.trade_market,
        "trd_env": settings.trade_env,
        "acc_id": _mask_identifier(settings.account_id),
        "acc_index": settings.account_index,
        "currency": settings.currency,
    }


def _diagnostic_requested_payload(settings: FutuSidecarSettings) -> dict[str, Any]:
    return {
        "security_firm": settings.security_firm,
        "trd_market": settings.trade_market,
        "acc_id": _mask_identifier(settings.account_id),
    }


def _snapshot_payload(
    *,
    request: SnapshotRequest,
    settings: FutuSidecarSettings,
    as_of: datetime,
    received_at: datetime,
    positions: list[dict[str, Any]],
    cash_balances: list[dict[str, Any]],
    missing_fields: list[str],
    status: Literal["complete", "partial"],
    provider: str,
) -> dict[str, Any]:
    return {
        "tenant_id": request.tenant_id,
        "broker_connection_id": request.broker_connection_id,
        "broker": "futu",
        "source_key": SOURCE_KEY,
        "source_tier": SOURCE_TIER,
        "connector_mode": "local_connector",
        "permission_scope": READ_ONLY_SCOPE,
        "as_of": as_of,
        "received_at": received_at,
        "positions": positions,
        "cash_balances": cash_balances,
        "missing_fields": missing_fields,
        "status": status,
        "lineage": {
            "read_mode": "local_connector",
            "read_only": True,
            "provider": provider,
            "sidecar_mode": settings.mode,
            "opend_host": settings.opend_host,
            "opend_port": settings.opend_port,
            "snapshot_label": request.snapshot_label,
            "account_context": _account_context_payload(settings),
        },
    }


def _option_chain_payload(
    *,
    request: OptionChainRequest,
    settings: FutuSidecarSettings,
    as_of: datetime,
    received_at: datetime,
    contracts: list[dict[str, Any]],
    missing_fields: list[str],
    status: Literal["complete", "partial"],
    provider: str,
) -> dict[str, Any]:
    return {
        "tenant_id": request.tenant_id,
        "broker_connection_id": request.broker_connection_id,
        "underlying_symbol": request.underlying_symbol.upper(),
        "broker": "futu",
        "source_key": SOURCE_KEY,
        "source_tier": SOURCE_TIER,
        "connector_mode": "local_connector",
        "permission_scope": READ_ONLY_SCOPE,
        "as_of": as_of,
        "received_at": received_at,
        "contracts": contracts,
        "missing_fields": missing_fields,
        "status": status,
        "lineage": {
            "read_mode": "local_connector",
            "read_only": True,
            "provider": provider,
            "sidecar_mode": settings.mode,
            "opend_host": settings.opend_host,
            "opend_port": settings.opend_port,
            "snapshot_label": request.snapshot_label,
            "account_context": _account_context_payload(settings),
        },
    }


def _map_position_record(item: dict[str, Any], default_currency: str) -> dict[str, Any]:
    code = _as_str(_pick(item, "code", "symbol"))
    symbol = _strip_market_prefix(code)
    name = _position_name_from_record(item)
    option_parts = _parse_option_symbol(symbol)
    market = _as_str(_pick(item, "position_market", "market")) or _market_from_code(code)
    quantity = _to_float(_pick(item, "qty", "quantity", "position"))
    average_cost = _to_float(_pick(item, "average_cost", "cost_price", "diluted_cost"))
    market_price = _to_float(_pick(item, "nominal_price", "market_price", "last_price"))
    currency = _as_str(_pick(item, "currency")) or default_currency
    asset_category = _as_str(_pick(item, "asset_category", "security_type")).lower()
    instrument_type = "option_contract" if option_parts else ("etf" if "etf" in asset_category else "stock")
    return {
        "symbol": symbol,
        "name": name or None,
        "market": market or "US",
        "instrument_type": instrument_type,
        "quantity": quantity or 0.0,
        "average_cost": average_cost,
        "market_price": market_price,
        "currency": currency,
        "option_type": option_parts.get("option_type") if option_parts else None,
        "strike": option_parts.get("strike") if option_parts else None,
        "expiry": option_parts.get("expiry") if option_parts else None,
    }


def _position_name_from_record(item: dict[str, Any]) -> str:
    return _as_str(
        _pick(
            item,
            "name",
            "stock_name",
            "security_name",
            "short_name",
            "stock_name_en",
            "stock_name_cn",
            "sec_name",
        )
    )


def _map_cash_record(item: dict[str, Any], default_currency: str) -> dict[str, Any]:
    currency = _as_str(_pick(item, "currency")) or default_currency
    currency_key = currency.lower()
    available_cash = _to_float(
        _pick(
            item,
            f"{currency_key}_net_cash_power",
            "net_cash_power",
            "available_cash",
            "cash",
            "power",
        )
    )
    buying_power = _to_float(_pick(item, f"{currency_key}_power", "buying_power", "power"))
    return {
        "currency": currency,
        "available_cash": available_cash or 0.0,
        "buying_power": buying_power,
        "cash_secured_reserve": _to_float(_pick(item, "cash_secured_reserve")),
    }


def _map_option_contract(
    *,
    chain_item: dict[str, Any],
    snapshot: dict[str, Any],
    request: OptionChainRequest,
    as_of: datetime,
) -> dict[str, Any]:
    code = _as_str(_pick(chain_item, "code", "contract_code"))
    symbol = _strip_market_prefix(code)
    expiry = _as_str(_pick(snapshot, "strike_time", "option_expiry_date", "expiry") or _pick(chain_item, "strike_time", "expiry"))
    strike = _to_float(_pick(snapshot, "option_strike_price", "strike") or _pick(chain_item, "strike_price", "option_strike_price", "strike"))
    option_type = _normalize_option_type(_pick(snapshot, "option_type") or _pick(chain_item, "option_type") or request.option_type)
    days_to_expiry = _to_int(_pick(snapshot, "option_expiry_date_distance", "days_to_expiry") or _days_to_expiry(expiry))
    return {
        "contract_symbol": symbol,
        "underlying_symbol": request.underlying_symbol.upper(),
        "option_type": option_type,
        "strike": strike or 0.0,
        "expiry": expiry or "",
        "days_to_expiry": days_to_expiry or 0,
        "bid": _to_float(_pick(snapshot, "bid_price", "bid")),
        "ask": _to_float(_pick(snapshot, "ask_price", "ask")),
        "delta": _to_float(_pick(snapshot, "option_delta", "delta") or _pick(chain_item, "delta")),
        "implied_volatility": _normalize_percent(_to_float(_pick(snapshot, "option_implied_volatility", "implied_volatility") or _pick(chain_item, "implied_volatility"))),
        "open_interest": _to_int(_pick(snapshot, "option_open_interest", "open_interest") or _pick(chain_item, "open_interest")),
        "volume": _to_int(_pick(snapshot, "volume")),
        "currency": _as_str(_pick(snapshot, "currency")) or "USD",
        "as_of": _parse_datetime(_pick(snapshot, "update_time")) or as_of,
        "source_key": SOURCE_KEY,
        "source_tier": SOURCE_TIER,
    }


def _records(data: Any) -> list[dict[str, Any]]:
    if data is None:
        return []
    if hasattr(data, "to_dict"):
        return [dict(item) for item in data.to_dict(orient="records")]
    if isinstance(data, list):
        return [dict(item) for item in data if isinstance(item, dict)]
    if isinstance(data, dict):
        return [dict(data)]
    return []


def _ensure_ret_ok(sdk: Any, ret: Any, data: Any, method_name: str) -> None:
    ret_ok = getattr(sdk, "RET_OK", 0)
    if ret != ret_ok:
        raise FutuSidecarError(f"{method_name} failed: {data}")


def _import_futu_sdk(module_name: str) -> Any:
    try:
        return importlib.import_module(module_name)
    except ImportError as first_exc:
        if module_name != "moomoo":
            try:
                return importlib.import_module("moomoo")
            except ImportError:
                pass
        raise FutuSidecarError(
            "Futu SDK is not installed. Install futu-api/moomoo in the local sidecar environment or use FUTU_SIDECAR_MODE=mock."
        ) from first_exc


def _sdk_constant(container: Any, name: str, *, required: bool = True) -> Any:
    normalized = str(name).strip().upper()
    for candidate in (normalized, normalized.replace("-", "_"), name):
        if hasattr(container, candidate):
            return getattr(container, candidate)
    if required:
        raise FutuSidecarError(f"Futu SDK constant not found: {name}")
    return None


def _option_type_constant(sdk: Any, option_type: str) -> Any:
    if option_type == "put":
        return _sdk_constant(sdk.OptionType, "PUT")
    if option_type == "call":
        return _sdk_constant(sdk.OptionType, "CALL")
    return _sdk_constant(sdk.OptionType, "ALL")


def _close_context(ctx: Any) -> None:
    close = getattr(ctx, "close", None)
    if callable(close):
        close()


def _pick(item: dict[str, Any], *names: str) -> Any:
    for name in names:
        if name in item:
            value = item[name]
            if not _is_blank(value):
                return value
    return None


def _is_blank(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, float) and math.isnan(value):
        return True
    if str(value).strip() in {"", "--", "N/A", "nan", "None"}:
        return True
    return False


def _to_float(value: Any) -> Optional[float]:
    if _is_blank(value):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _to_int(value: Any) -> Optional[int]:
    if _is_blank(value):
        return None
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return None


def _as_str(value: Any) -> str:
    if _is_blank(value):
        return ""
    return str(value).strip()


def _strip_market_prefix(code: str) -> str:
    return code.split(".", 1)[1] if "." in code else code


def _market_from_code(code: str) -> str:
    return code.split(".", 1)[0] if "." in code else ""


def _market_code(symbol: str, market: str) -> str:
    if "." in symbol:
        return symbol
    return f"{market.upper()}.{symbol.upper()}"


def _parse_option_symbol(symbol: str) -> dict[str, Any]:
    match = re.match(r"^([A-Z]{1,8})(\d{6})([CP])(\d+(?:\.\d+)?)$", symbol.upper())
    if not match:
        return {}
    _, yymmdd, side, strike_text = match.groups()
    expiry = f"20{yymmdd[0:2]}-{yymmdd[2:4]}-{yymmdd[4:6]}"
    return {
        "option_type": "put" if side == "P" else "call",
        "strike": _parse_option_strike(strike_text),
        "expiry": expiry,
    }


def _parse_option_strike(value: str) -> float:
    if "." in value:
        return float(value)
    if len(value) >= 6:
        return float(value) / 1000.0
    return float(value)


def _normalize_option_type(value: Any) -> str:
    normalized = _as_str(value).lower()
    if "put" in normalized or normalized in {"p", "2"}:
        return "put"
    if "call" in normalized or normalized in {"c", "1"}:
        return "call"
    return "put"


def _normalize_percent(value: Optional[float]) -> Optional[float]:
    if value is None:
        return None
    return value / 100 if value > 1 else value


def _parse_datetime(value: Any) -> Optional[datetime]:
    if _is_blank(value):
        return None
    raw = _as_str(value)
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%d"):
        try:
            parsed = datetime.strptime(raw, fmt)
            return parsed.replace(tzinfo=timezone.utc) if parsed.tzinfo is None else parsed
        except ValueError:
            continue
    return None


def _days_to_expiry(expiry: str) -> Optional[int]:
    if not expiry:
        return None
    try:
        return max((date.fromisoformat(expiry) - date.today()).days, 0)
    except ValueError:
        return None


def _expiry_window(request: OptionChainRequest) -> tuple[str, str]:
    today = date.today()
    start_days = request.min_days_to_expiry if request.min_days_to_expiry is not None else 0
    end_days = request.max_days_to_expiry if request.max_days_to_expiry is not None else 60
    return (today + timedelta(days=start_days)).isoformat(), (today + timedelta(days=end_days)).isoformat()


def _option_contract_matches(item: dict[str, Any], request: OptionChainRequest) -> bool:
    if request.option_type != "all" and item.get("option_type") != request.option_type:
        return False
    dte = item.get("days_to_expiry")
    if dte is not None:
        dte_value = int(dte)
        if request.min_days_to_expiry is not None and dte_value < request.min_days_to_expiry:
            return False
        if request.max_days_to_expiry is not None and dte_value > request.max_days_to_expiry:
            return False
    return True


def _diagnostic_security_firms(sdk: Any, current: str) -> list[str]:
    preferred = [current.upper(), "FUTUSECURITIES", "FUTUINC", "FUTUSG", "FUTUAU", "FUTUCA"]
    return _dedupe_candidates(
        name for name in preferred if hasattr(sdk.SecurityFirm, str(name).upper())
    )


def _diagnostic_trade_markets(sdk: Any, current: str) -> list[str]:
    preferred = [current.upper(), "US", "HK", "HKCC", "SG", "AU", "CA"]
    return _dedupe_candidates(
        name for name in preferred if hasattr(sdk.TrdMarket, str(name).upper())
    )


def _dedupe_candidates(values: list[str] | tuple[str, ...] | Any) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        normalized = _as_str(value).upper()
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        result.append(normalized)
    return result


def _dedupe_messages(messages: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for message in messages:
        normalized = message.strip()
        if not normalized:
            continue
        key = normalized.casefold()
        if key in seen:
            continue
        seen.add(key)
        result.append(normalized)
    return result


def _resolve_candidate_account_selector(
    settings: FutuSidecarSettings,
    accounts: list[dict[str, Any]],
) -> tuple[int, int]:
    configured_acc_id = settings.account_id
    configured_acc_index = settings.account_index
    if configured_acc_id:
        for item in accounts:
            if _to_int(_pick(item, "acc_id")) == configured_acc_id:
                return configured_acc_id, configured_acc_index
    if accounts:
        first_acc_id = _to_int(_pick(accounts[0], "acc_id"))
        if first_acc_id is not None:
            return first_acc_id, 0
    return configured_acc_id, configured_acc_index


def _build_diagnostic_recommendations(requested: dict[str, Any], candidates: list[dict[str, Any]]) -> list[str]:
    matching = next((item for item in candidates if item.get("matches_requested")), None)
    non_zero_candidates = [item for item in candidates if (item.get("position_count") or 0) > 0]
    total_accounts = sum(int(item.get("account_count") or 0) for item in candidates)
    messages: list[str] = []

    if any(item.get("status") == "partial" for item in candidates):
        messages.append("部分候选组合查询失败；确认 OpenD 已登录目标账户，且 sidecar 正在使用 real + read_only 模式。")

    if non_zero_candidates:
        preferred = non_zero_candidates[0]
        if matching is None or (matching.get("position_count") or 0) == 0:
            messages.append(
                "发现非当前请求组合存在持仓；优先核对 security_firm/trd_market/acc_id，"
                f"可先尝试 {preferred['security_firm']}/{preferred['trd_market']}/{preferred['acc_id']}。"
            )
        if matching and matching.get("acc_id") != requested.get("acc_id"):
            messages.append(
                f"当前请求 acc_id={requested.get('acc_id', '-')} 未命中可读账户，"
                f"实际命中 acc_id={matching.get('acc_id', '-')}；请核对 acc_id 配置。"
            )
    elif total_accounts == 0:
        messages.append("未发现可读账户；确认 OpenD 已登录到目标券商实体，并已打开对应市场的交易连接。")
    else:
        messages.append("已发现账户但持仓数量均为 0；若账户实际有持仓，请逐项核对 security_firm/trd_market/acc_id。")

    if not messages:
        messages.append("诊断结果未发现明显异常；若同步仍为空，请重新运行本地 diagnostic 复查当前配置。")
    return _dedupe_messages(messages)


def _mask_identifier(value: Any) -> str:
    raw = _as_str(value)
    if not raw:
        return ""
    if raw == "0":
        return "0"
    if len(raw) <= 4:
        return "*" * len(raw)
    return f"{'*' * (len(raw) - 4)}{raw[-4:]}"


def _sanitize_error_message(message: str) -> str:
    return re.sub(r"\d{4,}", lambda match: _mask_identifier(match.group(0)), message)


def _enforce_request_read_only(permission_scope: str) -> None:
    if permission_scope != READ_ONLY_SCOPE:
        raise HTTPException(status_code=403, detail={"ok": False, "message": "Futu sidecar is read-only"})


def _normalize_sidecar_mode(value: str) -> Literal["mock", "real"]:
    return "real" if value.strip().lower() in {"real", "opend", "futu"} else "mock"


app = create_app()


def main() -> None:
    import uvicorn

    host = os.getenv("FUTU_SIDECAR_HOST", "127.0.0.1")
    port = int(os.getenv("FUTU_SIDECAR_PORT", "8765"))
    uvicorn.run("local_connectors.futu_opend.server:app", host=host, port=port, reload=False)


if __name__ == "__main__":
    main()
