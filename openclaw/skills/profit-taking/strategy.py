"""
Profit-taking strategy engine.

This module is intentionally pure: it accepts historical bars, market bars,
position data, and a current quote, then returns a deterministic action plan.
The orchestrator owns IO, persistence, and delivery creation.
"""
from __future__ import annotations

from dataclasses import dataclass
from statistics import mean
from typing import Any


MIN_BACKTEST_BARS = 40
MIN_VALIDATION_SIGNALS = 4
MIN_VALIDATION_WIN_RATE = 0.5


@dataclass(frozen=True)
class StrategyRule:
    """A candidate profit-taking rule tested against history."""

    profit_trigger_pct: float
    trailing_drawdown_pct: float
    atr_multiple: float
    reduce_ratio: float


DEFAULT_RULES = [
    StrategyRule(0.10, 0.045, 2.0, 0.25),
    StrategyRule(0.15, 0.060, 2.5, 0.33),
    StrategyRule(0.20, 0.075, 3.0, 0.40),
]


def build_profit_taking_plan(
    position: dict[str, Any],
    quote: dict[str, Any],
    price_bars: list[dict[str, Any]],
    market_bars: list[dict[str, Any]],
    today: str,
) -> dict[str, Any]:
    """
    Build a profit-taking action plan for one holding.

    Strategy outline:
    - validate candidate rules with historical backtest
    - adjust the target threshold using broad-market regime
    - track current profit, ATR, RSI, moving averages, and trailing drawdown
    - emit TAKE_PROFIT when the rule is hit, WATCH_TARGET when today's range can
      plausibly touch the target, otherwise HOLD
    """
    symbol = str(position.get("symbol") or "")
    name = str(position.get("stock_name") or position.get("name") or symbol)
    market = str(position.get("market") or quote.get("market") or "")
    average_cost = _as_float(position.get("average_cost")) or _as_float(position.get("price")) or 0.0
    quantity = int(_as_float(position.get("total_quantity")) or _as_float(position.get("quantity")) or 0)
    current_price = _as_float(quote.get("price")) or _last_close(price_bars) or 0.0

    backtest = backtest_profit_taking_strategy(price_bars)
    indicators = calculate_indicators(price_bars)
    market_regime = classify_market_regime(market_bars)

    if average_cost <= 0 or quantity <= 0 or current_price <= 0:
        return _plan(
            position=position,
            symbol=symbol,
            name=name,
            market=market,
            today=today,
            action="HOLD",
            target_price=0.0,
            stop_price=0.0,
            reduce_ratio=0.0,
            today_reach_probability="low",
            metrics={"profit_pct": 0.0, **indicators},
            backtest=backtest,
            reason="持仓成本、数量或当前价格不足，暂不生成止盈指令。",
        )

    selected_rule = backtest["selected_rule"]
    threshold = float(selected_rule["profit_trigger_pct"])
    if market_regime["regime"] == "risk_off":
        threshold = max(0.06, threshold - 0.03)
    elif market_regime["regime"] == "risk_on":
        threshold = threshold + 0.02

    target_price = round(average_cost * (1 + threshold), 4)
    atr = max(float(indicators.get("atr14") or 0), current_price * 0.015)
    highest_close_20 = float(indicators.get("highest_close_20") or current_price)
    trailing_stop_price = round(
        max(
            average_cost * 1.02,
            highest_close_20 - atr * float(selected_rule["atr_multiple"]),
        ),
        4,
    )

    profit_pct = (current_price - average_cost) / average_cost
    drawdown_from_high = (
        (highest_close_20 - current_price) / highest_close_20
        if highest_close_20 > 0 else 0.0
    )
    rsi14 = float(indicators.get("rsi14") or 50)
    close_above_sma20 = current_price >= float(indicators.get("sma20") or current_price)
    overbought = rsi14 >= 70 or quote.get("change_rate", 0) >= 3
    trailing_hit = (
        profit_pct > 0.04
        and drawdown_from_high >= float(selected_rule["trailing_drawdown_pct"])
    )
    target_hit = profit_pct >= threshold
    target_gap = max(target_price - current_price, 0.0)
    today_reach_probability = _estimate_today_reach_probability(
        target_gap=target_gap,
        atr=atr,
        close_above_sma20=close_above_sma20,
        market_regime=market_regime["regime"],
    )

    metrics = {
        "profit_pct": round(profit_pct, 4),
        "drawdown_from_high": round(drawdown_from_high, 4),
        **indicators,
        "market_regime": market_regime,
    }

    if not backtest["validated"]:
        action = "HOLD"
        reduce_ratio = 0.0
        reason = "历史回测样本未证明当前止盈规则有效，今日仅观察不发出止盈指令。"
    elif target_hit and (overbought or trailing_hit or not close_above_sma20):
        action = "TAKE_PROFIT"
        reduce_ratio = float(selected_rule["reduce_ratio"])
        if market_regime["regime"] == "risk_off":
            reduce_ratio = min(0.5, reduce_ratio + 0.1)
        reason = (
            f"{name}({symbol}) 当前浮盈 {profit_pct:.1%}，已达到回测验证的"
            f"{threshold:.1%} 止盈阈值；RSI={rsi14:.1f}，20日高点回撤"
            f"{drawdown_from_high:.1%}。建议按计划止盈。"
        )
    elif target_gap <= atr and profit_pct > 0:
        action = "WATCH_TARGET"
        reduce_ratio = 0.0
        reason = (
            f"{name}({symbol}) 距离止盈目标约 {target_gap:.2f}，小于一日ATR"
            f"{atr:.2f}，今日有机会触达目标价。"
        )
    else:
        action = "HOLD"
        reduce_ratio = 0.0
        reason = (
            f"{name}({symbol}) 当前浮盈 {profit_pct:.1%}，尚未满足止盈行动规则。"
        )

    return _plan(
        position=position,
        symbol=symbol,
        name=name,
        market=market,
        today=today,
        action=action,
        target_price=target_price,
        stop_price=trailing_stop_price,
        reduce_ratio=round(reduce_ratio, 2),
        today_reach_probability=today_reach_probability,
        metrics=metrics,
        backtest=backtest,
        reason=reason,
    )


