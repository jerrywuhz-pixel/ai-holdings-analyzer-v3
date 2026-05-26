from __future__ import annotations

"""
Futu read-only local connector boundary.

P0 keeps the cloud service read-only and token-free. Real Futu OpenD access is
expected to happen through a local sidecar process on the user's machine. This
adapter can either use the deterministic local mock or call that sidecar over
HTTP, while preserving lineage and explicit fallback markers.
"""

import os
from datetime import datetime, timedelta, timezone
from typing import Any, Literal, Optional

import httpx
from pydantic import BaseModel, Field


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


class FutuPositionSnapshot(BaseModel):
    symbol: str
    name: Optional[str] = None
    market: str
    instrument_type: Literal["stock", "etf", "option_contract"]
    quantity: float
    average_cost: Optional[float] = None
    market_price: Optional[float] = None
    currency: str
    option_type: Optional[Literal["put", "call"]] = None
    strike: Optional[float] = None
    expiry: Optional[str] = None


class FutuCashSnapshot(BaseModel):
    currency: str
    available_cash: float
    buying_power: Optional[float] = None
    cash_secured_reserve: Optional[float] = None


ConnectorMode = Literal["local_mock", "local_connector"]
ConnectorModeRequest = Literal["auto", "local_mock", "local_connector"]


class FutuAccountSnapshot(BaseModel):
    tenant_id: str
    broker_connection_id: str
    broker: Literal["futu"] = "futu"
    source_key: Literal["futu_openapi"] = "futu_openapi"
    source_tier: Literal["L1_trading"] = "L1_trading"
    connector_mode: ConnectorMode = "local_mock"
    permission_scope: Literal["read_only"] = "read_only"
    as_of: datetime
    received_at: datetime
    positions: list[FutuPositionSnapshot] = Field(default_factory=list)
    cash_balances: list[FutuCashSnapshot] = Field(default_factory=list)
    missing_fields: list[str] = Field(default_factory=list)
    status: Literal["complete", "partial"] = "complete"
    lineage: dict[str, Any] = Field(default_factory=dict)


class FutuSnapshotReadRequest(BaseModel):
    tenant_id: str
    broker_connection_id: str
    snapshot_label: str = "default"
    include_positions: bool = True
    include_cash: bool = True
    connector_mode: ConnectorModeRequest = "auto"
    allow_mock_fallback: bool = False


class FutuOptionChainContract(BaseModel):
    contract_symbol: str
    underlying_symbol: str
    option_type: Literal["put", "call"]
    strike: float
    expiry: str
    days_to_expiry: int
    bid: Optional[float] = None
    ask: Optional[float] = None
    delta: Optional[float] = None
    implied_volatility: Optional[float] = None
    open_interest: Optional[int] = None
    volume: Optional[int] = None
    currency: str = "USD"
    as_of: datetime
    source_key: Literal["futu_openapi"] = "futu_openapi"
    source_tier: Literal["L1_trading"] = "L1_trading"


class FutuOptionChainSnapshot(BaseModel):
    tenant_id: str
    broker_connection_id: str
    underlying_symbol: str
    broker: Literal["futu"] = "futu"
    source_key: Literal["futu_openapi"] = "futu_openapi"
    source_tier: Literal["L1_trading"] = "L1_trading"
    connector_mode: ConnectorMode = "local_mock"
    permission_scope: Literal["read_only"] = "read_only"
    as_of: datetime
    received_at: datetime
    contracts: list[FutuOptionChainContract] = Field(default_factory=list)
    missing_fields: list[str] = Field(default_factory=list)
    status: Literal["complete", "partial"] = "complete"
    lineage: dict[str, Any] = Field(default_factory=dict)


class FutuOptionChainReadRequest(BaseModel):
    tenant_id: str
    broker_connection_id: str
    underlying_symbol: str
    snapshot_label: str = "default"
    option_type: Literal["put", "call", "all"] = "put"
    min_days_to_expiry: Optional[int] = None
    max_days_to_expiry: Optional[int] = None
    connector_mode: ConnectorModeRequest = "auto"
    allow_mock_fallback: bool = False


