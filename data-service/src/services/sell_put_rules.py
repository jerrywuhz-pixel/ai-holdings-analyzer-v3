from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, Field

MarketState = Literal["normal", "cautious", "stressed"]
AssignmentIntent = Literal["avoid_assignment", "neutral", "willing_to_assign"]


class SellPutThresholdOverrides(BaseModel):
    min_days_to_expiry: Optional[int] = None
    max_days_to_expiry: Optional[int] = None
    min_abs_delta: Optional[float] = None
    max_abs_delta: Optional[float] = None
    max_bid_ask_spread_pct: Optional[float] = None
    min_open_interest: Optional[int] = None
    min_volume: Optional[int] = None
    min_implied_volatility: Optional[float] = None
    max_implied_volatility: Optional[float] = None
    min_cash_coverage_ratio: Optional[float] = None
    max_underlying_concentration_ratio: Optional[float] = None
    allow_existing_short_put_exposure: Optional[bool] = None
    assignment_intent: Optional[AssignmentIntent] = None


class SellPutThresholdProfile(BaseModel):
    market_state: MarketState
    assignment_intent: AssignmentIntent
    min_days_to_expiry: int
    max_days_to_expiry: int
    min_abs_delta: float
    max_abs_delta: float
    max_bid_ask_spread_pct: float
    min_open_interest: int
    min_volume: int
    min_implied_volatility: float
    max_implied_volatility: float
    min_cash_coverage_ratio: float
    max_underlying_concentration_ratio: float
    allow_existing_short_put_exposure: bool


class CandidateRuleEvaluation(BaseModel):
    score: float
    spread_pct: float
    midpoint: float
    otm_pct: float
    annualized_yield: float
    cash_coverage_ratio: Optional[float] = None
    assignment_risk: Literal["low", "moderate", "high"]
    hard_blocks: list[str] = Field(default_factory=list)
    soft_flags: list[str] = Field(default_factory=list)
    fit_tags: list[str] = Field(default_factory=list)


class SellPutPlaybookStep(BaseModel):
    phase: Literal["close", "roll", "assignment"]
    trigger: str
    guidance: str
    auto_execute: bool = False


class SellPutPlaybook(BaseModel):
    mode: Literal["draft_only"] = "draft_only"
    summary: str
    assignment_risk: Literal["low", "moderate", "high"]
    actions: list[SellPutPlaybookStep] = Field(default_factory=list)


class UnderlyingGateAssessment(BaseModel):
    gate_status: Literal["passed", "degraded", "blocked"]
    actionability: Literal["trade_draft", "analysis_only", "blocked"]
    suitability_score: float
    market_state: MarketState
    assignment_intent: AssignmentIntent
    thresholds: SellPutThresholdProfile
    reasons: list[str] = Field(default_factory=list)
    user_reasons: list[str] = Field(default_factory=list)
    passed_checks: list[str] = Field(default_factory=list)
    user_note: str = ""


class CandidateRankingItem(BaseModel):
    rank: int
    contract_symbol: str
    actionability: Literal["trade_draft", "suggested_action", "analysis_only", "blocked"]
    score: float
    assignment_risk: Literal["low", "moderate", "high"]
    spread_pct: float
    rank_reasons: list[str] = Field(default_factory=list)


def resolve_thresholds(
    *,
    market_state: MarketState,
    assignment_intent: AssignmentIntent,
    overrides: Optional[SellPutThresholdOverrides] = None,
) -> SellPutThresholdProfile:
    defaults: dict[MarketState, dict[str, float | int]] = {
        "normal": {
            "min_days_to_expiry": 25,
            "max_days_to_expiry": 45,
            "min_abs_delta": 0.15,
            "max_abs_delta": 0.30,
            "max_bid_ask_spread_pct": 0.12,
            "min_open_interest": 500,
            "min_volume": 50,
            "min_implied_volatility": 0.20,
            "max_implied_volatility": 0.60,
            "min_cash_coverage_ratio": 1.0,
            "max_underlying_concentration_ratio": 0.75,
            "allow_existing_short_put_exposure": False,
        },
        "cautious": {
            "min_days_to_expiry": 21,
            "max_days_to_expiry": 40,
            "min_abs_delta": 0.12,
            "max_abs_delta": 0.25,
            "max_bid_ask_spread_pct": 0.10,
            "min_open_interest": 750,
            "min_volume": 75,
            "min_implied_volatility": 0.22,
            "max_implied_volatility": 0.52,
            "min_cash_coverage_ratio": 1.0,
            "max_underlying_concentration_ratio": 0.65,
            "allow_existing_short_put_exposure": False,
        },
        "stressed": {
            "min_days_to_expiry": 14,
            "max_days_to_expiry": 30,
            "min_abs_delta": 0.08,
            "max_abs_delta": 0.18,
            "max_bid_ask_spread_pct": 0.06,
            "min_open_interest": 1000,
            "min_volume": 100,
            "min_implied_volatility": 0.24,
            "max_implied_volatility": 0.48,
            "min_cash_coverage_ratio": 1.05,
            "max_underlying_concentration_ratio": 0.55,
            "allow_existing_short_put_exposure": False,
        },
    }

    values = dict(defaults[market_state])
    if assignment_intent == "avoid_assignment":
        values["max_abs_delta"] = round(max(float(values["min_abs_delta"]) + 0.02, float(values["max_abs_delta"]) - 0.03), 2)
    elif assignment_intent == "willing_to_assign":
        values["max_abs_delta"] = round(float(values["max_abs_delta"]) + 0.05, 2)
        values["min_cash_coverage_ratio"] = max(0.9, float(values["min_cash_coverage_ratio"]) - 0.05)

    if overrides:
        override_data = overrides.model_dump(exclude_none=True)
        override_data.pop("assignment_intent", None)
        values.update(override_data)

    return SellPutThresholdProfile(
        market_state=market_state,
        assignment_intent=overrides.assignment_intent if overrides and overrides.assignment_intent else assignment_intent,
        **values,
    )