def backtest_profit_taking_strategy(
    price_bars: list[dict[str, Any]],
    candidate_rules: list[StrategyRule] | None = None,
) -> dict[str, Any]:
    """
    Backtest candidate profit-taking rules on historical bars.

    A signal is considered successful when selling after the trigger avoids a
    weak short-term path: either the next five bars end lower than the signal
    close or their max drawdown exceeds 3%. This is deliberately conservative;
    the rule must prove that it tends to protect gains, not merely fire often.
    """
    bars = _normalize_bars(price_bars)
    rules = candidate_rules or DEFAULT_RULES

    if len(bars) < MIN_BACKTEST_BARS:
        return _backtest_result(False, rules[0], 0, 0, 0.0, 0.0)

    best: dict[str, Any] | None = None
    for rule in rules:
        signals = 0
        wins = 0
        avoided_drawdowns: list[float] = []

        for idx in range(20, len(bars) - 5):
            window = bars[idx - 20:idx + 1]
            current = bars[idx]
            base_close = bars[max(0, idx - 20)]["close"]
            highest_close = max(row["close"] for row in window)
            profit_pct = (current["close"] - base_close) / base_close if base_close else 0
            drawdown = (highest_close - current["close"]) / highest_close if highest_close else 0

            if profit_pct < rule.profit_trigger_pct and drawdown < rule.trailing_drawdown_pct:
                continue

            future = bars[idx + 1:idx + 6]
            future_return = (future[-1]["close"] - current["close"]) / current["close"]
            future_drawdown = (
                min(row["low"] for row in future) - current["close"]
            ) / current["close"]
            success = future_return <= 0 or future_drawdown <= -0.03

            signals += 1
            if success:
                wins += 1
                avoided_drawdowns.append(abs(future_drawdown))

        win_rate = wins / signals if signals else 0.0
        avg_avoided_drawdown = mean(avoided_drawdowns) if avoided_drawdowns else 0.0
        score = win_rate * min(signals, 20) + avg_avoided_drawdown * 10
        candidate = _backtest_result(
            validated=signals >= MIN_VALIDATION_SIGNALS and win_rate >= MIN_VALIDATION_WIN_RATE,
            rule=rule,
            sample_size=signals,
            wins=wins,
            win_rate=win_rate,
            avg_avoided_drawdown=avg_avoided_drawdown,
            score=score,
        )
        if best is None or candidate["score"] > best["score"]:
            best = candidate

    assert best is not None
    return best


