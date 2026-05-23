from __future__ import annotations

"""
Sell Put data-query / scoring input service.
"""

import os
from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel, Field, model_validator

from services.freshness import CombinedFreshnessResult, FreshnessGate
from services.margin import MarginEstimator, SellPutMarginEstimate, SellPutMarginEstimateRequest
from services.sell_put_rules import (
    AssignmentIntent,
    CandidateRankingItem,
    MarketState,
    SellPutPlaybook,
    SellPutThresholdOverrides,
    SellPutThresholdProfile,
    UnderlyingGateAssessment,
    build_playbook,
    evaluate_candidate_rules,
    resolve_thresholds,
)
from adapters.futu import FutuAccountSnapshot


def env_positive_int(name: str, default: int) -> int:
    try:
        value = int(os.getenv(name, "").strip())
    except ValueError:
        return default
    return value if value > 0 else default


def default_sell_put_market_staleness_seconds() -> int:
    return env_positive_int("SELL_PUT_FRESHNESS_SECONDS", 60)


def default_broker_snapshot_staleness_seconds() -> int:
    return env_positive_int("BROKER_SNAPSHOT_MAX_STALENESS_SECONDS", 300)


class SellPutQuoteInput(BaseModel):
    symbol: str
    as_of: datetime
    price: float
    currency: str
    source_key: str = "futu_openapi"
    source_tier: str = "L1_trading"
    fallback_used: bool = False
    cross_check_status: Literal["matched", "mismatch", "unchecked"] = "unchecked"


class SellPutOptionCandidateInput(BaseModel):
    contract_symbol: str
    option_type: Literal["put", "call"] = "put"
    strike: float
    contracts: int = Field(default=1, ge=1)
    expiry: str
    days_to_expiry: int
    bid: Optional[float] = None
    ask: Optional[float] = None
    delta: Optional[float] = None
    implied_volatility: Optional[float] = None
    open_interest: Optional[int] = None
    volume: Optional[int] = None
    as_of: datetime
    source_key: str = "futu_openapi"
    source_tier: str = "L1_trading"

    @model_validator(mode="after")
    def _normalize_option_type(self) -> "SellPutOptionCandidateInput":
        self.option_type = self.option_type.lower()
        return self


class SellPutAnalysisRequest(BaseModel):
    tenant_id: str
    underlying_symbol: str
    quote: SellPutQuoteInput
    option_candidates: list[SellPutOptionCandidateInput]
    account_snapshot: Optional[FutuAccountSnapshot] = None
    max_market_staleness_seconds: int = Field(default_factory=default_sell_put_market_staleness_seconds)
    max_broker_staleness_seconds: int = Field(default_factory=default_broker_snapshot_staleness_seconds)
    market_state: MarketState = "normal"
    assignment_intent: AssignmentIntent = "avoid_assignment"
    threshold_overrides: Optional[SellPutThresholdOverrides] = None


class SellPutCandidateAssessment(BaseModel):
    contract_symbol: str
    actionability: Literal["trade_draft", "suggested_action", "analysis_only", "blocked"]
    action_label: str
    score: float
    missing_fields: list[str] = Field(default_factory=list)
    reasons: list[str] = Field(default_factory=list)
    user_reasons: list[str] = Field(default_factory=list)
    user_note: str = ""
    margin_estimate: SellPutMarginEstimate
    playbook: SellPutPlaybook
    account_constraint_summary: "SellPutAccountConstraintSummary"


class SellPutAccountConstraintSummary(BaseModel):
    has_existing_short_put: bool
    existing_short_put_contracts: int = 0
    same_underlying_share_quantity: float = 0.0
    same_underlying_share_market_value: float = 0.0
    projected_contracts: int = 1
    projected_cash_secured_requirement: float = 0.0
    existing_short_put_cash_secured_requirement: float = 0.0
    account_risk_budget: Optional[float] = None
    underlying_concentration_ratio: Optional[float] = None
    concentration_limit_ratio: float
    concentration_is_high: bool = False
    actionability_cap: Literal["trade_draft", "suggested_action", "analysis_only", "blocked"] = "trade_draft"
    constraint_reasons: list[str] = Field(default_factory=list)
    constraint_note: str = ""


SellPutCandidateAssessment.model_rebuild()