def evaluate_candidate_rules(
    *,
    quote_price: float,
    strike: float,
    days_to_expiry: int,
    bid: float,
    ask: float,
    delta: float,
    implied_volatility: float,
    open_interest: int,
    volume: int,
    contracts: int,
    available_cash: Optional[float],
    thresholds: SellPutThresholdProfile,
    market_state: MarketState,
    broker_verified: bool,
) -> CandidateRuleEvaluation:
    midpoint = (bid + ask) / 2
    spread_pct = 1.0
    if midpoint > 0:
        spread_pct = max(ask - bid, 0.0) / midpoint

    otm_pct = max((quote_price - strike) / quote_price, 0.0) if quote_price else 0.0
    abs_delta = abs(delta)
    annualized_yield = 0.0
    if midpoint > 0 and strike > 0:
        annualized_yield = midpoint / strike * (365 / max(days_to_expiry, 1))

    cash_requirement = strike * 100 * contracts
    cash_coverage_ratio = None
    if available_cash is not None and cash_requirement > 0:
        cash_coverage_ratio = available_cash / cash_requirement

    hard_blocks: list[str] = []
    soft_flags: list[str] = []
    fit_tags: list[str] = []

    if not thresholds.min_days_to_expiry <= days_to_expiry <= thresholds.max_days_to_expiry:
        hard_blocks.append("dte_out_of_range")
    else:
        fit_tags.append("dte_in_range")

    if not thresholds.min_abs_delta <= abs_delta <= thresholds.max_abs_delta:
        hard_blocks.append("delta_out_of_range")
    else:
        fit_tags.append("delta_in_range")

    if spread_pct > thresholds.max_bid_ask_spread_pct:
        hard_blocks.append("spread_too_wide")
    else:
        fit_tags.append("spread_acceptable")

    if open_interest < thresholds.min_open_interest:
        hard_blocks.append("open_interest_below_threshold")
    else:
        fit_tags.append("open_interest_ok")

    if volume < thresholds.min_volume:
        hard_blocks.append("volume_below_threshold")
    else:
        fit_tags.append("volume_ok")

    if not thresholds.min_implied_volatility <= implied_volatility <= thresholds.max_implied_volatility:
        hard_blocks.append("implied_volatility_out_of_range")
    else:
        fit_tags.append("iv_in_band")

    if cash_coverage_ratio is not None and cash_coverage_ratio < thresholds.min_cash_coverage_ratio:
        hard_blocks.append("insufficient_cash_coverage")
    if available_cash is None:
        soft_flags.append("cash_not_verified")

    if market_state == "cautious":
        soft_flags.append("market_state_cautious")
    elif market_state == "stressed":
        soft_flags.append("market_state_stressed")

    if not broker_verified:
        soft_flags.append("broker_not_verified")

    assignment_risk: Literal["low", "moderate", "high"] = "low"
    if market_state == "stressed" or strike >= quote_price * 0.98 or abs_delta >= max(thresholds.max_abs_delta, 0.30):
        assignment_risk = "high"
        soft_flags.append("assignment_risk_high")
    elif strike >= quote_price * 0.94 or abs_delta >= 0.20:
        assignment_risk = "moderate"
        soft_flags.append("assignment_risk_moderate")

    score = 0.0
    delta_center = (thresholds.min_abs_delta + thresholds.max_abs_delta) / 2
    delta_width = max(thresholds.max_abs_delta - thresholds.min_abs_delta, 0.01)
    score += max(0.0, 26.0 * (1 - abs(abs_delta - delta_center) / delta_width))

    dte_center = (thresholds.min_days_to_expiry + thresholds.max_days_to_expiry) / 2
    dte_width = max(thresholds.max_days_to_expiry - thresholds.min_days_to_expiry, 1)
    score += max(0.0, 22.0 * (1 - abs(days_to_expiry - dte_center) / dte_width))

    if spread_pct <= thresholds.max_bid_ask_spread_pct:
        score += 16.0
    elif midpoint > 0:
        score += max(0.0, 8.0 * (thresholds.max_bid_ask_spread_pct / spread_pct))

    if open_interest >= thresholds.min_open_interest:
        score += min(12.0, 6.0 + (open_interest / max(thresholds.min_open_interest, 1)))
    else:
        score += max(0.0, 6.0 * (open_interest / max(thresholds.min_open_interest, 1)))

    if volume >= thresholds.min_volume:
        score += min(10.0, 5.0 + (volume / max(thresholds.min_volume, 1)))
    else:
        score += max(0.0, 5.0 * (volume / max(thresholds.min_volume, 1)))

    if thresholds.min_implied_volatility <= implied_volatility <= thresholds.max_implied_volatility:
        score += 8.0

    if otm_pct >= 0.08:
        score += 4.0
    elif otm_pct >= 0.05:
        score += 2.0

    if annualized_yield >= 0.18:
        score += 4.0
    elif annualized_yield >= 0.10:
        score += 2.0

    if cash_coverage_ratio is not None and cash_coverage_ratio >= thresholds.min_cash_coverage_ratio:
        score += 4.0

    if market_state == "cautious":
        score -= 3.0
    elif market_state == "stressed":
        score -= 8.0

    return CandidateRuleEvaluation(
        score=round(max(0.0, min(score, 100.0)), 2),
        spread_pct=round(spread_pct, 4),
        midpoint=round(midpoint, 4),
        otm_pct=round(otm_pct, 4),
        annualized_yield=round(annualized_yield, 4),
        cash_coverage_ratio=round(cash_coverage_ratio, 4) if cash_coverage_ratio is not None else None,
        assignment_risk=assignment_risk,
        hard_blocks=sorted(set(hard_blocks)),
        soft_flags=sorted(set(soft_flags)),
        fit_tags=sorted(set(fit_tags)),
    )