def calculate_indicators(price_bars: list[dict[str, Any]]) -> dict[str, Any]:
    """Calculate a compact indicator set used by the action rules."""
    bars = _normalize_bars(price_bars)
    if not bars:
        return {
            "sma20": None,
            "sma60": None,
            "atr14": None,
            "rsi14": None,
            "highest_close_20": None,
        }

    closes = [row["close"] for row in bars]
    sma20 = mean(closes[-20:]) if len(closes) >= 20 else mean(closes)
    sma60 = mean(closes[-60:]) if len(closes) >= 60 else sma20
    highest_close_20 = max(closes[-20:])

    true_ranges: list[float] = []
    for idx, row in enumerate(bars[-14:], start=max(0, len(bars) - 14)):
        prev_close = bars[idx - 1]["close"] if idx > 0 else row["close"]
        true_ranges.append(max(
            row["high"] - row["low"],
            abs(row["high"] - prev_close),
            abs(row["low"] - prev_close),
        ))
    atr14 = mean(true_ranges) if true_ranges else 0.0
    rsi14 = _rsi(closes[-15:])

    return {
        "sma20": round(sma20, 4),
        "sma60": round(sma60, 4),
        "atr14": round(atr14, 4),
        "rsi14": round(rsi14, 2),
        "highest_close_20": round(highest_close_20, 4),
    }


def classify_market_regime(market_bars: list[dict[str, Any]]) -> dict[str, Any]:
    """Classify broad-market state from index bars."""
    bars = _normalize_bars(market_bars)
    if len(bars) < 20:
        return {"regime": "neutral", "reason": "大盘历史样本不足"}

    closes = [row["close"] for row in bars]
    last_close = closes[-1]
    sma20 = mean(closes[-20:])
    sma60 = mean(closes[-60:]) if len(closes) >= 60 else sma20
    return_20d = (last_close - closes[-20]) / closes[-20] if closes[-20] else 0.0

    if last_close < sma20 and return_20d < -0.03:
        regime = "risk_off"
        reason = "指数低于20日均线且20日跌幅超过3%"
    elif last_close > sma20 > sma60 and return_20d > 0.02:
        regime = "risk_on"
        reason = "指数位于20/60日均线上方且20日趋势向上"
    else:
        regime = "neutral"
        reason = "指数趋势中性"

    return {
        "regime": regime,
        "reason": reason,
        "index_close": round(last_close, 4),
        "sma20": round(sma20, 4),
        "sma60": round(sma60, 4),
        "return_20d": round(return_20d, 4),
    }


def _plan(
    position: dict[str, Any],
    symbol: str,
    name: str,
    market: str,
    today: str,
    action: str,
    target_price: float,
    stop_price: float,
    reduce_ratio: float,
    today_reach_probability: str,
    metrics: dict[str, Any],
    backtest: dict[str, Any],
    reason: str,
) -> dict[str, Any]:
    instruction = _format_instruction(
        action=action,
        symbol=symbol,
        name=name,
        quantity=int(_as_float(position.get("total_quantity")) or 0),
        target_price=target_price,
        stop_price=stop_price,
        reduce_ratio=reduce_ratio,
        reason=reason,
    )
    return {
        "tenant_id": position.get("tenant_id"),
        "symbol": symbol,
        "stock_name": name,
        "market": market,
        "plan_date": today,
        "action": action,
        "target_price": target_price,
        "stop_price": stop_price,
        "reduce_ratio": reduce_ratio,
        "today_reach_probability": today_reach_probability,
        "metrics": metrics,
        "backtest": backtest,
        "reason": reason,
        "instruction": instruction,
        "should_push": action in {"TAKE_PROFIT", "WATCH_TARGET"},
    }


