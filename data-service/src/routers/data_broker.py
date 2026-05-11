from __future__ import annotations

"""
3.0 P0 data-service and broker foundation endpoints.
"""

from typing import Any, Literal, Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from adapters.futu import (
    ConnectorModeRequest,
    FutuConnectorError,
    FutuLocalConnectorMock,
    FutuOptionChainReadRequest,
    FutuSnapshotReadRequest,
)
from adapters.tencent_finance import TencentFinanceAdapter, TencentFinanceQuoteRequest
from services.historical_store import HistoricalDataStore, HistoricalManifestCreateRequest, create_historical_blob_store_from_env
from services.margin import MarginEstimator, SellPutMarginEstimateRequest
from services.broker_sync import FutuBrokerSyncRequest, FutuBrokerSyncService
from services.sell_put import SellPutAnalysisRequest, SellPutAnalysisService

router = APIRouter(tags=["data-broker"])

_futu_connector = FutuLocalConnectorMock()
_tencent_adapter = TencentFinanceAdapter()
_historical_store = HistoricalDataStore(blob_store=create_historical_blob_store_from_env())
_margin_estimator = MarginEstimator()
_sell_put_service = SellPutAnalysisService(margin_estimator=_margin_estimator)
_futu_sync_service = FutuBrokerSyncService(connector=_futu_connector)


class FutuSellPutAnalyzeRequest(BaseModel):
    tenant_id: str
    broker_connection_id: str
    underlying_symbol: str
    underlying_price: Optional[float] = None
    currency: str = "USD"
    snapshot_label: str = "default"
    option_type: Literal["put", "call", "all"] = "put"
    min_days_to_expiry: Optional[int] = 20
    max_days_to_expiry: Optional[int] = 60
    connector_mode: ConnectorModeRequest = "auto"
    allow_mock_fallback: bool = False
    max_market_staleness_seconds: int = 60
    max_broker_staleness_seconds: int = 300


@router.get("/v3/broker/futu/capabilities")
async def get_futu_capabilities() -> dict[str, Any]:
    return {"ok": True, "data": _futu_connector.capabilities()}


@router.post("/v3/broker/futu/snapshot")
async def read_futu_snapshot(payload: FutuSnapshotReadRequest) -> dict[str, Any]:
    try:
        snapshot = await _futu_connector.read_account_snapshot(payload)
        return {"ok": True, "data": snapshot.model_dump(mode="json")}
    except FutuConnectorError as exc:
        raise HTTPException(
            status_code=503,
            detail={"ok": False, "message": f"Futu local connector unavailable: {exc}"},
        )
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail={"ok": False, "message": f"Failed to read futu snapshot: {exc}"},
        )


@router.post("/v3/broker/futu/sync")
async def sync_futu_snapshot(payload: FutuBrokerSyncRequest) -> dict[str, Any]:
    try:
        result = await _futu_sync_service.sync(payload)
        return {"ok": True, "data": result}
    except ValueError as exc:
        raise HTTPException(
            status_code=422,
            detail={"ok": False, "message": str(exc)},
        )
    except FutuConnectorError as exc:
        raise HTTPException(
            status_code=503,
            detail={"ok": False, "message": f"Futu local connector unavailable: {exc}"},
        )
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail={"ok": False, "message": f"Failed to sync futu snapshot: {exc}"},
        )


@router.post("/v3/broker/futu/option-chain")
async def read_futu_option_chain(payload: FutuOptionChainReadRequest) -> dict[str, Any]:
    try:
        snapshot = await _futu_connector.read_option_chain(payload)
        return {"ok": True, "data": snapshot.model_dump(mode="json")}
    except FutuConnectorError as exc:
        raise HTTPException(
            status_code=503,
            detail={"ok": False, "message": f"Futu local connector unavailable: {exc}"},
        )
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail={"ok": False, "message": f"Failed to read futu option chain: {exc}"},
        )


@router.get("/v3/market/tencent-finance/capabilities")
async def get_tencent_finance_capabilities() -> dict[str, Any]:
    return {"ok": True, "data": _tencent_adapter.capabilities()}


@router.post("/v3/market/tencent-finance/quote")
async def get_tencent_finance_placeholder_quote(payload: TencentFinanceQuoteRequest) -> dict[str, Any]:
    try:
        quote = await _tencent_adapter.fetch_placeholder_quote(payload)
        return {"ok": True, "data": quote.model_dump(mode="json")}
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail={"ok": False, "message": f"Failed to read tencent finance placeholder quote: {exc}"},
        )


@router.post("/v3/market/history/manifests")
async def register_historical_manifest(payload: HistoricalManifestCreateRequest) -> dict[str, Any]:
    try:
        manifest = await _historical_store.register_manifest(payload)
        return {"ok": True, "data": manifest.model_dump(mode="json")}
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail={"ok": False, "message": f"Failed to register manifest: {exc}"},
        )


@router.get("/v3/market/history/manifests/{manifest_id}")
async def get_historical_manifest(manifest_id: str) -> dict[str, Any]:
    manifest = await _historical_store.get_manifest(manifest_id)
    if manifest is None:
        raise HTTPException(
            status_code=404,
            detail={"ok": False, "message": f"Manifest not found: {manifest_id}"},
        )
    return {"ok": True, "data": manifest.model_dump(mode="json")}


