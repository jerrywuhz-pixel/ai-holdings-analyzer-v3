from __future__ import annotations

import pytest


def test_run_smoke_exercises_cloud_registration_and_runtime(monkeypatch):
    from scripts import lightweight_cloud_smoke as smoke

    calls: list[tuple[str, str]] = []
    cleanup: list[str] = []

    def fake_request(method, url, **kwargs):
        calls.append((method, url))
        if url.endswith("/api/auth/register"):
            return 200, {"status": "verification_required", "provider": "local", "delivery": "email_sent"}, "{}"
        if url.endswith("/api/auth/verify"):
            return 200, {"status": "signed_in", "user": {"provider": "local", "id": "tenant-1"}}, "{}"
        if url.endswith("/api/onboarding/wechat/binding"):
            return 200, {"status": "qr_pending", "auth": {"id": "auth-1", "qrcode": "qr-1", "qrcode_url": "https://qr"}}, "{}"
        if url.endswith("/api/v3/connectors/poll"):
            return 200, {"ok": True, "data": {"tasks": [{"upload_url": "/api/v3/connectors/upload"}]}}, "{}"
        if "/api/v3/portfolio/overview" in url:
            return 200, {"ok": True, "data": {"positions_count": 2, "freshness": {"snapshot_id": "snap-1"}}}, "{}"
        if url.endswith("/api/quote/AAPL"):
            return 200, {"ok": True, "data": {"symbol": "AAPL", "quote_actionability": "blocked"}}, "{}"
        if url.endswith("/api/v3/options/sell-put/analyze"):
            return 200, {"ok": True, "data": {"overall_actionability": "trade_draft", "candidates": [{}]}}, "{}"
        if url.endswith("/api/openclaw/wechat/messages"):
            return 200, {"result_type": "ignored"}, "{}"
        raise AssertionError(f"unexpected request: {method} {url} {kwargs}")

    monkeypatch.setattr(smoke, "_request_json", fake_request)
    monkeypatch.setattr(smoke, "_lookup_local_verification_code", lambda config, email: "123456")
    monkeypatch.setattr(smoke, "_cleanup_smoke_user", lambda config, email: cleanup.append(email))

    config = smoke.CloudSmokeConfig(
        webapp_base_url="https://app.example.test",
        data_service_base_url="http://data-service:8000",
        openclaw_base_url="http://openclaw:8080",
        connector_pairing_token="pairing-token",
        email="codex-smoke@example.test",
        password="CodexSmoke123!",
        tenant_id="00000000-0000-0000-0000-000000000000",
    )

    summary = smoke.run_smoke(config)

    assert summary["status"] == "pass"
    assert summary["counts"] == {"passed": 8, "failed": 0}
    assert [step["step"] for step in summary["steps"]] == [
        "register",
        "verify_email",
        "wechat_binding_start",
        "futu_connector_poll",
        "portfolio_overview",
        "quote",
        "sell_put",
        "openclaw_ingress",
    ]
    assert cleanup == ["codex-smoke@example.test"]
    assert ("POST", "https://app.example.test/api/auth/register") in calls
    assert ("POST", "http://data-service:8000/api/v3/connectors/poll") in calls


def test_run_smoke_cleans_up_when_a_step_fails(monkeypatch):
    from scripts import lightweight_cloud_smoke as smoke

    cleanup: list[str] = []

    def fake_request(method, url, **kwargs):
        if url.endswith("/api/auth/register"):
            return 500, None, "registration failed"
        raise AssertionError("smoke should stop after failed registration")

    monkeypatch.setattr(smoke, "_request_json", fake_request)
    monkeypatch.setattr(smoke, "_cleanup_smoke_user", lambda config, email: cleanup.append(email))

    config = smoke.CloudSmokeConfig(
        webapp_base_url="https://app.example.test",
        data_service_base_url="http://data-service:8000",
        openclaw_base_url="http://openclaw:8080",
        connector_pairing_token="pairing-token",
        email="codex-smoke@example.test",
        password="CodexSmoke123!",
        tenant_id="00000000-0000-0000-0000-000000000000",
    )

    summary = smoke.run_smoke(config)

    assert summary["status"] == "fail"
    assert summary["counts"] == {"passed": 0, "failed": 1}
    assert summary["steps"][0]["step"] == "register"
    assert "registration failed" in summary["steps"][0]["detail"]
    assert cleanup == ["codex-smoke@example.test"]


def test_run_smoke_requires_connector_pairing_token_when_poll_enabled():
    from scripts import lightweight_cloud_smoke as smoke

    config = smoke.CloudSmokeConfig(
        webapp_base_url="https://app.example.test",
        data_service_base_url="http://data-service:8000",
        openclaw_base_url="http://openclaw:8080",
        connector_pairing_token="",
        email="codex-smoke@example.test",
        password="CodexSmoke123!",
        tenant_id="00000000-0000-0000-0000-000000000000",
    )

    with pytest.raises(ValueError, match="connector pairing token"):
        smoke.run_smoke(config)