def _format_instruction(
    action: str,
    symbol: str,
    name: str,
    quantity: int,
    target_price: float,
    stop_price: float,
    reduce_ratio: float,
    reason: str,
) -> str:
    display = f"{name}({symbol})" if name else symbol
    if action == "TAKE_PROFIT":
        reduce_qty = max(1, int(quantity * reduce_ratio)) if quantity > 0 else 0
        return (
            f"止盈提醒：{display} 已触发止盈纪律。可考虑分批降低约 {reduce_ratio:.0%}"
            f"仓位（约 {reduce_qty} 股/份），参考目标价 {target_price:.2f}，动态保护价"
            f" {stop_price:.2f}。依据：{reason} 执行前请结合实时盘口和账户情况确认。"
        )
    if action == "WATCH_TARGET":
        return (
            f"止盈观察：{display} 今日接近止盈观察价 {target_price:.2f}。"
            f"若盘中放量冲高且接近该价位，可优先评估是否分批止盈；动态保护价 {stop_price:.2f}。"
            f"依据：{reason}"
        )
    return f"止盈计划：{display} 暂未触发止盈纪律，参考目标价 {target_price:.2f}。依据：{reason}"


def _estimate_today_reach_probability(
    target_gap: float,
    atr: float,
    close_above_sma20: bool,
    market_regime: str,
) -> str:
    if target_gap <= 0:
        return "high"
    if atr <= 0:
        return "low"
    ratio = target_gap / atr
    if ratio <= 0.5:
        return "high"
    if ratio <= 1.0:
        return "medium" if close_above_sma20 or market_regime != "risk_off" else "low"
    return "low"


def _backtest_result(
    validated: bool,
    rule: StrategyRule,
    sample_size: int,
    wins: int,
    win_rate: float,
    avg_avoided_drawdown: float,
    score: float = 0.0,
) -> dict[str, Any]:
    return {
        "validated": validated,
        "sample_size": sample_size,
        "wins": wins,
        "win_rate": round(win_rate, 4),
        "avg_avoided_drawdown": round(avg_avoided_drawdown, 4),
        "score": round(score, 4),
        "selected_rule": {
            "profit_trigger_pct": rule.profit_trigger_pct,
            "trailing_drawdown_pct": rule.trailing_drawdown_pct,
            "atr_multiple": rule.atr_multiple,
            "reduce_ratio": rule.reduce_ratio,
        },
    }


def _normalize_bars(price_bars: list[dict[str, Any]]) -> list[dict[str, float]]:
    bars: list[dict[str, float]] = []
    for row in price_bars:
        close = _as_float(row.get("close"))
        if close is None or close <= 0:
            continue
        high = _as_float(row.get("high")) or close
        low = _as_float(row.get("low")) or close
        open_price = _as_float(row.get("open")) or close
        bars.append({
            "open": open_price,
            "high": max(high, low, close, open_price),
            "low": min(high, low, close, open_price),
            "close": close,
            "volume": _as_float(row.get("volume")) or 0.0,
        })
    return bars


def _rsi(closes: list[float]) -> float:
    if len(closes) < 2:
        return 50.0
    gains: list[float] = []
    losses: list[float] = []
    for prev, current in zip(closes, closes[1:]):
        change = current - prev
        if change >= 0:
            gains.append(change)
            losses.append(0.0)
        else:
            gains.append(0.0)
            losses.append(abs(change))
    avg_gain = mean(gains) if gains else 0.0
    avg_loss = mean(losses) if losses else 0.0
    if avg_loss == 0:
        return 100.0 if avg_gain > 0 else 50.0
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))


def _last_close(price_bars: list[dict[str, Any]]) -> float | None:
    bars = _normalize_bars(price_bars)
    if not bars:
        return None
    return bars[-1]["close"]


def _as_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