@router.get("/v3/market/history/coverage")
async def get_historical_coverage(
    symbol: str = Query(...),
    market: str = Query(...),
    data_kind: str = Query(...),
    interval: str = Query(...),
) -> dict[str, Any]:
    coverage = await _historical_store.find_coverage(
        symbol=symbol,
        market=market,
        data_kind=data_kind,
        interval=interval,
    )
    return {"ok": True, "data": coverage.model_dump(mode="json")}


@router.post("/v3/risk/margin/sell-put/estimate")
async def estimate_sell_put_margin(payload: SellPutMarginEstimateRequest) -> dict[str, Any]:
    try:
        estimate = _margin_estimator.estimate_sell_put(payload)
        return {"ok": True, "data": estimate.model_dump(mode="json")}
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail={"ok": False, "message": f"Failed to estimate sell put margin: {exc}"},
        )


@router.post("/v3/options/sell-put/analyze")
async def analyze_sell_put(payload: SellPutAnalysisRequest) -> dict[str, Any]:
    try:
        result = await _sell_put_service.analyze(payload)
        return {"ok": True, "data": result.model_dump(mode="json")}
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail={"ok": False, "message": f"Failed to analyze sell put inputs: {exc}"},
        )


@router.post("/v3/options/sell-put/analyze-from-futu")
async def analyze_sell_put_from_futu(payload: FutuSellPutAnalyzeRequest) -> dict[str, Any]:
    try:
        account_snapshot = await _futu_connector.read_account_snapshot(
            FutuSnapshotReadRequest(
                tenant_id=payload.tenant_id,
                broker_connection_id=payload.broker_connection_id,
                snapshot_label=payload.snapshot_label,
                include_positions=True,
                include_cash=True,
                connector_mode=payload.connector_mode,
                allow_mock_fallback=payload.allow_mock_fallback,
            )
        )
        option_chain = await _futu_connector.read_option_chain(
            FutuOptionChainReadRequest(
                tenant_id=payload.tenant_id,
                broker_connection_id=payload.broker_connection_id,
                underlying_symbol=payload.underlying_symbol,
                snapshot_label=payload.snapshot_label,
                option_type=payload.option_type,
                min_days_to_expiry=payload.min_days_to_expiry,
                max_days_to_expiry=payload.max_days_to_expiry,
                connector_mode=payload.connector_mode,
                allow_mock_fallback=payload.allow_mock_fallback,
            )
        )
    except FutuConnectorError as exc:
        raise HTTPException(
            status_code=503,
            detail={"ok": False, "message": f"Futu local connector unavailable: {exc}"},
        )

    underlying_price = payload.underlying_price or _underlying_price_from_snapshot(
        account_snapshot.model_dump(mode="python"),
        payload.underlying_symbol,
    )
    if underlying_price is None:
        raise HTTPException(
            status_code=422,
            detail={
                "ok": False,
                "message": "underlying_price is required when the Futu snapshot does not include the underlying market price",
            },
        )

    try:
        analysis_payload = SellPutAnalysisRequest(
            tenant_id=payload.tenant_id,
            underlying_symbol=payload.underlying_symbol,
            quote={
                "symbol": payload.underlying_symbol,
                "as_of": option_chain.as_of,
                "price": underlying_price,
                "currency": payload.currency,
                "source_key": "futu_openapi",
                "source_tier": option_chain.source_tier,
                "fallback_used": option_chain.lineage.get("fallback_used", False),
                "cross_check_status": "unchecked",
            },
            option_candidates=[
                {
                    "contract_symbol": contract.contract_symbol,
                    "option_type": contract.option_type,
                    "strike": contract.strike,
                    "expiry": contract.expiry,
                    "days_to_expiry": contract.days_to_expiry,
                    "bid": contract.bid,
                    "ask": contract.ask,
                    "delta": contract.delta,
                    "implied_volatility": contract.implied_volatility,
                    "open_interest": contract.open_interest,
                    "volume": contract.volume,
                    "as_of": contract.as_of,
                    "source_key": contract.source_key,
                    "source_tier": contract.source_tier,
                }
                for contract in option_chain.contracts
            ],
            account_snapshot=account_snapshot,
            max_market_staleness_seconds=payload.max_market_staleness_seconds,
            max_broker_staleness_seconds=payload.max_broker_staleness_seconds,
        )
        result = await _sell_put_service.analyze(analysis_payload)
        return {
            "ok": True,
            "data": {
                "analysis": result.model_dump(mode="json"),
                "input_lineage": {
                    "account_snapshot": account_snapshot.lineage,
                    "option_chain": option_chain.lineage,
                    "connector_mode": account_snapshot.connector_mode,
                    "permission_scope": account_snapshot.permission_scope,
                },
            },
        }
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail={"ok": False, "message": f"Failed to analyze Futu sell put inputs: {exc}"},
        )


def _underlying_price_from_snapshot(account_snapshot: dict[str, Any], symbol: str) -> Optional[float]:
    normalized = symbol.upper()
    for position in account_snapshot.get("positions") or []:
        if str(position.get("symbol") or "").upper() == normalized and position.get("market_price") is not None:
            return float(position["market_price"])
    return None
