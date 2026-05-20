from datetime import date, datetime, timedelta, timezone
from uuid import uuid4

from fastapi.testclient import TestClient

from main import app

client = TestClient(app)


def test_connector_poll_requires_pairing_token(monkeypatch):
    monkeypatch.delenv("FUTU_CONNECTOR_PAIRING_TOKEN", raising=False)

    response = client.post(
        "/api/v3/connectors/poll",
        json={
            "tenant_id": "tenant-1",
            "connector_instance_id": "connector-1",
        },
    )

    assert response.status_code == 503


def test_connector_poll_returns_read_only_snapshot_task(monkeypatch):
    monkeypatch.setenv("FUTU_CONNECTOR_PAIRING_TOKEN", "pairing-token")

    response = client.post(
        "/api/v3/connectors/poll",
        headers={"X-Connector-Pairing-Token": "pairing-token"},
        json={
            "tenant_id": "tenant-1",
            "connector_instance_id": "connector-1",
        },
    )

    assert response.status_code == 200
    payload = response.json()["data"]
    assert payload["permission_scope"] == "read_only"
    assert payload["tasks"][0]["kind"] == "account_snapshot"
    assert payload["tasks"][0]["upload_url"] == "/api/v3/connectors/upload"


def test_connector_upload_can_accept_snapshot_without_persisting(monkeypatch):
    now = datetime.now(timezone.utc).isoformat()
    monkeypatch.setenv("FUTU_CONNECTOR_PAIRING_TOKEN", "pairing-token")

    response = client.post(
        "/api/v3/connectors/upload",
        headers={"X-Connector-Pairing-Token": "pairing-token"},
        json={
            "tenant_id": "tenant-1",
            "connector_instance_id": "connector-1",
            "task_id": "task-1",
            "persist": False,
            "snapshot": {
                "broker_connection_id": "bc-1",
                "as_of": now,
                "received_at": now,
                "positions": [],
                "cash_balances": [],
            },
        },
    )

    assert response.status_code == 200
    payload = response.json()["data"]
    assert payload["persisted"] is False
    assert payload["permission_scope"] == "read_only"
    assert payload["snapshot_summary"]["positions_count"] == 0


def test_futu_snapshot_endpoint_returns_read_only_mock():
    response = client.post(
        "/api/v3/broker/futu/snapshot",
        json={
            "tenant_id": "tenant-1",
            "broker_connection_id": "bc-futu-1",
            "snapshot_label": "default",
        },
    )

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["permission_scope"] == "read_only"
    assert data["connector_mode"] == "local_mock"
    assert data["source_key"] == "futu_openapi"


def test_futu_sync_endpoint_can_dry_run_without_persisting():
    response = client.post(
        "/api/v3/broker/futu/sync",
        json={
            "tenant_id": "tenant-1",
            "connection_label": "富途本地 OpenD 测试",
            "snapshot_label": "default",
            "connector_mode": "local_mock",
            "persist": False,
        },
    )

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["persisted"] is False
    assert data["source_quality"] == "estimated"
    assert data["snapshot_summary"]["positions_count"] == 2
    assert data["snapshot_summary"]["cash_balance_count"] == 1
    assert data["account_snapshot"]["permission_scope"] == "read_only"
    assert data["account_snapshot"]["connector_mode"] == "local_mock"


def test_futu_sync_endpoint_rejects_mismatched_authenticated_tenant(monkeypatch):
    monkeypatch.setenv("DATA_SERVICE_TENANT_AUTH_REQUIRED", "true")
    monkeypatch.setenv("DATA_SERVICE_INTERNAL_TOKEN", "service-token")

    response = client.post(
        "/api/v3/broker/futu/sync",
        headers={
            "X-Data-Service-Token": "service-token",
            "X-Data-Service-Tenant-Id": "tenant-1",
        },
        json={
            "tenant_id": "tenant-2",
            "connection_label": "富途本地 OpenD 测试",
            "snapshot_label": "default",
            "connector_mode": "local_mock",
            "persist": False,
        },
    )

    assert response.status_code == 403
    assert "tenant_id does not match authenticated user" in response.json()["detail"]["message"]


def test_futu_option_chain_endpoint_returns_read_only_mock_candidates():
    response = client.post(
        "/api/v3/broker/futu/option-chain",
        json={
            "tenant_id": "tenant-1",
            "broker_connection_id": "bc-futu-1",
            "underlying_symbol": "AAPL",
            "option_type": "put",
            "min_days_to_expiry": 30,
            "max_days_to_expiry": 45,
        },
    )

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["permission_scope"] == "read_only"
    assert data["connector_mode"] == "local_mock"
    assert data["underlying_symbol"] == "AAPL"
    assert data["contracts"]
    assert data["contracts"][0]["source_key"] == "futu_openapi"


def test_sell_put_analyze_from_futu_returns_analysis_only_when_existing_exposure_is_high():
    response = client.post(
        "/api/v3/options/sell-put/analyze-from-futu",
        json={
            "tenant_id": "tenant-1",
            "broker_connection_id": "bc-futu-1",
            "underlying_symbol": "AAPL",
            "underlying_price": 190.0,
            "option_type": "put",
            "min_days_to_expiry": 30,
            "max_days_to_expiry": 45,
            "connector_mode": "local_mock",
        },
    )

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["input_lineage"]["permission_scope"] == "read_only"
    assert data["input_lineage"]["connector_mode"] == "local_mock"
    assert data["analysis"]["broker_snapshot_mode"] == "broker_verified"
    assert data["analysis"]["overall_actionability"] == "analysis_only"
    assert data["analysis"]["underlying_gate"]["gate_status"] == "degraded"
    assert data["analysis"]["candidate_ranking"][0]["rank"] == 1
    assert data["analysis"]["candidate_ranking"][0]["contract_symbol"] == "AAPL260619P175"
    assert data["analysis"]["candidates"][0]["contract_symbol"] == "AAPL260619P175"
    assert data["analysis"]["candidates"][0]["actionability"] == "analysis_only"
    assert data["analysis"]["candidates"][0]["playbook"]["mode"] == "draft_only"
    assert data["analysis"]["candidates"][0]["account_constraint_summary"]["has_existing_short_put"] is True
    assert data["analysis"]["candidates"][0]["account_constraint_summary"]["concentration_is_high"] is True
    assert "不会自动下单" in data["analysis"]["candidates"][0]["user_note"]


