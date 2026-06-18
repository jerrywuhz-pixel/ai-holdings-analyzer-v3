from __future__ import annotations

import json

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from openclaw.gateway.domain_tools import DomainToolsFacade
from openclaw.gateway.routers.hermes_domain_tools import router


def _client_for(handler):
    transport = httpx.MockTransport(handler)
    return lambda: httpx.AsyncClient(transport=transport)


@pytest.mark.asyncio
async def test_market_quote_calls_data_service_with_freshness_params() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/quote/NVDA"
        assert request.url.params["source"] == "futu"
        assert request.url.params["require_fresh"] == "true"
        assert request.url.params["max_age_seconds"] == "30"
        return httpx.Response(
            200,
            json={"ok": True, "data": {"symbol": "NVDA", "price": 980.5, "source": "futu"}},
        )

    facade = DomainToolsFacade(data_service_url="http://data-service:8000", http_client_factory=_client_for(handler))
    result = await facade.invoke(
        "market.quote",
        {"symbol": "NVDA", "source": "futu", "require_fresh": True, "max_age_seconds": 30},
    )

    assert result["ok"] is True
    assert result["data"]["price"] == 980.5
    assert result["source_refs"] == [{"source": "data-service", "ref": "/api/quote/NVDA"}]


@pytest.mark.asyncio
async def test_sell_put_rank_uses_futu_endpoint_when_broker_connection_present() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/v3/options/sell-put/analyze-from-futu"
        body = json.loads(request.content)
        assert body["tenant_id"] == "tenant-1"
        assert body["broker_connection_id"] == "broker-1"
        assert body["allow_mock_fallback"] is False
        return httpx.Response(
            200,
            json={
                "ok": True,
                "data": {
                    "analysis": {
                        "underlying_symbol": "AAPL",
                        "overall_actionability": "trade_draft",
                        "broker_snapshot_mode": "broker_verified",
                        "data_quality_note": "券商只读同步。",
                        "candidate_ranking": [{"rank": 1, "contract_symbol": "AAPL260619P175"}],
                    }
                },
            },
        )

    facade = DomainToolsFacade(data_service_url="http://data-service:8000", http_client_factory=_client_for(handler))
    result = await facade.invoke(
        "options.sell_put_rank",
        {"tenant_id": "tenant-1", "broker_connection_id": "broker-1", "underlying_symbol": "AAPL"},
    )

    assert result["ok"] is True
    assert result["data"]["summary"]["overall_actionability"] == "trade_draft"
    assert result["data"]["summary"]["top_candidates"][0]["contract_symbol"] == "AAPL260619P175"


@pytest.mark.asyncio
async def test_broker_positions_read_defaults_to_portfolio_read_model() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/v3/portfolio/positions"
        assert request.url.params["tenant_id"] == "tenant-1"
        return httpx.Response(
            200,
            json={"ok": True, "data": {"equity_positions": [{"symbol": "00700"}], "option_positions": []}},
        )

    facade = DomainToolsFacade(data_service_url="http://data-service:8000", http_client_factory=_client_for(handler))
    result = await facade.invoke("broker.positions_read", {"tenant_id": "tenant-1"})

    assert result["ok"] is True
    assert result["data"]["equity_positions"][0]["symbol"] == "00700"


@pytest.mark.asyncio
async def test_ima_search_returns_disabled_without_credentials(monkeypatch) -> None:
    monkeypatch.delenv("IMA_REFERENCE_SOURCE_ENABLED", raising=False)
    monkeypatch.delenv("IMA_OPENAPI_CLIENTID", raising=False)
    monkeypatch.delenv("IMA_OPENAPI_APIKEY", raising=False)

    facade = DomainToolsFacade(ima_skill_dir="/tmp/missing-ima-skill")
    result = await facade.invoke("reference.ima.search", {"query": "英伟达 期权"})

    assert result["ok"] is False
    assert result["status"] == "disabled"
    assert result["reference_only"] is True
    assert any("IMA_REFERENCE_SOURCE_ENABLED" in reason for reason in result["reasons"])


def test_router_lists_and_invokes_domain_tools(monkeypatch) -> None:
    monkeypatch.delenv("HERMES_DOMAIN_TOOLS_KEY", raising=False)
    monkeypatch.delenv("OPENCLAW_SKILL_KEY", raising=False)

    class FakeFacade:
        async def invoke(self, tool_name, arguments):
            assert tool_name == "market.quote"
            assert arguments["tenant_id"] == "tenant-1"
            assert arguments["symbol"] == "AAPL"
            return {"tool": tool_name, "ok": True, "status": "ok", "data": {"symbol": "AAPL"}}

    app = FastAPI()
    app.include_router(router)
    app.state.domain_tools_facade = FakeFacade()
    client = TestClient(app)

    manifest = client.get("/api/hermes/domain-tools")
    assert manifest.status_code == 200
    assert any(tool["name"] == "market.quote" for tool in manifest.json()["tools"])

    response = client.post(
        "/api/hermes/domain-tools/invoke",
        json={"tool": "market.quote", "tenant_id": "tenant-1", "arguments": {"symbol": "AAPL"}},
    )
    assert response.status_code == 200
    assert response.json()["ok"] is True
    assert response.json()["result"]["data"]["symbol"] == "AAPL"
