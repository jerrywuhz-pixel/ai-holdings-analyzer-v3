from __future__ import annotations

import pytest

from services.hermes import domain_tools
from services.hermes.domain_tools import DomainToolsFacade


@pytest.mark.asyncio
async def test_sector_context_domain_tool_uses_reader(monkeypatch):
    async def fake_load_sector_context(**kwargs):
        assert kwargs["tenant_id"] == "tenant-test"
        assert kwargs["market"] == "US"
        assert kwargs["sector"] == "Technology"
        return {
            "ok": True,
            "status": "available",
            "data": {
                "schema_version": "sector_context_v1",
                "sector_context": {
                    "status": "available",
                    "sector": "Technology",
                    "latest": {"change_pct": 1.23, "relative_strength": 0.87},
                    "snapshots": [],
                },
            },
            "source_refs": [{"source": "postgres", "ref": "sector_daily_snapshots"}],
        }

    monkeypatch.setattr(domain_tools, "load_sector_context", fake_load_sector_context)

    result = await DomainToolsFacade().invoke(
        "sector.context",
        {
            "tenant_id": "tenant-test",
            "symbol": "NVDA",
            "market": "US",
            "sector": "Technology",
            "industry": "Semiconductors",
        },
    )

    assert result["tool"] == "sector.context"
    assert result["ok"] is True
    assert result["data"]["schema_version"] == "sector_context_v1"
    assert result["data"]["sector_context"]["status"] == "available"
    assert {"source": "symbol", "ref": "NVDA"} in result["source_refs"]


@pytest.mark.asyncio
async def test_market_regime_domain_tool_uses_reader(monkeypatch):
    async def fake_load_market_regime(**kwargs):
        assert kwargs["tenant_id"] == "tenant-test"
        assert kwargs["market"] == "US"
        return {
            "ok": True,
            "status": "available",
            "data": {
                "schema_version": "market_regime_v1",
                "market_regime": {
                    "status": "available",
                    "market": "US",
                    "regime": "risk_on",
                    "risk_bias": "constructive",
                    "summary": "市场风险偏好较强",
                },
            },
            "source_refs": [{"source": "postgres", "ref": "sector_daily_snapshots"}],
        }

    monkeypatch.setattr(domain_tools, "load_market_regime", fake_load_market_regime)

    result = await DomainToolsFacade().invoke(
        "market.regime",
        {
            "tenant_id": "tenant-test",
            "market": "US",
        },
    )

    assert result["tool"] == "market.regime"
    assert result["ok"] is True
    assert result["data"]["schema_version"] == "market_regime_v1"
    assert result["data"]["market_regime"]["regime"] == "risk_on"


@pytest.mark.asyncio
async def test_stock_analysis_domain_tool_accepts_news_context(monkeypatch):
    captured: dict[str, object] = {}

    class FakeStockAnalysisService:
        def __init__(self, **kwargs):
            captured.update(kwargs)

        async def analyze(self, **kwargs):
            news_reader = captured["news_context_reader"]
            news_payload = await news_reader(
                kwargs["tenant_id"],
                kwargs["symbol"],
                "US",
                "Technology",
                "Semiconductors",
            )
            return type(
                "FakeResult",
                (),
                {
                    "model_dump": lambda self: {
                        "tool": "stock.analysis",
                        "ok": True,
                        "status": "ok",
                        "data": {
                            "symbol": kwargs["symbol"],
                            "news_payload": news_payload,
                        },
                        "source_refs": [],
                    }
                },
            )()

    monkeypatch.setattr(domain_tools, "HermesStockAnalysisService", FakeStockAnalysisService)

    result = await DomainToolsFacade().invoke(
        "stock.analysis",
        {
            "tenant_id": "tenant-test",
            "symbol": "NVDA",
            "persist": False,
            "news_context": {
                "items": [{"headline": "NVIDIA 发布新 AI 芯片路线图"}],
                "catalysts": [{"label": "财报窗口", "date": "2026-06-20"}],
            },
        },
    )

    news_context = result["data"]["news_payload"]["data"]["news_context"]
    assert result["tool"] == "stock.analysis"
    assert result["data"]["news_payload"]["tool"] == "news.context"
    assert news_context["items"][0]["headline"] == "NVIDIA 发布新 AI 芯片路线图"
    assert news_context["catalysts"][0]["label"] == "财报窗口"
