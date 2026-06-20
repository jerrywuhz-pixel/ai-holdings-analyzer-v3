from __future__ import annotations

import pytest

from services.hermes.opportunity_research import (
    OpportunityResearchPersistence,
    OpportunityResearchWorkflow,
    build_opportunity_mark,
    qqq_2x_daily_reset_return,
)


class FakePersistence(OpportunityResearchPersistence):
    def __init__(self) -> None:
        super().__init__(None, "")
        self.saved_research = []
        self.saved_marks = []
        self.candidate_pool = []

    async def load_candidate_pool(self, **kwargs):
        return self.candidate_pool

    async def save_research(self, **kwargs):
        self.saved_research.append(kwargs)
        return {
            "status": "saved",
            "agent_run_id": "run-1",
            "artifact_id": "artifact-1",
            "opportunity_case_ids": ["case-1"],
            "delivery": {"status": "enqueued"},
        }

    async def mark_case(self, **kwargs):
        self.saved_marks.append(kwargs)
        return {"status": "saved", "opportunity_case_mark_id": "mark-1", "mark": kwargs["mark"]}


@pytest.mark.asyncio
async def test_opportunity_research_creates_paper_cases_with_four_gates():
    persistence = FakePersistence()

    async def market_regime_reader(args):
        return {
            "tool": "market.regime",
            "ok": True,
            "data": {
                "schema_version": "market_regime_v1",
                "market_regime": {"status": "available", "market": args["market"], "regime": "risk_on", "risk_bias": "constructive"},
            },
            "source_refs": [{"source": "postgres", "ref": "sector_daily_snapshots"}],
        }

    async def portfolio_overview_reader(_args):
        return {"tool": "portfolio.overview", "ok": True, "data": {"year_to_date_profit": 10000}, "source_refs": [{"source": "postgres", "ref": "portfolio_overview"}]}

    async def positions_reader(_args):
        return {"tool": "broker.positions_read", "ok": True, "data": {"equity_positions": [{"symbol": "NVDA", "quantity": 1}]}, "source_refs": [{"source": "postgres", "ref": "portfolio_positions"}]}

    async def quote_reader(args):
        return {"tool": "market.quote", "ok": True, "data": {"symbol": args["symbol"], "price": 120, "market": "US"}}

    async def stock_analysis_reader(args):
        return {
            "tool": "stock.analysis",
            "ok": True,
            "data": {
                "symbol": args["symbol"],
                "name": args["symbol"],
                "market": "US",
                "current_price": 120,
                "actionability_cap": "suggested_action",
                "watch_conditions": ["突破昨日高点后复核"],
                "data_quality": {"quote_source": "test", "quote_actionability": "trade_draft"},
                "discipline_result": {"status": "passed", "actionability_cap": "suggested_action"},
                "report": {"conclusion": f"{args['symbol']} thesis present"},
                "persistence": {"decision_signal_id": "11111111-1111-1111-1111-111111111111"},
            },
            "source_refs": [{"source": "hermes-data-service", "ref": f"/api/quote/{args['symbol']}"}],
        }

    async def sell_put_reader(_args):
        return {"tool": "options.sell_put_rank", "ok": True, "data": {"summary": {"candidate_count": 0}}, "source_refs": []}

    workflow = OpportunityResearchWorkflow(
        market_regime_reader=market_regime_reader,
        portfolio_overview_reader=portfolio_overview_reader,
        positions_reader=positions_reader,
        quote_reader=quote_reader,
        stock_analysis_reader=stock_analysis_reader,
        sell_put_reader=sell_put_reader,
        persistence=persistence,
    )

    result = await workflow.run_research(
        tenant_id="22222222-2222-2222-2222-222222222222",
        market="US",
        symbols=["NVDA"],
        max_candidates=1,
        delivery_context={"channel_binding_id": "33333333-3333-3333-3333-333333333333"},
    )

    data = result.model_dump()["data"]
    assert data["schema_version"] == "opportunity_research_v1"
    assert data["safety"]["places_orders"] is False
    assert data["cases"][0]["symbol"] == "NVDA"
    assert data["cases"][0]["actionability_cap"] == "suggested_action"
    assert data["cases"][0]["discipline_snapshot"]["four_gates"]["fact_gate"]["status"] == "passed"
    assert data["cases"][0]["benchmark_policy"]["stretch_comparator"] == "QQQ_2x_daily_reset"
    assert data["candidate_pool"]["policy"]["leader_only"] is True
    assert data["model_policy"]["light_scan"]["model"] == "glm-5.2"
    assert data["model_policy"]["deep_research"] == {"model": "gpt-5.5", "fallback": "glm-5.2"}
    assert data["persistence"]["delivery"]["status"] == "enqueued"
    assert persistence.saved_research


