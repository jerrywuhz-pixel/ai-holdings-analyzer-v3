from __future__ import annotations

from openclaw.gateway.skill_registry import build_data_source_status, discover_openclaw_skills


def test_discover_openclaw_skills_includes_data_and_reference_skills() -> None:
    skills = discover_openclaw_skills()

    assert "ftshare-market-data" in skills
    assert "ima-skill" in skills
    assert "quant-options-strategy" in skills
    assert "opportunity-hunter" in skills


def test_build_data_source_status_exposes_skills_without_secrets(monkeypatch) -> None:
    monkeypatch.setenv("DATA_SERVICE_URL", "http://data-service:8000")
    monkeypatch.setenv("TUSHARE_TOKEN", "secret-token")
    monkeypatch.setenv("IMA_REFERENCE_SOURCE_ENABLED", "true")
    monkeypatch.setenv("IMA_OPENAPI_CLIENTID", "client")
    monkeypatch.setenv("IMA_OPENAPI_APIKEY", "secret")
    monkeypatch.setenv("FUTU_CONNECTOR_MODE", "user_local_polling")
    monkeypatch.setenv("DATABASE_URL", "postgresql://postgres:postgres@postgres:5432/ai_holdings")

    statuses = {item["id"]: item for item in build_data_source_status()}

    assert statuses["data-service"]["status"] == "configured"
    assert statuses["ftshare-market-data"]["status"] == "configured"
    assert statuses["ima-reference"]["status"] == "configured"
    assert statuses["futu"]["status"] == "configured"
    assert statuses["tushare"]["status"] == "configured"
    assert statuses["gbrain-mcp"]["status"] == "configured"
    assert "secret-token" not in repr(statuses)
    assert "secret" not in repr(statuses)