class FutuQuoteReadRequest(BaseModel):
    symbols: list[str]
    market: str = "US"
    connector_mode: ConnectorModeRequest = "auto"
    allow_mock_fallback: bool = False


class FutuConnectorError(RuntimeError):
    """Raised when the local Futu connector is unavailable or violates policy."""


class FutuReadOnlyConnector:
    """
    本地 Futu connector 边界。

    - local_mock: deterministic fixtures for local P0 tests.
    - local_connector: HTTP boundary to a user's local OpenD sidecar.
    """

    def __init__(
        self,
        *,
        mode: str | None = None,
        base_url: str | None = None,
        snapshot_path: str | None = None,
        option_chain_path: str | None = None,
        health_path: str | None = None,
        timeout_seconds: float | None = None,
    ) -> None:
        self._mode = _normalize_mode(mode or os.getenv("FUTU_CONNECTOR_MODE", "local_mock"))
        self._base_url = (base_url or os.getenv("FUTU_CONNECTOR_BASE_URL", "http://localhost:8765")).rstrip("/")
        self._snapshot_path = snapshot_path or os.getenv("FUTU_CONNECTOR_SNAPSHOT_PATH") or os.getenv(
            "FUTU_CONNECTOR_UPLOAD_PATH",
            "/api/v1/snapshots",
        )
        self._option_chain_path = option_chain_path or os.getenv(
            "FUTU_CONNECTOR_OPTION_CHAIN_PATH",
            "/api/v1/option-chain",
        )
        self._quotes_path = os.getenv("FUTU_CONNECTOR_QUOTES_PATH", "/api/v1/quotes")
        self._health_path = health_path or os.getenv("FUTU_CONNECTOR_HEARTBEAT_PATH", "/health")
        self._timeout_seconds = timeout_seconds or float(os.getenv("FUTU_CONNECTOR_TIMEOUT_SECONDS", "8"))
        self._snapshots: dict[str, dict[str, Any]] = {
            "default": {
                "positions": [
                    {
                        "symbol": "AAPL",
                        "market": "US",
                        "instrument_type": "stock",
                        "quantity": 100,
                        "average_cost": 182.5,
                        "market_price": 191.2,
                        "currency": "USD",
                    },
                    {
                        "symbol": "AAPL240621P170",
                        "market": "US",
                        "instrument_type": "option_contract",
                        "quantity": -1,
                        "average_cost": 4.8,
                        "market_price": 3.9,
                        "currency": "USD",
                        "option_type": "put",
                        "strike": 170,
                        "expiry": "2026-06-21",
                    },
                ],
                "cash_balances": [
                    {
                        "currency": "USD",
                        "available_cash": 25000.0,
                        "buying_power": 48000.0,
                        "cash_secured_reserve": 17000.0,
                    }
                ],
                "missing_fields": [],
                "status": "complete",
            }
        }
        self._option_chains: dict[str, list[dict[str, Any]]] = {
            "default:AAPL": [
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
                },
            ]
        }

    def capabilities(self) -> dict[str, Any]:
        mode = self._mode
        health = self._read_local_connector_health() if mode == "local_connector" else None
        account_context = _configured_account_context()
        diagnostics = {
            "sidecar_health_url": f"{self._base_url}{_ensure_leading_slash(self._health_path)}",
            "account_context_path": "/api/v1/account-diagnostics",
        }
        if isinstance(health, dict):
            if isinstance(health.get("account_context"), dict):
                account_context = dict(health["account_context"])
            if isinstance(health.get("diagnostics"), dict):
                diagnostics.update(dict(health["diagnostics"]))
            diagnostics["sidecar_health_ok"] = True
        elif isinstance(health, str):
            diagnostics["sidecar_health_ok"] = False
            diagnostics["sidecar_health_error"] = health
        return {
            "broker": "futu",
            "connector_mode": mode,
            "permission_scope": "read_only",
            "account_context": account_context,
            "local_connector": {
                "base_url": self._base_url,
                "health_path": self._health_path,
                "snapshot_path": self._snapshot_path,
                "option_chain_path": self._option_chain_path,
            },
            "diagnostics": diagnostics,
            "supports": {
                "quotes": True,
                "positions": True,
                "cash_balances": True,
                "option_positions": True,
                "option_chain": True,
                "account_diagnostics": True,
                "place_order": False,
                "modify_order": False,
                "cancel_order": False,
            },
            "notes": [
                "P0 uses read-only local connector boundaries only.",
                "No OpenD token persistence or trading operation is implemented.",
                "If fallback is enabled, fallback snapshots are explicitly marked local_mock and partial.",
            ],
        }

    async def read_account_snapshot(
        self,
        request: FutuSnapshotReadRequest,
        snapshot_override: Optional[dict[str, Any]] = None,
    ) -> FutuAccountSnapshot:
        mode = self._resolve_request_mode(request.connector_mode)
        if mode == "local_connector":
            try:
                return await self._read_account_snapshot_from_local_connector(request)
            except Exception as exc:
                if not request.allow_mock_fallback:
                    raise FutuConnectorError(str(exc)) from exc
                return await self._read_account_snapshot_from_mock(
                    request,
                    snapshot_override=snapshot_override,
                    fallback_reason=str(exc),
                )
        return await self._read_account_snapshot_from_mock(
            request,
            snapshot_override=snapshot_override,
        )

    async def read_option_chain(
        self,
        request: FutuOptionChainReadRequest,
        chain_override: Optional[list[dict[str, Any]]] = None,
    ) -> FutuOptionChainSnapshot:
        mode = self._resolve_request_mode(request.connector_mode)
        if mode == "local_connector":
            try:
                return await self._read_option_chain_from_local_connector(request)
            except Exception as exc:
                if not request.allow_mock_fallback:
                    raise FutuConnectorError(str(exc)) from exc
                return await self._read_option_chain_from_mock(
                    request,
                    chain_override=chain_override,
                    fallback_reason=str(exc),
                )
        return await self._read_option_chain_from_mock(
            request,
            chain_override=chain_override,
        )

    async def read_quotes(
        self,
        request: FutuQuoteReadRequest,
    ) -> dict[str, Any]:
        mode = self._resolve_request_mode(request.connector_mode)
        if mode == "local_connector":
            try:
                return await self._read_quotes_from_local_connector(request)
            except Exception as exc:
                if not request.allow_mock_fallback:
                    raise FutuConnectorError(str(exc)) from exc
                return await self._read_quotes_from_mock(request, fallback_reason=str(exc))
        return await self._read_quotes_from_mock(request)

    async def _read_account_snapshot_from_mock(
        self,
        request: FutuSnapshotReadRequest,
        *,
        snapshot_override: Optional[dict[str, Any]] = None,
        fallback_reason: str | None = None,
    ) -> FutuAccountSnapshot:
        now = _utc_now()
        payload = snapshot_override or self._snapshots.get(request.snapshot_label) or self._snapshots["default"]

        positions = payload.get("positions", []) if request.include_positions else []
        cash_balances = payload.get("cash_balances", []) if request.include_cash else []
        missing_fields = list(payload.get("missing_fields", []))

        if request.include_cash and "cash_balances" not in payload:
            missing_fields.append("cash_balances")
        if request.include_positions and "positions" not in payload:
            missing_fields.append("positions")
        if fallback_reason:
            missing_fields.append("local_connector_unavailable")

        status = "complete" if not missing_fields else "partial"
        as_of = payload.get("as_of") or (now - timedelta(seconds=12))

        return FutuAccountSnapshot(
            tenant_id=request.tenant_id,
            broker_connection_id=request.broker_connection_id,
            connector_mode="local_mock",
            as_of=as_of,
            received_at=now,
            positions=[FutuPositionSnapshot.model_validate(item) for item in positions],
            cash_balances=[FutuCashSnapshot.model_validate(item) for item in cash_balances],
            missing_fields=missing_fields,
            status=status,
            lineage={
                "read_mode": "local_mock",
                "read_only": True,
                "snapshot_label": request.snapshot_label,
                "provider": "futu_opend_local_connector_mock",
                "fallback_used": fallback_reason is not None,
                "fallback_reason": fallback_reason,
            },
        )

    async def _read_option_chain_from_mock(
        self,
        request: FutuOptionChainReadRequest,
        *,
        chain_override: Optional[list[dict[str, Any]]] = None,
        fallback_reason: str | None = None,
    ) -> FutuOptionChainSnapshot:
        now = _utc_now()
        key = f"{request.snapshot_label}:{request.underlying_symbol.upper()}"
        raw_contracts = chain_override or self._option_chains.get(key) or []
        contracts = [
            _with_default_as_of(item, now - timedelta(seconds=10))
            for item in raw_contracts
            if _option_contract_matches(item, request)
        ]
        missing_fields: list[str] = []
        if not contracts:
            missing_fields.append("option_chain")
        if fallback_reason:
            missing_fields.append("local_connector_unavailable")
        return FutuOptionChainSnapshot(
            tenant_id=request.tenant_id,
            broker_connection_id=request.broker_connection_id,
            underlying_symbol=request.underlying_symbol.upper(),
            connector_mode="local_mock",
            as_of=max((item["as_of"] for item in contracts), default=now - timedelta(seconds=10)),
            received_at=now,
            contracts=[FutuOptionChainContract.model_validate(item) for item in contracts],
            missing_fields=missing_fields,
            status="complete" if not missing_fields else "partial",
            lineage={
                "read_mode": "local_mock",
                "read_only": True,
                "snapshot_label": request.snapshot_label,
                "provider": "futu_opend_local_connector_mock",
                "fallback_used": fallback_reason is not None,
                "fallback_reason": fallback_reason,
            },
        )

    async def _read_quotes_from_mock(
        self,
        request: FutuQuoteReadRequest,
        *,
        fallback_reason: str | None = None,
    ) -> dict[str, Any]:
        now = _utc_now()
        quotes: list[dict[str, Any]] = []
        for symbol in request.symbols:
            normalized = symbol.upper()
            for payload in self._snapshots.values():
                for position in payload.get("positions", []):
                    if str(position.get("symbol", "")).upper() != normalized:
                        continue
                    if position.get("market_price") is None:
                        continue
                    quotes.append({
                        "symbol": normalized,
                        "name": position.get("name"),
                        "market": position.get("market") or request.market,
                        "exchange": position.get("market") or request.market,
                        "price": float(position["market_price"]),
                        "change": None,
                        "change_rate": None,
                        "currency": position.get("currency") or "USD",
                        "timestamp": int((now - timedelta(seconds=12)).timestamp()),
                    })
                    break
        missing_fields = []
        if len(quotes) != len(request.symbols):
            missing_fields.append("quotes")
        if fallback_reason:
            missing_fields.append("local_connector_unavailable")
        return {
            "connector_mode": "local_mock",
            "permission_scope": "read_only",
            "source_key": "futu_openapi",
            "source_tier": "L1_trading",
            "as_of": (now - timedelta(seconds=12)).isoformat(),
            "received_at": now.isoformat(),
            "quotes": quotes,
            "missing_fields": missing_fields,
            "status": "complete" if not missing_fields else "partial",
            "lineage": {
                "read_mode": "local_mock",
                "read_only": True,
                "provider": "futu_opend_local_connector_mock",
                "fallback_used": fallback_reason is not None,
                "fallback_reason": fallback_reason,
            },
        }

    async def _read_account_snapshot_from_local_connector(
        self,
        request: FutuSnapshotReadRequest,
    ) -> FutuAccountSnapshot:
        payload = await self._post_local_connector(
            self._snapshot_path,
            {
                **request.model_dump(mode="json"),
                "connector_mode": "local_connector",
                "permission_scope": "read_only",
            },
        )
        data = _unwrap_response_data(payload)
        data.setdefault("tenant_id", request.tenant_id)
        data.setdefault("broker_connection_id", request.broker_connection_id)
        data.setdefault("connector_mode", "local_connector")
        data.setdefault("permission_scope", "read_only")
        data.setdefault("source_key", "futu_openapi")
        data.setdefault("source_tier", "L1_trading")
        data.setdefault("received_at", _utc_now())
        data.setdefault("as_of", data["received_at"])
        missing_fields = list(data.get("missing_fields") or [])
        if request.include_positions and "positions" not in data:
            missing_fields.append("positions")
        if request.include_cash and "cash_balances" not in data:
            missing_fields.append("cash_balances")
        data["missing_fields"] = missing_fields
        data["status"] = "complete" if not missing_fields else "partial"
        data["lineage"] = {
            **(data.get("lineage") or {}),
            "read_mode": "local_connector",
            "read_only": True,
            "provider": "futu_opend_local_connector",
        }
        snapshot = FutuAccountSnapshot.model_validate(data)
        _enforce_read_only(snapshot.permission_scope)
        return snapshot

    async def _read_option_chain_from_local_connector(
        self,
        request: FutuOptionChainReadRequest,
    ) -> FutuOptionChainSnapshot:
        payload = await self._post_local_connector(
            self._option_chain_path,
            {
                **request.model_dump(mode="json"),
                "connector_mode": "local_connector",
                "permission_scope": "read_only",
            },
        )
        data = _unwrap_response_data(payload)
        data.setdefault("tenant_id", request.tenant_id)
        data.setdefault("broker_connection_id", request.broker_connection_id)
        data.setdefault("underlying_symbol", request.underlying_symbol.upper())
        data.setdefault("connector_mode", "local_connector")
        data.setdefault("permission_scope", "read_only")
        data.setdefault("source_key", "futu_openapi")
        data.setdefault("source_tier", "L1_trading")
        data.setdefault("received_at", _utc_now())
        data.setdefault("as_of", data["received_at"])
        raw_contracts = data.get("contracts")
        if raw_contracts is None:
            raw_contracts = []
        if not isinstance(raw_contracts, list):
            raise FutuConnectorError("local connector option chain contracts must be a list")
        normalized_contracts = []
        for item in raw_contracts:
            if not isinstance(item, dict):
                raise FutuConnectorError("local connector option chain contract must be an object")
            normalized_contracts.append(
                {
                    **item,
                    "underlying_symbol": item.get("underlying_symbol") or data["underlying_symbol"],
                    "currency": item.get("currency") or "USD",
                    "as_of": item.get("as_of") or data["as_of"],
                    "source_key": item.get("source_key") or data["source_key"],
                    "source_tier": item.get("source_tier") or data["source_tier"],
                }
            )
        missing_fields = list(data.get("missing_fields") or [])
        if not normalized_contracts:
            missing_fields.append("option_chain")
        data["contracts"] = normalized_contracts
        data["missing_fields"] = missing_fields
        data["status"] = "complete" if not missing_fields else "partial"
        data["lineage"] = {
            **(data.get("lineage") or {}),
            "read_mode": "local_connector",
            "read_only": True,
            "provider": "futu_opend_local_connector",
        }
        snapshot = FutuOptionChainSnapshot.model_validate(data)
        _enforce_read_only(snapshot.permission_scope)
        return snapshot

    async def _read_quotes_from_local_connector(
        self,
        request: FutuQuoteReadRequest,
    ) -> dict[str, Any]:
        payload = await self._post_local_connector(
            self._quotes_path,
            {
                **request.model_dump(mode="json"),
                "connector_mode": "local_connector",
                "permission_scope": "read_only",
            },
        )
        data = _unwrap_response_data(payload)
        raw_quotes = data.get("quotes")
        if not isinstance(raw_quotes, list):
            raise FutuConnectorError("local connector quote response must include quotes list")
        missing_fields = list(data.get("missing_fields") or [])
        if len(raw_quotes) != len(request.symbols):
            missing_fields.append("quotes")
        return {
            **data,
            "connector_mode": data.get("connector_mode") or "local_connector",
            "permission_scope": data.get("permission_scope") or "read_only",
            "source_key": data.get("source_key") or "futu_openapi",
            "source_tier": data.get("source_tier") or "L1_trading",
            "quotes": raw_quotes,
            "missing_fields": missing_fields,
            "status": "complete" if not missing_fields else "partial",
            "lineage": {
                **(data.get("lineage") or {}),
                "read_mode": "local_connector",
                "read_only": True,
                "provider": "futu_opend_local_connector",
            },
        }

    async def _post_local_connector(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        url = f"{self._base_url}{_ensure_leading_slash(path)}"
        async with httpx.AsyncClient(timeout=self._timeout_seconds) as client:
            response = await client.post(url, json=payload)
            response.raise_for_status()
            try:
                data = response.json()
            except ValueError as exc:
                raise FutuConnectorError("local connector returned non-JSON response") from exc
            if not isinstance(data, dict):
                raise FutuConnectorError("local connector response must be an object")
            return data

    def _read_local_connector_health(self) -> dict[str, Any] | str | None:
        url = f"{self._base_url}{_ensure_leading_slash(self._health_path)}"
        timeout = min(self._timeout_seconds, 2.0)
        try:
            with httpx.Client(timeout=timeout) as client:
                response = client.get(url)
                response.raise_for_status()
                data = response.json()
        except Exception as exc:
            return _sanitize_error_message(str(exc))
        if not isinstance(data, dict):
            return "local connector health response must be an object"
        return data

    def _resolve_request_mode(self, request_mode: ConnectorModeRequest) -> ConnectorMode:
        if request_mode != "auto":
            return request_mode
        return self._mode


FutuLocalConnectorMock = FutuReadOnlyConnector


def _normalize_mode(value: str) -> ConnectorMode:
    normalized = value.strip().lower().replace("-", "_")
    if normalized in {"local_stub", "mock", "stub", "local_mock"}:
        return "local_mock"
    if normalized in {"local_connector", "connector", "http", "opend"}:
        return "local_connector"
    return "local_mock"


def _unwrap_response_data(payload: dict[str, Any]) -> dict[str, Any]:
    data = payload.get("data", payload)
    if not isinstance(data, dict):
        raise FutuConnectorError("local connector data payload must be an object")
    if payload.get("ok") is False:
        raise FutuConnectorError(
            _sanitize_error_message(str(payload.get("message") or payload.get("error") or "local connector failed"))
        )
    return dict(data)


def _enforce_read_only(permission_scope: str) -> None:
    if permission_scope != "read_only":
        raise FutuConnectorError("local connector must return permission_scope=read_only")


def _ensure_leading_slash(path: str) -> str:
    return path if path.startswith("/") else f"/{path}"


def _with_default_as_of(item: dict[str, Any], as_of: datetime) -> dict[str, Any]:
    return {
        **item,
        "as_of": item.get("as_of") or as_of,
    }


def _configured_account_context() -> dict[str, Any]:
    return {
        "security_firm": os.getenv("FUTU_SECURITY_FIRM", "FUTUINC"),
        "trd_market": os.getenv("FUTU_TRD_MARKET", "US"),
        "trd_env": os.getenv("FUTU_TRD_ENV", "REAL"),
        "acc_id": _mask_identifier(os.getenv("FUTU_ACC_ID", "0")),
        "acc_index": int(os.getenv("FUTU_ACC_INDEX", "0")),
    }


def _mask_identifier(value: Any) -> str:
    raw = str(value).strip()
    if not raw:
        return ""
    if raw == "0":
        return "0"
    if len(raw) <= 4:
        return "*" * len(raw)
    return f"{'*' * (len(raw) - 4)}{raw[-4:]}"


def _sanitize_error_message(message: str) -> str:
    masked = []
    digit_run = ""
    for char in message:
        if char.isdigit():
            digit_run += char
            continue
        if digit_run:
            masked.append(_mask_identifier(digit_run) if len(digit_run) >= 4 else digit_run)
            digit_run = ""
        masked.append(char)
    if digit_run:
        masked.append(_mask_identifier(digit_run) if len(digit_run) >= 4 else digit_run)
    return "".join(masked)


def _option_contract_matches(item: dict[str, Any], request: FutuOptionChainReadRequest) -> bool:
    if request.option_type != "all" and item.get("option_type") != request.option_type:
        return False
    dte = item.get("days_to_expiry")
    if dte is not None:
        if request.min_days_to_expiry is not None and int(dte) < request.min_days_to_expiry:
            return False
        if request.max_days_to_expiry is not None and int(dte) > request.max_days_to_expiry:
            return False
    return True
