from __future__ import annotations

import sys
import types

import pytest

from services.hermes.stock_analysis import (
    ANALYSIS_CONTEXT_SCHEMA_VERSION,
    MAX_REPORT_MODULE_CHARS,
    HermesStockAnalysisService,
    StockAnalysisPersistence,
    _build_analysis as service_module_build_analysis_for_test,
)


async def _quote_reader(symbol: str):
    return {
        "ok": True,
        "data": {
            "symbol": symbol,
            "name": "NVIDIA",
            "market": "US",
            "price": 123.45,
            "currency": "USD",
            "source": "test",
            "sector": "Technology",
            "industry": "Semiconductors",
            "quote_actionability": "analysis_only",
            "freshness_seconds": 30,
        },
    }


async def _positions_reader(_tenant_id: str):
    return {
        "ok": True,
        "data": {
            "equity_positions": [
                {
                    "symbol": "NVDA",
                    "name": "NVIDIA",
                    "quantity": 10,
                    "average_cost": 100,
                    "unrealized_pnl_pct": 23.45,
                    "market_value": 1234.5,
                    "currency": "USD",
                }
            ],
            "option_positions": [],
        },
    }


async def _history_reader(_symbol: str, _market: str):
    return {
        "ok": True,
        "data": {
            "found": True,
            "cache_status": "hit",
            "bars": [{"close": value} for value in [100, 101, 102, 103, 104, 105, 106, 108, 110, 112, 115]],
        },
    }


async def _sector_context_reader(_tenant_id: str, _symbol: str, market: str, sector: str | None, industry: str | None):
    return {
        "tool": "sector.context",
        "ok": True,
        "status": "ok",
        "data": {
            "schema_version": "sector_context_v1",
            "sector_context": {
                "status": "available",
                "sector": sector,
                "industry": industry,
                "latest": {
                    "market": market,
                    "sector": sector,
                    "industry": industry,
                    "snapshot_date": "2026-06-12",
                    "change_pct": 1.23,
                    "relative_strength": 0.87,
                    "quality_status": "validated",
                },
                "snapshots": [],
            },
        },
        "source_refs": [{"source": "postgres", "ref": "sector_daily_snapshots"}],
    }


async def _market_regime_reader(_tenant_id: str, market: str):
    return {
        "tool": "market.regime",
        "ok": True,
        "status": "ok",
        "data": {
            "schema_version": "market_regime_v1",
            "market_regime": {
                "status": "available",
                "market": market,
                "regime": "risk_on",
                "risk_bias": "constructive",
                "summary": "市场风险偏好较强，板块平均 +1.50%，上涨占比 70%",
                "sector_count": 10,
                "positive_sector_ratio": 0.7,
                "average_change_pct": 1.5,
            },
        },
        "source_refs": [{"source": "postgres", "ref": "sector_daily_snapshots"}],
    }


async def _news_context_reader(_tenant_id: str, symbol: str, market: str, _sector: str | None, _industry: str | None):
    return {
        "tool": "news.context",
        "ok": True,
        "status": "available",
        "data": {
            "schema_version": "stock_news_context_v1",
            "news_context": {
                "status": "available",
                "symbol": symbol,
                "market": market,
                "summary": "AI 芯片需求与财报窗口共同抬高波动。",
                "items": [
                    {
                        "headline": "NVIDIA 发布新 AI 芯片路线图",
                        "source": "test-news",
                        "published_at": "2026-06-17T01:00:00Z",
                        "impact": "positive",
                    }
                ],
                "catalysts": [
                    {
                        "label": "财报窗口",
                        "date": "2026-06-20",
                        "impact": "volatility",
                        "summary": "财报前后波动可能放大。",
                    }
                ],
            },
        },
        "source_refs": [{"source": "test", "ref": "news_context"}],
    }


