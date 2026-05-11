from datetime import datetime, timezone
from unittest.mock import AsyncMock, Mock, patch

import pytest

from adapters.futu import (
    FutuConnectorError,
    FutuOptionChainReadRequest,
    FutuReadOnlyConnector,
    FutuSnapshotReadRequest,
)


@pytest.mark.asyncio
async def test_local_connector_snapshot_success_is_read_only_and_lineaged():
    connector = FutuReadOnlyConnector(
        mode="local_connector",
        base_url="http://localhost:8765",
        snapshot_path="/api/v1/snapshots",
    )
    now = datetime(2026, 5, 10, 2, 0, tzinfo=timezone.utc)
    response_payload = {
        "ok": True,
        "data": {
            "tenant_id": "tenant-1",
            "broker_connection_id": "bc-1",
            "connector_mode": "local_connector",
            "permission_scope": "read_only",
            "as_of": now.isoformat(),
            "received_at": now.isoformat(),
            "positions": [
                {
                    "symbol": "AAPL",
                    "market": "US",
                    "instrument_type": "stock",
                    "quantity": 10,
                    "average_cost": 180.0,
                    "market_price": 190.0,
                    "currency": "USD",
                }
            ],
            "cash_balances": [{"currency": "USD", "available_cash": 10000.0}],
            "missing_fields": [],
            "status": "complete",
        },
    }

    with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
        mock_response = Mock()
        mock_response.json.return_value = response_payload
        mock_response.raise_for_status.return_value = None
        mock_post.return_value = mock_response

        snapshot = await connector.read_account_snapshot(
            FutuSnapshotReadRequest(
                tenant_id="tenant-1",
                broker_connection_id="bc-1",
                connector_mode="local_connector",
            )
        )

    assert snapshot.connector_mode == "local_connector"
    assert snapshot.permission_scope == "read_only"
    assert snapshot.positions[0].symbol == "AAPL"
    assert snapshot.lineage["provider"] == "futu_opend_local_connector"
    mock_post.assert_awaited_once()
    assert mock_post.call_args.kwargs["json"]["permission_scope"] == "read_only"


@pytest.mark.asyncio
async def test_local_connector_rejects_non_read_only_snapshot():
    connector = FutuReadOnlyConnector(mode="local_connector")
    now = datetime(2026, 5, 10, 2, 0, tzinfo=timezone.utc)

    with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
        mock_response = Mock()
        mock_response.json.return_value = {
            "ok": True,
            "data": {
                "tenant_id": "tenant-1",
                "broker_connection_id": "bc-1",
                "connector_mode": "local_connector",
                "permission_scope": "admin_write",
                "as_of": now.isoformat(),
                "received_at": now.isoformat(),
                "positions": [],
                "cash_balances": [],
                "missing_fields": [],
                "status": "complete",
            },
        }
        mock_response.raise_for_status.return_value = None
        mock_post.return_value = mock_response

        with pytest.raises(FutuConnectorError):
            await connector.read_account_snapshot(
                FutuSnapshotReadRequest(
                    tenant_id="tenant-1",
                    broker_connection_id="bc-1",
                    connector_mode="local_connector",
                )
            )


@pytest.mark.asyncio
async def test_local_connector_can_fallback_to_marked_mock_snapshot():
    connector = FutuReadOnlyConnector(mode="local_connector")

    with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
        mock_post.side_effect = RuntimeError("opend sidecar down")

        snapshot = await connector.read_account_snapshot(
            FutuSnapshotReadRequest(
                tenant_id="tenant-1",
                broker_connection_id="bc-1",
                connector_mode="local_connector",
                allow_mock_fallback=True,
            )
        )

    assert snapshot.connector_mode == "local_mock"
    assert snapshot.status == "partial"
    assert "local_connector_unavailable" in snapshot.missing_fields
    assert snapshot.lineage["fallback_used"] is True


@pytest.mark.asyncio
async def test_mock_option_chain_filters_put_candidates_by_dte():
    connector = FutuReadOnlyConnector(mode="local_mock")

    snapshot = await connector.read_option_chain(
        FutuOptionChainReadRequest(
            tenant_id="tenant-1",
            broker_connection_id="bc-1",
            underlying_symbol="AAPL",
            option_type="put",
            min_days_to_expiry=30,
            max_days_to_expiry=45,
        )
    )

    assert snapshot.connector_mode == "local_mock"
    assert snapshot.permission_scope == "read_only"
    assert snapshot.status == "complete"
    assert len(snapshot.contracts) == 2
    assert all(contract.option_type == "put" for contract in snapshot.contracts)