def build_playbook(
    *,
    underlying_symbol: str,
    contract_symbol: str,
    strike: float,
    days_to_expiry: int,
    evaluation: CandidateRuleEvaluation,
    thresholds: SellPutThresholdProfile,
) -> SellPutPlaybook:
    close_trigger = f"DTE <= {min(21, thresholds.max_days_to_expiry)} 或剩余权利金价值回落到初始信用的 20%-30%"
    roll_trigger = f"DTE <= {min(14, thresholds.max_days_to_expiry)} 且 delta 回到 {max(thresholds.max_abs_delta, 0.25):.2f}+ 或标的接近/跌破 {strike:g}"
    assignment_trigger = f"到期前处于实值且 assignment risk={evaluation.assignment_risk}"

    assignment_guidance = (
        f"如 {underlying_symbol} 在到期前仍接近或低于 {strike:g}，先比较平仓与向后滚动的净信用；"
        "仅作为建议，不会自动下单。"
    )
    if thresholds.assignment_intent == "avoid_assignment":
        assignment_guidance = (
            f"当前默认避免被指派。若 {contract_symbol} 临近到期仍偏实值，优先平仓或滚动，"
            "不把持股接仓当成默认路径。"
        )
    elif thresholds.assignment_intent == "willing_to_assign":
        assignment_guidance = (
            f"当前可接受被指派。若 {contract_symbol} 到期实值且现金覆盖充足，可按计划接仓，"
            "但仍需人工确认券商端资金与风险。"
        )

    summary = (
        f"{contract_symbol} 当前 assignment risk={evaluation.assignment_risk}，"
        f"playbook 仅输出 close/roll/assignment 草稿，DTE={days_to_expiry}，不会自动下单。"
    )
    return SellPutPlaybook(
        summary=summary,
        assignment_risk=evaluation.assignment_risk,
        actions=[
            SellPutPlaybookStep(
                phase="close",
                trigger=close_trigger,
                guidance="优先锁定大部分已赚权利金，避免尾部 gamma/assignment 风险。",
            ),
            SellPutPlaybookStep(
                phase="roll",
                trigger=roll_trigger,
                guidance="优先寻找向后一期且更低 strike 的净信用滚动方案，若只能借记滚动则降级为观察。",
            ),
            SellPutPlaybookStep(
                phase="assignment",
                trigger=assignment_trigger,
                guidance=assignment_guidance,
            ),
        ],
    )