@pytest.mark.asyncio
async def test_stock_analysis_builds_conclusion_first_bounded_report():
    service = HermesStockAnalysisService(
        quote_reader=_quote_reader,
        positions_reader=_positions_reader,
        history_reader=_history_reader,
        persistence=StockAnalysisPersistence(None),
    )

    result = await service.analyze(
        tenant_id="tenant-test",
        symbol="NVDA",
        prompt="NVDA 怎么看",
    )
    payload = result.model_dump()
    data = payload["data"]

    assert payload["tool"] == "stock.analysis"
    assert data["schema_version"] == "stock_analysis_p1"
    assert data["action"] == "review_take_profit"
    assert data["report_constraints"] == {
        "conclusion_first": True,
        "module_max_chars": MAX_REPORT_MODULE_CHARS,
    }
    assert list(data["report"].keys())[0] == "conclusion"
    assert "Technology/Semiconductors" in data["report"]["market"]
    assert data["trend"]["change_5d_pct"] == 9.52
    assert data["context_pack"]["schema_version"] == ANALYSIS_CONTEXT_SCHEMA_VERSION
    assert data["context_pack"]["summary"]["held"] is True
    assert data["discipline_result"]["status"] in {"warned", "requires_confirmation", "passed"}
    assert data["discipline_result"]["actionability_cap"] == "analysis_only"
    assert data["quality_display"]["schema_version"] == "quality_display_v1"
    assert data["quality_display"]["source"] == "test"
    assert data["quality_display"]["freshness"] == "fresh"
    assert data["quality_display"]["actionability"] == "analysis_only"
    assert data["quality_display"]["actionability_label"] == "只能观察"
    assert "数据质量：" in data["short_reply"]
    assert all(len(value) <= MAX_REPORT_MODULE_CHARS for value in data["report"].values())


@pytest.mark.asyncio
async def test_stock_analysis_quality_display_marks_stale_and_missing_position_context():
    async def stale_quote_reader(symbol: str):
        return {
            "ok": True,
            "data": {
                "symbol": symbol,
                "name": "Intel",
                "market": "US",
                "price": 31.2,
                "currency": "USD",
                "source": "test-stale",
                "quote_actionability": "analysis_only",
                "freshness_seconds": 3600,
                "as_of": "2026-06-17T01:00:00+00:00",
            },
        }

    async def empty_positions_reader(_tenant_id: str):
        return {"ok": True, "data": {"equity_positions": [], "option_positions": []}}

    service = HermesStockAnalysisService(
        quote_reader=stale_quote_reader,
        positions_reader=empty_positions_reader,
        persistence=StockAnalysisPersistence(None),
    )

    payload = (
        await service.analyze(
            tenant_id="tenant-test",
            symbol="INTC",
            prompt="INTC 怎么看",
            persist=False,
        )
    ).model_dump()

    quality = payload["data"]["quality_display"]
    assert quality["source"] == "test-stale"
    assert quality["as_of"] == "2026-06-17T01:00:00+00:00"
    assert quality["freshness"] == "stale"
    assert quality["freshness_label"] == "数据过期"
    assert quality["actionability_label"] == "只能观察"
    assert quality["degrade_reason"] == "data_stale"
    assert "数据过期" in quality["summary"]
    assert payload["data"]["persistence"] == {"status": "skipped", "reason": "persist_false"}


