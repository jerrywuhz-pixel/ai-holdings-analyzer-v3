from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class OpenScoreInput:
    symbol: str
    strike: float
    expiry: str
    underlying_price: float
    premium: float
    dte: int
    delta: float
    iv_rank: float
    iv_percentile: float
    iv_hv_ratio: float
    annualized_premium_yield: float
    premium_to_max_loss_pct: float
    premium_to_account_pct: float
    bid_ask_spread_pct: float
    contract_open_interest: int
    contract_volume: int
    revenue_growth_yoy: float
    eps_growth_yoy: float
    fcf_positive: bool
    fcf_growing: bool
    debt_to_equity: float
    price_vs_ma200_pct: float
    ma_alignment: str
    rsi14: float
    max_drawdown_30d_pct: float
    market_cap_b: float
    avg_volume_20d_m: float
    chain_open_interest: int
    earnings_before_expiry: bool
    earnings_days_before_expiry: int | None
    ex_dividend_before_expiry: bool
    major_event_before_expiry: bool
    theta_to_premium_pct: float
    vega_pnl_impact_pct_per_iv_point: float
    gamma_risk: str
    vix: float
    vix_term_structure: str
    spy_trend: str
    market_breadth_pct_above_ma200: float
    rate_environment: str
    otm_pct: float | None = None


@dataclass(frozen=True)
class HoldScoreInput:
    symbol: str
    strike: float
    underlying_price: float
    premium_collected: float
    current_option_price: float
    dte_remaining: int
    dte_original: int
    current_iv_rank: float
    open_iv_rank: float
    iv_change_pct: float
    vix_change: str
    trend_change: str
    has_new_negative_event: bool
    position_account_pct: float
    margin_usage_pct: float
    roll_quality: str
    event_before_expiry: bool


@dataclass(frozen=True)
class ScoreResult:
    symbol: str
    total_score: float
    grade: str
    action: str
    dimension_scores: dict[str, float]
    details: dict[str, Any] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    recommendation: str = ""