class SellPutAnalysisResponse(BaseModel):
    underlying_symbol: str
    overall_actionability: Literal["trade_draft", "analysis_only", "blocked"]
    overall_action_label: str
    freshness: CombinedFreshnessResult
    broker_snapshot_mode: Literal["broker_verified", "estimated_only"]
    data_quality_note: str
    underlying_gate: UnderlyingGateAssessment
    candidate_ranking: list[CandidateRankingItem]
    candidates: list[SellPutCandidateAssessment]
    blocked_reasons: list[str] = Field(default_factory=list)
    user_blocked_reasons: list[str] = Field(default_factory=list)


class SellPutAnalysisService:
    REQUIRED_OPTION_FIELDS = [
        "bid",
        "ask",
        "delta",
        "implied_volatility",
        "open_interest",
        "volume",
        "days_to_expiry",
    ]

    def __init__(
        self,
        freshness_gate: Optional[FreshnessGate] = None,
        margin_estimator: Optional[MarginEstimator] = None,
    ) -> None:
        self._freshness_gate = freshness_gate or FreshnessGate()
        self._margin_estimator = margin_estimator or MarginEstimator()

    def _option_missing_fields(self, option: SellPutOptionCandidateInput) -> list[str]:
        missing: list[str] = []
        for field_name in self.REQUIRED_OPTION_FIELDS:
            if getattr(option, field_name) is None:
                missing.append(field_name)
        if option.option_type != "put":
            missing.append("option_type_not_put")
        return missing

    async def analyze(self, payload: SellPutAnalysisRequest) -> SellPutAnalysisResponse:
        account_snapshot = payload.account_snapshot
        broker_verified = account_snapshot is not None and not account_snapshot.missing_fields
        broker_as_of = account_snapshot.as_of if account_snapshot else payload.quote.as_of
        broker_source_tier = account_snapshot.source_tier if account_snapshot else "estimated"
        broker_missing_fields = list(account_snapshot.missing_fields) if account_snapshot else []
        option_chain_missing_fields = [] if payload.option_candidates else ["option_chain"]
        thresholds = resolve_thresholds(
            market_state=payload.market_state,
            assignment_intent=payload.assignment_intent,
            overrides=payload.threshold_overrides,
        )

        quote_trade_allowed = not payload.quote.fallback_used and payload.quote.cross_check_status != "mismatch"
        freshness = self._freshness_gate.evaluate_sell_put_inputs(
            quote_as_of=payload.quote.as_of,
            option_chain_as_of=min((item.as_of for item in payload.option_candidates), default=payload.quote.as_of),
            broker_as_of=broker_as_of,
            quote_source_tier=payload.quote.source_tier,
            option_source_tier=payload.option_candidates[0].source_tier if payload.option_candidates else "L1_trading",
            broker_source_tier=broker_source_tier,
            max_market_age_seconds=payload.max_market_staleness_seconds,
            max_broker_age_seconds=payload.max_broker_staleness_seconds,
            broker_verified=broker_verified,
            option_missing_fields=option_chain_missing_fields,
            broker_missing_fields=sorted(set(broker_missing_fields)),
            now=None,
        )

        blocked_reasons = list(freshness.reasons)
        if not quote_trade_allowed:
            blocked_reasons.append("quote_fallback_or_cross_check_mismatch")
        if payload.market_state == "cautious":
            blocked_reasons.append("market_state_cautious")
        elif payload.market_state == "stressed":
            blocked_reasons.append("market_state_stressed")

        available_cash = None
        if account_snapshot and account_snapshot.cash_balances:
            available_cash = account_snapshot.cash_balances[0].available_cash

        results: list[SellPutCandidateAssessment] = []
        ranking_items: list[CandidateRankingItem] = []
        overall = freshness.overall_actionability
        if not quote_trade_allowed and overall == "trade_draft":
            overall = "analysis_only"
        if payload.market_state == "stressed" and overall == "trade_draft":
            overall = "analysis_only"

        for option in payload.option_candidates:
            missing_fields = self._option_missing_fields(option)
            option_freshness = self._freshness_gate.evaluate(
                as_of=option.as_of,
                max_age_seconds=payload.max_market_staleness_seconds,
                source_tier=option.source_tier,
                now=None,
            )
            midpoint = ((option.bid or 0.0) + (option.ask or 0.0)) / 2
            margin_estimate = self._margin_estimator.estimate_sell_put(
                request=SellPutMarginEstimateRequest(
                    underlying_symbol=payload.underlying_symbol,
                    underlying_price=payload.quote.price,
                    strike=option.strike,
                    contracts=option.contracts,
                    premium_per_share=midpoint,
                    available_cash=available_cash,
                )
            )
            account_constraint_summary = _build_account_constraint_summary(
                underlying_symbol=payload.underlying_symbol,
                option=option,
                account_snapshot=account_snapshot,
                thresholds=thresholds,
            )

            reasons: list[str] = []
            score = 0.0
            assignment_risk: Literal["low", "moderate", "high"] = "high"
            spread_pct = 1.0
            actionability: Literal["trade_draft", "suggested_action", "analysis_only", "blocked"] = "analysis_only"
            evaluation = None

            if missing_fields:
                reasons.append(f"missing_fields:{','.join(missing_fields)}")
                actionability = "blocked"
            else:
                evaluation = evaluate_candidate_rules(
                    quote_price=payload.quote.price,
                    strike=option.strike,
                    days_to_expiry=option.days_to_expiry,
                    bid=float(option.bid or 0.0),
                    ask=float(option.ask or 0.0),
                    delta=float(option.delta or 0.0),
                    implied_volatility=float(option.implied_volatility or 0.0),
                    open_interest=int(option.open_interest or 0),
                    volume=int(option.volume or 0),
                    contracts=option.contracts,
                    available_cash=available_cash,
                    thresholds=thresholds,
                    market_state=payload.market_state,
                    broker_verified=broker_verified,
                )
                score = evaluation.score
                assignment_risk = evaluation.assignment_risk
                spread_pct = evaluation.spread_pct
                reasons.extend(evaluation.hard_blocks)
                reasons.extend(evaluation.soft_flags)

                if freshness.overall_actionability == "blocked":
                    actionability = "blocked"
                    reasons.append("freshness_gate_blocked")
                elif option_freshness.actionability == "blocked":
                    actionability = "blocked"
                    reasons.extend(option_freshness.reasons)
                elif evaluation.hard_blocks:
                    actionability = "blocked"
                elif option_freshness.actionability == "analysis_only":
                    actionability = "analysis_only"
                    reasons.extend(option_freshness.reasons)
                elif overall == "analysis_only":
                    actionability = "analysis_only"
                    reasons.append("freshness_or_source_gate_analysis_only")
                elif payload.market_state == "stressed":
                    actionability = "suggested_action" if score >= 78 and broker_verified else "analysis_only"
                elif score >= 85 and margin_estimate.sufficient_available_cash is not False and broker_verified:
                    actionability = "trade_draft"
                elif score >= 70:
                    actionability = "suggested_action"
                else:
                    actionability = "analysis_only"

            reasons.extend(account_constraint_summary.constraint_reasons)
            actionability = _cap_actionability(actionability, account_constraint_summary.actionability_cap)

            if margin_estimate.sufficient_available_cash is False:
                reasons.append("insufficient_available_cash")
                actionability = "blocked"

            if not broker_verified:
                reasons.append("broker_margin_reference_only")

            playbook = build_playbook(
                underlying_symbol=payload.underlying_symbol,
                contract_symbol=option.contract_symbol,
                strike=option.strike,
                days_to_expiry=option.days_to_expiry,
                evaluation=evaluation
                or evaluate_candidate_rules(
                    quote_price=payload.quote.price,
                    strike=option.strike,
                    days_to_expiry=option.days_to_expiry,
                    bid=float(option.bid or 0.0),
                    ask=float(option.ask or 0.0),
                    delta=float(option.delta or 0.0),
                    implied_volatility=float(option.implied_volatility or 0.0),
                    open_interest=int(option.open_interest or 0),
                    volume=int(option.volume or 0),
                    contracts=option.contracts,
                    available_cash=available_cash,
                    thresholds=thresholds,
                    market_state=payload.market_state,
                    broker_verified=broker_verified,
                ),
                thresholds=thresholds,
            )
            user_reasons = _humanize_reasons(reasons)
            results.append(
                SellPutCandidateAssessment(
                    contract_symbol=option.contract_symbol,
                    actionability=actionability,
                    action_label=_actionability_label(actionability),
                    score=score,
                    missing_fields=missing_fields,
                    reasons=reasons,
                    user_reasons=user_reasons,
                    user_note=_candidate_user_note(actionability, user_reasons),
                    margin_estimate=margin_estimate,
                    playbook=playbook,
                    account_constraint_summary=account_constraint_summary,
                )
            )
            ranking_items.append(
                CandidateRankingItem(
                    rank=0,
                    contract_symbol=option.contract_symbol,
                    actionability=actionability,
                    score=score,
                    assignment_risk=assignment_risk,
                    spread_pct=spread_pct,
                    rank_reasons=_candidate_rank_reasons(
                        actionability=actionability,
                        score=score,
                        spread_pct=spread_pct,
                        reasons=reasons,
                    ),
                )
            )

        if not any(item.actionability == "trade_draft" for item in results) and overall == "trade_draft":
            overall = "analysis_only"
        if not results or all(item.actionability == "blocked" for item in results):
            overall = "blocked"

        sorted_results = sorted(results, key=_candidate_sort_key)
        sorted_ranking = sorted(ranking_items, key=_ranking_sort_key)
        for index, item in enumerate(sorted_ranking, start=1):
            item.rank = index

        broker_snapshot_mode: Literal["broker_verified", "estimated_only"] = (
            "broker_verified" if broker_verified else "estimated_only"
        )
        underlying_gate = _build_underlying_gate(
            payload=payload,
            thresholds=thresholds,
            freshness=freshness,
            broker_verified=broker_verified,
            available_cash=available_cash,
            overall=overall,
            candidates=sorted_results,
        )
        if underlying_gate.actionability == "blocked":
            overall = "blocked"
        elif underlying_gate.actionability == "analysis_only" and overall == "trade_draft":
            overall = "analysis_only"

        blocked_reasons.extend(underlying_gate.reasons)
        return SellPutAnalysisResponse(
            underlying_symbol=payload.underlying_symbol,
            overall_actionability=overall,
            overall_action_label=_overall_actionability_label(overall),
            freshness=freshness,
            broker_snapshot_mode=broker_snapshot_mode,
            data_quality_note=_broker_mode_note(broker_snapshot_mode, payload.market_state),
            underlying_gate=underlying_gate,
            candidate_ranking=sorted_ranking,
            candidates=sorted_results,
            blocked_reasons=sorted(set(blocked_reasons)),
            user_blocked_reasons=_humanize_reasons(sorted(set(blocked_reasons))),
        )