@pytest.mark.asyncio
async def test_local_connector_option_chain_success_is_lineaged_and_normalized():
    connector = FutuReadOnlyConnector(
        mode="local_connector",
        base_url="http://localhost:8765",
        option_chain_path="/api/v1/option-chain",
    )
    now = datetime(2026, 5, 10, 2, 0, tzinfo=timezone.utc)
    response_payload = {
        "ok": True,
        "data": {
            "tenant_id": "tenant-1",
            "broker_connection_id": "bc-1",
            "connector_mode": "local_connector",
            "permission_scope": "read_only",
            "as_of": now.isoformat(),
            "received_at": now.isoformat(),
            "contracts": [
                {
                    "contract_symbol": "AAPL260619P175",
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
                }
            ],
        },
    }

    with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
        mock_response = Mock()
        mock_response.json.return_value = response_payload
        mock_response.raise_for_status.return_value = None
        mock_post.return_value = mock_response

        snapshot = await connector.read_option_chain(
            FutuOptionChainReadRequest(
                tenant_id="tenant-1",
                broker_connection_id="bc-1",
                underlying_symbol="AAPL",
                connector_mode="local_connector",
            )
        )

    assert snapshot.connector_mode == "local_connector"
    assert snapshot.status == "complete"
    assert snapshot.contracts[0].underlying_symbol == "AAPL"
    assert snapshot.contracts[0].currency == "USD"
    assert snapshot.contracts[0].source_key == "futu_openapi"
    assert snapshot.contracts[0].source_tier == "L1_trading"
    assert snapshot.lineage["provider"] == "futu_opend_local_connector"
    mock_post.assert_awaited_once()
    assert mock_post.call_args.kwargs["json"]["permission_scope"] == "read_only"


@pytest.mark.asyncio
async def test_local_connector_option_chain_marks_empty_contracts_as_partial():
    connector = FutuReadOnlyConnector(mode="local_connector")
    now = datetime(2026, 5, 10, 2, 0, tzinfo=timezone.utc)

    with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
        mock_response = Mock()
        mock_response.json.return_value = {
            "ok": True,
            "data": {
                "tenant_id": "tenant-1",
                "broker_connection_id": "bc-1",
                "connector_mode": "local_connector",
                "permission_scope": "read_only",
                "as_of": now.isoformat(),
                "received_at": now.isoformat(),
            },
        }
        mock_response.raise_for_status.return_value = None
        mock_post.return_value = mock_response

        snapshot = await connector.read_option_chain(
            FutuOptionChainReadRequest(
                tenant_id="tenant-1",
                broker_connection_id="bc-1",
                underlying_symbol="AAPL",
                connector_mode="local_connector",
            )
        )

    assert snapshot.contracts == []
    assert snapshot.status == "partial"
    assert snapshot.missing_fields == ["option_chain"]


def test_capabilities_include_sidecar_account_context(monkeypatch):
    connector = FutuReadOnlyConnector(
        mode="local_connector",
        base_url="http://localhost:8765",
        health_path="/health",
    )
    response_payload = {
        "ok": True,
        "account_context": {
            "security_firm": "FUTUSECURITIES",
            "trd_market": "US",
            "trd_env": "REAL",
            "acc_id": "****5678",
            "acc_index": 1,
        },
        "diagnostics": {
            "account_context_path": "/api/v1/account-diagnostics",
        },
    }

    with patch("httpx.Client.get") as mock_get:
        mock_response = Mock()
        mock_response.json.return_value = response_payload
        mock_response.raise_for_status.return_value = None
        mock_get.return_value = mock_response

        capabilities = connector.capabilities()

    assert capabilities["account_context"]["security_firm"] == "FUTUSECURITIES"
    assert capabilities["account_context"]["acc_id"] == "****5678"
    assert capabilities["supports"]["account_diagnostics"] is True
    assert capabilities["diagnostics"]["account_context_path"] == "/api/v1/account-diagnostics"
    assert capabilities["diagnostics"]["sidecar_health_ok"] is True


def test_capabilities_falls_back_to_masked_env_context_when_health_unavailable(monkeypatch):
    monkeypatch.setenv("FUTU_SECURITY_FIRM", "FUTUINC")
    monkeypatch.setenv("FUTU_TRD_MARKET", "US")
    monkeypatch.setenv("FUTU_TRD_ENV", "REAL")
    monkeypatch.setenv("FUTU_ACC_ID", "12345678")
    monkeypatch.setenv("FUTU_ACC_INDEX", "3")
    connector = FutuReadOnlyConnector(mode="local_connector")

    with patch("httpx.Client.get", side_effect=RuntimeError("account 12345678 unavailable")):
        capabilities = connector.capabilities()

    assert capabilities["account_context"]["security_firm"] == "FUTUINC"
    assert capabilities["account_context"]["acc_id"] == "****5678"
    assert capabilities["account_context"]["acc_index"] == 3
    assert "12345678" not in capabilities["diagnostics"]["sidecar_health_error"]
    assert "****5678" in capabilities["diagnostics"]["sidecar_health_error"]


@pytest.mark.asyncio
async def test_local_connector_error_payload_is_sanitized():
    connector = FutuReadOnlyConnector(mode="local_connector")

    with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
        mock_response = Mock()
        mock_response.json.return_value = {
            "ok": False,
            "message": "acc 12345678 failed",
        }
        mock_response.raise_for_status.return_value = None
        mock_post.return_value = mock_response

        with pytest.raises(FutuConnectorError, match=r"\*{4}5678"):
            await connector.read_account_snapshot(
                FutuSnapshotReadRequest(
                    tenant_id="tenant-1",
                    broker_connection_id="bc-1",
                    connector_mode="local_connector",
                )
            )