@pytest.mark.asyncio
async def test_opportunity_research_allows_top3_per_theme_layer_into_cases():
    persistence = FakePersistence()
    persistence.candidate_pool = [
        {"market": "US", "symbol": "LDR1", "asset_theme": "AI accelerator leader 1", "asset_path": "ai_semiconductor_power_chain", "five_layer": "accelerated_compute", "playbook_key": "hard_tech_acceleration", "status": "watching"},
        {"market": "US", "symbol": "LDR2", "asset_theme": "AI accelerator leader 2", "asset_path": "ai_semiconductor_power_chain", "five_layer": "accelerated_compute", "playbook_key": "hard_tech_acceleration", "status": "watching"},
        {"market": "US", "symbol": "LDR3", "asset_theme": "AI accelerator leader 3", "asset_path": "ai_semiconductor_power_chain", "five_layer": "accelerated_compute", "playbook_key": "hard_tech_acceleration", "status": "watching"},
        {"market": "US", "symbol": "LDR4", "asset_theme": "AI accelerator laggard", "asset_path": "ai_semiconductor_power_chain", "five_layer": "accelerated_compute", "playbook_key": "hard_tech_acceleration", "status": "watching"},
    ]
    calls = []

    async def market_regime_reader(args):
        return {"ok": True, "data": {"market_regime": {"market": args["market"], "regime": "risk_on", "risk_bias": "constructive"}}, "source_refs": []}

    async def portfolio_overview_reader(_args):
        return {"ok": True, "data": {"year_to_date_profit": 10000}, "source_refs": []}

    async def positions_reader(_args):
        return {"ok": True, "data": {"equity_positions": []}, "source_refs": []}

    async def quote_reader(args):
        quotes = {
            "LDR1": {"symbol": "LDR1", "price": 140, "previous_close": 130, "relative_strength": 92},
            "LDR2": {"symbol": "LDR2", "price": 120, "previous_close": 116, "relative_strength": 84},
            "LDR3": {"symbol": "LDR3", "price": 90, "previous_close": 89, "relative_strength": 76},
            "LDR4": {"symbol": "LDR4", "price": 80, "previous_close": 81, "relative_strength": 68},
        }
        return {"ok": True, "data": quotes.get(args["symbol"], {"symbol": args["symbol"], "price": 10, "previous_close": 10, "relative_strength": 45}), "source_refs": [{"source": "test", "ref": args["symbol"]}]}

    async def stock_analysis_reader(args):
        calls.append(args["symbol"])
        return {
            "ok": True,
            "data": {
                "symbol": args["symbol"],
                "market": "US",
                "current_price": 100,
                "actionability_cap": "suggested_action",
                "watch_conditions": ["leader strength persists"],
                "data_quality": {"quote_source": "test", "quote_actionability": "trade_draft"},
                "report": {"conclusion": f"{args['symbol']} remains leader"},
            },
            "source_refs": [{"source": "analysis", "ref": args["symbol"]}],
        }

    workflow = OpportunityResearchWorkflow(
        market_regime_reader=market_regime_reader,
        portfolio_overview_reader=portfolio_overview_reader,
        positions_reader=positions_reader,
        quote_reader=quote_reader,
        stock_analysis_reader=stock_analysis_reader,
        persistence=persistence,
    )

    result = await workflow.run_research(
        tenant_id="22222222-2222-2222-2222-222222222222",
        market="US",
        universe_policy="candidate_pool",
        max_candidates=10,
        persist=False,
    )

    data = result.model_dump()["data"]
    stock_cases = [case for case in data["cases"] if case["instrument_type"] == "stock"]
    case_symbols = {case["symbol"] for case in stock_cases}
    removal_symbols = {item["symbol"] for item in data["candidate_pool"]["removals"]}

    assert {"LDR1", "LDR2", "LDR3"} <= case_symbols
    assert "LDR4" not in case_symbols
    assert "LDR4" in removal_symbols
    assert calls == [case["symbol"] for case in stock_cases]
    assert all(case["leader_rank"] <= 3 for case in stock_cases)
    assert data["candidate_pool"]["mode"] == "centaur_leader_rotation"
    assert data["candidate_pool"]["policy"]["leader_top_n_per_group"] == 3


def test_opportunity_mark_uses_daily_reset_for_qqq_2x():
    mark = build_opportunity_mark(
        entry_price=100,
        mark_price=110,
        benchmark_entry_price=100,
        benchmark_mark_price=105,
        stretch_daily_returns=[0.10, -0.05],
        thesis_status="confirmed",
        discipline_status="adhered",
    )

    assert mark["paper_pnl_pct"] == 10.0
    assert mark["benchmark_return"] == 5.0
    assert mark["excess_return"] == 5.0
    assert mark["stretch_return"] == pytest.approx(8.0)
    assert qqq_2x_daily_reset_return([0.10, -0.05]) == pytest.approx(0.08)


@pytest.mark.asyncio
async def test_opportunity_review_marks_supplied_cases():
    persistence = FakePersistence()

    async def noop_reader(_args):
        return {"ok": True, "data": {}, "source_refs": []}

    async def quote_reader(args):
        return {"ok": True, "data": {"symbol": args["symbol"], "price": 105}}

    workflow = OpportunityResearchWorkflow(
        market_regime_reader=noop_reader,
        portfolio_overview_reader=noop_reader,
        positions_reader=noop_reader,
        quote_reader=quote_reader,
        stock_analysis_reader=noop_reader,
        persistence=persistence,
    )

    result = await workflow.run_review(
        tenant_id="22222222-2222-2222-2222-222222222222",
        cases=[
            {
                "id": "44444444-4444-4444-4444-444444444444",
                "symbol": "NVDA",
                "entry_rule": {"reference_price": 100},
                "benchmark_policy": {"entry_price": 100, "mark_price": 102},
            }
        ],
    )

    data = result.model_dump()["data"]
    assert data["reviewed_cases"] == 1
    assert data["marks"][0]["mark"]["paper_pnl_pct"] == 5.0
    assert persistence.saved_marks[0]["case_id"] == "44444444-4444-4444-4444-444444444444"