def _actionability_label(actionability: str) -> str:
    labels = {
        "trade_draft": "可生成交易草稿",
        "suggested_action": "可作为候选观察",
        "analysis_only": "仅供观察",
        "blocked": "暂不建议操作",
    }
    return labels.get(actionability, "仅供观察")


def _overall_actionability_label(actionability: str) -> str:
    labels = {
        "trade_draft": "本轮结果可生成交易草稿",
        "analysis_only": "本轮结果仅供观察",
        "blocked": "本轮结果暂不适合继续操作",
    }
    return labels.get(actionability, "本轮结果仅供观察")


def _broker_mode_note(mode: str, market_state: MarketState) -> str:
    state_note = {
        "normal": "市场状态为 normal。",
        "cautious": "市场状态为 cautious，阈值已收紧。",
        "stressed": "市场状态为 stressed，结果默认降级为观察/建议。",
    }[market_state]
    if mode == "broker_verified":
        return f"账户现金和持仓来自券商只读同步。{state_note}"
    return f"未取得券商账户确认，现金占用和保证金为系统估算，仅供参考。{state_note}"


def _humanize_reasons(reasons: list[str]) -> list[str]:
    notes: list[str] = []
    for reason in reasons:
        if reason.startswith("missing_fields:"):
            fields = reason.split(":", 1)[1]
            notes.append(f"期权链字段不完整（{fields}），暂不生成交易草稿。")
        elif reason == "existing_short_put_exposure_present":
            notes.append("账户内已有同标的短 Put 暴露，本轮只保留观察结论。")
        elif reason == "freshness_gate_blocked":
            notes.append("行情或账户数据不足，暂不生成交易草稿。")
        elif reason == "freshness_or_source_gate_analysis_only":
            notes.append("行情或账户数据需要复核，当前仅提供观察结论。")
        elif reason == "insufficient_available_cash":
            notes.append("可用现金不足以覆盖现金担保。")
        elif reason == "insufficient_cash_coverage":
            notes.append("现金覆盖比例低于当前 sell put 阈值。")
        elif reason == "same_underlying_concentration_high":
            notes.append("同标的持仓与短 Put 暴露集中度偏高，需要先降风险再考虑新仓。")
        elif reason == "broker_margin_reference_only":
            notes.append("未连接券商账户，现金占用和保证金仅为系统估算。")
        elif reason == "broker_cash_margin_not_verified":
            notes.append("券商现金和保证金数据未确认，相关结果仅供参考。")
        elif reason == "quote_fallback_or_cross_check_mismatch":
            notes.append("行情来源校验未通过，当前仅供观察。")
        elif reason == "market_state_cautious":
            notes.append("当前市场状态为 cautious，系统已提高筛选门槛。")
        elif reason == "market_state_stressed":
            notes.append("当前市场状态为 stressed，系统默认只给观察/建议，不给交易草稿。")
        elif reason == "spread_too_wide":
            notes.append("买卖价差过宽，流动性不足。")
        elif reason == "open_interest_below_threshold":
            notes.append("持仓量低于阈值，流动性偏弱。")
        elif reason == "volume_below_threshold":
            notes.append("成交量低于阈值，成交质量不足。")
        elif reason == "dte_out_of_range":
            notes.append("到期天数不在当前默认窗口内。")
        elif reason == "delta_out_of_range":
            notes.append("delta 不在当前默认风险窗口内。")
        elif reason == "implied_volatility_out_of_range":
            notes.append("隐含波动率不在当前默认区间内。")
        elif reason == "assignment_risk_high":
            notes.append("被指派风险偏高，需要提前准备 roll/close 方案。")
        elif reason == "assignment_risk_moderate":
            notes.append("被指派风险中等，建议持续跟踪 delta 与到期日。")
        elif reason == "cash_not_verified":
            notes.append("账户现金未核验，仓位适配度仅供参考。")
        elif reason == "broker_not_verified":
            notes.append("券商账户未核验，不生成交易草稿。")
        elif reason == "underlying_no_viable_candidates":
            notes.append("当前标的下没有通过第一层筛选的 put 候选。")
        elif reason == "underlying_cash_secured_capacity_missing":
            notes.append("当前账户资金无法支撑该标的的现金担保 sell put。")
        elif reason == "underlying_assignment_risk_too_high":
            notes.append("当前标的的 assignment 风险与默认意图不匹配。")
        elif reason.startswith("missing_fields"):
            notes.append("关键字段不完整，暂不生成交易草稿。")
        elif reason.startswith("source_tier"):
            notes.append("当前使用的行情来源不适合直接生成交易草稿。")
        elif reason.startswith("stale:"):
            notes.append("行情或账户数据更新时间偏久，当前仅供观察。")
        elif reason == "trade_action_not_allowed":
            notes.append("当前数据状态不支持生成交易动作。")
    return sorted(set(notes))


