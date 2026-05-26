from __future__ import annotations

from .sellput_models import HoldScoreInput, OpenScoreInput, ScoreResult


class ScoreEngine:
    """Deterministic Sell Put scorecard engine used by Hermes."""

    def score_open(self, data: OpenScoreInput) -> ScoreResult:
        underlying, underlying_details = self._score_underlying_quality(data)
        option_value, option_details = self._score_option_value(data)
        risk, risk_details = self._score_open_risk(data)
        regime, regime_details = self._score_market_regime(data)

        total = round(underlying + option_value + risk + regime, 2)
        grade, action = self._open_grade_action(total)
        warnings = self._open_warnings(data)

        return ScoreResult(
            symbol=data.symbol,
            total_score=total,
            grade=grade,
            action=action,
            dimension_scores={
                "underlying_quality": underlying,
                "option_value": option_value,
                "risk_assessment": risk,
                "market_regime": regime,
            },
            details={
                "underlying_quality": underlying_details,
                "option_value": option_details,
                "risk_assessment": risk_details,
                "market_regime": regime_details,
            },
            warnings=warnings,
            recommendation=self._open_recommendation(action),
        )

    def score_hold(self, data: HoldScoreInput) -> ScoreResult:
        pnl, pnl_details = self._score_hold_pnl(data)
        underlying, underlying_details = self._score_hold_underlying(data)
        iv, iv_details = self._score_hold_iv(data)
        time_decay, time_details = self._score_hold_time_decay(data)
        management, management_details = self._score_hold_management(data)

        total = round(pnl + underlying + iv + time_decay + management, 2)
        grade, action = self._hold_grade_action(total)

        return ScoreResult(
            symbol=data.symbol,
            total_score=total,
            grade=grade,
            action=action,
            dimension_scores={
                "pnl_status": pnl,
                "underlying_dynamics": underlying,
                "iv_dynamics": iv,
                "time_decay": time_decay,
                "position_management": management,
            },
            details={
                "pnl_status": pnl_details,
                "underlying_dynamics": underlying_details,
                "iv_dynamics": iv_details,
                "time_decay": time_details,
                "position_management": management_details,
            },
            warnings=self._hold_warnings(data),
            recommendation=self._hold_recommendation(action),
        )

    def scan_chain(
        self,
        contracts: list[OpenScoreInput],
        min_score: int = 70,
    ) -> list[ScoreResult]:
        scores = [self.score_open(contract) for contract in contracts]
        eligible = [score for score in scores if score.total_score >= min_score]
        return sorted(eligible, key=lambda score: score.total_score, reverse=True)

    def _score_underlying_quality(
        self, data: OpenScoreInput
    ) -> tuple[float, dict[str, float]]:
        fundamentals = (
            self._score_revenue_growth(data.revenue_growth_yoy)
            + self._score_eps_growth(data.eps_growth_yoy)
            + (2 if data.fcf_positive and data.fcf_growing else 1 if data.fcf_positive else 0)
            + self._score_debt_to_equity(data.debt_to_equity)
        )
        technicals = (
            self._score_price_vs_ma200(data.price_vs_ma200_pct)
            + self._score_ma_alignment(data.ma_alignment)
            + self._score_rsi(data.rsi14)
            + self._score_drawdown(data.max_drawdown_30d_pct)
        )
        liquidity = (
            self._score_market_cap(data.market_cap_b)
            + self._score_stock_volume(data.avg_volume_20d_m)
            + self._score_chain_oi(data.chain_open_interest)
        )
        return round(fundamentals + technicals + liquidity, 2), {
            "fundamentals": round(fundamentals, 2),
            "technicals": round(technicals, 2),
            "liquidity": round(liquidity, 2),
        }

    def _score_option_value(
        self, data: OpenScoreInput
    ) -> tuple[float, dict[str, float]]:
        iv = (
            self._score_iv_rank(data.iv_rank)
            + self._score_iv_percentile(data.iv_percentile)
            + self._score_iv_hv(data.iv_hv_ratio)
        )
        premium = (
            self._score_annualized_yield(data.annualized_premium_yield)
            + self._score_premium_to_max_loss(data.premium_to_max_loss_pct)
            + self._score_premium_to_account(data.premium_to_account_pct)
        )
        microstructure = (
            self._score_spread(data.bid_ask_spread_pct)
            + self._score_contract_oi(data.contract_open_interest)
            + self._score_contract_volume(data.contract_volume)
        )
        return round(iv + premium + microstructure, 2), {
            "iv": round(iv, 2),
            "premium": round(premium, 2),
            "microstructure": round(microstructure, 2),
        }

    def _score_open_risk(self, data: OpenScoreInput) -> tuple[float, dict[str, float]]:
        otm_pct = data.otm_pct
        if otm_pct is None:
            otm_pct = max((data.underlying_price - data.strike) / data.underlying_price * 100, 0)
        breakeven = data.strike - data.premium
        breakeven_buffer_pct = max((data.underlying_price - breakeven) / data.underlying_price * 100, 0)
        distance = (
            self._score_otm(otm_pct)
            + self._score_delta(abs(data.delta))
            + self._score_breakeven_buffer(breakeven_buffer_pct)
        )
        events = (
            self._score_dte(data.dte)
            + self._score_earnings(data.earnings_before_expiry, data.earnings_days_before_expiry)
            + (0 if data.ex_dividend_before_expiry else 2)
            + (0 if data.major_event_before_expiry else 2)
        )
        greeks = (
            self._score_theta_efficiency(data.theta_to_premium_pct)
            + self._score_vega_impact(data.vega_pnl_impact_pct_per_iv_point)
            + self._score_gamma(data.gamma_risk)
        )
        return round(distance + events + greeks, 2), {
            "distance": round(distance, 2),
            "events": round(events, 2),
            "greeks": round(greeks, 2),
            "otm_pct": round(otm_pct, 2),
            "breakeven_buffer_pct": round(breakeven_buffer_pct, 2),
        }

    def _score_market_regime(self, data: OpenScoreInput) -> tuple[float, dict[str, float]]:
        vix = self._score_vix(data.vix)
        term = {"contango": 3, "flat": 1.5, "backwardation": 0}.get(
            data.vix_term_structure, 0
        )
        spy = {"bullish": 4, "above_ma50": 3, "bearish": 1}.get(data.spy_trend, 1)
        breadth = (
            2
            if data.market_breadth_pct_above_ma200 > 60
            else 1
            if data.market_breadth_pct_above_ma200 >= 40
            else 0
        )
        rates = {"stable": 2, "easing": 2, "moderate_hiking": 1, "aggressive_hiking": 0}.get(
            data.rate_environment, 1
        )
        return round(vix + term + spy + breadth + rates, 2), {
            "vix": vix,
            "term_structure": term,
            "spy": spy,
            "breadth": breadth,
            "rates": rates,
        }

    def _score_hold_pnl(self, data: HoldScoreInput) -> tuple[float, dict[str, float]]:
        if data.premium_collected <= 0:
            realized_profit_pct = 0
        else:
            realized_profit_pct = max(
                (data.premium_collected - data.current_option_price)
                / data.premium_collected
                * 100,
                -100,
            )
        remaining_time_value_pct = (
            max(data.current_option_price / data.premium_collected * 100, 0)
            if data.premium_collected > 0
            else 100
        )

        profit_score = 15 if realized_profit_pct > 80 else 10 if realized_profit_pct >= 50 else 5 if realized_profit_pct >= 20 else 2
        time_value_score = 10 if remaining_time_value_pct < 10 else 6 if remaining_time_value_pct <= 30 else 3 if remaining_time_value_pct <= 60 else 1
        pnl_direction_score = 5 if realized_profit_pct > 0 else 2 if realized_profit_pct > -5 else 1 if realized_profit_pct > -10 else 0
        return round(profit_score + time_value_score + pnl_direction_score, 2), {
            "realized_profit_pct": round(realized_profit_pct, 2),
            "remaining_time_value_pct": round(remaining_time_value_pct, 2),
        }

    def _score_hold_underlying(self, data: HoldScoreInput) -> tuple[float, dict[str, float]]:
        distance_pct = (data.underlying_price - data.strike) / data.underlying_price * 100
        distance = 10 if distance_pct > 15 else 7 if distance_pct >= 10 else 4 if distance_pct >= 5 else 1 if distance_pct >= 0 else 0
        trend = {"improved": 8, "stable": 8, "slightly_weaker": 4, "bearish": 1}.get(
            data.trend_change, 4
        )
        event = 0 if data.has_new_negative_event else 7
        return round(distance + trend + event, 2), {"distance_pct": round(distance_pct, 2)}

    def _score_hold_iv(self, data: HoldScoreInput) -> tuple[float, dict[str, float]]:
        iv_change = 10 if data.iv_change_pct < 0 else 3 if data.iv_change_pct < 20 else 0
        rank_delta = data.current_iv_rank - data.open_iv_rank
        rank = 5 if rank_delta < -20 else 3 if rank_delta <= 0 else 1
        vix = {"improved": 5, "flat": 3, "worse": 1}.get(data.vix_change, 3)
        return round(iv_change + rank + vix, 2), {"iv_rank_delta": round(rank_delta, 2)}

    def _score_hold_time_decay(self, data: HoldScoreInput) -> tuple[float, dict[str, float]]:
        elapsed_pct = (
            (data.dte_original - data.dte_remaining) / data.dte_original * 100
            if data.dte_original > 0
            else 0
        )
        elapsed = 8 if elapsed_pct > 80 else 5 if elapsed_pct >= 50 else 2
        theta_phase = 4 if data.dte_remaining < 15 else 3 if data.dte_remaining <= 30 else 1
        event = 0 if data.event_before_expiry else 3
        return round(elapsed + theta_phase + event, 2), {"elapsed_pct": round(elapsed_pct, 2)}

    def _score_hold_management(self, data: HoldScoreInput) -> tuple[float, dict[str, float]]:
        size = 4 if data.position_account_pct < 5 else 3 if data.position_account_pct <= 10 else 1 if data.position_account_pct <= 20 else 0
        margin = 3 if data.margin_usage_pct < 30 else 2 if data.margin_usage_pct <= 60 else 0
        roll = {"profitable": 3, "available": 1, "not_available": 0}.get(data.roll_quality, 1)
        return round(size + margin + roll, 2), {}

    @staticmethod
    def _open_grade_action(total: float) -> tuple[str, str]:
        if total >= 90:
            return "A", "SELL_CONFIDENT"
        if total >= 70:
            return "B", "SELL_LIMITED"
        return "C", "AVOID"

    @staticmethod
    def _hold_grade_action(total: float) -> tuple[str, str]:
        if total >= 90:
            return "A", "TAKE_PROFIT"
        if total >= 70:
            return "B", "HOLD"
        return "C", "ADJUST_OR_HEDGE"

    @staticmethod
    def _open_warnings(data: OpenScoreInput) -> list[str]:
        warnings: list[str] = []
        if data.bid_ask_spread_pct > 20:
            warnings.append("bid-ask spread too wide")
        if data.earnings_before_expiry:
            warnings.append("earnings before expiry")
        if abs(data.delta) > 0.35:
            warnings.append("delta assignment risk too high")
        if data.vix > 35 or data.vix_term_structure == "backwardation":
            warnings.append("market regime hostile to short premium")
        if data.major_event_before_expiry:
            warnings.append("major event before expiry")
        return warnings

    @staticmethod
    def _hold_warnings(data: HoldScoreInput) -> list[str]:
        warnings: list[str] = []
        if data.underlying_price < data.strike:
            warnings.append("position is in the money")
        if data.has_new_negative_event:
            warnings.append("new negative event detected")
        if data.event_before_expiry:
            warnings.append("event risk before expiry")
        if data.margin_usage_pct > 60:
            warnings.append("margin usage elevated")
        return warnings

    @staticmethod
    def _open_recommendation(action: str) -> str:
        return {
            "SELL_CONFIDENT": "High-quality sell put candidate; still size within risk limits.",
            "SELL_LIMITED": "Investable sell put candidate; use reduced size or wait for better pricing.",
            "AVOID": "Risk/reward is not attractive enough for a new sell put.",
        }[action]

    @staticmethod
    def _hold_recommendation(action: str) -> str:
        return {
            "TAKE_PROFIT": "Most premium has been captured or risk has risen; consider closing.",
            "HOLD": "Original thesis remains intact; continue monitoring.",
            "ADJUST_OR_HEDGE": "Position logic is impaired; consider stop, hedge, or roll.",
        }[action]

    @staticmethod
    def _score_revenue_growth(value: float) -> float:
        return 3 if value > 15 else 2 if value >= 5 else 1 if value >= 0 else 0

    @staticmethod
    def _score_eps_growth(value: float) -> float:
        return 3 if value > 20 else 2 if value >= 5 else 1 if value >= 0 else 0

    @staticmethod
    def _score_debt_to_equity(value: float) -> float:
        return 2 if value < 0.5 else 1.5 if value <= 1 else 1 if value <= 2 else 0

    @staticmethod
    def _score_price_vs_ma200(value: float) -> float:
        return 3 if value > 5 else 1.5 if value >= -5 else 0

    @staticmethod
    def _score_ma_alignment(value: str) -> float:
        return {"bullish": 2, "neutral": 1, "bearish": 0}.get(value, 1)

    @staticmethod
    def _score_rsi(value: float) -> float:
        return 2 if 40 <= value <= 60 else 1 if 30 <= value < 40 or 60 < value <= 70 else 0.5

    @staticmethod
    def _score_drawdown(value: float) -> float:
        return 1 if value < 5 else 0.5 if value <= 10 else 0

    @staticmethod
    def _score_market_cap(value: float) -> float:
        return 3 if value > 50 else 2.5 if value >= 10 else 1.5 if value >= 2 else 0.5

    @staticmethod
    def _score_stock_volume(value: float) -> float:
        return 2 if value > 5 else 1.5 if value >= 1 else 1 if value >= 0.1 else 0

    @staticmethod
    def _score_chain_oi(value: int) -> float:
        return 2 if value > 100000 else 1 if value >= 10000 else 0

    @staticmethod
    def _score_iv_rank(value: float) -> float:
        return 5 if value > 70 else 4 if value >= 50 else 2.5 if value >= 30 else 1

    @staticmethod
    def _score_iv_percentile(value: float) -> float:
        return 3 if value > 80 else 2 if value >= 50 else 1

    @staticmethod
    def _score_iv_hv(value: float) -> float:
        return 4 if value > 1.3 else 3 if value >= 1.1 else 1.5 if value >= 0.9 else 0

    @staticmethod
    def _score_annualized_yield(value: float) -> float:
        return 5 if value > 30 else 4 if value >= 20 else 3 if value >= 12 else 1.5 if value >= 5 else 0

    @staticmethod
    def _score_premium_to_max_loss(value: float) -> float:
        return 3 if value > 5 else 2 if value >= 3 else 1 if value >= 1 else 0

    @staticmethod
    def _score_premium_to_account(value: float) -> float:
        return 2 if value > 0.5 else 1 if value >= 0.2 else 0

    @staticmethod
    def _score_spread(value: float) -> float:
        return 3 if value < 5 else 2 if value <= 10 else 1 if value <= 20 else 0

    @staticmethod
    def _score_contract_oi(value: int) -> float:
        return 3 if value > 5000 else 2 if value >= 1000 else 1 if value >= 100 else 0

    @staticmethod
    def _score_contract_volume(value: int) -> float:
        return 2 if value > 500 else 1.5 if value >= 100 else 0.5 if value >= 10 else 0

    @staticmethod
    def _score_otm(value: float) -> float:
        return 5 if value > 15 else 4 if value >= 10 else 2.5 if value >= 5 else 1 if value >= 3 else 0

    @staticmethod
    def _score_delta(value: float) -> float:
        return 3 if value < 0.15 else 2 if value <= 0.25 else 1 if value <= 0.35 else 0

    @staticmethod
    def _score_breakeven_buffer(value: float) -> float:
        return 2 if value > 20 else 1.5 if value >= 10 else 0.5 if value >= 5 else 0

    @staticmethod
    def _score_dte(value: int) -> float:
        return 4 if 30 <= value <= 45 else 3 if 20 <= value < 30 or 45 < value <= 60 else 2 if 7 <= value < 20 else 1

    @staticmethod
    def _score_earnings(before_expiry: bool, days_before_expiry: int | None) -> float:
        if not before_expiry:
            return 4
        if days_before_expiry is None:
            return 1.5
        return 1.5 if days_before_expiry > 7 else 0

    @staticmethod
    def _score_theta_efficiency(value: float) -> float:
        return 3 if value > 3 else 2 if value >= 2 else 1 if value >= 1 else 0

    @staticmethod
    def _score_vega_impact(value: float) -> float:
        return 3 if value < 2 else 2 if value <= 3 else 0

    @staticmethod
    def _score_gamma(value: str) -> float:
        return {"low": 2, "medium": 1, "high": 0}.get(value, 1)

    @staticmethod
    def _score_vix(value: float) -> float:
        return 4 if 15 <= value <= 25 else 3 if 25 < value <= 35 else 2 if value < 15 else 1