@pytest.mark.asyncio
async def test_stock_analysis_builds_context_pack_v2_with_legacy_fields():
    captured: dict[str, object] = {}

    class CapturingPersistence(StockAnalysisPersistence):
        async def save(self, **kwargs):
            captured.update(kwargs)
            return {"status": "captured"}

    service = HermesStockAnalysisService(
        quote_reader=_quote_reader,
        positions_reader=_positions_reader,
        history_reader=_history_reader,
        persistence=CapturingPersistence(None),
    )

    result = await service.analyze(
        tenant_id="tenant-test",
        symbol="NVDA",
        prompt="NVDA 怎么看",
    )
    context = captured["context"]
    data = result.model_dump()["data"]

    assert context["schema_version"] == ANALYSIS_CONTEXT_SCHEMA_VERSION
    assert context["legacy_schema_version"] == "stock_analysis_context_p1"
    assert context["quote"]["symbol"] == "NVDA"
    assert context["portfolio_summary"]["held_position"]["symbol"] == "NVDA"
    assert context["position_context"]["status"] == "held"
    assert context["market_context"]["trend"]["change_10d_pct"] == 15.0
    assert context["sector_context"]["status"] == "not_available"
    assert context["rules_context"]["active_rules"] == []
    assert context["historical_decisions"]["items"] == []
    assert context["news_context"]["status"] == "not_configured"
    assert context["data_quality"]["coverage"]["quote"] is True
    assert data["persistence"] == {"status": "captured"}


@pytest.mark.asyncio
async def test_stock_analysis_uses_sector_context_reader():
    service = HermesStockAnalysisService(
        quote_reader=_quote_reader,
        positions_reader=_positions_reader,
        history_reader=_history_reader,
        sector_context_reader=_sector_context_reader,
        persistence=StockAnalysisPersistence(None),
    )

    result = await service.analyze(tenant_id="tenant-test", symbol="NVDA", persist=False)
    data = result.model_dump()["data"]

    assert data["context_pack"]["summary"]["sector_context_status"] == "available"
    assert data["data_quality"]["sector_context_status"] == "available"
    assert "板块+1.23%" in data["report"]["market"]
    assert "相对强度+0.87" in data["report"]["market"]


@pytest.mark.asyncio
async def test_stock_analysis_uses_market_regime_reader():
    service = HermesStockAnalysisService(
        quote_reader=_quote_reader,
        positions_reader=_positions_reader,
        history_reader=_history_reader,
        market_regime_reader=_market_regime_reader,
        persistence=StockAnalysisPersistence(None),
    )

    result = await service.analyze(tenant_id="tenant-test", symbol="NVDA", persist=False)
    data = result.model_dump()["data"]

    assert data["context_pack"]["summary"]["market_regime_status"] == "available"
    assert data["context_pack"]["summary"]["market_regime"] == "risk_on"
    assert data["data_quality"]["market_regime_status"] == "available"
    assert "市场风险偏好较强" in data["report"]["market"]


@pytest.mark.asyncio
async def test_stock_analysis_v2_outputs_news_catalysts_and_change_reason():
    service = HermesStockAnalysisService(
        quote_reader=_quote_reader,
        positions_reader=_positions_reader,
        history_reader=_history_reader,
        sector_context_reader=_sector_context_reader,
        market_regime_reader=_market_regime_reader,
        news_context_reader=_news_context_reader,
        persistence=StockAnalysisPersistence(None),
    )

    result = await service.analyze(tenant_id="tenant-test", symbol="NVDA", persist=False)
    data = result.model_dump()["data"]

    assert data["context_pack"]["summary"]["news_status"] == "available"
    assert data["data_quality"]["news_status"] == "available"
    assert data["data_quality"]["news_items_count"] == 1
    assert data["data_quality"]["catalysts_count"] == 1
    assert data["why_changed"]["status"] in {"changed_explained", "context_explained"}
    assert "NVIDIA 发布新 AI 芯片路线图" in data["report"]["events"]
    assert "为什么变了" in data["report"]["why_changed"]
    assert any("近期催化剂" in item for item in data["risk_flags"])
    assert all(len(value) <= MAX_REPORT_MODULE_CHARS for value in data["report"].values())