def _candidate_user_note(actionability: str, user_reasons: list[str]) -> str:
    if user_reasons:
        if actionability == "trade_draft":
            return "；".join(user_reasons + ["满足当前规则，可生成交易草稿；仍需人工确认，不会自动下单。"])
        if actionability in {"suggested_action", "analysis_only"}:
            return "；".join(user_reasons + ["playbook 仅供草稿参考，不会自动下单。"])
        return "；".join(user_reasons)
    if actionability == "trade_draft":
        return "满足当前规则，可生成交易草稿；仍需人工确认，不会自动下单。"
    if actionability == "suggested_action":
        return "可加入候选观察，生成草稿前仍需复核账户现金和实时行情；不会自动下单。"
    if actionability == "blocked":
        return "暂不建议继续操作。"
    return "仅供观察，不生成交易草稿；不会自动下单。"


def _candidate_sort_key(candidate: SellPutCandidateAssessment) -> tuple[int, float, str]:
    priority = {
        "trade_draft": 0,
        "suggested_action": 1,
        "analysis_only": 2,
        "blocked": 3,
    }
    return (priority[candidate.actionability], -candidate.score, candidate.contract_symbol)


def _ranking_sort_key(item: CandidateRankingItem) -> tuple[int, float, float, str]:
    priority = {
        "trade_draft": 0,
        "suggested_action": 1,
        "analysis_only": 2,
        "blocked": 3,
    }
    return (priority[item.actionability], -item.score, item.spread_pct, item.contract_symbol)


