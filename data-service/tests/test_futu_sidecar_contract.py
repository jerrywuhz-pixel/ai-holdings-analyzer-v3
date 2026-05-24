import sys
from pathlib import Path

from fastapi.testclient import TestClient


PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import local_connectors.futu_opend.server as sidecar_server  # noqa: E402
from local_connectors.futu_opend.server import create_app  # noqa: E402


client = TestClient(create_app())


def _set_deterministic_mock_env(monkeypatch):
    monkeypatch.setenv("FUTU_SIDECAR_MODE", "mock")
    monkeypatch.setenv("FUTU_SECURITY_FIRM", "FUTUINC")
    monkeypatch.setenv("FUTU_TRD_MARKET", "US")
    monkeypatch.setenv("FUTU_TRD_ENV", "REAL")
    monkeypatch.setenv("FUTU_ACC_ID", "0")
    monkeypatch.setenv("FUTU_ACC_INDEX", "0")


def test_futu_sidecar_health_is_read_only(monkeypatch):
    _set_deterministic_mock_env(monkeypatch)

    response = client.get("/health")

    assert response.status_code == 200
    payload = response.json()
    assert payload["permission_scope"] == "read_only"
    assert payload["supports"]["positions"] is True
    assert payload["supports"]["option_chain"] is True
    assert payload["supports"]["account_diagnostics"] is True
    assert payload["supports"]["place_order"] is False
    assert payload["supports"]["modify_order"] is False
    assert payload["supports"]["cancel_order"] is False
    assert payload["account_context"]["security_firm"] == "FUTUINC"
    assert payload["account_context"]["trd_market"] == "US"
    assert payload["account_context"]["trd_env"] == "REAL"
    assert payload["account_context"]["acc_id"] == "0"
    assert payload["diagnostics"]["account_context_path"] == "/api/v1/account-diagnostics"


def test_futu_sidecar_snapshot_contract_returns_read_only_payload(monkeypatch):
    _set_deterministic_mock_env(monkeypatch)

    response = client.post(
        "/api/v1/snapshots",
        json={
            "tenant_id": "tenant-1",
            "broker_connection_id": "bc-futu-1",
            "snapshot_label": "default",
            "permission_scope": "read_only",
        },
    )

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["connector_mode"] == "local_connector"
    assert data["permission_scope"] == "read_only"
    assert data["source_key"] == "futu_openapi"
    assert data["positions"][0]["symbol"] == "AAPL"
    assert data["cash_balances"][0]["currency"] == "USD"
    assert data["lineage"]["provider"] == "futu_opend_sidecar_mock"
    assert data["lineage"]["account_context"]["security_firm"] == "FUTUINC"
    assert data["lineage"]["account_context"]["acc_id"] == "0"


def test_futu_sidecar_option_chain_contract_returns_sell_put_fields(monkeypatch):
    _set_deterministic_mock_env(monkeypatch)

    response = client.post(
        "/api/v1/option-chain",
        json={
            "tenant_id": "tenant-1",
            "broker_connection_id": "bc-futu-1",
            "underlying_symbol": "AAPL",
            "option_type": "put",
            "min_days_to_expiry": 30,
            "max_days_to_expiry": 45,
            "permission_scope": "read_only",
        },
    )

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["connector_mode"] == "local_connector"
    assert data["permission_scope"] == "read_only"
    assert data["underlying_symbol"] == "AAPL"
    assert data["contracts"][0]["contract_symbol"] == "AAPL260619P175"
    assert data["contracts"][0]["bid"] is not None
    assert data["contracts"][0]["ask"] is not None
    assert data["contracts"][0]["delta"] is not None
    assert data["contracts"][0]["implied_volatility"] is not None
    assert data["contracts"][0]["open_interest"] is not None
    assert data["lineage"]["account_context"]["security_firm"] == "FUTUINC"


def test_futu_sidecar_parses_futu_us_option_strike_scale():
    parsed = sidecar_server._parse_option_symbol("WDC260522P400000")

    assert parsed["option_type"] == "put"
    assert parsed["expiry"] == "2026-05-22"
    assert parsed["strike"] == 400.0


def test_futu_sidecar_parses_compact_us_option_strike_scale():
    parsed = sidecar_server._parse_option_symbol("AAOX260618P45000")

    assert parsed["option_type"] == "put"
    assert parsed["expiry"] == "2026-06-18"
    assert parsed["strike"] == 45.0


def test_futu_sidecar_maps_position_security_name():
    mapped = sidecar_server._map_position_record(
        {
            "code": "HK.00700",
            "stock_name": "腾讯控股",
            "position_market": "HK",
            "qty": 100,
            "average_cost": 350,
            "nominal_price": 400,
            "currency": "HKD",
        },
        default_currency="USD",
    )

    assert mapped["symbol"] == "00700"
    assert mapped["name"] == "腾讯控股"
    assert mapped["market"] == "HK"