@pytest.mark.asyncio
async def test_stock_analysis_outputs_historical_decision_compare():
    async def historical_positions(_tenant_id: str):
        payload = await _positions_reader(_tenant_id)
        payload["data"]["equity_positions"][0]["unrealized_pnl_pct"] = 23.45
        return payload

    service = HermesStockAnalysisService(
        quote_reader=_quote_reader,
        positions_reader=historical_positions,
        history_reader=_history_reader,
        persistence=StockAnalysisPersistence(None),
    )

    context = {
        "schema_version": ANALYSIS_CONTEXT_SCHEMA_VERSION,
        "rules_context": {},
        "sector_context": {},
        "market_regime": {},
        "news_context": {},
        "historical_decisions": {
            "status": "available",
            "items": [
                {
                    "id": "signal-prev",
                    "action": "watch",
                    "action_label": "观察",
                    "score": 55,
                    "watch_conditions": ["观察价格是否有效突破或跌破 123.45 附近"],
                }
            ],
        },
    }
    quote = (await _quote_reader("NVDA"))["data"]
    positions = (await historical_positions("tenant-test"))["data"]
    history = await _history_reader("NVDA", "US")
    data = service_module_build_analysis_for_test(
        symbol="NVDA",
        market="US",
        quote=quote,
        positions=positions,
        held_position=positions["equity_positions"][0],
        history_payload=history,
        prompt="NVDA 怎么看",
        context=context,
    )

    assert data["history_compare"]["status"] == "changed"
    assert data["history_compare"]["action_change"] == "观察 -> 复核止盈"
    assert data["history_compare"]["repeated_watch_conditions_count"] == 1
    assert "历史对比" in data["report"]["history_compare"]


@pytest.mark.asyncio
async def test_stock_analysis_blocks_sell_put_when_cash_is_insufficient():
    async def low_cash_positions(_tenant_id: str):
        payload = await _positions_reader(_tenant_id)
        payload["data"]["available_cash"] = 1_000
        payload["data"]["total_equity"] = 50_000
        return payload

    service = HermesStockAnalysisService(
        quote_reader=_quote_reader,
        positions_reader=low_cash_positions,
        history_reader=_history_reader,
        persistence=StockAnalysisPersistence(None),
    )

    result = await service.analyze(
        tenant_id="tenant-test",
        symbol="NVDA",
        prompt="NVDA sell put 可以做吗",
        persist=False,
    )
    data = result.model_dump()["data"]

    assert data["actionability_cap"] == "blocked"
    assert data["action"] == "discipline_blocked"
    assert data["discipline_result"]["status"] == "blocked"
    assert any(item["rule"] == "sell_put_cash_secured" for item in data["discipline_result"]["violations"])
    assert "现金担保不足" in data["report"]["discipline"]


@pytest.mark.asyncio
async def test_stock_analysis_applies_configured_trading_rule_cash_buffer():
    quote = (await _quote_reader("NVDA"))["data"]
    positions = (await _positions_reader("tenant-test"))["data"]
    positions["available_cash"] = 3_000
    positions["total_equity"] = 50_000
    context = {
        "schema_version": ANALYSIS_CONTEXT_SCHEMA_VERSION,
        "rules_context": {
            "status": "available",
            "active_rules": [],
            "recent_triggers": [],
            "trading_rules": [
                {
                    "id": "rule-cash-buffer",
                    "name": "加仓前现金缓冲",
                    "rule_key": "custom-cash-buffer",
                    "rule_type": "risk_budget",
                    "scopes": ["trade_draft"],
                    "markets": ["US"],
                    "instruments": ["stock"],
                    "condition": {"min_cash_buffer_pct": 20},
                    "message": "现金缓冲不足，先不要加仓。",
                    "action_on_violation": "block",
                    "priority": 5,
                }
            ],
        },
        "sector_context": {},
        "market_regime": {},
        "news_context": {},
        "historical_decisions": {"status": "available", "items": []},
    }

    data = service_module_build_analysis_for_test(
        symbol="NVDA",
        market="US",
        quote=quote,
        positions=positions,
        held_position=positions["equity_positions"][0],
        history_payload=await _history_reader("NVDA", "US"),
        prompt="NVDA 要不要加仓",
        context=context,
    )

    assert data["actionability_cap"] == "blocked"
    assert data["action"] == "discipline_blocked"
    assert data["data_quality"]["trading_rules_count"] == 1
    assert any(item["rule"] == "trading_rules:custom-cash-buffer" for item in data["discipline_result"]["violations"])
    assert "现金缓冲不足，先不要加仓" in data["report"]["discipline"]