def _candidate_rank_reasons(
    *,
    actionability: str,
    score: float,
    spread_pct: float,
    reasons: list[str],
) -> list[str]:
    notes = [f"score={score:.2f}", f"spread_pct={spread_pct:.2%}", f"actionability={actionability}"]
    notes.extend(sorted(set(reasons))[:3])
    return notes


def _cap_actionability(
    current: Literal["trade_draft", "suggested_action", "analysis_only", "blocked"],
    cap: Literal["trade_draft", "suggested_action", "analysis_only", "blocked"],
) -> Literal["trade_draft", "suggested_action", "analysis_only", "blocked"]:
    priority = {
        "trade_draft": 0,
        "suggested_action": 1,
        "analysis_only": 2,
        "blocked": 3,
    }
    if priority[current] >= priority[cap]:
        return current
    return cap


def _build_account_constraint_summary(
    *,
    underlying_symbol: str,
    option: SellPutOptionCandidateInput,
    account_snapshot: Optional[FutuAccountSnapshot],
    thresholds: SellPutThresholdProfile,
) -> SellPutAccountConstraintSummary:
    normalized = underlying_symbol.upper()
    same_underlying_share_quantity = 0.0
    same_underlying_share_market_value = 0.0
    existing_short_put_contracts = 0
    existing_short_put_cash_secured_requirement = 0.0
    account_risk_budget: Optional[float] = None

    if account_snapshot:
        for balance in account_snapshot.cash_balances:
            if str(balance.currency).upper() != "USD":
                continue
            account_risk_budget = balance.buying_power or balance.available_cash
            if account_risk_budget is not None:
                break

        for position in account_snapshot.positions:
            position_symbol = str(position.symbol or "").upper()
            if position.instrument_type in {"stock", "etf"} and position_symbol == normalized:
                quantity = abs(float(position.quantity or 0.0))
                reference_price = float(position.market_price or position.average_cost or 0.0)
                same_underlying_share_quantity += quantity
                same_underlying_share_market_value += quantity * reference_price
                continue

            if (
                position.instrument_type == "option_contract"
                and position.option_type == "put"
                and float(position.quantity or 0.0) < 0
                and _position_matches_underlying(position_symbol, normalized)
            ):
                contracts = int(abs(float(position.quantity or 0.0)))
                existing_short_put_contracts += contracts
                existing_short_put_cash_secured_requirement += float(position.strike or 0.0) * 100 * contracts

    projected_cash_secured_requirement = round(float(option.strike) * 100 * option.contracts, 2)
    total_underlying_exposure = (
        same_underlying_share_market_value
        + existing_short_put_cash_secured_requirement
        + projected_cash_secured_requirement
    )
    underlying_concentration_ratio = None
    if account_risk_budget and account_risk_budget > 0:
        underlying_concentration_ratio = round(total_underlying_exposure / account_risk_budget, 4)

    constraint_reasons: list[str] = []
    actionability_cap: Literal["trade_draft", "suggested_action", "analysis_only", "blocked"] = "trade_draft"
    if existing_short_put_contracts > 0 and not thresholds.allow_existing_short_put_exposure:
        constraint_reasons.append("existing_short_put_exposure_present")
        actionability_cap = "analysis_only"

    concentration_is_high = (
        underlying_concentration_ratio is not None
        and underlying_concentration_ratio > thresholds.max_underlying_concentration_ratio
    )
    if concentration_is_high:
        constraint_reasons.append("same_underlying_concentration_high")
        actionability_cap = _cap_actionability(actionability_cap, "suggested_action")

    constraint_note_parts: list[str] = []
    if same_underlying_share_quantity > 0:
        constraint_note_parts.append(
            f"同标的现货 {same_underlying_share_quantity:g} 股，市值约 {same_underlying_share_market_value:.2f} 美元"
        )
    if existing_short_put_contracts > 0:
        constraint_note_parts.append(
            f"已有同标的短 Put {existing_short_put_contracts} 张，对应现金担保约 {existing_short_put_cash_secured_requirement:.2f} 美元"
        )
    if underlying_concentration_ratio is not None:
        constraint_note_parts.append(
            f"加入本候选后同标的风险预算占用约 {underlying_concentration_ratio:.1%}，阈值 {thresholds.max_underlying_concentration_ratio:.0%}"
        )
    if not constraint_note_parts:
        constraint_note_parts.append("账户内暂无同标的现货或短 Put 暴露。")

    return SellPutAccountConstraintSummary(
        has_existing_short_put=existing_short_put_contracts > 0,
        existing_short_put_contracts=existing_short_put_contracts,
        same_underlying_share_quantity=round(same_underlying_share_quantity, 4),
        same_underlying_share_market_value=round(same_underlying_share_market_value, 2),
        projected_contracts=option.contracts,
        projected_cash_secured_requirement=projected_cash_secured_requirement,
        existing_short_put_cash_secured_requirement=round(existing_short_put_cash_secured_requirement, 2),
        account_risk_budget=round(account_risk_budget, 2) if account_risk_budget is not None else None,
        underlying_concentration_ratio=underlying_concentration_ratio,
        concentration_limit_ratio=thresholds.max_underlying_concentration_ratio,
        concentration_is_high=concentration_is_high,
        actionability_cap=actionability_cap,
        constraint_reasons=sorted(set(constraint_reasons)),
        constraint_note="；".join(constraint_note_parts),
    )


