"""
Tests for the profit-taking action plan strategy.

The strategy must be deterministic and testable without live market data:
- historical bars are backtested before a rule is accepted
- market regime adjusts the profit threshold
- current holdings produce concrete reduce/watch/hold instructions
"""
import importlib
import sys
from datetime import date, timedelta

import pytest

_PROJECT_ROOT = "/Users/jerry.wu/Documents/vibecodingapp/ai-holdings-analyzer-v2"
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

strategy_mod = importlib.import_module("openclaw.skills.profit-taking.strategy")


def _bars(start: str, prices: list[float]) -> list[dict]:
    start_date = date.fromisoformat(start)
    rows = []
    prev = prices[0]
    for idx, close in enumerate(prices):
        rows.append({
            "date": (start_date + timedelta(days=idx)).isoformat(),
            "open": prev,
            "high": max(prev, close) * 1.01,
            "low": min(prev, close) * 0.99,
            "close": close,
            "volume": 1_000_000 + idx * 1000,
        })
        prev = close
    return rows


def test_backtest_selects_effective_profit_rule():
    prices = []
    price = 100.0
    for cycle in range(8):
        prices.extend([price, price * 1.04, price * 1.09, price * 1.15, price * 1.18])
        price *= 1.07
        prices.extend([price, price * 0.96, price * 0.93, price * 0.91])
        price *= 0.98

    result = strategy_mod.backtest_profit_taking_strategy(_bars("2025-01-01", prices))

    assert result["validated"] is True
    assert result["sample_size"] >= 5
    assert result["win_rate"] >= 0.5
    assert result["selected_rule"]["profit_trigger_pct"] > 0


def test_build_action_plan_emits_take_profit_when_rules_hit():
    stock_prices = []
    base = 100.0
    for _ in range(10):
        stock_prices.extend([base, base * 1.05, base * 1.12, base * 1.18, base * 1.12])
        base *= 1.03
    stock_prices[-5:] = [178, 182, 186, 181, 176]
    market_prices = [3000 + idx * 2 for idx in range(90)]

    plan = strategy_mod.build_profit_taking_plan(
        position={
            "tenant_id": "tenant-a",
            "symbol": "SH600519",
            "stock_name": "贵州茅台",
            "market": "CN",
            "average_cost": 120,
            "total_quantity": 100,
        },
        quote={"price": 176, "change_rate": -1.2},
        price_bars=_bars("2025-01-01", stock_prices),
        market_bars=_bars("2025-01-01", market_prices),
        today="2025-04-01",
    )

    assert plan["action"] == "TAKE_PROFIT"
    assert plan["reduce_ratio"] > 0
    assert "止盈" in plan["instruction"]
    assert plan["backtest"]["validated"] is True


def test_build_action_plan_warns_when_target_is_reachable_today():
    stock_prices = []
    base = 100.0
    for _ in range(12):
        stock_prices.extend([base, base * 1.04, base * 1.10, base * 1.16, base * 1.08, base * 1.04])
        base *= 1.015
    stock_prices[-5:] = [114, 116, 118, 119, 119.5]
    market_prices = [3000 + idx for idx in range(90)]

    plan = strategy_mod.build_profit_taking_plan(
        position={
            "tenant_id": "tenant-a",
            "symbol": "AAPL",
            "stock_name": "Apple",
            "market": "US",
            "average_cost": 112,
            "total_quantity": 20,
        },
        quote={"price": 119.5, "change_rate": 0.8},
        price_bars=_bars("2025-01-01", stock_prices),
        market_bars=_bars("2025-01-01", market_prices),
        today="2025-04-01",
    )

    assert plan["action"] in {"WATCH_TARGET", "TAKE_PROFIT"}
    assert plan["target_price"] >= 119.5
    assert plan["today_reach_probability"] in {"medium", "high"}


def test_build_action_plan_holds_when_backtest_is_not_validated():
    flat_prices = [100.0 for _ in range(45)]

    plan = strategy_mod.build_profit_taking_plan(
        position={
            "tenant_id": "tenant-a",
            "symbol": "HK00700",
            "stock_name": "腾讯控股",
            "market": "HK",
            "average_cost": 99,
            "total_quantity": 100,
        },
        quote={"price": 100, "change_rate": 0.1},
        price_bars=_bars("2025-01-01", flat_prices),
        market_bars=_bars("2025-01-01", flat_prices),
        today="2025-04-01",
    )

    assert plan["action"] == "HOLD"
    assert plan["backtest"]["validated"] is False