def test_futu_sidecar_real_position_query_uses_configured_account_selector():
    class FakeTrdEnv:
        REAL = "REAL"

    class FakeTrdMarket:
        US = "US"

    class FakeSdk:
        RET_OK = 0
        TrdEnv = FakeTrdEnv
        TrdMarket = FakeTrdMarket

    class FakeTradeContext:
        def __init__(self):
            self.position_kwargs = None

        def position_list_query(self, **kwargs):
            self.position_kwargs = kwargs
            return (
                FakeSdk.RET_OK,
                [
                    {
                        "code": "US.AAPL",
                        "position_market": "US",
                        "qty": 10,
                        "average_cost": 100,
                        "nominal_price": 120,
                    }
                ],
            )

    settings = sidecar_server.FutuSidecarSettings(
        mode="real",
        trade_market="US",
        trade_env="REAL",
        account_id=12345678,
        account_index=2,
    )
    reader = sidecar_server.FutuSdkSidecarReader.__new__(sidecar_server.FutuSdkSidecarReader)
    reader._settings = settings
    reader._sdk = FakeSdk
    ctx = FakeTradeContext()

    positions = reader._read_positions(ctx)

    assert positions[0]["symbol"] == "AAPL"
    assert ctx.position_kwargs == {
        "trd_env": "REAL",
        "acc_id": 12345678,
        "acc_index": 2,
        "refresh_cache": False,
        "position_market": "US",
    }


def test_futu_sidecar_diagnostic_falls_back_to_account_index_when_acc_id_is_rejected():
    class FakeTrdEnv:
        REAL = "REAL"

    class FakeTrdMarket:
        US = "US"

    class FakeSdk:
        RET_OK = 0
        TrdEnv = FakeTrdEnv
        TrdMarket = FakeTrdMarket

    class FakeTradeContext:
        def __init__(self):
            self.calls = []

        def position_list_query(self, **kwargs):
            self.calls.append(kwargs)
            if kwargs["acc_id"] == 12345678:
                return 1, "ERROR. Nonexisting acc_id 12345678!"
            return FakeSdk.RET_OK, [{"code": "US.AAPL", "qty": 10}]

    settings = sidecar_server.FutuSidecarSettings(
        mode="real",
        trade_market="US",
        trade_env="REAL",
        account_id=12345678,
        account_index=2,
    )
    reader = sidecar_server.FutuSdkSidecarReader.__new__(sidecar_server.FutuSdkSidecarReader)
    reader._settings = settings
    reader._sdk = FakeSdk
    ctx = FakeTradeContext()

    position_count, error = reader._diagnostic_position_count(
        ctx,
        acc_id=12345678,
        acc_index=2,
        trade_market="US",
    )

    assert position_count == 1
    assert error is None
    assert ctx.calls[0]["acc_id"] == 12345678
    assert ctx.calls[1]["acc_id"] == 0
    assert ctx.calls[1]["acc_index"] == 2


def test_futu_sidecar_account_diagnostics_returns_minimal_masked_payload(monkeypatch):
    monkeypatch.setenv("FUTU_SIDECAR_MODE", "mock")
    monkeypatch.setenv("FUTU_SECURITY_FIRM", "FUTUSECURITIES")
    monkeypatch.setenv("FUTU_TRD_MARKET", "US")
    monkeypatch.setenv("FUTU_TRD_ENV", "REAL")
    monkeypatch.setenv("FUTU_ACC_ID", "12345678")
    monkeypatch.setenv("FUTU_ACC_INDEX", "2")

    response = client.get("/api/v1/account-diagnostics")

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["requested"]["security_firm"] == "FUTUSECURITIES"
    assert data["requested"]["trd_market"] == "US"
    assert data["requested"]["acc_id"] == "****5678"
    assert "acc_index" not in data["requested"]
    assert "trd_env" not in data["requested"]
    assert data["candidate_entities"][0]["security_firm"] == "FUTUSECURITIES"
    assert data["candidate_entities"][0]["trd_market"] == "US"
    assert data["candidate_entities"][0]["acc_id"] == "****5678"
    assert data["candidate_entities"][0]["account_count"] == 1
    assert data["candidate_entities"][0]["position_count"] is None
    assert "account_ids" not in data["candidate_entities"][0]
    assert "query_selector" not in data["candidate_entities"][0]
    assert data["recommendations"]
    assert all("read_only" in item or "diagnostic" in item or "持仓" in item for item in data["recommendations"])


def test_futu_sidecar_account_diagnostics_recommendations_flag_selector_mismatch():
    requested = {"security_firm": "FUTUINC", "trd_market": "US", "acc_id": "****0001"}
    candidates = [
        {
            "security_firm": "FUTUINC",
            "trd_market": "US",
            "acc_id": "****0002",
            "account_count": 1,
            "position_count": 0,
            "matches_requested": True,
            "status": "ok",
        },
        {
            "security_firm": "FUTUSECURITIES",
            "trd_market": "US",
            "acc_id": "****0003",
            "account_count": 1,
            "position_count": 4,
            "matches_requested": False,
            "status": "ok",
        },
    ]

    recommendations = sidecar_server._build_diagnostic_recommendations(requested, candidates)

    assert any("FUTUSECURITIES/US/****0003" in item for item in recommendations)
    assert any("security_firm/trd_market/acc_id" in item for item in recommendations)


def test_futu_sidecar_account_diagnostics_error_is_sanitized(monkeypatch):
    class BrokenReader:
        def read_account_diagnostics(self):
            raise sidecar_server.FutuSidecarError("acc 12345678 failed for card 87654321")

    monkeypatch.setattr(sidecar_server, "_build_reader", lambda settings: BrokenReader())

    response = client.get("/api/v1/account-diagnostics")

    assert response.status_code == 503
    detail = response.json()["detail"]
    assert "12345678" not in detail["message"]
    assert "87654321" not in detail["message"]
    assert "****5678" in detail["message"]
    assert "****4321" in detail["message"]