@pytest.mark.asyncio
async def test_stock_analysis_degrades_when_quote_is_unavailable():
    async def failing_quote(_symbol: str):
        raise RuntimeError("quote down")

    service = HermesStockAnalysisService(
        quote_reader=failing_quote,
        positions_reader=_positions_reader,
        persistence=StockAnalysisPersistence(None),
    )

    result = await service.analyze(tenant_id="tenant-test", symbol="NVDA", persist=False)
    data = result.model_dump()["data"]

    assert data["action"] == "data_blocked"
    assert data["actionability_cap"] == "blocked"
    assert "行情不可用" in data["report"]["risk"]


@pytest.mark.asyncio
async def test_stock_analysis_persistence_uses_database_url(monkeypatch):
    executed_sql: list[str] = []

    class FakeCursor:
        def __init__(self):
            self.index = 0

        def __enter__(self):
            return self

        def __exit__(self, *_exc):
            return False

        def execute(self, sql, _params=None):
            executed_sql.append(sql)
            return self

        def fetchone(self):
            self.index += 1
            return {"id": f"00000000-0000-0000-0000-00000000000{self.index}"}

    class FakeConnection:
        def __init__(self):
            self.committed = False
            self.cursor_instance = FakeCursor()

        def __enter__(self):
            return self

        def __exit__(self, *_exc):
            return False

        def cursor(self):
            return self.cursor_instance

        def commit(self):
            self.committed = True

    fake_connection = FakeConnection()
    fake_psycopg = types.ModuleType("psycopg")
    fake_psycopg.connect = lambda *_args, **_kwargs: fake_connection
    fake_rows = types.ModuleType("psycopg.rows")
    fake_rows.dict_row = object()
    fake_json = types.ModuleType("psycopg.types.json")
    fake_json.Jsonb = lambda value: value

    monkeypatch.setitem(sys.modules, "psycopg", fake_psycopg)
    monkeypatch.setitem(sys.modules, "psycopg.rows", fake_rows)
    monkeypatch.setitem(sys.modules, "psycopg.types.json", fake_json)

    persistence = StockAnalysisPersistence(database_url="postgresql://example")
    result = await persistence.save(
        tenant_id="00000000-0000-0000-0000-000000000000",
        symbol="NVDA",
        analysis={
            "actionability_cap": "analysis_only",
            "action": "watch",
            "action_label": "观察",
            "confidence_score": 0.65,
            "score": 55,
            "market": "US",
            "report": {"conclusion": "观察"},
            "watch_conditions": ["观察价格"],
            "risk_flags": [],
            "data_quality": {},
            "discipline_result": {
                "status": "warned",
                "highest_action": "warn",
                "summary": "现金缓冲不足，先不要加仓。",
                "checks": [],
                "violations": [
                    {
                        "source": "trading_rules",
                        "rule_id": "11111111-1111-1111-1111-111111111111",
                        "action": "warn",
                        "message": "现金缓冲不足，先不要加仓。",
                    }
                ],
            },
        },
        context={"source_refs": []},
        create_alert_drafts=True,
    )

    assert result["status"] == "saved"
    assert result["backend"] == "postgres"
    assert fake_connection.committed is True
    assert any("INSERT INTO public.agent_runs" in sql for sql in executed_sql)
    assert any("INSERT INTO public.decision_signals" in sql for sql in executed_sql)
    assert any("INSERT INTO public.discipline_checks" in sql for sql in executed_sql)
    assert any("INSERT INTO public.alert_rules" in sql for sql in executed_sql)