def _position_matches_underlying(position_symbol: str, underlying_symbol: str) -> bool:
    return position_symbol == underlying_symbol or position_symbol.startswith(underlying_symbol)


def _build_underlying_gate(
    *,
    payload: SellPutAnalysisRequest,
    thresholds,
    freshness: CombinedFreshnessResult,
    broker_verified: bool,
    available_cash: Optional[float],
    overall: str,
    candidates: list[SellPutCandidateAssessment],
) -> UnderlyingGateAssessment:
    reasons: list[str] = []
    passed_checks: list[str] = []
    best_candidate = candidates[0] if candidates else None
    suitability_score = best_candidate.score if best_candidate else 0.0

    if freshness.overall_actionability == "blocked":
        reasons.append("freshness_gate_blocked")
    else:
        passed_checks.append("freshness_checked")

    if broker_verified:
        passed_checks.append("broker_verified")
    else:
        reasons.append("broker_not_verified")

    viable_candidates = [item for item in candidates if item.actionability != "blocked"]
    if viable_candidates:
        passed_checks.append("candidate_pool_viable")
    else:
        reasons.append("underlying_no_viable_candidates")

    if available_cash is None:
        reasons.append("cash_not_verified")
    elif not any(item.margin_estimate.sufficient_available_cash is not False for item in candidates):
        reasons.append("underlying_cash_secured_capacity_missing")
    else:
        passed_checks.append("cash_secured_capacity_ok")

    if any("existing_short_put_exposure_present" in item.reasons for item in candidates):
        reasons.append("existing_short_put_exposure_present")
    if any("same_underlying_concentration_high" in item.reasons for item in candidates):
        reasons.append("same_underlying_concentration_high")

    if payload.market_state == "stressed":
        reasons.append("market_state_stressed")
    elif payload.market_state == "cautious":
        reasons.append("market_state_cautious")

    if (
        best_candidate
        and best_candidate.playbook.assignment_risk == "high"
        and thresholds.assignment_intent == "avoid_assignment"
    ):
        reasons.append("underlying_assignment_risk_too_high")

    if "freshness_gate_blocked" in reasons or "underlying_no_viable_candidates" in reasons:
        gate_status: Literal["passed", "degraded", "blocked"] = "blocked"
    elif any(
        reason in reasons
        for reason in (
            "broker_not_verified",
            "cash_not_verified",
            "market_state_cautious",
            "market_state_stressed",
            "existing_short_put_exposure_present",
            "same_underlying_concentration_high",
            "underlying_assignment_risk_too_high",
        )
    ):
        gate_status = "degraded"
    else:
        gate_status = "passed"

    actionability: Literal["trade_draft", "analysis_only", "blocked"]
    if gate_status == "passed" and overall == "trade_draft":
        actionability = "trade_draft"
    elif gate_status == "blocked" or overall == "blocked":
        actionability = "blocked"
    else:
        actionability = "analysis_only"

    user_reasons = _humanize_reasons(reasons)
    if gate_status == "passed":
        user_note = "标的通过第一层 sell put 适合度筛选。"
    elif gate_status == "degraded":
        user_note = "标的可继续观察，但当前只建议生成分析/草稿建议，不直接进入可交易状态。"
    else:
        user_note = "标的未通过第一层筛选，当前不建议继续生成 sell put 交易草稿。"

    return UnderlyingGateAssessment(
        gate_status=gate_status,
        actionability=actionability,
        suitability_score=round(suitability_score, 2),
        market_state=payload.market_state,
        assignment_intent=thresholds.assignment_intent,
        thresholds=thresholds,
        reasons=sorted(set(reasons)),
        user_reasons=user_reasons,
        passed_checks=sorted(set(passed_checks)),
        user_note=user_note,
    )