def test_historical_manifest_endpoints_register_and_query_coverage():
    symbol = f"AAPL{uuid4().hex[:6]}".upper()
    response = client.post(
        "/api/v3/market/history/manifests",
        json={
            "tenant_id": "tenant-1",
            "job_id": f"job-{uuid4().hex[:8]}",
            "source_key": "futu_openapi",
            "market": "US",
            "symbol": symbol,
            "instrument_type": "stock",
            "data_kind": "bar_1d",
            "interval": "1d",
            "coverage_start": str(date(2026, 5, 1)),
            "coverage_end": str(date(2026, 5, 9)),
        },
    )

    assert response.status_code == 200
    manifest = response.json()["data"]
    assert manifest["storage_uri"].startswith("memory://market-data/curated/")

    coverage = client.get(
        "/api/v3/market/history/coverage",
        params={
            "symbol": symbol,
            "market": "US",
            "data_kind": "bar_1d",
            "interval": "1d",
        },
    )

    assert coverage.status_code == 200
    payload = coverage.json()["data"]
    assert payload["found"] is True
    assert payload["manifest"]["symbol"] == symbol


def test_sell_put_analyze_endpoint_blocks_missing_option_fields():
    now = datetime.now(timezone.utc)
    response = client.post(
        "/api/v3/options/sell-put/analyze",
        json={
            "tenant_id": "tenant-1",
            "underlying_symbol": "AAPL",
            "quote": {
                "symbol": "AAPL",
                "as_of": (now - timedelta(seconds=10)).isoformat(),
                "price": 190.0,
                "currency": "USD",
                "cross_check_status": "matched",
            },
            "account_snapshot": {
                "tenant_id": "tenant-1",
                "broker_connection_id": "bc-1",
                "as_of": (now - timedelta(seconds=10)).isoformat(),
                "received_at": now.isoformat(),
                "positions": [],
                "cash_balances": [
                    {
                        "currency": "USD",
                        "available_cash": 25000.0,
                        "buying_power": 50000.0,
                        "cash_secured_reserve": 0.0,
                    }
                ],
                "missing_fields": [],
                "status": "complete",
                "lineage": {"read_only": True},
            },
            "option_candidates": [
                {
                    "contract_symbol": "AAPL260619P175",
                    "strike": 175.0,
                    "expiry": "2026-06-19",
                    "days_to_expiry": 40,
                    "bid": 2.4,
                    "ask": 2.7,
                    "delta": 0.21,
                    "implied_volatility": 0.34,
                    "open_interest": None,
                    "volume": 120,
                    "as_of": (now - timedelta(seconds=10)).isoformat(),
                }
            ],
        },
    )

    assert response.status_code == 200
    payload = response.json()["data"]
    assert payload["underlying_gate"]["gate_status"] == "blocked"
    assert payload["candidates"][0]["actionability"] == "blocked"
    assert "open_interest" in payload["candidates"][0]["missing_fields"]


def test_sell_put_analyze_endpoint_without_broker_verification_never_returns_trade_draft():
    now = datetime.now(timezone.utc)
    response = client.post(
        "/api/v3/options/sell-put/analyze",
        json={
            "tenant_id": "tenant-1",
            "underlying_symbol": "AAPL",
            "quote": {
                "symbol": "AAPL",
                "as_of": (now - timedelta(seconds=10)).isoformat(),
                "price": 190.0,
                "currency": "USD",
                "cross_check_status": "matched",
            },
            "option_candidates": [
                {
                    "contract_symbol": "AAPL260619P175",
                    "strike": 175.0,
                    "expiry": "2026-06-19",
                    "days_to_expiry": 40,
                    "bid": 2.4,
                    "ask": 2.7,
                    "delta": 0.21,
                    "implied_volatility": 0.34,
                    "open_interest": 1200,
                    "volume": 180,
                    "as_of": (now - timedelta(seconds=10)).isoformat(),
                }
            ],
        },
    )

    assert response.status_code == 200
    payload = response.json()["data"]
    assert payload["broker_snapshot_mode"] == "estimated_only"
    assert payload["overall_actionability"] == "analysis_only"
    assert payload["underlying_gate"]["actionability"] == "analysis_only"
    assert payload["candidates"][0]["actionability"] != "trade_draft"
    assert payload["candidate_ranking"][0]["actionability"] != "trade_draft"


def test_sell_put_margin_endpoint_returns_reference_disclaimer():
    response = client.post(
        "/api/v3/risk/margin/sell-put/estimate",
        json={
            "underlying_symbol": "AAPL",
            "underlying_price": 190.0,
            "strike": 175.0,
            "contracts": 1,
            "premium_per_share": 2.5,
            "available_cash": 20000.0,
        },
    )

    assert response.status_code == 200
    payload = response.json()["data"]
    assert payload["estimate_mode"] == "builtin_reference"
    assert "仅供参考" in payload["disclaimer"]
